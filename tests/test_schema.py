"""Prueba del reconciliador de esquema (migraciones aditivas sin dependencias)."""

from __future__ import annotations

from sqlalchemy import inspect, text


def test_reconciliador_añade_columnas_faltantes(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("PASSWD_COOKIE_SECURE", "false")
    monkeypatch.delenv("PASSWD_DATABASE_URL", raising=False)

    from app.config import reset_settings
    from app.database import Base, get_engine, reset_engine

    reset_settings()
    reset_engine()
    engine = get_engine()

    # BD "antigua": tabla con menos columnas de las que define el modelo actual.
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE servidores_fisicos "
            "(id INTEGER PRIMARY KEY, nombre VARCHAR(120), tipo VARCHAR(32))"
        ))

    import app.models  # noqa: F401  (registra los modelos)
    from app.schema_sync import reconciliar_esquema

    Base.metadata.create_all(engine)          # crea el resto de tablas
    aplicados = reconciliar_esquema(engine)

    columnas = {c["name"] for c in inspect(engine).get_columns("servidores_fisicos")}
    assert "ubicacion" in columnas            # columna que faltaba, ahora presente
    assert "ip_gestion" in columnas
    assert any(a.startswith("servidores_fisicos.") for a in aplicados)

    # Idempotente: una segunda pasada no añade nada.
    assert reconciliar_esquema(engine) == []

    reset_engine()
    reset_settings()


def test_reconciliador_repara_check_obsoleta_de_dispositivos(tmp_path, monkeypatch):
    """Regresión del 500 en producción al guardar la credencial de un dispositivo.

    Simula una BD anterior a los dispositivos de red (esquema Alembic 0004) que
    se actualiza de forma aditiva al levantar la app: la columna
    ``dispositivo_red_id`` se añade, pero la CHECK «un activo» quedaba obsoleta y
    guardar la credencial de un dispositivo fallaba. ``init_db`` debe repararla.
    """
    from pathlib import Path

    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("PASSWD_COOKIE_SECURE", "false")
    monkeypatch.delenv("PASSWD_DATABASE_URL", raising=False)

    from alembic import command
    from alembic.config import Config as AlembicConfig

    from app.config import reset_settings
    from app.database import get_db, init_db, reset_engine
    from app.security.crypto import cifrar

    reset_settings()
    reset_engine()

    # 1) BD anterior a los dispositivos: Alembic hasta la revisión 0004.
    raiz = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "migrations"))
    command.upgrade(cfg, "0004")
    reset_settings()

    # 2) "Levantar la app": init_db aplica lo aditivo Y repara las restricciones.
    init_db()

    # 3) Guardar la credencial de un dispositivo ya no debe fallar…
    from app.models import Credencial, DispositivoRed, ServidorFisico

    db = next(get_db())
    try:
        disp = DispositivoRed(nombre="sw-core-01", ip_gestion="10.0.0.2", descripcion="")
        db.add(disp)
        db.flush()
        db.add(Credencial(dispositivo_red_id=disp.id, usuario_acceso="admin",
                          password_cifrada=cifrar("SwitchPwd!2026"), servicio="SSH", descripcion=""))
        db.flush()
        # …y la CHECK «un activo» debe SEGUIR vigente (rechaza la credencial huérfana).
        import pytest
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(Credencial(usuario_acceso="x", password_cifrada=cifrar("y"),
                                  servicio="SSH", descripcion=""))
                db.flush()
        # Y el inventario clásico sigue intacto.
        srv = ServidorFisico(nombre="srv1", descripcion="", sistema_operativo="",
                             marca_modelo="", ubicacion="", ip_gestion="")
        db.add(srv)
        db.flush()
        db.commit()
    finally:
        db.close()

    # 4) Idempotente: un segundo arranque no vuelve a reconstruir nada.
    from app.database import get_engine
    from app.schema_sync import reconciliar_restricciones

    assert reconciliar_restricciones(get_engine()) == []

    reset_engine()
    reset_settings()
