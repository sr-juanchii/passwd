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
