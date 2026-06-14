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
    aplicados: list[str] = []

    with engine.begin() as conexion:
        for tabla in Base.metadata.sorted_tables:
            if tabla.name not in tablas_existentes:
                continue  # tabla nueva: la crea create_all
            columnas_db = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in columnas_db:
                    continue
                tipo_ddl = columna.type.compile(dialect=engine.dialect)
                clausula = f'ALTER TABLE {tabla.name} ADD COLUMN "{columna.name}" {tipo_ddl}'
                # Solo se marca NOT NULL si hay un valor por defecto a nivel de
                # servidor; de lo contrario se añade nullable para no romper las
                # filas ya existentes.
                if columna.server_default is not None:
                    defecto = columna.server_default.arg  # type: ignore[attr-defined]
                    defecto_txt = defecto.text if hasattr(defecto, "text") else str(defecto)
                    clausula += f" DEFAULT {defecto_txt}"
                    if not columna.nullable:
                        clausula += " NOT NULL"
                conexion.execute(text(clausula))
                aplicados.append(f"{tabla.name}.{columna.name}")
                logger.info("Esquema: columna añadida %s.%s", tabla.name, columna.name)

    return aplicados
