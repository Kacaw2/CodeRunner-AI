"""Minimal standalone User model for Agent Host — read-only access to role info."""

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Mapped

from core.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = Column(Integer, primary_key=True)
    role: Mapped[str] = Column(String(20), nullable=False)
