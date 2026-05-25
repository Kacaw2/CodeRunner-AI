"""Standalone SQLAlchemy session factory for MCP Server (no Flask dependency)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

_engine = None
_SessionLocal = None


def init_db(database_url: str):
    global _engine, _SessionLocal
    _engine = create_engine(
        database_url,
        pool_size=5,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    _SessionLocal = sessionmaker(bind=_engine)


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _SessionLocal()
