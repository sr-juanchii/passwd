"""Esquema de los agentes de rotación (v1.4.0, commit de modelos).

Cubre lo que el esquema garantiza por sí solo, antes de que exista ningún
servicio que lo use: que una base de la 1.3.0 se pone al día sin perder el
libro mayor, que la migración va y vuelve, y que las invariantes que el plan
encarga a la base de datos (un agente vigente por activo, un trabajo activo por
agente, vínculo con exactamente un activo) se cumplen en el motor y no solo en
el código. Plan: docs/plan-rotacion-agentes.md §3.1.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

RAIZ = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------


def _alembic(tmp_path, monkeypatch):
    from alembic.config import Config as AlembicConfig

    from app.config import reset_settings

    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.delenv("PASSWD_DATABASE_URL", raising=False)
    reset_settings()
    configuracion = AlembicConfig(str(RAIZ / "alembic.ini"))
    configuracion.set_main_option("script_location", str(RAIZ / "migrations"))
    return configuracion, f"sqlite:///{tmp_path / 'datos' / 'passwd.db'}"


def test_una_base_de_la_1_3_0_se_pone_al_dia_sin_perder_el_libro_mayor(tmp_path, monkeypatch):
    """El camino real de una instalación existente: `create_all` + reconciliador."""
    from alembic import command

    import app.models  # noqa: F401 — registra las tablas
    from app.config import reset_settings
    from app.database import Base
    from app.schema_sync import reconciliar_esquema

    configuracion, url = _alembic(tmp_path, monkeypatch)
    command.upgrade(configuracion, "0010")  # base tal como la deja la 1.3.0

    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO rotaciones_credencial (activo_nombre, usuario_acceso, servicio, estado,"
            " tipo, solicitado_por_username, solicitado_en, motivo, temprana,"
            " autorizado_por_username, reautenticado, emergencia_sin_segundo_par, nota_revision,"
            " motivo_rechazo, resultado, via, verificacion, detalle_error)"
            " VALUES ('srv-1', 'root', 'SSH', 'cerrada', 'manual', 'admin', '2026-11-20 10:00:00',"
            " 'Rotación de la 1.3.0', 0, 'admin2', 1, 0, '', '', 'manual', 'manual', 'ninguna', '')"
        ))

    Base.metadata.create_all(engine)
    aplicados = reconciliar_esquema(engine)

    inspector = inspect(engine)
    assert {"agentes", "trabajos_rotacion", "telemetria_agente"} <= set(inspector.get_table_names())
    assert {"rotaciones_credencial.agente_id", "rotaciones_credencial.agente_nombre",
            "rotaciones_credencial.clave_agente_huella"} <= set(aplicados)

    with engine.connect() as c:
        fila = c.execute(text(
            "SELECT motivo, autorizado_por_username, agente_id, agente_nombre FROM rotaciones_credencial"
        )).one()
    assert fila == ("Rotación de la 1.3.0", "admin2", None, "")

    assert reconciliar_esquema(engine) == []  # idempotente
    engine.dispose()
    reset_settings()


def test_la_migracion_0011_va_y_vuelve(tmp_path, monkeypatch):
    from alembic import command

    from app.config import reset_settings

    configuracion, url = _alembic(tmp_path, monkeypatch)
    command.upgrade(configuracion, "head")
    command.downgrade(configuracion, "0010")

    engine = create_engine(url)
    inspector = inspect(engine)
    assert "agentes" not in inspector.get_table_names()
    assert "agente_id" not in {c["name"] for c in inspector.get_columns("rotaciones_credencial")}
    engine.dispose()

    command.upgrade(configuracion, "head")
    engine = create_engine(url)
    assert "agentes" in inspect(engine).get_table_names()
    engine.dispose()
    reset_settings()


# ---------------------------------------------------------------------------
# Invariantes que garantiza el motor
# ---------------------------------------------------------------------------


@pytest.fixture()
def bd(aplicacion):
    from tests.conftest import sesion_bd

    db = sesion_bd()
    yield db
    db.rollback()
    db.close()


def _servidor(db, nombre="srv-agente"):
    from app.models import ServidorFisico

    servidor = ServidorFisico(nombre=nombre)
    db.add(servidor)
    db.flush()
    return servidor


def _agente(db, servidor, nombre="agente-1", vigente=True):
    from app.models import ACTIVO_FISICO, AGENTE_ACTIVO, AGENTE_REVOCADO, Agente, vinculo_activo

    agente = Agente(
        nombre=nombre,
        servidor_fisico_id=servidor.id,
        estado=AGENTE_ACTIVO if vigente else AGENTE_REVOCADO,
        vinculo_vigente=vinculo_activo(ACTIVO_FISICO, servidor.id) if vigente else None,
    )
    db.add(agente)
    db.flush()
    return agente


def _credencial_y_rotacion(db, servidor):
    from app.models import Credencial, RotacionCredencial
    from app.security.crypto import cifrar

    credencial = Credencial(
        servidor_fisico_id=servidor.id, usuario_acceso="root", password_cifrada=cifrar("Inicial-2026!")
    )
    db.add(credencial)
    db.flush()
    rotacion = RotacionCredencial(
        credencial_id=credencial.id, activo_nombre=servidor.nombre, usuario_acceso="root",
        motivo="Prueba del esquema de agentes",
    )
    db.add(rotacion)
    db.flush()
    return credencial, rotacion


def _trabajo(db, agente, credencial, rotacion, activo=True):
    from app.models import TRABAJO_APLICADO, TRABAJO_PENDIENTE, TrabajoRotacion, ahora_utc

    trabajo = TrabajoRotacion(
        agente_id=agente.id, credencial_id=credencial.id, rotacion_id=rotacion.id,
        activo_agente_id=agente.id if activo else None,
        estado=TRABAJO_PENDIENTE if activo else TRABAJO_APLICADO,
        ventana_expira_en=ahora_utc() + timedelta(minutes=15),
    )
    db.add(trabajo)
    db.flush()
    return trabajo


def test_un_agente_sin_activo_o_con_dos_se_rechaza(bd):
    from app.models import Agente, Hipervisor

    servidor = _servidor(bd)
    hipervisor = Hipervisor(nombre="hv-1")
    bd.add(hipervisor)
    bd.flush()

    bd.add(Agente(nombre="sin-activo"))
    with pytest.raises(IntegrityError):
        bd.flush()
    bd.rollback()

    servidor = _servidor(bd)
    hipervisor = Hipervisor(nombre="hv-1")
    bd.add(hipervisor)
    bd.flush()
    bd.add(Agente(nombre="dos-activos", servidor_fisico_id=servidor.id, hipervisor_id=hipervisor.id))
    with pytest.raises(IntegrityError):
        bd.flush()


def test_solo_un_agente_vigente_por_activo(bd):
    servidor = _servidor(bd)
    _agente(bd, servidor, "agente-viejo", vigente=False)  # revocado: historia, no estorba
    _agente(bd, servidor, "agente-vigente")

    with pytest.raises(IntegrityError):
        _agente(bd, servidor, "agente-duplicado")


def test_solo_un_trabajo_activo_por_agente(bd):
    servidor = _servidor(bd)
    agente = _agente(bd, servidor)
    credencial, rotacion = _credencial_y_rotacion(bd, servidor)

    _trabajo(bd, agente, credencial, rotacion, activo=False)  # cerrado: no ocupa el turno
    _trabajo(bd, agente, credencial, rotacion)

    with pytest.raises(IntegrityError):
        _trabajo(bd, agente, credencial, rotacion)


def test_borrar_el_activo_arrastra_al_agente_pero_no_al_libro_mayor(bd):
    from app.models import Agente, RotacionCredencial, TelemetriaAgente, TrabajoRotacion

    servidor = _servidor(bd)
    agente = _agente(bd, servidor)
    credencial, rotacion = _credencial_y_rotacion(bd, servidor)
    rotacion.agente_id = agente.id
    rotacion.agente_nombre = agente.nombre
    _trabajo(bd, agente, credencial, rotacion)
    bd.add(TelemetriaAgente(agente_id=agente.id, cpu_pct=12))
    bd.commit()
    id_rotacion = rotacion.id

    bd.delete(servidor)
    bd.commit()
    bd.expire_all()

    assert bd.scalars(select(Agente)).all() == []
    assert bd.scalars(select(TrabajoRotacion)).all() == []
    assert bd.scalars(select(TelemetriaAgente)).all() == []
    asiento = bd.get(RotacionCredencial, id_rotacion)
    assert asiento is not None
    assert asiento.credencial_id is None          # la credencial se fue con el activo
    assert asiento.agente_nombre == "agente-1"    # y el asiento sigue siendo legible
