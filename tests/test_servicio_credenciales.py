"""Pruebas del caso de uso de credenciales **sin HTTP**.

Criterio A1 de [`docs/plan-v2.0.md`](../docs/plan-v2.0.md): cada servicio tiene
pruebas propias que no pasan por un controlador. Importa porque las reglas que
aquí se comprueban —control de acceso por objeto, límite anti-exfiltración,
auditoría— son las mismas para la interfaz clásica y para la API JSON: si se
verifican una sola vez, en el servicio, dejan de poder divergir entre las dos,
que es exactamente lo que falló en la 1.2.0.

Nada de ``TestClient`` en este archivo: se trabaja con una sesión de base de
datos y objetos del dominio.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.conftest import sesion_bd

CLAVE = "Clave-Del-Servicio-2026!"


@pytest.fixture()
def db(aplicacion):
    """Sesión directa contra la base del test (la fixture monta la aplicación)."""
    sesion = sesion_bd()
    try:
        yield sesion
    finally:
        sesion.close()


def _admin(db):
    from app.models import ROL_ADMIN, Usuario

    return db.scalar(select(Usuario).where(Usuario.rol == ROL_ADMIN))


def _usuario(db, username: str, rol: str):
    from app.models import Usuario
    from app.security.passwords import hashear_password

    usuario = Usuario(
        username=username, email=f"{username}@ejemplo.local", nombre_completo=username,
        password_hash=hashear_password("Clave-De-Usuario-2026!"), rol=rol,
        mfa_habilitado=True, activo=True, debe_cambiar_password=False,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _servidor(db, nombre: str, *, restringido: bool = False):
    from app.models import ServidorFisico

    activo = ServidorFisico(nombre=nombre, descripcion="", sistema_operativo="Debian 12",
                            ubicacion="Sala", ip_gestion="10.0.0.9", restringido=restringido)
    db.add(activo)
    db.flush()
    return activo


def _credencial(db, activo, usuario, **extra):
    from app.servicios import credenciales as servicio

    return servicio.crear(
        db, usuario=usuario, tipo_activo="fisico", activo_id=activo.id,
        usuario_acceso="root", password=CLAVE, servicio="SSH", puerto=22,
        descripcion="Acceso de administración", **extra,
    )


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------


def test_el_alta_valida_sus_datos(db):
    from app.servicios.credenciales import ErrorCredencial, crear

    admin = _admin(db)
    activo = _servidor(db, "srv-validacion")

    for campos, esperado in (
        ({"usuario_acceso": "  ", "password": CLAVE}, "usuario de acceso"),
        ({"usuario_acceso": "root", "password": ""}, "contraseña"),
    ):
        with pytest.raises(ErrorCredencial) as exc:
            crear(db, usuario=admin, tipo_activo="fisico", activo_id=activo.id, **campos)
        assert esperado in exc.value.mensaje
        assert exc.value.codigo == 400


def test_el_alta_rechaza_un_puerto_fuera_de_rango(db):
    from app.servicios.credenciales import ErrorCredencial, crear

    admin = _admin(db)
    activo = _servidor(db, "srv-puerto")
    with pytest.raises(ErrorCredencial) as exc:
        crear(db, usuario=admin, tipo_activo="fisico", activo_id=activo.id,
              usuario_acceso="root", password=CLAVE, puerto=70000)
    assert exc.value.codigo == 400


def test_el_alta_cifra_la_contrasena_y_deja_rastro(db):
    from app.models import RegistroAuditoria
    from app.security.crypto import descifrar

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-alta"), admin)

    assert credencial.password_cifrada != CLAVE.encode()
    assert descifrar(credencial.password_cifrada) == CLAVE
    assert credencial.via_rotacion == "manual"
    assert db.scalar(select(func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.accion == "credencial_creada")) == 1


def test_un_activo_restringido_es_inexistente_para_el_operador(db):
    """No «403»: distinguirlo convertiría el endpoint en un enumerador."""
    from app.models import ROL_OPERADOR
    from app.servicios.credenciales import ErrorCredencial, crear

    operador = _usuario(db, "operadora", ROL_OPERADOR)
    activo = _servidor(db, "srv-oculto", restringido=True)

    with pytest.raises(ErrorCredencial) as exc:
        crear(db, usuario=operador, tipo_activo="fisico", activo_id=activo.id,
              usuario_acceso="root", password=CLAVE)
    assert exc.value.codigo == 404


# ---------------------------------------------------------------------------
# Entrega de secretos: el control que estaba duplicado
# ---------------------------------------------------------------------------


def test_sin_concesion_la_credencial_no_existe_y_queda_auditado(db):
    from app import audit
    from app.models import ROL_ANALISTA, RegistroAuditoria
    from app.servicios.credenciales import ErrorCredencial, entregar_password

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-sin-concesion"), admin)
    analista = _usuario(db, "analista-sin", ROL_ANALISTA)

    with pytest.raises(ErrorCredencial) as exc:
        entregar_password(db, usuario=analista, credencial_id=credencial.id,
                          accion=audit.CREDENCIAL_REVELADA)
    assert exc.value.codigo == 404
    assert db.scalar(select(func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.accion == audit.ACCESO_DENEGADO)) == 1


def test_una_concesion_de_solo_ver_no_permite_revelar(db):
    from app import audit
    from app.models import NIVEL_VER, ROL_ANALISTA, ConcesionAcceso
    from app.servicios.credenciales import ErrorCredencial, entregar_password

    admin = _admin(db)
    activo = _servidor(db, "srv-solo-ver")
    credencial = _credencial(db, activo, admin)
    analista = _usuario(db, "analista-ver", ROL_ANALISTA)
    db.add(ConcesionAcceso(usuario_id=analista.id, servidor_fisico_id=activo.id, nivel=NIVEL_VER))
    db.flush()

    with pytest.raises(ErrorCredencial) as exc:
        entregar_password(db, usuario=analista, credencial_id=credencial.id,
                          accion=audit.CREDENCIAL_REVELADA)
    assert exc.value.codigo == 403, "ve el activo, pero su concesión no llega a la contraseña"


def test_con_concesion_suficiente_entrega_la_contrasena(db):
    from app import audit
    from app.models import NIVEL_VER_CREDENCIALES, ROL_ANALISTA, ConcesionAcceso
    from app.servicios.credenciales import entregar_password

    admin = _admin(db)
    activo = _servidor(db, "srv-concedido")
    credencial = _credencial(db, activo, admin)
    analista = _usuario(db, "analista-ok", ROL_ANALISTA)
    db.add(ConcesionAcceso(usuario_id=analista.id, servidor_fisico_id=activo.id,
                           nivel=NIVEL_VER_CREDENCIALES))
    db.flush()

    datos = entregar_password(db, usuario=analista, credencial_id=credencial.id,
                              accion=audit.CREDENCIAL_REVELADA)
    assert datos == {"usuario": "root", "password": CLAVE}


def test_el_limite_anti_exfiltracion_corta_la_extraccion_masiva(db):
    """Frena el vaciado del inventario aun con una sesión legítima comprometida."""
    from app import audit
    from app.config import get_settings
    from app.servicios.credenciales import ErrorCredencial, entregar_password

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-limite"), admin)

    settings = get_settings()
    original = settings.reveal_rate_limit
    settings.reveal_rate_limit = 2
    try:
        for _ in range(2):
            entregar_password(db, usuario=admin, credencial_id=credencial.id,
                              accion=audit.CREDENCIAL_REVELADA)
        with pytest.raises(ErrorCredencial) as exc:
            entregar_password(db, usuario=admin, credencial_id=credencial.id,
                              accion=audit.CREDENCIAL_REVELADA)
    finally:
        settings.reveal_rate_limit = original

    assert exc.value.codigo == 429
    from app.models import RegistroAuditoria

    assert db.scalar(select(func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.accion == audit.REVELADO_TASA_EXCEDIDA)) == 1


def test_el_historial_comparte_el_mismo_limite_que_las_vigentes(db):
    """Si no, el historial sería la puerta de atrás del límite."""
    from app import audit
    from app.config import get_settings
    from app.models import HistorialCredencial
    from app.security.crypto import cifrar
    from app.servicios.credenciales import ErrorCredencial, revelar_historial

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-historial"), admin)
    entrada = HistorialCredencial(credencial_id=credencial.id,
                                  password_cifrada=cifrar("Anterior-2026!"),
                                  rotada_por_id=admin.id)
    db.add(entrada)
    db.flush()

    settings = get_settings()
    original = settings.reveal_rate_limit
    settings.reveal_rate_limit = 1
    try:
        datos = revelar_historial(db, usuario=admin, credencial_id=credencial.id,
                                  historial_id=entrada.id)
        assert datos == {"password": "Anterior-2026!"}
        with pytest.raises(ErrorCredencial) as exc:
            revelar_historial(db, usuario=admin, credencial_id=credencial.id,
                              historial_id=entrada.id)
    finally:
        settings.reveal_rate_limit = original
    assert exc.value.codigo == 429

    from app.models import RegistroAuditoria

    registro = db.scalar(select(RegistroAuditoria).where(
        RegistroAuditoria.accion == audit.REVELADO_TASA_EXCEDIDA))
    assert registro.objeto_tipo == "historial_credencial"


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------


def test_cambiar_la_contrasena_sin_autorizacion_no_deja_la_ficha_a_medias(db):
    """El control se comprueba ANTES de tocar ningún campo."""
    from app.servicios.credenciales import ErrorCredencial, actualizar

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-a-medias"), admin)

    with pytest.raises(ErrorCredencial) as exc:
        actualizar(db, usuario=admin, credencial_id=credencial.id,
                   usuario_acceso="otro-usuario", password="Intento-2026!",
                   servicio="RDP", puerto=3389, descripcion="cambiada")
    assert exc.value.codigo == 409

    db.rollback()
    credencial = db.get(type(credencial), credencial.id)
    assert credencial.usuario_acceso == "root", "la ficha no debe quedar medio editada"
    assert credencial.servicio == "SSH"


def test_editar_el_resto_de_campos_no_exige_rotacion(db):
    from app.servicios.credenciales import actualizar

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-campos-svc"), admin)

    actualizada, rotacion = actualizar(
        db, usuario=admin, credencial_id=credencial.id, usuario_acceso="root",
        servicio="RDP", puerto=3389, descripcion="Consola", usada_por="cron de respaldos",
    )
    assert rotacion is None
    assert actualizada.servicio == "RDP"
    assert actualizada.usada_por == "cron de respaldos"


def test_la_baja_deja_rastro_de_lo_que_se_borro(db):
    from app.models import Credencial, RegistroAuditoria
    from app.servicios.credenciales import eliminar

    admin = _admin(db)
    credencial = _credencial(db, _servidor(db, "srv-baja"), admin)
    credencial_id = credencial.id

    eliminar(db, usuario=admin, credencial_id=credencial_id)
    db.flush()

    assert db.get(Credencial, credencial_id) is None
    registro = db.scalar(select(RegistroAuditoria).where(
        RegistroAuditoria.accion == "credencial_eliminada"))
    assert "root@srv-baja" in registro.detalle
