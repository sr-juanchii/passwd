"""Despacho de rotaciones a agentes y cierre por su resultado (v1.4.0, 2b).

El agente nunca decide: ejecuta lo que dos personas autorizaron, y la contraseña
solo cambia en el inventario cuando él confirma, por el mismo punto único que la
vía manual. Plan: docs/plan-rotacion-agentes.md §2.2, §3.2 y §8.0.4.
"""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import select

MOTIVO = "Rotación periódica por agente de la prueba automatizada"
MOTIVO_EMERGENCIA = "Credencial expuesta en un ticket público: contención inmediata"


@pytest.fixture()
def bd(request, monkeypatch):
    monkeypatch.setenv("PASSWD_AGENTES_ENABLED", "true")
    request.getfixturevalue("aplicacion")
    from tests.conftest import sesion_bd

    db = sesion_bd()
    yield db
    db.rollback()
    db.close()


class Escenario:
    """Dos administradores, un servidor con su agente enrolado y una credencial por agente."""

    def __init__(self, bd, nombre="srv-despacho"):
        from app.models import ACTIVO_FISICO, ROL_ADMIN, ServidorFisico, Usuario, ahora_utc
        from app.servicios import agentes, rotacion

        self.bd = bd
        self.pide = Usuario(username=f"pide-{nombre}", email=f"pide-{nombre}@ejemplo.local",
                            password_hash="x", rol=ROL_ADMIN)
        self.autoriza = Usuario(username=f"autoriza-{nombre}", email=f"autoriza-{nombre}@ejemplo.local",
                                password_hash="x", rol=ROL_ADMIN)
        self.servidor = ServidorFisico(nombre=nombre)
        bd.add_all([self.pide, self.autoriza, self.servidor])
        bd.flush()

        _agente, enrolamiento = agentes.alta(bd, tipo_activo=ACTIVO_FISICO, activo_id=self.servidor.id,
                                             nombre=f"agente-{nombre}", usuario=self.pide)
        self.privada = X25519PrivateKey.generate()
        publica = base64.b64encode(self.privada.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.agente, _token = agentes.enrolar(bd, token_enrolamiento=enrolamiento, clave_publica=publica,
                                              nombre_host=nombre, version="1.4.0", ip="10.0.0.5")

        self.credencial = rotacion.nueva_credencial(bd, password="Actual-De-Partida-2026!",
                                                    usuario_acceso="deploy",
                                                    servidor_fisico_id=self.servidor.id)
        bd.flush()
        # Rotada hace un mes: ni temprana ni frenada por el anti-thrash.
        self.credencial.password_rotada_en = ahora_utc() - timedelta(days=30)
        agentes.usar_agente(bd, credencial=self.credencial, usuario=self.pide)

    def solicitar(self, tipo=None):
        from app.models import ROT_TIPO_MANUAL
        from app.servicios import rotacion

        return rotacion.solicitar(self.bd, credencial=self.credencial, usuario=self.pide,
                                  motivo=MOTIVO_EMERGENCIA if tipo else MOTIVO,
                                  tipo=tipo or ROT_TIPO_MANUAL)

    def autorizada(self, tipo=None):
        """Solicita y autoriza: al autorizar, se despacha sola."""
        from app.servicios import rotacion

        solicitud = self.solicitar(tipo)
        rotacion.autorizar(self.bd, rotacion=solicitud, usuario=self.autoriza)
        return solicitud

    def entregar(self):
        from app.servicios import cifrado_agente, rotacion

        entrega = rotacion.entregar(self.bd, agente=self.agente)
        if entrega is None:
            return None, None
        trabajo, sobre = entrega
        return trabajo, cifrado_agente.abrir(self.privada, sobre)


@pytest.fixture()
def esc(bd):
    return Escenario(bd)


def _acciones(bd, accion):
    from app.models import RegistroAuditoria

    return bd.scalars(select(RegistroAuditoria).where(RegistroAuditoria.accion == accion)).all()


# ---------------------------------------------------------------------------
# Despacho
# ---------------------------------------------------------------------------


def test_autorizar_despacha_y_el_agente_recibe_el_trabajo_sellado(esc):
    from app.models import ROT_DESPACHADA, TRABAJO_ENTREGADO

    solicitud = esc.autorizada()
    assert solicitud.estado == ROT_DESPACHADA
    assert solicitud.agente_nombre == esc.agente.nombre
    assert solicitud.clave_agente_huella == esc.agente.clave_huella

    trabajo, contenido = esc.entregar()
    assert trabajo.estado == TRABAJO_ENTREGADO
    assert contenido["tipo"] == "rotar_cuenta"
    assert contenido["usuario"] == "deploy"
    assert contenido["actual"] == "Actual-De-Partida-2026!"
    assert len(contenido["nueva"]) >= 20 and contenido["nueva"] != contenido["actual"]


def test_no_hay_despacho_sin_autorizacion(esc):
    """Invariante 1 (§3.2): ni siquiera llamando al servicio directamente."""
    from app.servicios import rotacion

    solicitud = esc.solicitar()
    with pytest.raises(rotacion.ErrorRotacion) as error:
        rotacion.despachar(esc.bd, rotacion=solicitud)
    assert error.value.codigo == 409
    assert esc.entregar() == (None, None)


def test_con_los_agentes_apagados_la_autorizacion_se_mantiene(esc, monkeypatch):
    from app import audit
    from app.config import get_settings
    from app.models import ROT_AUTORIZADA

    monkeypatch.setattr(get_settings(), "agentes_enabled", False)
    solicitud = esc.autorizada()
    assert solicitud.estado == ROT_AUTORIZADA       # la decisión de dos personas sigue en pie
    assert _acciones(esc.bd, audit.ROTACION_NO_DESPACHADA)


def test_el_agente_de_otro_activo_no_recibe_el_trabajo(bd):
    a = Escenario(bd, "srv-a")
    b = Escenario(bd, "srv-b")
    a.autorizada()
    from app.servicios import rotacion

    assert rotacion.entregar(bd, agente=b.agente) is None
    assert a.entregar()[0] is not None


def test_un_agente_revocado_no_recibe_trabajos(esc):
    from app.models import ROT_AUTORIZADA
    from app.servicios import agentes, rotacion

    solicitud = esc.autorizada()
    agentes.revocar(esc.bd, agente=esc.agente, usuario=esc.pide)
    assert rotacion.entregar(esc.bd, agente=esc.agente) is None
    assert solicitud.estado == ROT_AUTORIZADA       # el pendiente se canceló; la autorización vive


def test_el_anti_thrash_frena_salvo_en_emergencia(esc):
    from app import audit
    from app.models import ROT_AUTORIZADA, ROT_DESPACHADA, ROT_TIPO_EMERGENCIA, ahora_utc
    from app.servicios import rotacion

    esc.credencial.password_rotada_en = ahora_utc() - timedelta(hours=2)
    normal = esc.autorizada()
    assert normal.estado == ROT_AUTORIZADA          # frenada, sin trabajo
    rotacion.cancelar(esc.bd, rotacion=normal, usuario=esc.pide)

    urgente = esc.autorizada(tipo=ROT_TIPO_EMERGENCIA)
    assert urgente.estado == ROT_DESPACHADA
    assert _acciones(esc.bd, audit.ROTACION_ANTI_THRASH_SALTADO)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------


def test_aplicado_escribe_la_contrasena_archiva_la_anterior_y_purga(esc):
    from app.models import ROT_CERRADA, ROT_RES_APLICADA, ROT_VERIF_LOCAL, HistorialCredencial
    from app.security.crypto import descifrar
    from app.servicios import rotacion

    solicitud = esc.autorizada()
    trabajo, contenido = esc.entregar()
    rotacion.registrar_resultado(esc.bd, agente=esc.agente, trabajo_id=trabajo.id, estado="aplicado")

    assert descifrar(esc.credencial.password_cifrada) == contenido["nueva"]
    anteriores = esc.bd.scalars(select(HistorialCredencial)
                                .where(HistorialCredencial.credencial_id == esc.credencial.id)).all()
    assert [descifrar(h.password_cifrada) for h in anteriores] == ["Actual-De-Partida-2026!"]
    assert (solicitud.estado, solicitud.resultado, solicitud.verificacion) == \
        (ROT_CERRADA, ROT_RES_APLICADA, ROT_VERIF_LOCAL)
    assert solicitud.dias_al_rotar == 30
    assert trabajo.nueva_cifrada is None and trabajo.actual_cifrada is None
    assert trabajo.activo_agente_id is None


def test_revertido_no_toca_la_contrasena(esc):
    from app.models import ROT_RES_REVERTIDA
    from app.security.crypto import descifrar
    from app.servicios import rotacion

    solicitud = esc.autorizada()
    trabajo, _ = esc.entregar()
    rotacion.registrar_resultado(esc.bd, agente=esc.agente, trabajo_id=trabajo.id,
                                 estado="revertido", detalle="PAM no verificó la nueva")
    assert descifrar(esc.credencial.password_cifrada) == "Actual-De-Partida-2026!"
    assert solicitud.resultado == ROT_RES_REVERTIDA
    assert trabajo.nueva_cifrada is None


def test_un_segundo_resultado_se_rechaza(esc):
    """Anti-replay: un trabajo admite un único resultado."""
    from app.servicios import rotacion

    esc.autorizada()
    trabajo, _ = esc.entregar()
    rotacion.registrar_resultado(esc.bd, agente=esc.agente, trabajo_id=trabajo.id, estado="fallado")
    with pytest.raises(rotacion.ErrorRotacion) as error:
        rotacion.registrar_resultado(esc.bd, agente=esc.agente, trabajo_id=trabajo.id, estado="aplicado")
    assert error.value.codigo == 409


def test_un_agente_no_cierra_el_trabajo_de_otro(bd):
    from app.servicios import rotacion

    a = Escenario(bd, "srv-dueno")
    b = Escenario(bd, "srv-intruso")
    a.autorizada()
    trabajo, _ = a.entregar()
    with pytest.raises(rotacion.ErrorRotacion) as error:
        rotacion.registrar_resultado(bd, agente=b.agente, trabajo_id=trabajo.id, estado="aplicado")
    assert error.value.codigo == 403


def test_un_trabajo_sin_entregar_no_admite_resultado(esc):
    from app.servicios import rotacion

    esc.autorizada()
    trabajo = rotacion.trabajo_activo_de(esc.bd, esc.agente)
    with pytest.raises(rotacion.ErrorRotacion) as error:
        rotacion.registrar_resultado(esc.bd, agente=esc.agente, trabajo_id=trabajo.id, estado="aplicado")
    assert error.value.codigo == 409


def test_el_agente_no_puede_declarar_verificacion_remota(esc):
    from app.servicios import rotacion

    esc.autorizada()
    trabajo, _ = esc.entregar()
    with pytest.raises(rotacion.ErrorRotacion):
        rotacion.registrar_resultado(esc.bd, agente=esc.agente, trabajo_id=trabajo.id,
                                     estado="aplicado", verificacion="remota")


# ---------------------------------------------------------------------------
# Vencimientos y resolución
# ---------------------------------------------------------------------------


def test_un_pendiente_vencido_vuelve_a_quedar_autorizado(esc):
    from app.models import ROT_AUTORIZADA, TRABAJO_EXPIRADO, ahora_utc
    from app.servicios import rotacion

    solicitud = esc.autorizada()
    trabajo = rotacion.trabajo_activo_de(esc.bd, esc.agente)
    trabajo.ventana_expira_en = ahora_utc() - timedelta(seconds=1)

    assert esc.entregar() == (None, None)
    assert trabajo.estado == TRABAJO_EXPIRADO and trabajo.nueva_cifrada is None
    assert solicitud.estado == ROT_AUTORIZADA
    rotacion.despachar(esc.bd, rotacion=solicitud)   # y se puede volver a despachar


def test_un_entregado_sin_respuesta_queda_sin_confirmar_con_sus_secretos(esc):
    from app.models import ROT_CERRADA, ROT_DESPACHADA, ahora_utc
    from app.security.crypto import descifrar
    from app.servicios import rotacion

    solicitud = esc.autorizada()
    trabajo, contenido = esc.entregar()
    trabajo.ventana_expira_en = ahora_utc() - rotacion.MARGEN_CONFIRMACION - timedelta(seconds=1)

    assert rotacion.expirar_trabajos(esc.bd) == {"expirados": 0, "sin_confirmar": 1}
    assert rotacion.sin_confirmar(trabajo)
    assert trabajo.nueva_cifrada is not None        # la nueva puede ser la que vale en el activo
    assert solicitud.estado == ROT_DESPACHADA       # la credencial no admite otra rotación
    assert rotacion.expirar_trabajos(esc.bd) == {"expirados": 0, "sin_confirmar": 0}  # avisa una vez

    rotacion.resolver_sin_confirmar(esc.bd, trabajo=trabajo, aplicada=True, usuario=esc.autoriza)
    assert descifrar(esc.credencial.password_cifrada) == contenido["nueva"]
    assert solicitud.estado == ROT_CERRADA
    assert trabajo.nueva_cifrada is None


def test_no_se_resuelve_a_mano_lo_que_el_agente_aun_puede_confirmar(esc):
    from app.servicios import rotacion

    esc.autorizada()
    trabajo, _ = esc.entregar()
    with pytest.raises(rotacion.ErrorRotacion) as error:
        rotacion.resolver_sin_confirmar(esc.bd, trabajo=trabajo, aplicada=True, usuario=esc.autoriza)
    assert error.value.codigo == 409


def test_cancelar_retira_un_pendiente_pero_no_un_entregado(bd):
    from app.models import ROT_CANCELADA, TRABAJO_CANCELADO
    from app.servicios import rotacion

    a = Escenario(bd, "srv-cancela")
    solicitud = a.autorizada()
    trabajo = rotacion.trabajo_activo_de(bd, a.agente)
    rotacion.cancelar(bd, rotacion=solicitud, usuario=a.pide)
    assert solicitud.estado == ROT_CANCELADA and trabajo.estado == TRABAJO_CANCELADO

    b = Escenario(bd, "srv-en-curso")
    otra = b.autorizada()
    b.entregar()
    with pytest.raises(rotacion.ErrorRotacion) as error:
        rotacion.cancelar(bd, rotacion=otra, usuario=b.pide)
    assert error.value.codigo == 409


# ---------------------------------------------------------------------------
# Respaldo
# ---------------------------------------------------------------------------


def test_el_respaldo_repone_agentes_revocados_y_nunca_trabajos(esc):
    from app import backup
    from app.models import (
        AGENTE_REVOCADO,
        ROT_AUTORIZADA,
        VIA_ROTACION_MANUAL,
        Agente,
        Credencial,
        RotacionCredencial,
        TrabajoRotacion,
    )

    solicitud = esc.autorizada()                    # despachada, con un trabajo en curso
    esc.bd.commit()
    archivo = backup.exportar(esc.bd, "frase-de-respaldo-de-prueba")

    backup.restaurar(esc.bd, archivo, "frase-de-respaldo-de-prueba", sobrescribir=True)
    esc.bd.commit()
    esc.bd.expire_all()

    agente = esc.bd.scalars(select(Agente)).one()
    assert agente.estado == AGENTE_REVOCADO and agente.vinculo_vigente is None
    assert agente.token_hash is None
    assert esc.bd.scalars(select(TrabajoRotacion)).all() == []
    assert esc.bd.scalars(select(Credencial)).one().via_rotacion == VIA_ROTACION_MANUAL
    asiento = esc.bd.get(RotacionCredencial, solicitud.id)
    assert asiento.estado == ROT_AUTORIZADA          # no queda abierto para siempre
    assert "respaldo" in asiento.detalle_error
    assert asiento.agente_nombre == esc.agente.nombre
