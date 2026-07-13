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
        opciones: dict = {"pool_pre_ping": True}
        if settings.database_url.startswith("sqlite"):
            opciones["connect_args"] = {"check_same_thread": False}
        else:
            # Pool afinado para motores cliente/servidor (MySQL/MariaDB): tamaño,
            # desbordamiento y reciclado antes del wait_timeout del servidor.
            opciones["pool_size"] = settings.db_pool_size
            opciones["max_overflow"] = settings.db_max_overflow
            opciones["pool_recycle"] = settings.db_pool_recycle
            # MySQL/MariaDB usan REPEATABLE READ por defecto: una sesión fija su
            # snapshot al primer SELECT y no ve los commits posteriores de otras
            # transacciones durante toda su vida. En el flujo multi-paso (login →
            # cambio de contraseña → MFA → sesión activa) cada petición es una
            # transacción nueva que debe ver el cambio recién confirmado por la
            # anterior; con READ COMMITTED cada sentencia lee el último estado
            # confirmado, eliminando esa lectura-tras-escritura obsoleta. SQLite
            # no tiene este problema (sin MVCC multi-versión por conexión).
            opciones["isolation_level"] = "READ COMMITTED"
        _engine = create_engine(settings.database_url, **opciones)
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _activar_fk(dbapi_conn, _record) -> None:  # pragma: no cover
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    """Crea las tablas que falten y reconcilia columnas nuevas (cambios aditivos)."""
    from app import models  # noqa: F401  (registra los modelos)
    from app.schema_sync import migrar_inventario_nivel_superior, reconciliar_esquema

    engine = get_engine()
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
