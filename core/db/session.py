"""Unified SQLAlchemy session factory — replaces agent_host/core/db.py and mcp_gateway/db.py."""

import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from core.config import get_settings
from domain.base import DomainBase

logger = logging.getLogger(__name__)

# Temporary import-compatibility alias. There is exactly ONE registry/metadata
# in the app (``DomainBase``); ``Base`` is kept only so existing imports of
# ``core.db.session.Base`` keep working. It is NOT a second registry.
Base = DomainBase

_engine = None
_SessionLocal = None


def init_db(database_url: str | None = None):
    """Optional explicit initializer (used by mcp_gateway entry point)."""
    global _engine, _SessionLocal
    if database_url is None:
        database_url = get_settings().DB_URL
    _engine = create_engine(
        database_url,
        pool_size=5,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.DB_URL,
            pool_size=settings.DB_POOL_SIZE,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
            echo=settings.DEBUG,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def get_session() -> Session:
    """Plain session getter (used by mcp_gateway and non-request code)."""
    return get_session_factory()()


def get_db() -> Session:
    """FastAPI dependency that yields a DB session and auto-closes it."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def db_session() -> Session:
    """Context-manager for non-request code (workers, startup)."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
