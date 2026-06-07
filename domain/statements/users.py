"""``select(User)`` builders usable by both sync and async sessions.

Keeping the statement construction here (separate from execution) lets the sync
Flask request path and any async runtime share the exact same query semantics.
"""

from __future__ import annotations

from sqlalchemy import Select, or_, select

from domain.models.user import User


def select_user_by_id(user_id: int) -> Select:
    """Build a statement selecting the user with the given primary key."""
    return select(User).where(User.id == user_id)


def select_user_by_username(username: str) -> Select:
    """Build a statement selecting the user with the given username."""
    return select(User).where(User.username == username)


def select_user_by_email(email: str) -> Select:
    """Build a statement selecting the user with the given email."""
    return select(User).where(User.email == email)


def select_user_by_username_or_email(identifier: str) -> Select:
    """Build a statement matching ``username`` OR ``email`` against one value."""
    return select(User).where(
        or_(User.username == identifier, User.email == identifier)
    )
