"""``select`` / ``update`` builders for the chat domain.

Keeping statement construction here (separate from execution) lets the sync
Flask request path and any async runtime share the exact same query semantics.
The status-transition UPDATEs are guarded compare-and-set statements
(``WHERE id=:id AND status=:expected``) so two workers can never both drive the
same task through a transition.
"""

from __future__ import annotations

from sqlalchemy import Select, Update, func, select, update

from domain.models.chat import AIConversation, AIMessage, ChatTask


# ── Conversations ─────────────────────────────────────────────

def select_conversation_by_id(conversation_id: int) -> Select:
    return select(AIConversation).where(AIConversation.id == conversation_id)


def select_conversation_for_user(
    conversation_id: int, user_id: int, agent_type: str | None = None
) -> Select:
    stmt = select(AIConversation).where(
        AIConversation.id == conversation_id,
        AIConversation.user_id == user_id,
    )
    if agent_type is not None:
        stmt = stmt.where(AIConversation.agent_type == agent_type)
    return stmt


def select_conversations_for_user(
    user_id: int, agent_type: str | None = None
) -> Select:
    """Conversations owned by a user, newest-updated first.

    Used to list conversations. Apply ``offset``/``limit`` at the call site.
    """
    stmt = select(AIConversation).where(AIConversation.user_id == user_id)
    if agent_type:
        stmt = stmt.where(AIConversation.agent_type == agent_type)
    return stmt.order_by(AIConversation.updated_at.desc())


def select_conversation_count_for_user(
    user_id: int, agent_type: str | None = None
) -> Select:
    stmt = select(func.count(AIConversation.id)).where(
        AIConversation.user_id == user_id
    )
    if agent_type:
        stmt = stmt.where(AIConversation.agent_type == agent_type)
    return stmt


def select_recent_summarized_conversations(
    user_id: int,
    exclude_conversation_id: int | None = None,
    limit: int = 3,
    agent_types: tuple[str, ...] | None = None,
) -> Select:
    """Most recent prior conversations of a user that already have a summary.

    Mirrors the mid-term memory query: summary present, optionally excluding the
    current conversation and restricting to specific ``agent_type`` values,
    ordered by ``updated_at`` desc and limited.
    """
    stmt = (
        select(AIConversation)
        .where(AIConversation.user_id == user_id)
        .where(AIConversation.summary.isnot(None))
    )
    if exclude_conversation_id is not None:
        stmt = stmt.where(AIConversation.id != exclude_conversation_id)
    if agent_types:
        stmt = stmt.where(AIConversation.agent_type.in_(agent_types))
    return stmt.order_by(AIConversation.updated_at.desc()).limit(limit)


# ── Messages ──────────────────────────────────────────────────

def select_messages_ordered(conversation_id: int) -> Select:
    """All messages for a conversation, ordered by ``AIMessage.id``."""
    return (
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.id)
    )


def select_message_count(conversation_id: int) -> Select:
    return select(func.count(AIMessage.id)).where(
        AIMessage.conversation_id == conversation_id
    )


def select_message_by_id(message_id: int) -> Select:
    return select(AIMessage).where(AIMessage.id == message_id)


def select_last_message_by_role(conversation_id: int, role: str) -> Select:
    """The newest message (highest id) of a given role in a conversation."""
    return (
        select(AIMessage)
        .where(
            AIMessage.conversation_id == conversation_id,
            AIMessage.role == role,
        )
        .order_by(AIMessage.id.desc())
    )


# ── Tasks ─────────────────────────────────────────────────────

def select_task_by_id(task_id: str) -> Select:
    return select(ChatTask).where(ChatTask.id == task_id)


def select_task_for_user(task_id: str, user_id: int) -> Select:
    return select(ChatTask).where(
        ChatTask.id == task_id,
        ChatTask.user_id == user_id,
    )


# ── Guarded status transitions (compare-and-set) ──────────────

def update_task_status_cas(task_id: str, expected_status: str, **values) -> Update:
    """Build a guarded UPDATE: transition the task only if it is still in
    ``expected_status``. Additional column values are set atomically.

    The statement matches at most one row; the caller inspects
    ``result.rowcount`` to learn whether the transition actually happened.
    """
    return (
        update(ChatTask)
        .where(ChatTask.id == task_id, ChatTask.status == expected_status)
        .values(**values)
    )
