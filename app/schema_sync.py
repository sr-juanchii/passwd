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

# Tablas del subgrafo de inventario en orden hijo→padre (para poder borrarlas
# respetando las claves foráneas).
_TABLAS_INVENTARIO = (
    "historial_credenciales",
    "credenciales",
    "concesiones_acceso",
    "maquinas_virtuales",
    "hipervisores",
    "servidores_fisicos",
)


def migrar_inventario_nivel_superior(engine: Engine) -> bool:
    """Migra el inventario al modelo de hipervisores de nivel superior.

    En el modelo nuevo el hipervisor es un activo de nivel superior (no se anida
    bajo un servidor físico), por lo que la tabla ``hipervisores`` ya no tiene la
    columna ``servidor_fisico_id``. Si se detecta el esquema antiguo (esa columna
    presente), se recrean las tablas de inventario con el esquema nuevo.

    Es un cambio NO aditivo (cambia claves foráneas y columnas), de modo que solo
    es seguro porque el inventario se considera recreable; las cuentas de usuario
    y la bitácora de auditoría NO se tocan. Idempotente: no hace nada si el
    esquema ya es el nuevo o si la base está vacía.
    """
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    if "hipervisores" not in tablas:
        return False  # base nueva: create_all construirá el esquema nuevo
    columnas = {c["name"] for c in inspector.get_columns("hipervisores")}
    if "servidor_fisico_id" not in columnas:
        return False  # ya está en el esquema nuevo

    logger.warning(
        "Esquema de inventario antiguo detectado (hipervisor anidado). Recreando "
        "las tablas de inventario con el modelo nuevo; el inventario previo se descarta "
        "(usuarios y auditoría se conservan)."
    )
    es_sqlite = engine.dialect.name == "sqlite"
    with engine.begin() as conexion:
        if es_sqlite:
            conexion.execute(text("PRAGMA foreign_keys=OFF"))
        for tabla in _TABLAS_INVENTARIO:
            if tabla in tablas:
                conexion.execute(text(f"DROP TABLE IF EXISTS {tabla}"))
        if es_sqlite:
            conexion.execute(text("PRAGMA foreign_keys=ON"))
    return True


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
