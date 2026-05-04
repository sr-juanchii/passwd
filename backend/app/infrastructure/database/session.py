from __future__ import annotations

import logging
import ssl
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config.settings import Settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_ssl_context(cafile: str) -> ssl.SSLContext:
    ca_path = Path(cafile)
    if not ca_path.is_file():
        raise FileNotFoundError(f"Database CA file not found: {cafile}")

    context = ssl.create_default_context(cafile=str(ca_path))
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


async def init_db_engine(settings: Settings) -> None:
    """Create the async SQLAlchemy engine with optimized connection pooling."""

    global _engine, _session_factory

    if _engine is not None:
        return

    engine_kwargs: dict[str, object] = {
        "echo": False,
        "poolclass": AsyncAdaptedQueuePool,
        "pool_size": 20,
        "max_overflow": 10,
        "pool_timeout": 20,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_reset_on_return": "rollback",
        "echo_pool": False,
    }

    ssl_context = _build_ssl_context(settings.database_ssl_ca)
    engine_kwargs["connect_args"] = {"ssl": ssl_context}

    _engine = create_async_engine(settings.async_database_url, **engine_kwargs)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    logger.info(
        "Database engine initialised with optimized pooling",
        extra={
            "host": settings.database_host,
            "ssl": ssl_context is not None,
            "pool_size": 20,
            "max_overflow": 10,
        },
    )


async def dispose_db_engine() -> None:
    """Dispose the async engine if it exists."""

    global _engine, _session_factory

    if _engine is None:
        return

    await _engine.dispose()
    _engine = None
    _session_factory = None
    logger.info("Database engine disposed")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a per-request async database session."""

    if _session_factory is None:
        raise RuntimeError("Database engine has not been initialised")

    async with _session_factory() as session:
        yield session
