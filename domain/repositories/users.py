"""User repositories for sync and async sessions.

Both repositories are constructed with a session and only stage (``add``) or read
(``get_*``). They DO NOT commit — the caller owns the transaction/commit.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from domain.models.user import User
from domain.statements.users import (
    select_user_by_email,
    select_user_by_id,
    select_user_by_username,
    select_user_by_username_or_email,
)


class SyncUserRepository:
    """Synchronous user accessor bound to a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> User:
        """Stage a user for insertion. Does NOT commit."""
        self.session.add(user)
        return user

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.session.execute(select_user_by_id(user_id)).scalar_one_or_none()

    def get_by_username(self, username: str) -> Optional[User]:
        return self.session.execute(
            select_user_by_username(username)
        ).scalar_one_or_none()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.session.execute(
            select_user_by_email(email)
        ).scalar_one_or_none()

    def get_by_username_or_email(self, identifier: str) -> Optional[User]:
        return self.session.execute(
            select_user_by_username_or_email(identifier)
        ).scalar_one_or_none()


class AsyncUserRepository:
    """Asynchronous user accessor bound to a SQLAlchemy ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, user: User) -> User:
        """Stage a user for insertion. Does NOT commit."""
        self.session.add(user)
        return user

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(select_user_by_id(user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        result = await self.session.execute(select_user_by_username(username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(select_user_by_email(email))
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, identifier: str) -> Optional[User]:
        result = await self.session.execute(
            select_user_by_username_or_email(identifier)
        )
        return result.scalar_one_or_none()
