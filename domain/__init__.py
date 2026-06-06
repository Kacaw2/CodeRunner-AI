"""Runtime-neutral domain layer.

This package MUST NOT import Flask or FastAPI. It owns the single SQLAlchemy
``DeclarativeBase`` (:class:`domain.base.DomainBase`) shared by every process.
"""

from domain.base import DomainBase

__all__ = ["DomainBase"]
