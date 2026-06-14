"""Reconciliación de esquema idempotente y sin dependencias.

Cubre los cambios **aditivos** (tablas nuevas y columnas nuevas) para que las
bases de datos existentes adopten versiones nuevas sin recrearse ni perder
datos. Se ejecuta al arrancar, tras ``create_all``:

- Tablas nuevas: las crea ``create_all``.
- Columnas nuevas: se añaden con ``ALTER TABLE ADD COLUMN`` (soportado por
  SQLite y MySQL), respetando tipo y ``server_default`` cuando existan.

Para cambios **no aditivos** (eliminar/renombrar columnas, cambiar tipos o
restricciones CHECK) se recomienda adoptar Alembic; este reconciliador no los
realiza a propósito, para no arriesgar los datos.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import Base

logger = logging.getLogger("passwd.schema")


def reconciliar_esquema(engine: Engine) -> list[str]:
    """Añade columnas que falten en las tablas existentes. Devuelve lo aplicado."""
    inspector = inspect(engine)
    tablas_existentes = set(inspector.get_table_names())
    compilador = engine.dialect.ddl_compiler(engine.dialect, None)
    aplicados: list[str] = []

    with engine.begin() as conexion:
        for tabla in Base.metadata.sorted_tables:
            if tabla.name not in tablas_existentes:
                continue  # tabla nueva: la crea create_all
            columnas_db = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in columnas_db:
                    continue
                # SQLAlchemy renderiza tipo, NOT NULL y DEFAULT (entrecomillado
                # correctamente). Las columnas nuevas deben traer server_default
                # para poder añadirse NOT NULL sobre filas existentes.
                especificacion = compilador.get_column_specification(columna)
                conexion.execute(text(f"ALTER TABLE {tabla.name} ADD COLUMN {especificacion}"))
                aplicados.append(f"{tabla.name}.{columna.name}")
                logger.info("Esquema: columna añadida %s.%s", tabla.name, columna.name)

    return aplicados
