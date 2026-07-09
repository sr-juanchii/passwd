"""ESC-1 — migraciones con Alembic (`docs/analisis-mejoras.md`).

La revisión baseline (0001) debe reproducir EXACTAMENTE el mismo esquema que
`Base.metadata.create_all()`: mismas tablas y mismas columnas. Si el modelo
cambia sin su migración correspondiente, esta prueba lo detecta.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

RAIZ = Path(__file__).resolve().parents[1]


def _esquema(engine) -> dict[str, set[str]]:
    inspector = inspect(engine)
    return {
        tabla: {col["name"] for col in inspector.get_columns(tabla)}
        for tabla in inspector.get_table_names()
        if tabla != "alembic_version"
    }


def test_alembic_baseline_reproduce_el_esquema_completo(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from app import models  # noqa: F401 — registra las tablas en Base.metadata
    from app.config import reset_settings
    from app.database import Base

    # Esquema de referencia: create_all sobre una BD limpia.
    engine_modelo = create_engine(f"sqlite:///{tmp_path / 'modelo.db'}")
    Base.metadata.create_all(engine_modelo)
    esquema_modelo = _esquema(engine_modelo)
    engine_modelo.dispose()

    # Esquema migrado: alembic upgrade head sobre otra BD limpia.
    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "migrada"))
    monkeypatch.delenv("PASSWD_DATABASE_URL", raising=False)
    reset_settings()
    configuracion = AlembicConfig(str(RAIZ / "alembic.ini"))
    configuracion.set_main_option("script_location", str(RAIZ / "migrations"))
    command.upgrade(configuracion, "head")
    reset_settings()

    engine_migrada = create_engine(f"sqlite:///{tmp_path / 'migrada' / 'passwd.db'}")
    esquema_migrado = _esquema(engine_migrada)
    engine_migrada.dispose()

    assert set(esquema_migrado) == set(esquema_modelo)
    for tabla, columnas in esquema_modelo.items():
        assert esquema_migrado[tabla] == columnas, f"Columnas distintas en {tabla}"
