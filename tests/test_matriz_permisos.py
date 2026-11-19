"""Matriz de permisos **generada del registro de rutas** (A4 de `docs/plan-v2.0.md`).

Criterio: *añadir un endpoint sin declarar su política hace fallar la suite*.

Una lista de rutas escrita a mano envejece, y deja de cubrir justo lo que se
añadió después. Aquí la superficie se enumera del registro real
(``tests/rutas.py``) y cada ruta tiene que contestar una de dos cosas: qué
permiso RBAC exige, o por qué no exige ninguno. Una ruta nueva que no conteste
ninguna de las dos rompe la suite, que es cuando conviene enterarse.

Las exenciones se agrupan **por motivo**, no como una lista plana: lo que hay
que poder revisar dentro de un año no es qué rutas están exentas, sino por qué.
"""

from __future__ import annotations

import pytest

from app.models import ROLES_VALIDOS
from app.rbac import PERMISOS, tiene_permiso
from tests.conftest import (
    ADMIN_USER,
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
)
from tests.rutas import concretar, rutas_de

# ── Rutas que legítimamente no exigen un permiso RBAC ────────────────────────

#: El flujo de acceso. Lo gobierna la ETAPA de la sesión, no el rol: en esas
#: etapas el usuario todavía no tiene rol que aplicar. Que ninguna entregue
#: datos antes del segundo factor lo verifica `tests/test_bypass_mfa.py`.
FLUJO_DE_ACCESO = {
    "GET /login", "POST /login", "POST /logout",
    "GET /password/cambiar", "POST /password/cambiar",
    "GET /mfa/configurar", "POST /mfa/configurar",
    "GET /mfa/verificar", "POST /mfa/verificar", "POST /mfa/otp-correo",
    "GET /recuperar", "POST /recuperar",
    "GET /recuperar/verificar", "POST /recuperar/verificar",
    "GET /recuperar/cambiar", "POST /recuperar/cambiar",
    "POST /api/web/login", "POST /api/web/logout",
    "POST /api/web/password/cambiar",
    "GET /api/web/mfa/configurar", "POST /api/web/mfa/configurar",
    "GET /api/web/mfa/configurar/metodos",
    "POST /api/web/mfa/configurar/correo", "POST /api/web/mfa/configurar/correo/enviar",
    "GET /api/web/mfa/verificar", "POST /api/web/mfa/verificar",
    "GET /api/web/mfa/metodos", "POST /api/web/mfa/otp-correo",
    "POST /api/web/password/recuperar/iniciar",
    "POST /api/web/password/recuperar/verificar",
    "POST /api/web/password/recuperar/cambiar",
}

#: «Mi seguridad»: cada usuario actúa sobre su PROPIA cuenta. No hay datos
#: ajenos que proteger, así que no hay permiso que aplicar; el objeto es quien
#: llama. Las acciones de impacto piden reautenticación, no un rol distinto.
CUENTA_PROPIA = {
    "GET /api/web/cuenta/seguridad",
    "POST /api/web/cuenta/mfa/codigos",
    "POST /api/web/cuenta/mfa/totp/iniciar", "POST /api/web/cuenta/mfa/totp/activar",
    "POST /api/web/cuenta/mfa/correo/enviar", "POST /api/web/cuenta/mfa/correo/activar",
}

#: Estado de la sesión del propio titular, y el token CSRF del formulario de
#: acceso (que es anterior a tener sesión).
SESION_PROPIA = {
    "GET /api/web/csrf",
    "GET /api/web/session",
    "POST /api/web/session/extender",
}

#: Sonda de salud: sin datos y sin sesión, por diseño.
PUBLICAS = {"GET /healthz"}

EXENCIONES: dict[str, set[str]] = {
    "flujo de acceso (lo gobierna la etapa de la sesión)": FLUJO_DE_ACCESO,
    "cuenta propia (el objeto es quien llama)": CUENTA_PROPIA,
    "sesión propia": SESION_PROPIA,
    "pública": PUBLICAS,
}

TODAS_LAS_EXENCIONES = {clave for grupo in EXENCIONES.values() for clave in grupo}

# Respuestas que constituyen un rechazo correcto por falta de permisos.
#   303 → la interfaz clásica redirige al acceso
#   401 → no autenticado
#   403 → autenticado, sin permiso
#   404 → el recurso no existe para ese rol (activo restringido)
#   405 → método no permitido
#   422 se queda FUERA: significaría que la petición pasó la autorización y
#   llegó a validar el cuerpo.
CODIGOS_DE_RECHAZO = {303, 401, 403, 404, 405}


def _rutas(aplicacion):
    return rutas_de(aplicacion)


# ---------------------------------------------------------------------------
# 1. Toda ruta declara su política
# ---------------------------------------------------------------------------


def test_toda_ruta_declara_su_politica(aplicacion):
    """El control que hace fallar la suite ante un endpoint nuevo sin política.

    Si esta prueba falla, alguien añadió una ruta sin decidir quién puede
    usarla. No se arregla añadiéndola a las exenciones por inercia: se arregla
    poniéndole su `requiere_permiso`, o declarando y justificando por qué no lo
    lleva.
    """
    sin_politica = [
        r.clave for r in _rutas(aplicacion)
        if r.permiso is None and r.clave not in TODAS_LAS_EXENCIONES
    ]
    assert not sin_politica, (
        "Rutas sin permiso RBAC y sin exención justificada:\n  "
        + "\n  ".join(sorted(sin_politica))
    )


