"""Entorno de Alembic: enlaza las migraciones con el modelo de la aplicación.

La URL de conexión se resuelve desde la configuración real de la app
(``PASSWD_DATABASE_URL`` o el SQLite del directorio de datos), así las
migraciones actúan sobre la misma base que usa el servicio.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401 — registra todas las tablas en Base.metadata
from app.config import get_settings
from app.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Modo offline: emite el SQL sin conectarse (``alembic upgrade --sql``)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # ALTER portable también en SQLite
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # ALTER portable también en SQLite
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
