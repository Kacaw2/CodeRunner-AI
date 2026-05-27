"""Async chat worker: runs AI agent tasks in a background thread pool.

Architecture:
  POST /chat/async  ->  creates ChatTask (pending)  ->  submit_chat_task()
  Worker thread picks up task  ->  streams events to Redis buffer
  GET /chat/task/<id>/stream  ->  reads from Redis buffer (SSE with catch-up)

Redis keys per task (TTL = 1 hour):
  chat_task:{task_id}:status  ->  "pending" | "processing" | "completed" | "failed"
  chat_task:{task_id}:buffer  ->  List of SSE event JSON strings
  chat_task:{task_id}:agent   ->  routed agent type
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from app.core.extensions import db, redis_client
from app.core.timezone import now_china

logger = logging.getLogger(__name__)

# ── Thread pool ──────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-worker")

# ── Redis key patterns ───────────────────────────────────────

_STATUS_KEY = "chat_task:{task_id}:status"
_BUFFER_KEY = "chat_task:{task_id}:buffer"
_AGENT_KEY = "chat_task:{task_id}:agent"
_TTL = 3600  # 1 hour


# ── Public API ───────────────────────────────────────────────

def submit_chat_task(task_id: str, app):
    """Submit a chat task to the thread pool for async processing."""
    _executor.submit(_run_chat_task, task_id, app)


def get_task_events(task_id: str, start: int = 0) -> list:
    """Read buffered SSE events from Redis, starting at `start` index."""
    if not redis_client:
        return []
    try:
        key = _BUFFER_KEY.format(task_id=task_id)
        raw_list = redis_client.lrange(key, start, -1)
        return [json.loads(r) for r in raw_list]
    except Exception as e:
        logger.warning("Redis read failed for task %s: %s", task_id, e)
        return []


def get_task_event_count(task_id: str) -> int:
    """Get current number of buffered events."""
    if not redis_client:
        return 0
    try:
        key = _BUFFER_KEY.format(task_id=task_id)
        return redis_client.llen(key) or 0
    except Exception:
        return 0


def get_task_status_from_redis(task_id: str) -> dict:
    """Get task status and agent from Redis (fast path, no DB hit)."""
    if not redis_client:
        return {}
    try:
        status = redis_client.get(_STATUS_KEY.format(task_id=task_id))
        agent = redis_client.get(_AGENT_KEY.format(task_id=task_id))
        return {"status": status, "agent": agent}
    except Exception:
        return {}


# ── Redis helpers ────────────────────────────────────────────

def _set_redis(task_id: str, status: str, agent: str = None):
    if not redis_client:
        return
    try:
        redis_client.set(_STATUS_KEY.format(task_id=task_id), status, ex=_TTL)
        if agent:
            redis_client.set(_AGENT_KEY.format(task_id=task_id), agent, ex=_TTL)
    except Exception as e:
        logger.warning("Redis set failed for task %s: %s", task_id, e)


def _push_event(task_id: str, event: dict):
    if not redis_client:
        return
    try:
        key = _BUFFER_KEY.format(task_id=task_id)
        redis_client.rpush(key, json.dumps(event, ensure_ascii=False))
        redis_client.expire(key, _TTL)
    except Exception as e:
        logger.warning("Redis push failed for task %s: %s", task_id, e)


# ── Worker logic ─────────────────────────────────────────────

def _run_chat_task(task_id: str, app):
    """Execute the chat task in a background thread."""
    with app.app_context():
        from app.models.chat_task import ChatTask
        from app.models.ai_conversation import AIConversation, AIMessage
        from agent_host.security import filter_output
        from agent_host.exceptions import AIError

        task = ChatTask.query.get(task_id)
        if not task:
            logger.error("ChatTask %s not found", task_id)
            return

        # ── Mark processing ──
        task.status = "processing"
        task.started_at = now_china()
        db.session.commit()
        _set_redis(task_id, "processing")

        try:
            conv = AIConversation.query.get(task.conversation_id)
            user_msg = (AIMessage.query.get(task.user_message_id)
                        if task.user_message_id else None)
            message = user_msg.content if user_msg else ""

            from app.models.user import User
            user = User.query.get(task.user_id)
            user_role = (user.role.value
                         if hasattr(user.role, "value") else str(user.role))

            # ── Load history (exclude the current user message) ──
            from langchain_core.messages import (
                HumanMessage, AIMessage as LCAIMessage,
            )
            rows = (AIMessage.query
                    .filter_by(conversation_id=task.conversation_id)
                    .order_by(AIMessage.id).all())
            history = []
            current_msg_id = user_msg.id if user_msg else None
            for r in rows:
                if r.id == current_msg_id:
                    break
                if r.role == "user":
                    history.append(HumanMessage(content=r.content))
                elif r.role == "assistant":
                    history.append(LCAIMessage(content=r.content))

            context = {"conversation_id": task.conversation_id}

            # ── Agent map ──
            from agent_host.agents import (
                TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent,
            )
            from agent_host.orchestrator import _classify_intent, MAX_HANDOFFS

            _AGENT_MAP = {
                "tutor": TutorAgent,
                "reviewer": ReviewerAgent,
                "generator": GeneratorAgent,
                "analytics": AnalyticsAgent,
            }

            state = {
                "messages": history + [HumanMessage(content=message)],
                "agent_type": task.agent_type,
                "user_id": task.user_id,
                "user_role": user_role,
                "context": context,
                "tool_results": [],
                "final_response": "",
            }

            # ── Intent classification / auto-routing ──
            resolved_agent_type = task.agent_type
            if not task.agent_type or task.agent_type == "auto":
                state = _classify_intent(state)
                resolved_agent_type = state.get("agent_type", "tutor")

            task.routed_agent = resolved_agent_type
            if conv:
                conv.agent_type = resolved_agent_type
            db.session.commit()
            _set_redis(task_id, "processing", resolved_agent_type)

            _push_event(task_id, {
                "type": "start",
                "conversation_id": task.conversation_id,
                "agent_type": resolved_agent_type,
            })

            if resolved_agent_type != task.agent_type:
                _push_event(task_id, {
                    "type": "route",
                    "agent_type": resolved_agent_type,
                })

            # ── Stream from agent ──
            agent_cls = _AGENT_MAP.get(resolved_agent_type, TutorAgent)
            agent = agent_cls()
            full_response = ""

            for event in agent.stream(state):
                if event["type"] == "token":
                    full_response += event["content"]
                _push_event(task_id, event)

            # ── Handle handoffs ──
            handoff_count = 0
            previous_agents = [resolved_agent_type]

            while (state.get("handoff_to")
                   and handoff_count < MAX_HANDOFFS
                   and state["handoff_to"] in _AGENT_MAP
                   and state["handoff_to"] not in previous_agents):

                target_type = state["handoff_to"]
                handoff_reason = state.get("handoff_reason", "")
                state["handoff_to"] = None
                state["handoff_reason"] = None
                state["agent_type"] = target_type

                _push_event(task_id, {
                    "type": "handoff_start",
                    "target": target_type,
                    "reason": handoff_reason,
                })

                target_agent = _AGENT_MAP.get(target_type, TutorAgent)()
                full_response = ""
                for event in target_agent.stream(state):
                    if event["type"] == "token":
                        full_response += event["content"]
                    _push_event(task_id, event)

                previous_agents.append(target_type)
                resolved_agent_type = target_type
                handoff_count += 1

                task.routed_agent = resolved_agent_type
                if conv:
                    conv.agent_type = resolved_agent_type
                db.session.commit()
                _set_redis(task_id, "processing", resolved_agent_type)

            if not full_response:
                full_response = state.get("final_response", "")

            filtered = filter_output(full_response, resolved_agent_type, user_role)

            # ── Save assistant message ──
            assistant_msg = AIMessage(
                conversation_id=task.conversation_id,
                role="assistant",
                content=filtered,
            )
            db.session.add(assistant_msg)
            if conv and not conv.title:
                conv.title = message[:80]
            db.session.flush()

            task.result_message_id = assistant_msg.id
            task.status = "completed"
            task.completed_at = now_china()
            db.session.commit()

            # ── Done event ──
            done_payload = {"type": "done", "message_id": assistant_msg.id}

            if resolved_agent_type == "generator":
                qdata = state.get("context", {}).get("generated_problem")
                if not qdata:
                    qdata = _try_extract_json(full_response)
                if qdata:
                    try:
                        from app.models.generated_question_draft import (
                            GeneratedQuestionDraft,
                        )
                        draft = GeneratedQuestionDraft(
                            teacher_id=task.user_id,
                            conversation_id=task.conversation_id,
                            question_data=qdata,
                            validation_status=(
                                "passed" if qdata.get("verified") else "unverified"
                            ),
                            status="pending_review",
                        )
                        db.session.add(draft)
                        db.session.commit()
                        done_payload["draft_id"] = draft.id
                        done_payload["draft_status"] = draft.validation_status
                    except Exception as e:
                        logger.warning("Auto-save draft failed: %s", e)

            _push_event(task_id, done_payload)
            _set_redis(task_id, "completed", resolved_agent_type)

            # ── Async summary ──
            _maybe_generate_summary(task.conversation_id, conv)

        except Exception as e:
            db.session.rollback()
            logger.exception("ChatTask %s failed", task_id)

            error_msg = (e.user_message if isinstance(e, AIError)
                         else "An unexpected error occurred.")

            task = ChatTask.query.get(task_id)
            if task:
                task.status = "failed"
                task.error_detail = str(e)[:500]
                task.completed_at = now_china()
                db.session.commit()

            _push_event(task_id, {"type": "error", "message": error_msg})
            _set_redis(task_id, "failed")


# ── Internal helpers ─────────────────────────────────────────

def _try_extract_json(text: str):
    """Try to extract a JSON object from LLM output (supports ```json fences)."""
    fence = re.search(r"```json\s*\n?(.*?)```", text, re.DOTALL)
    raw = fence.group(1) if fence else text
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if not brace:
        return None
    try:
        return json.loads(brace.group())
    except json.JSONDecodeError:
        return None


def _maybe_generate_summary(conv_id: int, conv):
    """Generate conversation summary when message count is high enough."""
    try:
        from app.models.ai_conversation import AIMessage
        msg_count = AIMessage.query.filter_by(conversation_id=conv_id).count()
        if msg_count >= 10 and conv and not conv.summary:
            from agent_host.memory import MemoryService
            summary = MemoryService.generate_conversation_summary(conv_id)
            if summary:
                conv.summary = summary
                db.session.commit()
    except Exception as e:
        logger.warning("Summary generation failed: %s", e)
