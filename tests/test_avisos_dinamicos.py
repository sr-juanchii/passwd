"""Pruebas de los avisos dinámicos, el MFA por correo y el reset administrativo.

Cubre las tres funcionalidades nuevas:

1. **MFA de respaldo por OTP al correo**: emisión, un solo uso, caducidad, tope de
   intentos, límite de tasa y que no sea una vía de entrada por sí sola.
2. **Restablecimiento administrativo**: la contraseña temporal viaja al correo del
   titular y NO se devuelve al administrador; exclusivo de administradores.
3. **Avisos dinámicos por matriz de permisos**: actividad propia, cambios en los
   permisos propios, credenciales compartidas y caducidad de rotación.

Invariante transversal verificada aquí
--------------------------------------
Ningún aviso sobre una credencial de servidor incluye la contraseña, ni la
anterior, ni la nueva. Los avisos comunican **el hecho, no el secreto**. Es la
propiedad que más fácilmente se rompería en un cambio futuro —basta añadir un
campo «útil» al cuerpo del correo— así que se comprueba de forma explícita contra
el texto real de los mensajes capturados.

El SMTP se sustituye por un capturador en memoria (``correos``), de modo que las
pruebas verifican destinatarios y CONTENIDO real sin enviar nada.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from tests.conftest import (
    ADMIN_PASS,
    ADMIN_USER,
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    extraer_csrf,
    login_password,
    sesion_bd,
)
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_servidor

RE_OTP = re.compile(r"CÓDIGO:\s*(\d{8})")


@pytest.fixture()
def correos(aplicacion, monkeypatch):
    """Captura los correos en memoria y habilita el correo y los avisos.

    Sustituye ``_enviar_smtp`` (el único punto de salida real) por un capturador,
    y enciende ``notify_enabled``/``notify_users_enabled`` sobre el singleton de
    configuración ya construido por la fixture ``aplicacion``.
    """
    from app import notifications
    from app.config import get_settings

    enviados: list[dict] = []

    def _capturar(settings, destinatarios, asunto, cuerpo):
        enviados.append({
            "para": list(destinatarios),
            "asunto": asunto,
            "cuerpo": cuerpo,
        })

    monkeypatch.setattr(notifications, "_enviar_smtp", _capturar)
    settings = get_settings()
    monkeypatch.setattr(settings, "notify_enabled", True, raising=False)
    monkeypatch.setattr(settings, "notify_users_enabled", True, raising=False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.pruebas.local", raising=False)
    monkeypatch.setattr(settings, "email_otp_enabled", True, raising=False)
    return enviados


def _para(correos, fragmento_asunto):
    """Correos cuyo asunto contiene el fragmento."""
    return [c for c in correos if fragmento_asunto.lower() in c["asunto"].lower()]


def _destinatarios(correos, fragmento_asunto) -> set[str]:
    return {d for c in _para(correos, fragmento_asunto) for d in c["para"]}


def _id_usuario(username: str) -> int:
    db = sesion_bd()
    try:
        from app.models import Usuario

        return db.scalar(select(Usuario.id).where(Usuario.username == username))
    finally:
        db.close()


def _id_credencial() -> int:
    db = sesion_bd()
    try:
        from app.models import Credencial

        return db.scalar(select(Credencial.id))
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# 1. MFA de respaldo: OTP enviado al correo
# ═════════════════════════════════════════════════════════════════════════════


def test_otp_correo_permite_completar_el_mfa_sin_el_dispositivo(client, crear_cliente, correos):
    """El usuario sin su aplicación autenticadora entra con el código del correo."""
    autenticar_admin(client)  # deja el MFA habilitado

    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)
    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)

    solicitud = usuario.post("/mfa/otp-correo", data={"csrf_token": csrf})
    assert solicitud.status_code == 200

    mensajes = _para(correos, "Código de verificación")
    assert len(mensajes) == 1, "Debe enviarse exactamente un correo con el código"
    codigo = RE_OTP.search(mensajes[0]["cuerpo"])
    assert codigo, f"No se encontró el código en el correo:\n{mensajes[0]['cuerpo']}"

    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    entrada = usuario.post("/mfa/verificar", data={"codigo": codigo.group(1), "csrf_token": csrf})
    assert entrada.status_code == 303, "El OTP del correo debe completar el segundo factor"
    assert usuario.get("/api/web/dashboard").status_code == 200


def test_el_otp_de_correo_es_de_un_solo_uso(client, crear_cliente, correos):
    """Un OTP consumido no vuelve a servir (ni en otra sesión)."""
    autenticar_admin(client)

    primero = crear_cliente()
    login_password(primero, ADMIN_USER, ADMIN_PASS)
    csrf = extraer_csrf(primero.get("/mfa/verificar").text)
    primero.post("/mfa/otp-correo", data={"csrf_token": csrf})
    codigo = RE_OTP.search(_para(correos, "Código de verificación")[0]["cuerpo"]).group(1)

    csrf = extraer_csrf(primero.get("/mfa/verificar").text)
    assert primero.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf}).status_code == 303

    # Reenvío del mismo código desde otra sesión (replay con proxy).
    atacante = crear_cliente()
    login_password(atacante, ADMIN_USER, ADMIN_PASS)
    csrf_a = extraer_csrf(atacante.get("/mfa/verificar").text)
    replay = atacante.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf_a})
    assert replay.status_code != 303, "Se reutilizó un OTP de correo ya consumido"
    assert atacante.get("/api/web/dashboard").status_code == 401


def test_emitir_un_otp_nuevo_invalida_el_anterior(client, crear_cliente, correos):
    """Solo hay un código vivo por cuenta: pedir otro anula el previo."""
    autenticar_admin(client)
    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)

    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    usuario.post("/mfa/otp-correo", data={"csrf_token": csrf})
    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    usuario.post("/mfa/otp-correo", data={"csrf_token": csrf})

    mensajes = _para(correos, "Código de verificación")
    assert len(mensajes) == 2
    primer_codigo = RE_OTP.search(mensajes[0]["cuerpo"]).group(1)
    segundo_codigo = RE_OTP.search(mensajes[1]["cuerpo"]).group(1)
    assert primer_codigo != segundo_codigo

    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    viejo = usuario.post("/mfa/verificar", data={"codigo": primer_codigo, "csrf_token": csrf})
    assert viejo.status_code != 303, "El código anterior debió quedar invalidado"


def test_el_otp_de_correo_caduca(client, crear_cliente, correos, monkeypatch):
    """Pasado el TTL, el código ya no sirve."""
    from app.config import get_settings

    autenticar_admin(client)
    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)
    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    usuario.post("/mfa/otp-correo", data={"csrf_token": csrf})
    codigo = RE_OTP.search(_para(correos, "Código de verificación")[0]["cuerpo"]).group(1)

    # Se envejece el registro más allá de su caducidad.
    import datetime

    from app.models import CodigoOtpCorreo

    db = sesion_bd()
    try:
        registro = db.scalar(select(CodigoOtpCorreo).order_by(CodigoOtpCorreo.id.desc()))
        registro.expira_en = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    caducado = usuario.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf})
    assert caducado.status_code != 303, "Se aceptó un OTP de correo caducado"
    assert get_settings().email_otp_ttl_minutes > 0


def test_el_otp_de_correo_no_es_una_via_de_entrada_sin_contrasena(client, crear_cliente, correos):
    """Sin sesión en 'mfa_pendiente' no se puede pedir un OTP.

    Es la propiedad que evita que el método de respaldo se convierta en un salto
    del MFA: exige la contraseña válida primero.
    """
    autenticar_admin(client)
    anonimo = crear_cliente()
    assert anonimo.post("/mfa/otp-correo", data={"csrf_token": "x"}).status_code == 303
    assert anonimo.post("/api/web/mfa/otp-correo", headers={"X-CSRF-Token": "x"}).status_code == 403
    assert not _para(correos, "Código de verificación")


def test_pedir_otp_exige_csrf(client, crear_cliente, correos):
    """Sin CSRF válido no se emite ni se envía ningún código."""
    autenticar_admin(client)
    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)
    respuesta = usuario.post("/mfa/otp-correo", data={"csrf_token": "falso"})
    assert respuesta.status_code == 403
    assert not _para(correos, "Código de verificación")


def test_el_otp_de_correo_tiene_limite_de_tasa(client, crear_cliente, correos):
    """No se puede inundar el buzón de un usuario ni usar el sistema de relé."""
    autenticar_admin(client)
    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)

    codigos_respuesta = []
    for _ in range(6):
        pagina = usuario.get("/mfa/verificar")
        if pagina.status_code != 200:
            break
        csrf = extraer_csrf(pagina.text)
        codigos_respuesta.append(usuario.post("/mfa/otp-correo", data={"csrf_token": csrf}).status_code)

    assert 429 in codigos_respuesta, f"No se aplicó límite de tasa: {codigos_respuesta}"
    assert len(_para(correos, "Código de verificación")) <= 3


def test_el_otp_desactivado_no_esta_disponible(client, crear_cliente, correos, monkeypatch):
    """Con PASSWD_EMAIL_OTP_ENABLED=false el método de respaldo desaparece."""
    from app.config import get_settings

    autenticar_admin(client)
    monkeypatch.setattr(get_settings(), "email_otp_enabled", False, raising=False)

    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)
    pagina = usuario.get("/mfa/verificar")
    assert "Enviarme un código por correo" not in pagina.text
    csrf = extraer_csrf(pagina.text)
    assert usuario.post("/mfa/otp-correo", data={"csrf_token": csrf}).status_code == 409
    assert not _para(correos, "Código de verificación")


def test_el_uso_del_otp_de_correo_queda_auditado(client, crear_cliente, correos):
    """Un acceso por el factor de respaldo debe ser rastreable en la bitácora."""
    from app import audit
    from app.models import RegistroAuditoria

    autenticar_admin(client)
    usuario = crear_cliente()
    login_password(usuario, ADMIN_USER, ADMIN_PASS)
    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    usuario.post("/mfa/otp-correo", data={"csrf_token": csrf})
    codigo = RE_OTP.search(_para(correos, "Código de verificación")[0]["cuerpo"]).group(1)
    csrf = extraer_csrf(usuario.get("/mfa/verificar").text)
    usuario.post("/mfa/verificar", data={"codigo": codigo, "csrf_token": csrf})

    db = sesion_bd()
    try:
        acciones = set(db.scalars(select(RegistroAuditoria.accion)).all())
    finally:
        db.close()
    assert audit.MFA_OTP_CORREO_SOLICITADO in acciones
    assert audit.MFA_OTP_CORREO_USADO in acciones


# ═════════════════════════════════════════════════════════════════════════════
# 2. Restablecimiento administrativo de contraseña por correo
# ═════════════════════════════════════════════════════════════════════════════


def test_el_reset_envia_la_password_al_usuario_y_no_la_muestra(client, crear_cliente, correos):
    """La contraseña temporal va al buzón del titular, no a la pantalla del admin."""
    autenticar_admin(client)
    crear_usuario(client, "operador1", "operador")
    uid = _id_usuario("operador1")

    csrf = csrf_de(client, "/usuarios")
    respuesta = client.post(f"/usuarios/{uid}/reset-password", data={"csrf_token": csrf})
    assert respuesta.status_code == 200

    mensajes = _para(correos, "contraseña ha sido restablecida")
    assert len(mensajes) == 1
    assert mensajes[0]["para"] == ["operador1@ejemplo.local"]

    # La contraseña temporal está en el correo...
    cuerpo = mensajes[0]["cuerpo"]
    encontrada = re.search(r"CONTRASEÑA TEMPORAL:\s*(\S+)", cuerpo)
    assert encontrada, f"El correo debe llevar la contraseña temporal:\n{cuerpo}"
    temporal = encontrada.group(1)

    # ...y NO en la respuesta que ve el administrador.
    assert temporal not in respuesta.text, (
        "La contraseña temporal apareció en la pantalla del administrador"
    )
    # La plantilla parte la frase en varias líneas: se normalizan los espacios.
    pantalla = " ".join(respuesta.text.split())
    assert "se envió a su correo registrado" in pantalla

    # Y funciona de verdad: el usuario entra y se le fuerza el cambio.
    nuevo = crear_cliente()
    r = login_password(nuevo, "operador1", temporal)
    assert r.status_code == 303 and r.headers["location"] == "/password/cambiar"


def test_el_reset_por_api_no_devuelve_la_password_si_el_correo_sale(client, correos):
    """La API JSON confirma el envío sin incluir el secreto."""
    autenticar_admin(client)
    crear_usuario(client, "operador2", "operador")
    uid = _id_usuario("operador2")

    csrf = csrf_de(client, "/usuarios")
    respuesta = client.post(f"/api/web/usuarios/{uid}/reset-password",
                            headers={"X-CSRF-Token": csrf})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["correo_enviado"] is True
    assert "password_temporal" not in cuerpo, "La API no debe devolver el secreto"
    # El destino va enmascarado: confirma el buzón sin exponer la dirección.
    assert cuerpo["destino"].endswith("@ejemplo.local")
    assert "*" in cuerpo["destino"]


def test_si_el_correo_falla_el_admin_recibe_la_password_de_contingencia(client, correos, monkeypatch):
    """Sin correo, la cuenta no puede quedar con una contraseña que nadie conoce."""
    from app import notifications

    autenticar_admin(client)
    crear_usuario(client, "operador3", "operador")
    uid = _id_usuario("operador3")

    def _fallar(*_a, **_k):
        raise OSError("SMTP caído")

    monkeypatch.setattr(notifications, "_enviar_smtp", _fallar)

    csrf = csrf_de(client, "/usuarios")
    respuesta = client.post(f"/api/web/usuarios/{uid}/reset-password",
                            headers={"X-CSRF-Token": csrf})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["correo_enviado"] is False
    assert cuerpo["password_temporal"], "Sin correo, el admin necesita el valor"
    assert "no se pudo enviar" in cuerpo["aviso"].lower()


def test_el_reset_es_exclusivo_de_administradores(client, crear_cliente, correos):
    """Ningún rol distinto de admin puede ejecutar el restablecimiento."""
    autenticar_admin(client)
    uid_admin = _id_usuario(ADMIN_USER)

    for username, rol in (("operador9", "operador"), ("auditor9", "auditor"), ("analista9", "analista")):
        clave = crear_usuario(client, username, rol)
        cli = crear_cliente()
        autenticar_usuario_nuevo(cli, username, clave)
        respuesta = cli.post(f"/api/web/usuarios/{uid_admin}/reset-password",
                             headers={"X-CSRF-Token": "x"})
        assert respuesta.status_code == 403, (
            f"El rol {rol} pudo restablecer una contraseña ({respuesta.status_code})"
        )
    assert not _para(correos, "contraseña ha sido restablecida")


# ═════════════════════════════════════════════════════════════════════════════
# 3. Avisos dinámicos por matriz de permisos
# ═════════════════════════════════════════════════════════════════════════════


def test_aviso_de_inicio_de_sesion_al_titular(client, correos):
    """Cada usuario recibe aviso de la apertura de sesión con su cuenta."""
    autenticar_admin(client)
    mensajes = _para(correos, "Inicio de sesión")
    assert mensajes, "Debe avisarse del inicio de sesión"
    assert mensajes[0]["para"] == ["admin@ejemplo.local"]
    assert "Dirección IP" in mensajes[0]["cuerpo"]


def test_aviso_al_usuario_cuando_cambian_sus_permisos(client, crear_cliente, correos):
    """Conceder y revocar acceso avisa al titular de la concesión."""
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-avisos", "web")
    clave = crear_usuario(client, "analista2", "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, "analista2", clave)
    uid = _id_usuario("analista2")

    csrf = csrf_de(client, "/")
    client.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    concedidos = _para(correos, "Cambio en sus permisos")
    assert concedidos, "Debe avisarse al conceder acceso"
    assert concedidos[-1]["para"] == ["analista2@ejemplo.local"]
    assert "CONCEDIDO" in concedidos[-1]["cuerpo"]
    assert "srv-avisos" in concedidos[-1]["cuerpo"]

    db = sesion_bd()
    try:
        from app.models import ConcesionAcceso

        concesion_id = db.scalar(select(ConcesionAcceso.id).where(ConcesionAcceso.usuario_id == uid))
    finally:
        db.close()

    csrf = csrf_de(client, "/")
    client.post(f"/accesos/{concesion_id}/revocar", data={"csrf_token": csrf})
    revocados = [c for c in _para(correos, "Cambio en sus permisos") if "REVOCADO" in c["cuerpo"]]
    assert revocados, "Debe avisarse al revocar acceso"
    assert revocados[-1]["para"] == ["analista2@ejemplo.local"]


def test_aviso_al_usuario_cuando_cambia_su_rol(client, correos):
    """Un cambio de rol altera los permisos y debe notificarse al titular."""
    autenticar_admin(client)
    crear_usuario(client, "operador4", "operador")
    uid = _id_usuario("operador4")

    csrf = csrf_de(client, "/usuarios")
    client.post(f"/usuarios/{uid}/rol", data={"rol": "auditor", "csrf_token": csrf})

    mensajes = [c for c in _para(correos, "Cambio en sus permisos") if "Rol modificado" in c["cuerpo"]]
    assert mensajes, "Debe avisarse del cambio de rol"
    assert mensajes[-1]["para"] == ["operador4@ejemplo.local"]
    assert "auditor" in mensajes[-1]["cuerpo"]


def test_aviso_a_los_demas_usuarios_con_acceso_al_cambiar_una_credencial(
    client, crear_cliente, correos
):
    """El resto de usuarios con acceso al activo recibe aviso de la modificación."""
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-compartido", "bd")
    _crear_credencial(client, "fisico", servidor, "root")
    credencial_id = _id_credencial()

    # Un analista con acceso al activo, y otro SIN acceso (no debe recibir nada).
    clave = crear_usuario(client, "conacceso", "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, "conacceso", clave)
    uid = _id_usuario("conacceso")
    csrf = csrf_de(client, "/")
    client.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    clave2 = crear_usuario(client, "sinacceso", "analista")
    cli2 = crear_cliente()
    autenticar_usuario_nuevo(cli2, "sinacceso", clave2)

    correos.clear()

    # El admin rota la contraseña de la credencial compartida.
    csrf = csrf_de(client, f"/credenciales/{credencial_id}/editar")
    respuesta = client.post(f"/credenciales/{credencial_id}/editar", data={
        "usuario_acceso": "root", "password": "Nueva-Clave-Rotada-2026!",
        "servicio": "SSH", "puerto": "22", "descripcion": "", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303

    avisados = _destinatarios(correos, "Contraseña actualizada")
    assert "conacceso@ejemplo.local" in avisados, "El usuario con acceso debe ser avisado"
    assert "sinacceso@ejemplo.local" not in avisados, (
        "Un usuario SIN acceso al activo no debe recibir el aviso"
    )
    assert "admin@ejemplo.local" not in avisados, "El autor del cambio no se avisa a sí mismo"


def test_el_aviso_de_credencial_nunca_incluye_la_contrasena(client, crear_cliente, correos):
    """INVARIANTE CENTRAL: el aviso comunica el hecho, nunca el secreto.

    Se comprueba contra el texto real del correo, con la contraseña ANTERIOR y la
    NUEVA. Si alguien añadiera al cuerpo el valor «para comodidad del usuario»,
    esta prueba lo detiene.
    """
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-secretos", "bd")
    _crear_credencial(client, "fisico", servidor, "root")
    credencial_id = _id_credencial()

    clave = crear_usuario(client, "colega", "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, "colega", clave)
    uid = _id_usuario("colega")
    csrf = csrf_de(client, "/")
    client.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    correos.clear()

    NUEVA = "Ultra-Secreta-Rotada-2026!"
    csrf = csrf_de(client, f"/credenciales/{credencial_id}/editar")
    client.post(f"/credenciales/{credencial_id}/editar", data={
        "usuario_acceso": "root", "password": NUEVA,
        "servicio": "SSH", "puerto": "22", "descripcion": "", "csrf_token": csrf,
    })

    mensajes = _para(correos, "Contraseña actualizada")
    assert mensajes, "Debe haberse enviado el aviso"
    for mensaje in mensajes:
        texto = mensaje["cuerpo"]
        assert NUEVA not in texto, "¡El aviso filtró la contraseña NUEVA!"
        assert CLAVE_SECRETA not in texto, "¡El aviso filtró la contraseña ANTERIOR!"
        # Sí debe decir QUÉ pasó y sobre qué activo.
        assert "srv-secretos" in texto
        assert "Se actualizó la CONTRASEÑA" in texto
        assert "admin" in texto


def test_ningun_aviso_dinamico_contiene_secretos_del_inventario(client, crear_cliente, correos):
    """Barrido: ningún correo emitido en un flujo completo lleva una contraseña."""
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-barrido", "web")
    _crear_credencial(client, "fisico", servidor, "root")
    credencial_id = _id_credencial()

    clave = crear_usuario(client, "analista5", "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, "analista5", clave)
    uid = _id_usuario("analista5")
    csrf = csrf_de(client, "/")
    client.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    # El analista revela la credencial (genera aviso de actividad sensible).
    csrf_cli = csrf_de(cli, f"/servidores/{servidor}")
    cli.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf_cli})

    NUEVA = "Barrido-Secreto-2026!"
    csrf = csrf_de(client, f"/credenciales/{credencial_id}/editar")
    client.post(f"/credenciales/{credencial_id}/editar", data={
        "usuario_acceso": "root", "password": NUEVA,
        "servicio": "SSH", "puerto": "22", "descripcion": "", "csrf_token": csrf,
    })

    assert correos, "El flujo debió generar avisos"
    for mensaje in correos:
        # Se excluyen los dos secretos legítimos y de un solo uso (OTP del MFA y
        # contraseña temporal de reset), que van al buzón de su propio titular.
        if "restablecid" in mensaje["asunto"].lower() or "verificación" in mensaje["asunto"].lower():
            continue
        assert NUEVA not in mensaje["cuerpo"], f"Secreto filtrado en «{mensaje['asunto']}»"
        assert CLAVE_SECRETA not in mensaje["cuerpo"], f"Secreto filtrado en «{mensaje['asunto']}»"


def test_aviso_de_actividad_sensible_se_deduplica_por_sesion(client, crear_cliente, correos):
    """Revelar varias credenciales en una sesión genera UN aviso, no una lluvia."""
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-dedup", "web")
    _crear_credencial(client, "fisico", servidor, "root")
    credencial_id = _id_credencial()
    correos.clear()

    for _ in range(4):
        csrf = csrf_de(client, f"/servidores/{servidor}")
        client.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf})

    mensajes = _para(correos, "Actividad sensible")
    assert len(mensajes) == 1, f"Se esperaba un único aviso por sesión, hubo {len(mensajes)}"


# ═════════════════════════════════════════════════════════════════════════════
# 3c. Alertas preventivas de caducidad (rotación)
# ═════════════════════════════════════════════════════════════════════════════


def _envejecer_credencial(credencial_id: int, dias: int) -> None:
    """Mueve ``password_rotada_en`` al pasado para simular antigüedad."""
    import datetime

    from app.models import Credencial

    db = sesion_bd()
    try:
        credencial = db.get(Credencial, credencial_id)
        credencial.password_rotada_en = datetime.datetime.utcnow() - datetime.timedelta(days=dias)
        db.commit()
    finally:
        db.close()


def test_aviso_de_rotacion_proxima_a_quienes_usan_la_credencial(client, crear_cliente, correos):
    """Al entrar en la ventana de preaviso se notifica a quienes pueden rotarla."""
    from app import avisos
    from app.config import get_settings

    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-rotacion", "bd")
    _crear_credencial(client, "fisico", servidor, "root")
    credencial_id = _id_credencial()

    # Analista que puede revelar (debe recibir el aviso) y auditor (no debe:
    # ve el activo pero nunca sus secretos, así que no rota contraseñas).
    clave = crear_usuario(client, "rotador", "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, "rotador", clave)
    uid = _id_usuario("rotador")
    csrf = csrf_de(client, "/")
    client.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    clave_aud = crear_usuario(client, "auditor5", "auditor")
    cli_aud = crear_cliente()
    autenticar_usuario_nuevo(cli_aud, "auditor5", clave_aud)

    settings = get_settings()
    # Justo dentro de la ventana de preaviso.
    _envejecer_credencial(credencial_id, settings.rotation_max_days - 3)
    correos.clear()

    db = sesion_bd()
    try:
        resumen = avisos.revisar_rotaciones(db)
        db.commit()
    finally:
        db.close()

    assert resumen["avisos_enviados"] > 0, f"No se enviaron avisos de rotación: {resumen}"
    avisados = _destinatarios(correos, "Rotación próxima")
    assert "rotador@ejemplo.local" in avisados, "Quien puede rotar debe ser avisado"
    assert "auditor5@ejemplo.local" not in avisados, (
        "El auditor no revela contraseñas: no le corresponde el aviso de rotación"
    )
    for mensaje in _para(correos, "Rotación próxima"):
        assert CLAVE_SECRETA not in mensaje["cuerpo"], "El aviso de rotación filtró el secreto"
        assert "srv-rotacion" in mensaje["cuerpo"]


def test_rotacion_vencida_se_distingue_de_proxima(client, correos):
    """Una rotación ya vencida se comunica como tal."""
    from app import avisos

    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-vencido", "bd")
    _crear_credencial(client, "fisico", servidor, "root")
    credencial_id = _id_credencial()

    from app.config import get_settings

    _envejecer_credencial(credencial_id, get_settings().rotation_max_days + 10)
    correos.clear()

    db = sesion_bd()
    try:
        avisos.revisar_rotaciones(db)
        db.commit()
    finally:
        db.close()

    vencidos = _para(correos, "Rotación VENCIDA")
    assert vencidos, "Debe distinguirse una rotación ya vencida"
    assert "VENCIÓ hace" in vencidos[0]["cuerpo"]


def test_las_credenciales_recientes_no_generan_aviso(client, correos):
    """Fuera de la ventana de preaviso no se molesta a nadie."""
    from app import avisos

    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-reciente", "bd")
    _crear_credencial(client, "fisico", servidor, "root")
    correos.clear()

    db = sesion_bd()
    try:
        resumen = avisos.revisar_rotaciones(db)
        db.commit()
    finally:
        db.close()

    assert resumen["avisos_enviados"] == 0
    assert not _para(correos, "Rotación")


def test_el_aviso_de_rotacion_no_se_repite_a_diario(client, correos):
    """Ejecutar la tarea programada dos veces no duplica el aviso."""
    from app import avisos
    from app.config import get_settings

    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-diario", "bd")
    _crear_credencial(client, "fisico", servidor, "root")
    _envejecer_credencial(_id_credencial(), get_settings().rotation_max_days - 2)
    correos.clear()

    db = sesion_bd()
    try:
        primero = avisos.revisar_rotaciones(db)
        db.commit()
        segundo = avisos.revisar_rotaciones(db)
        db.commit()
    finally:
        db.close()

    assert primero["avisos_enviados"] > 0
    assert segundo["avisos_enviados"] == 0, (
        "La segunda ejecución del día volvió a avisar; falta la deduplicación"
    )


def test_los_avisos_no_se_envian_si_estan_desactivados(client, crear_cliente, monkeypatch):
    """Con el correo apagado (por defecto) no sale ningún aviso dinámico."""
    from app import notifications

    enviados: list[dict] = []
    monkeypatch.setattr(
        notifications, "_enviar_smtp",
        lambda s, d, a, c: enviados.append({"para": d, "asunto": a, "cuerpo": c}),
    )
    # No se toca la configuración: notify_enabled es False por defecto.
    autenticar_admin(client)
    assert not enviados, "Con las notificaciones apagadas no debe salir ningún correo"
