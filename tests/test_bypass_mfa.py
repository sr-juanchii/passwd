"""Cobertura exhaustiva contra el salto del segundo factor (MFA).

Modelo de amenaza: un atacante que YA conoce la contraseña de un usuario (fuga,
reutilización, phishing) y usa un proxy de intercepción —Burp Suite, ZAP,
mitmproxy— para hablar directamente con la API, sin pasar por el frontend. El
guard de rutas del cliente (``frontend/src/proxy.ts``) no existe para él: puede
inventar cualquier petición con su cookie de sesión detenida antes del MFA.

La invariante que se verifica es única y absoluta:

    Con una sesión en cualquier etapa previa a ``activa``, NINGÚN endpoint de la
    aplicación debe entregar datos ni ejecutar efectos.

Estas pruebas se construyen ENUMERANDO las rutas registradas en la aplicación,
no con una lista escrita a mano. Así, un endpoint nuevo que olvide su
dependencia de sesión hace fallar la suite automáticamente, en lugar de pasar
inadvertido hasta que alguien lo encuentre con Burp en producción.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    ADMIN_PASS,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    autenticar_admin,
    cambiar_password,
    codigo_totp,
    extraer_csrf,
    login_password,
)

# ── Endpoints legítimamente alcanzables sin haber completado el MFA ───────────
# Cada uno es parte del propio flujo de autenticación o es público por diseño.
# Cualquier ruta que NO esté aquí debe rechazar una sesión pre-MFA.
RUTAS_PRE_MFA_LEGITIMAS = {
    "/login",
    "/logout",
    "/password/cambiar",
    "/mfa/configurar",
    "/mfa/verificar",
    "/recuperar",
    "/recuperar/verificar",
    "/recuperar/cambiar",
    "/healthz",
    "/api/web/csrf",
    "/api/web/session",
    "/api/web/login",
    "/api/web/logout",
    "/api/web/password/cambiar",
    "/api/web/mfa/configurar",
    "/api/web/mfa/verificar",
    # Método de respaldo del MFA: pedir un OTP al correo registrado. Alcanzable
    # solo desde 'mfa_pendiente' (la contraseña ya está validada), con CSRF y
    # doble límite de tasa; no entrega el código en la respuesta, solo lo envía.
    "/mfa/otp-correo",
    "/api/web/mfa/otp-correo",
    # Métodos de 2.º factor disponibles, para que la pantalla ofrezca los
    # correctos. Solo informa al titular de una sesión cuya contraseña ya se
    # validó, y sobre su propia cuenta.
    "/api/web/mfa/metodos",
    "/api/web/password/recuperar/iniciar",
    "/api/web/password/recuperar/verificar",
    "/api/web/password/recuperar/cambiar",
}

# Prefijos con su propio esquema de autenticación (token Bearer, no cookie de
# sesión), verificados aparte en ``test_api.py`` y más abajo en este módulo.
PREFIJOS_EXCLUIDOS = ("/api/v1", "/static", "/docs", "/redoc", "/openapi.json")

# Respuestas que constituyen un rechazo correcto de una sesión pre-MFA.
#   303 → la web Jinja redirige a /login
#   401 → la API JSON: no autenticado
#   403 → etapa de sesión inválida, CSRF ausente o sin permisos
#   404 → la ruta no existe para ese identificador
#   405 → método no permitido
#   423 → cuenta bloqueada
#   429 → límite de tasa
#
# El 422 queda DELIBERADAMENTE fuera: significaría que la petición superó la
# autenticación y llegó a validar el cuerpo. Con las dependencias de sesión bien
# puestas, FastAPI corta antes y nunca se llega ahí; aceptar 422 enmascararía un
# endpoint que sí se ejecutaría si el atacante enviara un cuerpo bien formado.
CODIGOS_DE_RECHAZO = {303, 401, 403, 404, 405, 423, 429}

METODOS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _rutas_de(aplicacion):
    """Enumera (ruta, métodos) de la aplicación real, sin listas a mano.

    Se usa el esquema OpenAPI en lugar de recorrer ``aplicacion.routes``: desde
    FastAPI 0.141 los routers incluidos quedan envueltos en ``_IncludedRouter``
    y ``aplicacion.routes`` NO los aplana, por lo que un recorrido plano solo
    encontraría los endpoints declarados directamente en la aplicación (uno) y
    el barrido pasaría en vacío.
    """
    esquema = aplicacion.openapi()
    rutas = []
    for camino, operaciones in esquema.get("paths", {}).items():
        if camino.startswith(PREFIJOS_EXCLUIDOS):
            continue
        metodos = {m.upper() for m in operaciones if m.upper() in METODOS}
        if metodos:
            rutas.append((camino, metodos))
    return sorted(rutas)


def _concretar(camino: str) -> str:
    """Sustituye los parámetros de ruta por un identificador plausible."""
    partes = []
    for parte in camino.split("/"):
        partes.append("1" if parte.startswith("{") and parte.endswith("}") else parte)
    return "/".join(partes)


def _sesion_en_etapa_cambio_password(client: TestClient) -> None:
    """Deja la sesión del admin inicial detenida en la etapa 'cambio_password'."""
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/password/cambiar"


def _sesion_en_etapa_mfa_enrolamiento(client: TestClient) -> None:
    """Deja la sesión detenida en 'mfa_enrolamiento' (contraseña ya cambiada)."""
    _sesion_en_etapa_cambio_password(client)
    respuesta = cambiar_password(client, ADMIN_PASS_INICIAL, ADMIN_PASS)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/mfa/configurar"


def _sesion_en_etapa_mfa_pendiente(client: TestClient, crear_cliente) -> None:
    """Deja la sesión detenida en 'mfa_pendiente': contraseña válida, MFA sin resolver.

    Es la etapa del atacante que conoce la contraseña pero no tiene el
    dispositivo autenticador: el escenario exacto del salto de MFA.
    """
    otro = crear_cliente()
    autenticar_admin(otro)  # deja al admin con MFA ya habilitado
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/mfa/verificar"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Barrido exhaustivo de TODA la superficie de la aplicación
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "preparar_etapa",
    ["cambio_password", "mfa_enrolamiento", "mfa_pendiente"],
)
def test_ninguna_ruta_entrega_datos_antes_de_completar_el_mfa(
    aplicacion, crear_cliente, preparar_etapa
):
    """Ningún endpoint responde 2xx a una sesión que no completó el MFA.

    Recorre TODAS las rutas registradas (menos las del propio flujo de login y
    las que usan token Bearer) con los métodos que declaran, usando la cookie de
    una sesión detenida en una etapa previa. Cualquier 2xx es un salto de MFA.
    """
    client = crear_cliente()
    if preparar_etapa == "cambio_password":
        _sesion_en_etapa_cambio_password(client)
    elif preparar_etapa == "mfa_enrolamiento":
        _sesion_en_etapa_mfa_enrolamiento(client)
    else:
        _sesion_en_etapa_mfa_pendiente(client, crear_cliente)

    fugas = []
    for camino, metodos in _rutas_de(aplicacion):
        if camino in RUTAS_PRE_MFA_LEGITIMAS:
            continue
        concreta = _concretar(camino)
        for metodo in sorted(metodos):
            respuesta = client.request(metodo, concreta)
            if respuesta.status_code not in CODIGOS_DE_RECHAZO:
                fugas.append(f"{metodo} {concreta} → {respuesta.status_code}")

    assert not fugas, (
        f"Salto de MFA en etapa '{preparar_etapa}': estos endpoints respondieron "
        f"sin exigir el segundo factor:\n  " + "\n  ".join(fugas)
    )


def test_el_barrido_cubre_una_superficie_representativa(aplicacion):
    """Red de seguridad del propio barrido: debe examinar muchas rutas.

    Si un refactor rompiera la enumeración, el test anterior pasaría en vacío
    sin verificar nada. Este control impide ese falso verde.
    """
    rutas = _rutas_de(aplicacion)
    examinadas = [c for c, _ in rutas if c not in RUTAS_PRE_MFA_LEGITIMAS]
    assert len(examinadas) >= 40, (
        f"El barrido solo encontró {len(examinadas)} rutas; la enumeración está rota."
    )


def test_las_rutas_declaradas_como_pre_mfa_existen_de_verdad(aplicacion):
    """La lista de excepciones no debe acumular rutas fantasma.

    Una entrada obsoleta en ``RUTAS_PRE_MFA_LEGITIMAS`` es una exención que
    podría volver a aplicarse por accidente a una ruta nueva con ese nombre.
    """
    reales = {c for c, _ in _rutas_de(aplicacion)} | {"/healthz"}
    fantasma = RUTAS_PRE_MFA_LEGITIMAS - reales
    assert not fantasma, f"Exenciones que ya no corresponden a rutas reales: {sorted(fantasma)}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Intentos dirigidos de cambio de etapa (escalada dentro del flujo de login)
# ─────────────────────────────────────────────────────────────────────────────


def test_no_se_puede_reenrolar_el_mfa_con_la_contrasena_conocida(crear_cliente):
    """El vector clásico: registrar MI autenticador en TU cuenta.

    Con MFA ya habilitado, el login deja la sesión en 'mfa_pendiente'. Si desde
    ahí se pudiera alcanzar el enrolamiento, el atacante inscribiría su propio
    dispositivo y el segundo factor dejaría de existir.
    """
    atacante = crear_cliente()
    _sesion_en_etapa_mfa_pendiente(atacante, crear_cliente)

    # Ni la vista de enrolamiento ni su confirmación deben ser alcanzables.
    assert atacante.get("/mfa/configurar").status_code == 303
    assert atacante.get("/api/web/mfa/configurar").status_code == 403

    respuesta = atacante.post(
        "/api/web/mfa/configurar",
        json={"codigo": "000000"},
        headers={"X-CSRF-Token": "cualquiera"},
    )
    assert respuesta.status_code == 403, "Se alcanzó el enrolamiento desde 'mfa_pendiente'"


def test_el_secreto_totp_no_se_expone_a_una_sesion_pre_mfa(crear_cliente):
    """El secreto TOTP nunca debe viajar a una sesión en 'mfa_pendiente'.

    Con el secreto, el atacante genera él mismo los códigos y el MFA se vuelve
    decorativo.
    """
    atacante = crear_cliente()
    _sesion_en_etapa_mfa_pendiente(atacante, crear_cliente)

    for ruta in ("/mfa/configurar", "/api/web/mfa/configurar", "/api/web/session"):
        respuesta = atacante.get(ruta)
        cuerpo = respuesta.text.lower()
        assert "secreto" not in cuerpo or respuesta.status_code in {303, 401, 403}
        assert "qr_data_uri" not in cuerpo
        assert "otpauth://" not in cuerpo


def test_no_se_puede_saltar_el_cambio_forzado_de_contrasena(crear_cliente):
    """Desde 'cambio_password' tampoco se llega al MFA ni a la aplicación."""
    client = crear_cliente()
    _sesion_en_etapa_cambio_password(client)

    assert client.get("/mfa/verificar").status_code == 303
    assert client.get("/api/web/mfa/verificar").status_code == 403
    assert client.get("/api/web/dashboard").status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 3. Reutilización y manipulación del código TOTP (replay con proxy)
# ─────────────────────────────────────────────────────────────────────────────


def test_el_codigo_totp_no_se_puede_reutilizar(crear_cliente):
    """RFC 6238 §5.2: un TOTP ya aceptado no vale una segunda vez.

    Es el ataque directo con Burp: capturar la petición de verificación del
    usuario legítimo y reenviarla desde otra sesión.
    """
    victima = crear_cliente()
    secreto = autenticar_admin(victima)

    # La víctima entra con normalidad: su código queda consumido. Se usa el
    # intervalo siguiente (+30 s) porque el del enrolamiento ya está registrado
    # como usado y sería rechazado por la propia protección anti-reutilización.
    otra_sesion = crear_cliente()
    login_password(otra_sesion, ADMIN_USER, ADMIN_PASS)
    codigo = codigo_totp(secreto, 30)
    csrf = extraer_csrf(otra_sesion.get("/mfa/verificar").text)
    r = otra_sesion.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf})
    assert r.status_code == 303 and r.headers["location"] == "/"

    # El atacante reenvía EXACTAMENTE el mismo código desde su propia sesión.
    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)
    csrf_atacante = extraer_csrf(atacante.get("/mfa/verificar").text)
    replay = atacante.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf_atacante})
    assert replay.status_code != 303, "Se aceptó la reutilización de un código TOTP"
    assert atacante.get("/api/web/dashboard").status_code == 401


def test_el_codigo_totp_no_se_reutiliza_con_espacios_intercalados(crear_cliente):
    """La reutilización no debe poder eludirse cambiando el formato del código.

    Las aplicaciones autenticadoras muestran los códigos como «123 456», así que
    tanto la forma con espacios como sin ellos llegan al servidor en la práctica.
    Si la comparación anti-reutilización no normaliza igual que la validación, el
    mismo código pasa dos veces con solo añadir un espacio en Burp.
    """
    victima = crear_cliente()
    secreto = autenticar_admin(victima)

    sesion = crear_cliente()
    login_password(sesion, ADMIN_USER, ADMIN_PASS)
    codigo = codigo_totp(secreto, 30)  # intervalo distinto al del enrolamiento
    csrf = extraer_csrf(sesion.get("/mfa/verificar").text)
    r = sesion.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf})
    assert r.status_code == 303

    # Mismo código, formateado con un espacio en medio (como lo muestra la app).
    espaciado = f"{codigo[:3]} {codigo[3:]}"
    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)
    csrf_atacante = extraer_csrf(atacante.get("/mfa/verificar").text)
    replay = atacante.post("/mfa/verificar", data={"codigo": espaciado, "csrf_token": csrf_atacante})
    assert replay.status_code != 303, (
        "Se aceptó el mismo TOTP reformateado con espacios: la comparación "
        "anti-reutilización no normaliza igual que la validación"
    )


def test_el_codigo_de_enrolamiento_no_se_puede_reutilizar_para_entrar(crear_cliente):
    """El código que habilitó el MFA tampoco vale como segundo factor después.

    El enrolamiento acepta el código y lo registra como usado; si lo guardara sin
    normalizar (p. ej. con espacios), quedaría reutilizable en el siguiente login
    durante su ventana de validez.
    """
    victima = crear_cliente()

    # Enrolamiento usando el formato con espacios que muestran las apps.
    _sesion_en_etapa_mfa_enrolamiento(victima)
    pagina = victima.get("/mfa/configurar")
    from tests.conftest import extraer_secreto

    secreto = extraer_secreto(pagina.text)
    csrf = extraer_csrf(pagina.text)
    codigo = pyotp.TOTP(secreto).now()
    espaciado = f"{codigo[:3]} {codigo[3:]}"
    r = victima.post("/mfa/configurar", data={"codigo": espaciado, "csrf_token": csrf})
    assert r.status_code == 200, "El enrolamiento debe aceptar el código con espacios"

    # El atacante reutiliza ese mismo código para superar el segundo factor.
    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)
    csrf_atacante = extraer_csrf(atacante.get("/mfa/verificar").text)
    for intento in (codigo, espaciado):
        replay = atacante.post("/mfa/verificar", data={"codigo": intento, "csrf_token": csrf_atacante})
        assert replay.status_code != 303, (
            f"Se reutilizó el código de enrolamiento ({intento!r}) como segundo factor"
        )


def test_el_codigo_de_recuperacion_es_de_un_solo_uso(crear_cliente):
    """Un código de recuperación consumido no vuelve a servir."""
    from tests.conftest import enrolar_mfa_con_codigos

    victima = crear_cliente()
    _sesion_en_etapa_mfa_enrolamiento(victima)
    _secreto, codigos = enrolar_mfa_con_codigos(victima)

    sesion = crear_cliente()
    login_password(sesion, ADMIN_USER, ADMIN_PASS)
    csrf = extraer_csrf(sesion.get("/mfa/verificar").text)
    r = sesion.post("/mfa/verificar", data={"codigo": codigos[0], "csrf_token": csrf})
    assert r.status_code == 303, "El código de recuperación debe funcionar la primera vez"

    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)
    csrf_atacante = extraer_csrf(atacante.get("/mfa/verificar").text)
    replay = atacante.post("/mfa/verificar", data={"codigo": codigos[0], "csrf_token": csrf_atacante})
    assert replay.status_code != 303, "Se reutilizó un código de recuperación"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fuerza bruta del segundo factor
# ─────────────────────────────────────────────────────────────────────────────


def test_la_fuerza_bruta_del_totp_bloquea_la_cuenta(crear_cliente):
    """Intruder de Burp contra los 6 dígitos: la cuenta debe cerrarse.

    Sin bloqueo, un atacante con la contraseña recorrería el espacio de códigos.
    """
    victima = crear_cliente()
    autenticar_admin(victima)

    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)

    bloqueado = False
    for i in range(25):
        pagina = atacante.get("/mfa/verificar")
        if pagina.status_code != 200:
            bloqueado = True  # la sesión ya fue revocada por el bloqueo
            break
        csrf = extraer_csrf(pagina.text)
        respuesta = atacante.post(
            "/mfa/verificar", data={"codigo": f"{i:06d}", "csrf_token": csrf}
        )
        if respuesta.status_code in {303, 423} and respuesta.headers.get("location") == "/login":
            bloqueado = True
            break
        assert respuesta.status_code != 303 or respuesta.headers.get("location") != "/", (
            f"Un código inventado ({i:06d}) superó el segundo factor"
        )

    assert bloqueado, "La fuerza bruta del TOTP no derivó en bloqueo de la cuenta"
    assert atacante.get("/api/web/dashboard").status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 5. Manipulación de la sesión y de la cookie (lo que se hace con Burp)
# ─────────────────────────────────────────────────────────────────────────────


def test_la_cookie_de_sesion_no_es_adivinable_ni_manipulable(crear_cliente):
    """Fijar a mano la cookie de sesión no concede acceso.

    En BD solo vive el hash SHA-256 del token, así que un valor inventado —o el
    propio hash— no resuelve a ninguna sesión.
    """
    atacante = crear_cliente()
    for valor in ("activa", "1", "admin", "a" * 43, "x" * 64):
        atacante.cookies.set("passwd_session", valor)
        assert atacante.get("/api/web/dashboard").status_code == 401
        atacante.cookies.clear()


def test_la_rotacion_del_token_invalida_la_cookie_previa_al_mfa(crear_cliente):
    """Anti fijación de sesión: la cookie de antes del MFA muere al completarlo.

    Si el token no rotara, un atacante que sembrara una cookie conocida en el
    navegador de la víctima la vería convertirse en sesión activa cuando la
    víctima superara el MFA.
    """
    primera = crear_cliente()
    secreto = autenticar_admin(primera)  # deja el MFA habilitado

    victima = crear_cliente()
    login_password(victima, ADMIN_USER, ADMIN_PASS)
    cookie_pre_mfa = victima.cookies.get("passwd_session")
    assert cookie_pre_mfa

    # La víctima completa su segundo factor: el token debe rotar aquí.
    csrf = extraer_csrf(victima.get("/mfa/verificar").text)
    r = victima.post("/mfa/verificar", data={"codigo": codigo_totp(secreto, 30), "csrf_token": csrf})
    assert r.status_code == 303 and r.headers["location"] == "/"

    # El atacante presenta la cookie de antes del MFA: ya no vale nada.
    atacante = crear_cliente()
    atacante.cookies.set("passwd_session", cookie_pre_mfa)
    assert atacante.get("/api/web/dashboard").status_code == 401, (
        "La cookie previa al MFA siguió siendo válida tras completarlo (fijación de sesión)"
    )


def test_el_csrf_es_obligatorio_en_la_verificacion_del_mfa(crear_cliente):
    """Sin CSRF válido, la verificación del MFA no se procesa."""
    victima = crear_cliente()
    autenticar_admin(victima)

    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)
    respuesta = atacante.post("/mfa/verificar", data={"codigo": "000000", "csrf_token": "falso"})
    assert respuesta.status_code == 403

    respuesta_json = atacante.post(
        "/api/web/mfa/verificar", json={"codigo": "000000"}, headers={"X-CSRF-Token": "falso"}
    )
    assert respuesta_json.status_code == 403


def test_el_csrf_de_una_sesion_no_sirve_en_otra(crear_cliente):
    """El token CSRF está ligado a su sesión, no es global."""
    victima = crear_cliente()
    autenticar_admin(victima)

    sesion_a = crear_cliente()
    login_password(sesion_a, ADMIN_USER, ADMIN_PASS)
    csrf_a = extraer_csrf(sesion_a.get("/mfa/verificar").text)

    sesion_b = crear_cliente()
    login_password(sesion_b, ADMIN_USER, ADMIN_PASS)
    respuesta = sesion_b.post("/mfa/verificar", data={"codigo": "000000", "csrf_token": csrf_a})
    assert respuesta.status_code == 403, "El CSRF de otra sesión fue aceptado"


# ─────────────────────────────────────────────────────────────────────────────
# 6. La recuperación de contraseña no es una puerta trasera al MFA
# ─────────────────────────────────────────────────────────────────────────────


def test_la_recuperacion_exige_el_segundo_factor(crear_cliente):
    """El vector clásico: «olvidé mi contraseña» como bypass del MFA.

    Conocer usuario y correo no debe bastar para cambiar la contraseña: hace
    falta el segundo factor. Y completar la recuperación no debe desactivar el
    MFA ni dejar la sesión activa.
    """
    victima = crear_cliente()
    autenticar_admin(victima)

    atacante = crear_cliente()
    csrf_login = atacante.get("/api/web/csrf").json()["csrf_login"]
    inicio = atacante.post(
        "/api/web/password/recuperar/iniciar",
        json={"username": ADMIN_USER, "email": "admin@ejemplo.local", "csrf_login": csrf_login},
    )
    assert inicio.status_code == 200
    csrf_desafio = inicio.json()["csrf"]

    # Sin segundo factor válido, la verificación falla...
    fallo = atacante.post(
        "/api/web/password/recuperar/verificar",
        json={"codigo": "000000"},
        headers={"X-CSRF-Token": csrf_desafio},
    )
    assert fallo.status_code in {401, 400}

    # ...y el paso de cambio queda cerrado aunque se invoque directamente.
    salto = atacante.post(
        "/api/web/password/recuperar/cambiar",
        json={"password_nueva": "Intruso-Total-2026!", "password_confirmacion": "Intruso-Total-2026!"},
        headers={"X-CSRF-Token": csrf_desafio},
    )
    assert salto.status_code == 400, "Se cambió la contraseña sin verificar el segundo factor"

    # La contraseña original sigue siendo la válida.
    comprobacion = crear_cliente()
    r = login_password(comprobacion, ADMIN_USER, ADMIN_PASS)
    assert r.status_code == 303 and r.headers["location"] == "/mfa/verificar"


def test_la_recuperacion_no_deja_sesion_activa_ni_desactiva_el_mfa(crear_cliente):
    """Tras una recuperación legítima sigue exigiéndose el MFA para entrar."""
    from tests.conftest import enrolar_mfa_con_codigos

    victima = crear_cliente()
    _sesion_en_etapa_mfa_enrolamiento(victima)
    _secreto, codigos = enrolar_mfa_con_codigos(victima)

    usuario_legitimo = crear_cliente()
    csrf_login = usuario_legitimo.get("/api/web/csrf").json()["csrf_login"]
    inicio = usuario_legitimo.post(
        "/api/web/password/recuperar/iniciar",
        json={"username": ADMIN_USER, "email": "admin@ejemplo.local", "csrf_login": csrf_login},
    )
    csrf_desafio = inicio.json()["csrf"]
    verif = usuario_legitimo.post(
        "/api/web/password/recuperar/verificar",
        json={"codigo": codigos[0]},
        headers={"X-CSRF-Token": csrf_desafio},
    )
    assert verif.status_code == 200

    nueva = "Recuperada-Segura-2026!"
    cambio = usuario_legitimo.post(
        "/api/web/password/recuperar/cambiar",
        json={"password_nueva": nueva, "password_confirmacion": nueva},
        headers={"X-CSRF-Token": csrf_desafio},
    )
    assert cambio.status_code == 200

    # La recuperación NO concede sesión: hay que volver a pasar por el MFA.
    assert usuario_legitimo.get("/api/web/dashboard").status_code == 401
    despues = crear_cliente()
    r = login_password(despues, ADMIN_USER, nueva)
    assert r.status_code == 303 and r.headers["location"] == "/mfa/verificar", (
        "La recuperación desactivó el MFA o dejó la sesión activa"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Los tokens de API no son una vía alterna sin MFA
# ─────────────────────────────────────────────────────────────────────────────


def test_una_sesion_pre_mfa_no_puede_emitir_tokens_de_api(crear_cliente):
    """Un token de API concede acceso sin MFA: emitirlo debe exigir MFA completo.

    Si una sesión en 'mfa_pendiente' pudiera crear un token, el segundo factor
    sería evitable de forma permanente.
    """
    atacante = crear_cliente()
    _sesion_en_etapa_mfa_pendiente(atacante, crear_cliente)

    for ruta in ("/tokens", "/api/web/tokens"):
        respuesta = atacante.post(ruta, json={"nombre": "intruso"}, headers={"X-CSRF-Token": "x"})
        assert respuesta.status_code in CODIGOS_DE_RECHAZO, (
            f"POST {ruta} → {respuesta.status_code}: una sesión pre-MFA emitió un token"
        )
        assert atacante.get(ruta).status_code in CODIGOS_DE_RECHAZO