def test_no_hay_exenciones_fantasma(aplicacion):
    """Una exención que ya no corresponde a ninguna ruta es una trampa.

    Quedaría lista para reaplicarse por accidente a una ruta nueva que reutilice
    ese camino, y nadie lo notaría.
    """
    reales = {r.clave for r in _rutas(aplicacion)}
    fantasma = {clave for clave in TODAS_LAS_EXENCIONES if clave not in reales}
    assert not fantasma, f"Exenciones que ya no corresponden a rutas reales: {sorted(fantasma)}"


def test_ninguna_ruta_exenta_exige_ademas_un_permiso(aplicacion):
    """Una ruta no puede estar en los dos sitios: o declara permiso, o está exenta."""
    confusas = [
        r.clave for r in _rutas(aplicacion)
        if r.permiso is not None and r.clave in TODAS_LAS_EXENCIONES
    ]
    assert not confusas, (
        "Rutas que exigen permiso y además figuran como exentas (retire la exención):\n  "
        + "\n  ".join(sorted(confusas))
    )


def test_los_permisos_declarados_existen_en_la_matriz(aplicacion):
    """Una errata en el nombre del permiso dejaría la ruta inalcanzable para todos."""
    desconocidos = sorted({
        r.permiso for r in _rutas(aplicacion)
        if r.permiso is not None and r.permiso not in PERMISOS
    })
    assert not desconocidos, f"Permisos que no existen en app/rbac.py: {desconocidos}"


def test_el_barrido_cubre_una_superficie_representativa(aplicacion):
    """Red de seguridad de la propia enumeración.

    Si un refactor rompiera el recorrido del registro, las pruebas anteriores
    pasarían en vacío sin verificar nada.
    """
    rutas = _rutas(aplicacion)
    assert len(rutas) >= 150, f"Solo se enumeraron {len(rutas)} rutas; el recorrido está roto."
    assert sum(1 for r in rutas if r.permiso) >= 100


# ---------------------------------------------------------------------------
# 2. La matriz rol × permiso se cumple de verdad
# ---------------------------------------------------------------------------
#
# Se prueba UNA ruta representativa por permiso y no las 136 por cada rol: el
# bloque anterior ya garantiza que toda ruta declara su política, y la
# comprobación la hace la misma dependencia para todas. Probar las 136 × 4
# añadiría cientos de peticiones a la suite sin cubrir nada nuevo.


def _representativa(aplicacion) -> dict[str, tuple[str, str]]:
    """Un `(método, camino)` por permiso, prefiriendo GET (sin CSRF ni cuerpo)."""
    por_permiso: dict[str, tuple[str, str]] = {}
    for ruta in _rutas(aplicacion):
        if ruta.permiso is None:
            continue
        actual = por_permiso.get(ruta.permiso)
        if actual is None or (actual[0] != "GET" and ruta.metodo == "GET"):
            por_permiso[ruta.permiso] = (ruta.metodo, ruta.camino)
    return por_permiso


@pytest.fixture()
def clientes_por_rol(client, crear_cliente):
    """Un cliente autenticado por cada rol, sobre la misma aplicación."""
    autenticar_admin(client)
    clientes = {"admin": client}
    for rol in ("operador", "auditor", "analista"):
        clave = crear_usuario(client, f"{rol}-matriz", rol)
        sesion = crear_cliente()
        autenticar_usuario_nuevo(sesion, f"{rol}-matriz", clave)
        clientes[rol] = sesion
    return clientes


def test_cada_rol_es_rechazado_en_los_permisos_que_no_tiene(aplicacion, clientes_por_rol):
    """El corazón de la matriz: lo que `app/rbac.py` niega, la aplicación lo niega.

    Un fallo aquí significa que la matriz de permisos y lo que el servidor hace
    de verdad se separaron, que es el escenario en el que alguien cree estar
    protegido y no lo está.
    """
    representativas = _representativa(aplicacion)
    assert representativas, "no se encontró ninguna ruta con permiso declarado"

    fugas = []
    for permiso, (metodo, camino) in sorted(representativas.items()):
        for rol in ROLES_VALIDOS:
            if tiene_permiso(rol, permiso):
                continue
            sesion = clientes_por_rol[rol]
            cabeceras = {"X-CSRF-Token": csrf_de(sesion, "/")} if metodo != "GET" else {}
            respuesta = sesion.request(metodo, concretar(camino), headers=cabeceras)
            if respuesta.status_code not in CODIGOS_DE_RECHAZO:
                fugas.append(
                    f"{rol} alcanzó {metodo} {camino} (permiso «{permiso}») "
                    f"→ {respuesta.status_code}"
                )

    assert not fugas, "La matriz de permisos no se aplica:\n  " + "\n  ".join(fugas)


def test_el_administrador_si_alcanza_lo_que_la_matriz_le_concede(aplicacion, clientes_por_rol):
    """Contrapeso: sin esto, una aplicación que lo rechace TODO pasaría la prueba anterior."""
    representativas = _representativa(aplicacion)
    admin = clientes_por_rol["admin"]

    alcanzadas = 0
    for permiso, (metodo, camino) in representativas.items():
        if metodo != "GET" or not tiene_permiso("admin", permiso):
            continue
        if admin.get(concretar(camino)).status_code not in CODIGOS_DE_RECHAZO:
            alcanzadas += 1
    assert alcanzadas >= 5, (
        f"El administrador solo alcanzó {alcanzadas} rutas: la prueba de rechazos "
        "podría estar pasando porque la aplicación rechaza todo."
    )
    assert ADMIN_USER
