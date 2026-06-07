"""Async SQLAlchemy session factory for the FastAPI agent runtime.

Lazily initialized: the async engine is only built when first requested, so
importing this module never requires the async driver (``asyncmy``) to be
installed and never raises on the SQLite/sync Flask test path.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        _async_engine = create_async_engine(
            settings.DB_ASYNC_URL,
            pool_size=settings.DB_POOL_SIZE,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
            echo=settings.DEBUG,
        )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(), expire_on_commit=False
        )
    return _AsyncSessionLocal


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Async dependency that yields a session and closes it on exit."""
    factory = get_async_session_factory()
    async with factory() as session:
        yield session
