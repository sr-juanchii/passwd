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
from sqlalchemy.schema import CreateIndex, CreateTable

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


# ---------------------------------------------------------------------------
# Reconciliación de restricciones obsoletas (no aditivas pero seguras)
# ---------------------------------------------------------------------------
#
# Una BD anterior a los «dispositivos de red» que se actualiza de forma aditiva
# (se le añade la columna ``dispositivo_red_id``) conserva la restricción CHECK
# «exactamente un activo» en su versión de 3 términos, y la UNIQUE de
# concesiones sin esa columna. Guardar la credencial/concesión de un dispositivo
# viola entonces la restricción (error 500 en producción). Este paso las pone al
# día. Es idempotente y seguro: recrear la restricción revalida las filas
# existentes, que ya la cumplen (los tres campos antiguos no cambian).

_NOMBRE_CHECK = {
    "credenciales": "ck_credenciales_un_activo",
    "concesiones_acceso": "ck_concesiones_un_activo",
}
_TABLAS_RESTRINGIDAS = ("credenciales", "concesiones_acceso")

_CHECK_UN_ACTIVO = (
    "(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1"
)
_UNIQUE_CONCESION = (
    "usuario_id, servidor_fisico_id, hipervisor_id, maquina_virtual_id, dispositivo_red_id"
)


def _check_incluye_dispositivo(engine: Engine, tabla: str) -> bool:
    """¿La CHECK «un activo» de la tabla ya contempla ``dispositivo_red_id``?

    Devuelve ``True`` (no reparar) cuando ya está al día o cuando no se puede
    localizar la restricción con seguridad (para no intervenir a ciegas).
    """
    nombre = _NOMBRE_CHECK[tabla]
    dialecto = engine.dialect.name
    if dialecto == "sqlite":
        with engine.connect() as con:
            sql = con.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": tabla}
            ).scalar()
        if not sql or nombre not in sql:
            return True
        pos = sql.find(nombre)
        return "dispositivo_red_id" in sql[pos:pos + 400]
    if dialecto in ("mysql", "mariadb"):
        with engine.connect() as con:
            clausula = con.execute(
                text(
                    "SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
                    "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = :n"
                ),
                {"n": nombre},
            ).scalar()
        if clausula is None:
            return True
        return "dispositivo_red_id" in clausula
    return True  # otros motores: no intervenir


def _reparar_sqlite(engine: Engine, tablas: list[str]) -> list[str]:
    """Recrea cada tabla con las restricciones actuales del modelo (batch rebuild)."""
    reparadas: list[str] = []
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")  # fuera de transacción: efectivo
        for nombre in tablas:
            tabla = Base.metadata.tables[nombre]
            columnas = ", ".join(c.name for c in tabla.columns)
            # Copia temporal DENTRO de Base.metadata para que sus claves foráneas
            # resuelvan las tablas referidas; se retira tras compilar el DDL.
            temporal = tabla.to_metadata(Base.metadata, name=f"{nombre}__nuevo")
            try:
                crear = str(CreateTable(temporal).compile(engine))
            finally:
                Base.metadata.remove(temporal)
            # Los nombres provienen del modelo (constantes internas), no de
            # entrada del usuario: no hay riesgo de inyección.
            cur.execute("BEGIN")
            cur.execute(crear)  # tabla temporal con las restricciones del modelo (sin índices)
            insertar = f"INSERT INTO {nombre}__nuevo ({columnas}) SELECT {columnas} FROM {nombre}"  # noqa: S608  # nosec B608
            cur.execute(insertar)
            cur.execute(f"DROP TABLE {nombre}")
            cur.execute(f"ALTER TABLE {nombre}__nuevo RENAME TO {nombre}")
            for indice in tabla.indexes:
                cur.execute(str(CreateIndex(indice).compile(engine)))
            raw.commit()
            reparadas.append(nombre)
            logger.warning("Esquema: restricciones de «%s» actualizadas (dispositivos de red).", nombre)
        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        try:
            raw.cursor().execute("PRAGMA foreign_keys=ON")
        except Exception:  # noqa: BLE001, S110 — restaurar FK es de mejor esfuerzo
            pass
        raw.close()
    return reparadas


def _reparar_mysql(engine: Engine, dialecto: str, tablas: list[str]) -> list[str]:
    """Actualiza las restricciones con ALTER TABLE (MySQL 8 / MariaDB)."""
    reparadas: list[str] = []
    with engine.begin() as con:
        for nombre in tablas:
            check = _NOMBRE_CHECK[nombre]
            # MySQL 8 usa DROP CHECK; MariaDB, DROP CONSTRAINT. Se prueban ambos.
            for drop in (f"ALTER TABLE {nombre} DROP CHECK {check}",
                         f"ALTER TABLE {nombre} DROP CONSTRAINT {check}"):
                try:
                    con.execute(text(drop))
                    break
                except Exception:  # noqa: BLE001, S112 — se intenta la otra sintaxis
                    continue
            con.execute(text(f"ALTER TABLE {nombre} ADD CONSTRAINT {check} CHECK ({_CHECK_UN_ACTIVO})"))
            reparadas.append(f"{nombre}.{check}")
            logger.warning("Esquema: CHECK «%s» actualizada (dispositivos de red).", check)
        if "concesiones_acceso" in tablas:
            con.execute(text("ALTER TABLE concesiones_acceso DROP INDEX uq_concesion_usuario_activo"))
            con.execute(text(
                "ALTER TABLE concesiones_acceso ADD CONSTRAINT uq_concesion_usuario_activo "
                f"UNIQUE ({_UNIQUE_CONCESION})"
            ))
            reparadas.append("concesiones_acceso.uq_concesion_usuario_activo")
            logger.warning("Esquema: UNIQUE de concesiones actualizada (dispositivos de red).")
    return reparadas


def reconciliar_restricciones(engine: Engine) -> list[str]:
    """Pone al día las restricciones CHECK/UNIQUE de inventario que quedaron obsoletas.

    Repara una BD anterior a los dispositivos de red actualizada aditivamente.
    Idempotente: si ya están al día no hace nada. Nunca aborta el arranque; ante
    un fallo, registra la reparación manual necesaria y continúa.
    """
    try:
        inspector = inspect(engine)
        tablas = set(inspector.get_table_names())
        if "dispositivos_red" not in tablas:
            return []  # aún no existe el activo: nada que reconciliar
        pendientes = [
            t for t in _TABLAS_RESTRINGIDAS
            if t in tablas
            and "dispositivo_red_id" in {c["name"] for c in inspector.get_columns(t)}
            and not _check_incluye_dispositivo(engine, t)
        ]
        if not pendientes:
            return []
        dialecto = engine.dialect.name
        if dialecto == "sqlite":
            return _reparar_sqlite(engine, pendientes)
        if dialecto in ("mysql", "mariadb"):
            return _reparar_mysql(engine, dialecto, pendientes)
        logger.warning(
            "Restricciones de inventario obsoletas (%s) en el motor «%s», que no admite "
            "reparación automática. Aplique las migraciones de Alembic.", pendientes, dialecto,
        )
        return []
    except Exception:  # noqa: BLE001 — no debe impedir el arranque de la app
        logger.exception(
            "No se pudieron reconciliar las restricciones de inventario automáticamente. "
            "Repárelas a mano: la CHECK «un activo» y la UNIQUE de concesiones deben incluir "
            "dispositivo_red_id (ver docs/guia-implementacion.md)."
        )
        return []
