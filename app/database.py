"""Motor de base de datos y sesiones SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings
from app.exceptions import RedirigirLogin


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        database_url = settings.database_url
        if database_url.startswith("mysql://"):
            database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
        opciones: dict = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            opciones["connect_args"] = {"check_same_thread": False}
        elif database_url.startswith(("postgresql", "postgres")):
            # Fuerza UTF-8 en el cliente (las BD gestionadas tipo Neon son UTF8);
            # evita errores de codificación si el servidor declarara otra cosa.
            opciones["connect_args"] = {"client_encoding": "utf8"}
        _engine = create_engine(database_url, **opciones)
        if database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _activar_fk(dbapi_conn, _record) -> None:  # pragma: no cover
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _esperar_bd(engine: Engine, intentos: int = 10, espera: float = 3.0) -> None:
    """Espera a que la BD acepte conexiones (la gestionada puede tardar en arrancar).

    Reintenta con una pausa fija; si tras todos los intentos sigue sin conectar,
    relanza el error (fallo ruidoso = configuración de BD incorrecta, p. ej. falta
    el plugin/Neon o ``PASSWD_DATABASE_URL`` no resuelve).
    """
    import logging
    import time

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    logger = logging.getLogger("passwd.db")
    for intento in range(1, intentos + 1):
        try:
            with engine.connect() as conexion:
                conexion.execute(text("SELECT 1"))
            return
        except OperationalError:
            if intento == intentos:
                logger.error("No se pudo conectar a la base de datos tras %s intentos.", intentos)
                raise
            logger.warning("BD no disponible (intento %s/%s); reintentando en %ss…", intento, intentos, espera)
            time.sleep(espera)


def init_db() -> None:
    """Crea las tablas que falten y reconcilia columnas nuevas (cambios aditivos)."""
    from app import models  # noqa: F401  (registra los modelos)
    from app.schema_sync import migrar_inventario_nivel_superior, reconciliar_esquema

    engine = get_engine()
    # Espera a que la BD acepte conexiones (despliegues gestionados: Railway/Neon…).
    _esperar_bd(engine)
    # Migración no aditiva del inventario (hipervisor de nivel superior) ANTES de
    # create_all, para que este recree las tablas de inventario con el esquema nuevo.
    migrar_inventario_nivel_superior(engine)
    Base.metadata.create_all(engine)
    reconciliar_esquema(engine)


def get_db() -> Iterator[Session]:
    """Dependencia FastAPI: una sesión de BD por petición."""
    get_engine()
    assert _session_factory is not None
    db = _session_factory()
    try:
        yield db
        db.commit()
    except RedirigirLogin:
        # Persistir revocaciones de sesiones expiradas antes de redirigir.
        db.commit()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_engine() -> None:
    """Libera el motor (uso exclusivo en pruebas)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
