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
