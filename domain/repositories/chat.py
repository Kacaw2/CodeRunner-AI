"""Chat repositories for sync and async sessions.

Both repositories are constructed with a session and only stage (``add``),
read, or execute guarded UPDATEs. They DO NOT commit — the caller owns the
transaction/commit.

Task status transitions use an expected-state compare-and-set (an UPDATE
guarded by ``WHERE id=:id AND status=:expected``) and return whether the row
was actually transitioned, so an embedded worker and a future remote worker can
never both execute the same task.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.timezone import now_china
from domain.models.chat import AIConversation, AIMessage, ChatTask
from domain.statements.chat import (
    select_conversation_by_id,
    select_conversation_count_for_user,
    select_conversation_for_user,
    select_conversations_for_user,
    select_last_message_by_role,
    select_message_by_id,
    select_message_count,
    select_messages_ordered,
    select_recent_summarized_conversations,
    select_task_by_id,
    select_task_for_user,
    update_task_status_cas,
)


class SyncChatRepository:
    """Synchronous chat accessor bound to a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Conversations ─────────────────────────────────────────

    def create_conversation(
        self,
        *,
        user_id: int,
        agent_type: str,
        context_type: Optional[str] = None,
        context_id: Optional[int] = None,
    ) -> AIConversation:
        conv = AIConversation(
            user_id=user_id,
            agent_type=agent_type,
            context_type=context_type,
            context_id=context_id,
        )
        self.session.add(conv)
        return conv

    def get_conversation(self, conversation_id: int) -> Optional[AIConversation]:
        return self.session.execute(
            select_conversation_by_id(conversation_id)
        ).scalar_one_or_none()

    def get_conversation_for_user(
        self, conversation_id: int, user_id: int, *, agent_type: Optional[str] = None
    ) -> Optional[AIConversation]:
        return self.session.execute(
            select_conversation_for_user(conversation_id, user_id, agent_type)
        ).scalar_one_or_none()

    def list_conversations_for_user(
        self,
        user_id: int,
        *,
        agent_type: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[AIConversation]:
        stmt = (
            select_conversations_for_user(user_id, agent_type)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def count_conversations_for_user(
        self, user_id: int, *, agent_type: Optional[str] = None
    ) -> int:
        return self.session.execute(
            select_conversation_count_for_user(user_id, agent_type)
        ).scalar_one()

    def get_recent_summarized_conversations(
        self,
        user_id: int,
        *,
        exclude_conversation_id: Optional[int] = None,
        limit: int = 3,
    ) -> list[AIConversation]:
        return list(
            self.session.execute(
                select_recent_summarized_conversations(
                    user_id, exclude_conversation_id, limit
                )
            ).scalars()
        )

    # ── Messages ──────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: int,
        *,
        role: str,
        content: str,
    ) -> AIMessage:
        msg = AIMessage(
            conversation_id=conversation_id, role=role, content=content
        )
        self.session.add(msg)
        return msg

    def get_message(self, message_id: int) -> Optional[AIMessage]:
        return self.session.execute(
            select_message_by_id(message_id)
        ).scalar_one_or_none()

    def get_messages_ordered(self, conversation_id: int) -> list[AIMessage]:
        return list(
            self.session.execute(
                select_messages_ordered(conversation_id)
            ).scalars()
        )

    def get_last_message_by_role(
        self, conversation_id: int, role: str
    ) -> Optional[AIMessage]:
        return self.session.execute(
            select_last_message_by_role(conversation_id, role)
        ).scalars().first()

    def count_messages(self, conversation_id: int) -> int:
        return self.session.execute(
            select_message_count(conversation_id)
        ).scalar_one()

    # ── Tasks ─────────────────────────────────────────────────

    def create_task(
        self,
        *,
        conversation_id: int,
        user_id: int,
        user_message_id: Optional[int] = None,
        agent_type: str = "auto",
        routed_agent: Optional[str] = None,
        status: str = "pending",
    ) -> ChatTask:
        task = ChatTask(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message_id=user_message_id,
            agent_type=agent_type,
            routed_agent=routed_agent,
            status=status,
        )
        self.session.add(task)
        return task

    def get_task(self, task_id: str) -> Optional[ChatTask]:
        return self.session.execute(
            select_task_by_id(task_id)
        ).scalar_one_or_none()

    def get_task_for_user(self, task_id: str, user_id: int) -> Optional[ChatTask]:
        return self.session.execute(
            select_task_for_user(task_id, user_id)
        ).scalar_one_or_none()

    # ── Guarded status transitions (compare-and-set) ──────────

    def _cas(self, task_id: str, expected_status: str, **values) -> bool:
        """Run a guarded UPDATE; return whether the row was transitioned.

        Expires the identity-map copy so a subsequently re-read/refreshed
        object reflects the UPDATE.
        """
        result = self.session.execute(
            update_task_status_cas(task_id, expected_status, **values)
        )
        return result.rowcount == 1

    def mark_processing(self, task_id: str, *, expected_status: str = "pending") -> bool:
        return self._cas(
            task_id, expected_status, status="processing", started_at=now_china()
        )

    def mark_completed(
        self,
        task_id: str,
        *,
        expected_status: str = "processing",
        result_message_id: Optional[int] = None,
    ) -> bool:
        return self._cas(
            task_id,
            expected_status,
            status="completed",
            result_message_id=result_message_id,
            completed_at=now_china(),
        )

    def mark_failed(
        self, task_id: str, *, error_detail: str, expected_status: Optional[str] = None
    ) -> bool:
        """Mark a task failed.

        By default this is unconditional (matches the worker's catch-all error
        path which fails the task from whatever state it was in). Pass
        ``expected_status`` to make it a guarded transition.
        """
        if expected_status is not None:
            return self._cas(
                task_id,
                expected_status,
                status="failed",
                error_detail=error_detail,
                completed_at=now_china(),
            )
        from sqlalchemy import update

        result = self.session.execute(
            update(ChatTask)
            .where(ChatTask.id == task_id)
            .values(
                status="failed",
                error_detail=error_detail,
                completed_at=now_china(),
            )
        )
        return result.rowcount == 1


class AsyncChatRepository:
    """Asynchronous chat accessor bound to a SQLAlchemy ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Conversations ─────────────────────────────────────────

    def create_conversation(
        self,
        *,
        user_id: int,
        agent_type: str,
        context_type: Optional[str] = None,
        context_id: Optional[int] = None,
    ) -> AIConversation:
        conv = AIConversation(
            user_id=user_id,
            agent_type=agent_type,
            context_type=context_type,
            context_id=context_id,
        )
        self.session.add(conv)
        return conv

    async def get_conversation(self, conversation_id: int) -> Optional[AIConversation]:
        result = await self.session.execute(
            select_conversation_by_id(conversation_id)
        )
        return result.scalar_one_or_none()

    async def get_conversation_for_user(
        self, conversation_id: int, user_id: int
    ) -> Optional[AIConversation]:
        result = await self.session.execute(
            select_conversation_for_user(conversation_id, user_id)
        )
        return result.scalar_one_or_none()

    # ── Messages ──────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: int,
        *,
        role: str,
        content: str,
    ) -> AIMessage:
        msg = AIMessage(
            conversation_id=conversation_id, role=role, content=content
        )
        self.session.add(msg)
        return msg

    async def get_message(self, message_id: int) -> Optional[AIMessage]:
        result = await self.session.execute(select_message_by_id(message_id))
        return result.scalar_one_or_none()

    async def get_messages_ordered(self, conversation_id: int) -> list[AIMessage]:
        result = await self.session.execute(
            select_messages_ordered(conversation_id)
        )
        return list(result.scalars())

    async def count_messages(self, conversation_id: int) -> int:
        result = await self.session.execute(select_message_count(conversation_id))
        return result.scalar_one()

    # ── Tasks ─────────────────────────────────────────────────

    def create_task(
        self,
        *,
        conversation_id: int,
        user_id: int,
        user_message_id: Optional[int] = None,
        agent_type: str = "auto",
        routed_agent: Optional[str] = None,
        status: str = "pending",
    ) -> ChatTask:
        task = ChatTask(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message_id=user_message_id,
            agent_type=agent_type,
            routed_agent=routed_agent,
            status=status,
        )
        self.session.add(task)
        return task

    async def get_task(self, task_id: str) -> Optional[ChatTask]:
        result = await self.session.execute(select_task_by_id(task_id))
        return result.scalar_one_or_none()

    async def get_task_for_user(
        self, task_id: str, user_id: int
    ) -> Optional[ChatTask]:
        result = await self.session.execute(select_task_for_user(task_id, user_id))
        return result.scalar_one_or_none()

    # ── Guarded status transitions (compare-and-set) ──────────

    async def _cas(self, task_id: str, expected_status: str, **values) -> bool:
        result = await self.session.execute(
            update_task_status_cas(task_id, expected_status, **values)
        )
        return result.rowcount == 1

    async def mark_processing(
        self, task_id: str, *, expected_status: str = "pending"
    ) -> bool:
        return await self._cas(
            task_id, expected_status, status="processing", started_at=now_china()
        )

    async def mark_completed(
        self,
        task_id: str,
        *,
        expected_status: str = "processing",
        result_message_id: Optional[int] = None,
    ) -> bool:
        return await self._cas(
            task_id,
            expected_status,
            status="completed",
            result_message_id=result_message_id,
            completed_at=now_china(),
        )

    async def mark_failed(
        self, task_id: str, *, error_detail: str, expected_status: Optional[str] = None
    ) -> bool:
        if expected_status is not None:
            return await self._cas(
                task_id,
                expected_status,
                status="failed",
                error_detail=error_detail,
                completed_at=now_china(),
            )
        from sqlalchemy import update

        result = await self.session.execute(
            update(ChatTask)
            .where(ChatTask.id == task_id)
            .values(
                status="failed",
                error_detail=error_detail,
                completed_at=now_china(),
            )
        )
        return result.rowcount == 1
