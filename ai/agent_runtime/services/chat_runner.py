"""Async chat runner — reproduces the embedded worker on the shared domain.

This is the remote counterpart of ``workers/chat.py::_run_chat_task``. It must
produce the SAME persisted outcome (task status via CAS, assistant message,
conversation title/agent_type updates) and the SAME Redis/SSE events so the
existing Flask SSE endpoint keeps working unchanged.

Async strategy (judgment call from the task brief): the agent kernel
(LangChain + DeepSeek, tracing, MCP capability tokens, the handoff loop) is
synchronous and deeply nested. Rather than fork a parallel async kernel — which
would duplicate the trace/tool/handoff logic and risk drift from the embedded
worker — the synchronous agent loop runs OFF the event loop via
``asyncio.to_thread``. The async path owns all DB I/O (AsyncChatRepository) and
Redis I/O; only the CPU/blocking agent stream is delegated to a worker thread.
This keeps the kernel (and its signed capability tokens, scope, trace_id and
envelope) byte-for-byte identical to the embedded path while never blocking the
event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from domain.repositories.chat import AsyncChatRepository

logger = logging.getLogger(__name__)

# Redis key patterns — IDENTICAL to workers/chat.py (the SSE contract).
_STATUS_KEY = "chat_task:{task_id}:status"
_BUFFER_KEY = "chat_task:{task_id}:buffer"
_AGENT_KEY = "chat_task:{task_id}:agent"
_TTL = 3600


class RedisSSEWriter:
    """Writes the task status + SSE event buffer to Redis.

    Wraps the same key layout / TTLs as ``workers/chat.py`` so the Flask stream
    endpoint reads remote-produced events transparently. ``redis_client`` may be
    None (events are simply dropped, mirroring the embedded worker) or any object
    implementing ``set``/``rpush``/``expire``/``lrange``/``get`` — including a
    fake used in tests.
    """

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    def set_status(self, task_id: str, status: str, agent: Optional[str] = None) -> None:
        if not self.redis:
            return
        try:
            self.redis.set(_STATUS_KEY.format(task_id=task_id), status, ex=_TTL)
            if agent:
                self.redis.set(_AGENT_KEY.format(task_id=task_id), agent, ex=_TTL)
        except Exception as exc:  # pragma: no cover - best effort, like worker
            logger.warning("Redis set failed for task %s: %s", task_id, exc)

    def push_event(self, task_id: str, event: dict) -> None:
        if not self.redis:
            return
        try:
            key = _BUFFER_KEY.format(task_id=task_id)
            self.redis.rpush(key, json.dumps(event, ensure_ascii=False))
            self.redis.expire(key, _TTL)
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis push failed for task %s: %s", task_id, exc)

    def read_events(self, task_id: str, start: int = 0) -> list:
        if not self.redis:
            return []
        try:
            key = _BUFFER_KEY.format(task_id=task_id)
            return [json.loads(r) for r in self.redis.lrange(key, start, -1)]
        except Exception:  # pragma: no cover
            return []

    def read_status(self, task_id: str) -> dict:
        if not self.redis:
            return {}
        try:
            return {
                "status": self.redis.get(_STATUS_KEY.format(task_id=task_id)),
                "agent": self.redis.get(_AGENT_KEY.format(task_id=task_id)),
            }
        except Exception:  # pragma: no cover
            return {}


def _try_extract_json(text: str):
    """Extract a JSON object from LLM output (supports ```json fences).

    Identical to ``workers/chat.py::_try_extract_json``.
    """
    fence = re.search(r"```json\s*\n?(.*?)```", text, re.DOTALL)
    raw = fence.group(1) if fence else text
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if not brace:
        return None
    try:
        return json.loads(brace.group())
    except json.JSONDecodeError:
        return None


def _chat_context_from_conversation(conv) -> dict:
    context = {"conversation_id": conv.id if conv else None}
    if conv and conv.context_type == "question" and conv.context_id is not None:
        context["question_id"] = conv.context_id
    return context


def _run_agent_stream(state, resolved_agent_type, task_agent_type):
    """Synchronous agent execution (runs in a worker thread).

    Mirrors the embedded worker's stream + handoff loop exactly. Collects every
    event into a list (instead of pushing to Redis from inside the thread, which
    keeps all Redis I/O on the event loop) and returns
    ``(events, final_agent_type, full_response, draft_payload_or_None)``.
    """
    from ai.agents.registry import AGENT_CLASSES, get_agent_instance
    from ai.graph.handoff import apply_handoff
    from ai.graph.runner import MAX_HANDOFFS

    events: list[dict] = []

    events.append({
        "type": "start",
        "conversation_id": state["context"].get("conversation_id"),
        "agent_type": resolved_agent_type,
    })
    if resolved_agent_type != task_agent_type:
        events.append({"type": "route", "agent_type": resolved_agent_type})

    agent = get_agent_instance(resolved_agent_type, default="tutor")
    full_response = ""
    for event in agent.stream(state):
        if event["type"] == "token":
            full_response += event["content"]
        events.append(event)

    handoff_count = 0
    previous_agents = [resolved_agent_type]
    while (
        state.get("handoff_to")
        and handoff_count < MAX_HANDOFFS
        and state["handoff_to"] in AGENT_CLASSES
        and state["handoff_to"] not in previous_agents
    ):
        target_type = state["handoff_to"]
        events.append({
            "type": "handoff_start",
            "target": target_type,
            "reason": state.get("handoff_reason", ""),
        })
        apply_handoff(state, use_reducer=False)
        target_agent = get_agent_instance(target_type, default="tutor")
        full_response = ""
        for event in target_agent.stream(state):
            if event["type"] == "token":
                full_response += event["content"]
            events.append(event)
        previous_agents.append(target_type)
        resolved_agent_type = target_type
        handoff_count += 1

    if not full_response:
        full_response = state.get("final_response", "")

    draft_payload = None
    if resolved_agent_type == "generator":
        draft_payload = state.get("context", {}).get("generated_problem")
        if not draft_payload:
            draft_payload = _try_extract_json(full_response)

    return events, resolved_agent_type, full_response, draft_payload


def _classify_state(state):
    """Run intent classification in a worker thread (it calls the LLM)."""
    from ai.graph.runner import _classify_intent

    return _classify_intent(state)


class AsyncChatRunner:
    """Drives one chat task to completion against an AsyncSession.

    The caller (the FastAPI handler) owns the transaction and commits. This
    runner only stages writes via ``AsyncChatRepository`` and runs the
    synchronous agent kernel off the event loop.
    """

    def __init__(self, session, redis_client=None) -> None:
        self.session = session
        self.repo = AsyncChatRepository(session)
        self.sse = RedisSSEWriter(redis_client)

    async def run(self, task_id: str) -> dict:
        """Claim and execute ``task_id``.

        Returns a result dict: ``{"claimed": bool, "status": str,
        "agent_type": str | None, "result_message_id": int | None}``. The caller
        commits the session.
        """
        from core.exceptions import AIError
        from core.security import filter_output
        from langchain_core.messages import HumanMessage
        from langchain_core.messages import AIMessage as LCAIMessage

        task = await self.repo.get_task(task_id)
        if not task:
            return {"claimed": False, "status": "not_found",
                    "agent_type": None, "result_message_id": None}

        # ── Claim via CAS (pending -> processing). Only the winner proceeds. ──
        if not await self.repo.mark_processing(task_id, expected_status="pending"):
            return {"claimed": False, "status": task.status,
                    "agent_type": task.routed_agent, "result_message_id": None}
        await self.session.commit()
        self.sse.set_status(task_id, "processing")

        conversation_id = task.conversation_id
        task_agent_type = task.agent_type
        try:
            conv = await self.repo.get_conversation(conversation_id)
            user_msg = (
                await self.repo.get_message(task.user_message_id)
                if task.user_message_id else None
            )
            message = user_msg.content if user_msg else ""

            from domain.repositories.users import AsyncUserRepository
            user = await AsyncUserRepository(self.session).get_by_id(task.user_id)
            user_role = (
                user.role.value if user and hasattr(user.role, "value")
                else (str(user.role) if user else "student")
            )

            rows = await self.repo.get_messages_ordered(conversation_id)
            history = []
            current_msg_id = user_msg.id if user_msg else None
            for r in rows:
                if r.id == current_msg_id:
                    break
                if r.role == "user":
                    history.append(HumanMessage(content=r.content))
                elif r.role == "assistant":
                    history.append(LCAIMessage(content=r.content))

            context = _chat_context_from_conversation(conv)
            resolved_agent_type = task.routed_agent or task.agent_type

            state = {
                "messages": history + [HumanMessage(content=message)],
                "agent_type": resolved_agent_type,
                "user_id": task.user_id,
                "user_role": user_role,
                "context": context,
                "tool_results": [],
                "final_response": "",
            }

            if not resolved_agent_type or resolved_agent_type == "auto":
                state = await asyncio.to_thread(_classify_state, state)
                resolved_agent_type = state.get("agent_type", "tutor")
                state["agent_type"] = resolved_agent_type

            # Persist the resolved routing before streaming (matches worker).
            task.routed_agent = resolved_agent_type
            if conv:
                conv.agent_type = resolved_agent_type
            await self.session.commit()
            self.sse.set_status(task_id, "processing", resolved_agent_type)

            # ── Run the synchronous agent kernel off the event loop. ──
            events, resolved_agent_type, full_response, draft_payload = (
                await asyncio.to_thread(
                    _run_agent_stream, state, resolved_agent_type, task_agent_type
                )
            )
            for event in events:
                self.sse.push_event(task_id, event)
            self.sse.set_status(task_id, "processing", resolved_agent_type)

            filtered = filter_output(full_response, resolved_agent_type, user_role)

            assistant_msg = self.repo.add_message(
                conversation_id, role="assistant", content=filtered
            )
            if conv and not conv.title:
                conv.title = message[:80]
            task.routed_agent = resolved_agent_type
            if conv:
                conv.agent_type = resolved_agent_type
            await self.session.flush()

            await self.repo.mark_completed(
                task_id,
                expected_status="processing",
                result_message_id=assistant_msg.id,
            )
            await self.session.commit()

            done_payload = {"type": "done", "message_id": assistant_msg.id}
            if resolved_agent_type == "generator" and draft_payload:
                draft_id = await self._save_generated_draft(
                    task, conversation_id, draft_payload
                )
                if draft_id is not None:
                    done_payload["draft_id"] = draft_id
                    done_payload["draft_status"] = (
                        "passed" if draft_payload.get("verified") else "unverified"
                    )

            self.sse.push_event(task_id, done_payload)
            self.sse.set_status(task_id, "completed", resolved_agent_type)

            return {
                "claimed": True,
                "status": "completed",
                "agent_type": resolved_agent_type,
                "result_message_id": assistant_msg.id,
            }

        except Exception as exc:  # noqa: BLE001 - mirror worker catch-all
            await self.session.rollback()
            logger.exception("ChatTask %s failed (remote)", task_id)
            error_msg = (
                exc.user_message if isinstance(exc, AIError)
                else "An unexpected error occurred."
            )
            if await self.repo.mark_failed(task_id, error_detail=str(exc)[:500]):
                await self.session.commit()
            self.sse.push_event(task_id, {"type": "error", "message": error_msg})
            self.sse.set_status(task_id, "failed")
            return {
                "claimed": True,
                "status": "failed",
                "agent_type": None,
                "result_message_id": None,
            }

    async def _save_generated_draft(self, task, conversation_id, qdata) -> Optional[int]:
        """Persist a generator draft. Best effort, never raises (matches worker).

        ``GeneratedQuestionDraft`` is still a Flask ``db.Model`` re-export living
        on the shared metadata, so it can be staged on the AsyncSession.
        """
        try:
            from app.models.generated_question_draft import GeneratedQuestionDraft

            draft = GeneratedQuestionDraft(
                teacher_id=task.user_id,
                conversation_id=conversation_id,
                question_data=qdata,
                validation_status=("passed" if qdata.get("verified") else "unverified"),
                status="pending_review",
            )
            self.session.add(draft)
            await self.session.flush()
            draft_id = draft.id
            await self.session.commit()
            return draft_id
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Auto-save draft failed (remote): %s", exc)
            await self.session.rollback()
            return None
