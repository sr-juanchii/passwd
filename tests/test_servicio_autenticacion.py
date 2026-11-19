"""Pruebas del caso de uso de autenticación **sin HTTP**.

Criterio A1 de [`docs/plan-v2.0.md`](../docs/plan-v2.0.md). Aquí importa más que
en ningún otro servicio: el login es la puerta, y hasta la 1.3.0 estaba escrito
dos veces —una por interfaz— con el mismo CSRF de doble cookie, el mismo límite
por IP, el mismo hash ficticio y el mismo bloqueo. Verificar esas reglas una
sola vez, en el servicio, es lo que impide que una de las dos copias se quede
atrás.

Nada de ``TestClient``: sesión de base de datos y objetos del dominio.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.conftest import sesion_bd

PASSWORD = "Clave-Del-Servicio-2026!"
CSRF = "token-csrf-de-login"


@pytest.fixture()
def db(aplicacion):
    sesion = sesion_bd()
    try:
        yield sesion
    finally:
        sesion.close()


def _usuario(db, username="usuaria", *, rol="operador", activo=True,
             debe_cambiar=False, mfa=True, password=PASSWORD):
    from app.models import Usuario
    from app.security.passwords import hashear_password

    usuario = Usuario(
        username=username, email=f"{username}@ejemplo.local", nombre_completo=username,
        password_hash=hashear_password(password), rol=rol, mfa_habilitado=mfa,
        activo=activo, debe_cambiar_password=debe_cambiar,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _entrar(db, **kwargs):
    """Todo se pasa por nombre: un parámetro posicional aquí se tragaría el
    `username` de quien llame y la prueba pasaría por el motivo equivocado."""
    from app.servicios.autenticacion import iniciar_sesion

    datos = {"username": "usuaria", "password": PASSWORD,
             "csrf_login": CSRF, "cookie_csrf": CSRF}
    datos.update(kwargs)
    return iniciar_sesion(db, **datos)


# ---------------------------------------------------------------------------
# Etapa inicial
# ---------------------------------------------------------------------------


def test_la_etapa_inicial_sale_del_estado_de_la_cuenta(db):
    from app.servicios.autenticacion import etapa_inicial

    assert etapa_inicial(_usuario(db, "a", debe_cambiar=True)) == "cambio_password"
    assert etapa_inicial(_usuario(db, "b", mfa=False)) == "mfa_enrolamiento"
    assert etapa_inicial(_usuario(db, "c")) == "mfa_pendiente"


def test_el_cambio_forzado_manda_sobre_el_segundo_factor(db):
    """Una contraseña temporal se cambia ANTES de llegar al MFA."""
    from app.servicios.autenticacion import etapa_inicial

    usuario = _usuario(db, "temporal", debe_cambiar=True, mfa=False)
    assert etapa_inicial(usuario) == "cambio_password"


# ---------------------------------------------------------------------------
# Primer factor
# ---------------------------------------------------------------------------


def test_el_login_correcto_abre_la_sesion(db):
    _usuario(db)
    resultado = _entrar(db)
    assert resultado.usuario.username == "usuaria"
    assert resultado.etapa == "mfa_pendiente"
    assert resultado.token


def test_un_csrf_de_login_que_no_cuadra_se_rechaza(db):
    """Defensa del formulario: sin la doble cookie no se procesa nada."""
    from app.servicios.autenticacion import ErrorAutenticacion

    _usuario(db)
    for csrf_login, cookie in (("", ""), (CSRF, ""), ("otro", CSRF)):
        with pytest.raises(ErrorAutenticacion) as exc:
            _entrar(db, csrf_login=csrf_login, cookie_csrf=cookie)
        assert exc.value.codigo == 403


def test_usuario_inexistente_y_contrasena_mala_son_indistinguibles(db):
    """Distinguirlos convertiría el formulario en un enumerador de cuentas."""
    from app.servicios.autenticacion import ErrorAutenticacion

    _usuario(db)

    with pytest.raises(ErrorAutenticacion) as sin_cuenta:
        _entrar(db, username="no-existe")
    with pytest.raises(ErrorAutenticacion) as mala:
        _entrar(db, password="Equivocada-2026!")

    assert sin_cuenta.value.mensaje == mala.value.mensaje == "Credenciales inválidas."
    assert sin_cuenta.value.codigo == mala.value.codigo == 401


def test_una_cuenta_desactivada_no_entra_ni_se_delata(db):
    from app.servicios.autenticacion import ErrorAutenticacion

    _usuario(db, activo=False)
    with pytest.raises(ErrorAutenticacion) as exc:
        _entrar(db)
    assert exc.value.mensaje == "Credenciales inválidas."


def test_la_cuenta_se_bloquea_al_llegar_al_limite_y_revoca_sus_sesiones(db):
    from app.config import get_settings
    from app.models import SesionWeb
    from app.servicios.autenticacion import ErrorAutenticacion

    usuario = _usuario(db)
    _entrar(db)  # deja una sesión viva
    assert db.scalar(select(func.count(SesionWeb.id)).where(
        SesionWeb.usuario_id == usuario.id, SesionWeb.revocada_en.is_(None))) == 1

    for _ in range(get_settings().max_failed_attempts):
        with pytest.raises(ErrorAutenticacion):
            _entrar(db, password="Equivocada-2026!")

    db.refresh(usuario)
    assert usuario.esta_bloqueado()
    assert db.scalar(select(func.count(SesionWeb.id)).where(
        SesionWeb.usuario_id == usuario.id, SesionWeb.revocada_en.is_(None))) == 0, (
        "una sesión abierta en otro sitio es justo lo que no conviene dejar en pie"
    )

    with pytest.raises(ErrorAutenticacion) as exc:
        _entrar(db)
    assert exc.value.codigo == 423


def test_el_bloqueo_queda_auditado(db):
    from app import audit
    from app.config import get_settings
    from app.models import RegistroAuditoria
    from app.servicios.autenticacion import ErrorAutenticacion

    _usuario(db)
    for _ in range(get_settings().max_failed_attempts):
        with pytest.raises(ErrorAutenticacion):
            _entrar(db, password="Equivocada-2026!")

    assert db.scalar(select(func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.accion == audit.CUENTA_BLOQUEADA)) == 1


def test_el_login_correcto_limpia_los_intentos_fallidos(db):
    from app.servicios.autenticacion import ErrorAutenticacion

    usuario = _usuario(db)
    with pytest.raises(ErrorAutenticacion):
        _entrar(db, password="Equivocada-2026!")
    db.refresh(usuario)
    assert usuario.intentos_fallidos == 1

    _entrar(db)
    db.refresh(usuario)
    assert usuario.intentos_fallidos == 0


def test_el_rehash_oportunista_actualiza_un_hash_antiguo(db, monkeypatch):
    """El único momento con la contraseña en claro se aprovecha para rehacer el hash."""
    from app.servicios import autenticacion

    usuario = _usuario(db)
    hash_original = usuario.password_hash
    monkeypatch.setattr(autenticacion, "necesita_rehash", lambda _h: True)

    _entrar(db)
    db.refresh(usuario)
    assert usuario.password_hash != hash_original


def test_el_limite_por_ip_frena_la_prueba_sistematica(db, monkeypatch):
    from app.servicios import autenticacion
    from app.servicios.autenticacion import ErrorAutenticacion

    _usuario(db)
    monkeypatch.setattr(autenticacion.ratelimit, "permitir_intento",
                        lambda *a, **k: False)
    with pytest.raises(ErrorAutenticacion) as exc:
        _entrar(db)
    assert exc.value.codigo == 429


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------


def _sesion_de(db, usuario, etapa="activa"):
    from app.security.sessions import crear_sesion

    sesion, _token = crear_sesion(db, usuario, etapa, direccion_ip="10.0.0.1", agente_usuario="pytest")
    db.flush()
    return sesion


def test_el_cambio_revoca_las_demas_sesiones_y_rota_la_actual(db):
    """Si la contraseña se cambia porque pudo quedar expuesta, dejar vivas las
    sesiones abiertas con la anterior anularía el motivo del cambio."""
    from app.models import SesionWeb
    from app.servicios.autenticacion import cambiar_password

    usuario = _usuario(db)
    otra = _sesion_de(db, usuario)
    actual = _sesion_de(db, usuario)
    token_antiguo = actual.token_hash

    resultado = cambiar_password(db, sesion=actual, actual=PASSWORD,
                                 nueva="Nueva-Clave-Distinta-2026!",
                                 confirmacion="Nueva-Clave-Distinta-2026!")

    db.refresh(otra)
    db.refresh(actual)
    assert otra.revocada_en is not None
    assert actual.revocada_en is None
    assert actual.token_hash != token_antiguo
    assert resultado.forzado is False
    assert db.scalar(select(func.count(SesionWeb.id)).where(
        SesionWeb.usuario_id == usuario.id, SesionWeb.revocada_en.is_(None))) == 1


def test_el_cambio_forzado_pasa_a_la_etapa_de_segundo_factor(db):
    from app.servicios.autenticacion import cambiar_password

    usuario = _usuario(db, debe_cambiar=True, mfa=True)
    sesion = _sesion_de(db, usuario, etapa="cambio_password")

    resultado = cambiar_password(db, sesion=sesion, actual=PASSWORD,
                                 nueva="Nueva-Clave-Distinta-2026!",
                                 confirmacion="Nueva-Clave-Distinta-2026!")
    assert resultado.forzado is True
    assert resultado.etapa == "mfa_pendiente"
    db.refresh(usuario)
    assert usuario.debe_cambiar_password is False


def test_el_cambio_forzado_sin_mfa_lleva_al_enrolamiento(db):
    from app.servicios.autenticacion import cambiar_password

    usuario = _usuario(db, debe_cambiar=True, mfa=False)
    sesion = _sesion_de(db, usuario, etapa="cambio_password")
    resultado = cambiar_password(db, sesion=sesion, actual=PASSWORD,
                                 nueva="Nueva-Clave-Distinta-2026!",
                                 confirmacion="Nueva-Clave-Distinta-2026!")
    assert resultado.etapa == "mfa_enrolamiento"


@pytest.mark.parametrize(
    ("nueva", "confirmacion", "fragmento"),
    [
        ("Nueva-Clave-2026!", "Otra-Clave-2026!", "confirmación"),
        (PASSWORD, PASSWORD, "distinta de la actual"),
        ("corta", "corta", "12"),
    ],
)
def test_el_cambio_valida_la_contrasena_nueva(db, nueva, confirmacion, fragmento):
    from app.servicios.autenticacion import ErrorAutenticacion, cambiar_password

    usuario = _usuario(db)
    sesion = _sesion_de(db, usuario)
    with pytest.raises(ErrorAutenticacion) as exc:
        cambiar_password(db, sesion=sesion, actual=PASSWORD,
                         nueva=nueva, confirmacion=confirmacion)
    assert exc.value.codigo == 400
    assert fragmento in exc.value.mensaje


def test_fallar_la_contrasena_actual_puede_bloquear_y_revocar(db):
    """El error lleva lo que el controlador necesita: código, destino y que hay
    que borrar la cookie."""
    from app.config import get_settings
    from app.servicios.autenticacion import ErrorAutenticacion, cambiar_password

    usuario = _usuario(db)
    sesion = _sesion_de(db, usuario)
    usuario.intentos_fallidos = get_settings().max_failed_attempts - 1
    db.flush()

    with pytest.raises(ErrorAutenticacion) as exc:
        cambiar_password(db, sesion=sesion, actual="Equivocada-2026!",
                         nueva="Nueva-Clave-2026!", confirmacion="Nueva-Clave-2026!")

    assert exc.value.codigo == 423
    assert exc.value.destino == "/login"
    assert exc.value.revocar_sesion is True
    db.refresh(sesion)
    assert sesion.revocada_en is not None


# ---------------------------------------------------------------------------
# Cierre de sesión
# ---------------------------------------------------------------------------


def test_cerrar_sesion_la_revoca_y_lo_audita(db):
    from app import audit
    from app.models import RegistroAuditoria
    from app.servicios.autenticacion import cerrar_sesion

    usuario = _usuario(db)
    sesion = _sesion_de(db, usuario)

    cerrar_sesion(db, sesion=sesion, usuario=usuario)

    db.refresh(sesion)
    assert sesion.revocada_en is not None
    assert db.scalar(select(func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.accion == audit.LOGOUT)) == 1
