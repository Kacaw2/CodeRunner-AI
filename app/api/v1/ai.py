import json
import logging
import threading
import time
from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from app.auth.decorators import require_auth, require_teacher, get_current_user_or_401
from app.core.extensions import db, redis_client
from app.models.ai_conversation import AIConversation, AIMessage
from agents.config import AGENT_RATE_LIMITS
from core.exceptions import AIError, RateLimitError, ConfigError
from core.security import detect_injection, sanitize_user_input, filter_output

logger = logging.getLogger(__name__)

bp = Blueprint("ai", __name__, url_prefix="/api/v1/ai")


def _normalize_chat_agent_type(_data=None) -> str:
    """User-facing chat always starts with server-side intent routing."""
    return "auto"


# ── Rate Limiting ─────────────────────────────────────────────

def _check_rate_limit(user_id: int, agent_type: str = "tutor") -> dict:
    """Check per-user, per-agent rate limit. Returns {allowed, limit, remaining, retry_after}."""
    limit = AGENT_RATE_LIMITS.get(agent_type, 20)
    window = 60

    if not redis_client:
        logger.warning("Redis unavailable — rate limiting disabled")
        return {"allowed": True, "limit": limit, "remaining": limit, "retry_after": 0}

    key = f"ai_rate:{user_id}:{agent_type}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, window)
        ttl = redis_client.ttl(key)
        remaining = max(0, limit - count)
        return {
            "allowed": count <= limit,
            "limit": limit,
            "remaining": remaining,
            "retry_after": ttl if count > limit else 0,
        }
    except Exception as e:
        logger.warning("Redis rate limit check failed: %s", e)
        return {"allowed": True, "limit": limit, "remaining": limit, "retry_after": 0}


def _rate_limit_headers(info: dict) -> dict:
    """Build standard rate limit response headers."""
    headers = {
        "X-RateLimit-Limit": str(info["limit"]),
        "X-RateLimit-Remaining": str(info["remaining"]),
    }
    if info.get("retry_after"):
        headers["Retry-After"] = str(info["retry_after"])
    return headers


def _rate_limit_or_abort(user_id: int, agent_type: str) -> dict:
    """Check rate limit; raise RateLimitError if exceeded. Returns limit info."""
    info = _check_rate_limit(user_id, agent_type)
    if not info["allowed"]:
        raise RateLimitError(retry_after=info["retry_after"])
    return info


def _classify_for_routing(message: str, agent_type: str, user_role: str) -> str:
    """Resolve the concrete agent that will handle an 'auto' chat request.

    Mirrors the orchestrator's routing so the API layer can enforce the real
    per-agent rate limit before any agent runs.
    """
    if agent_type and agent_type != "auto":
        return agent_type
    from langchain_core.messages import HumanMessage
    from graph.runner import _classify_intent

    state = _classify_intent({
        "messages": [HumanMessage(content=message)],
        "agent_type": agent_type,
        "user_role": user_role,
    })
    return state.get("agent_type", "tutor")


def _resolve_and_rate_limit(user_id: int, message: str, agent_type: str,
                            user_role: str) -> tuple[str, dict]:
    """Resolve the concrete agent and enforce its per-agent rate limit.

    For the 'auto' lane we first apply a cheap global throttle (so the
    classifier itself can't be spammed), then classify, then enforce the
    resolved agent's real limit. Returns (resolved_agent_type, header_info).
    Raises RateLimitError if either limit is exceeded.
    """
    if agent_type and agent_type != "auto":
        return agent_type, _rate_limit_or_abort(user_id, agent_type)

    _rate_limit_or_abort(user_id, "auto")
    resolved = _classify_for_routing(message, "auto", user_role)
    return resolved, _rate_limit_or_abort(user_id, resolved)


def _error_response(error_code: str, message: str, status: int, headers: dict | None = None):
    resp = jsonify({"error": error_code, "message": message})
    resp.status_code = status
    if headers:
        for k, v in headers.items():
            resp.headers[k] = v
    return resp


# ── Audit Logging ────────────────────────────────────────────

def _log_audit(user_id: int, agent_type: str, action: str, message: str,
               injection: bool = False, pattern: str = ""):
    try:
        from app.models.ai_audit_log import AIAuditLog
        log = AIAuditLog(
            user_id=user_id,
            agent_type=agent_type,
            action=action,
            input_preview=message[:200],
            injection_detected=injection,
            injection_pattern=pattern[:100] if pattern else None,
            ip_address=request.remote_addr,
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logger.warning("Failed to write audit log: %s", e)


# ── Incremental Knowledge Base Indexing ──────────────────────

def _maybe_index_problem(problem):
    """Index a newly published problem into the knowledge base (best-effort)."""
    if not problem:
        return
    try:
        from knowledge.store import get_knowledge_base
        kb = get_knowledge_base()
        kb.index_problem(problem)
    except Exception as e:
        logger.warning("Incremental KB indexing skipped for problem %s: %s",
                       getattr(problem, "id", "?"), e)


# ── Async Summary ────────────────────────────────────────────

def _maybe_generate_summary(conv_id: int):
    """Trigger async conversation summary when message count >= 10 and no summary exists."""
    try:
        msg_count = AIMessage.query.filter_by(conversation_id=conv_id).count()
        conv = AIConversation.query.get(conv_id)
        if msg_count >= 10 and conv and not conv.summary:
            app = current_app._get_current_object()

            def _generate(app_obj, cid):
                with app_obj.app_context():
                    try:
                        from memory.service import MemoryService
                        summary = MemoryService.generate_conversation_summary(cid)
                        if summary:
                            c = AIConversation.query.get(cid)
                            if c:
                                c.summary = summary
                                db.session.commit()
                    except Exception as e:
                        logger.warning("Async summary generation failed: %s", e)

            threading.Thread(target=_generate, args=(app, conv_id), daemon=True).start()
    except Exception as e:
        logger.warning("Summary check failed: %s", e)


# ── Helpers ───────────────────────────────────────────────────

def _build_context(data: dict) -> dict:
    ctx = {}
    for key in ("question_id", "submission_id", "code", "error_status",
                "language", "topic", "difficulty", "test_case_count", "quiz_id", "prompt",
                "target_student_id", "period"):
        if data.get(key) is not None:
            ctx[key] = data[key]
    return ctx


def _get_or_create_conversation(user_id, agent_type, conversation_id, context):
    if conversation_id:
        conv = AIConversation.query.filter_by(id=conversation_id, user_id=user_id).first()
        if conv:
            return conv
    conv = AIConversation(
        user_id=user_id,
        agent_type=agent_type,
        context_type="question" if context.get("question_id") else None,
        context_id=context.get("question_id"),
    )
    db.session.add(conv)
    db.session.flush()
    return conv


def _load_history(conversation_id: int) -> list:
    from langchain_core.messages import HumanMessage, AIMessage as LCAIMessage
    rows = AIMessage.query.filter_by(conversation_id=conversation_id).order_by(AIMessage.id).all()
    msgs = []
    for r in rows:
        if r.role == "user":
            msgs.append(HumanMessage(content=r.content))
        elif r.role == "assistant":
            msgs.append(LCAIMessage(content=r.content))
    return msgs


def _try_parse_review_json(text: str) -> dict | None:
    """Try to extract a structured review JSON from the LLM response."""
    import re
    fence = re.search(r"```json\s*\n?(.*?)```", text, re.DOTALL)
    raw = fence.group(1) if fence else text
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if not brace:
        return None
    try:
        return json.loads(brace.group())
    except json.JSONDecodeError:
        return None


def _slugify_problem_title(title: str) -> str:
    import re
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or "ai-generated-problem"


def _publish_question_data_as_problem(question_data: dict, created_by: int):
    """Create one Problem with one or more executable language variants."""
    from app.models.problem import Problem
    from app.models.question import Question, TestCase

    qd = question_data.get("question", question_data)
    title = qd.get("title", "AI Generated Question")
    base_slug = _slugify_problem_title(title)
    slug = base_slug
    suffix = 2
    while Problem.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    problem = Problem(
        slug=slug,
        title=title,
        description=qd.get("description", ""),
        difficulty=qd.get("difficulty", "medium"),
        points=qd.get("points", 10),
        order=qd.get("order", 1),
        created_by=created_by,
    )
    db.session.add(problem)
    db.session.flush()

    variants = qd.get("variants")
    if not variants:
        language = qd.get("programming_language") or qd.get("language") or "python"
        variants = [{
            "language": language,
            "starter_code": qd.get("starter_code", ""),
            "solution": qd.get("solution", ""),
            "solution_explanation": qd.get("solution_explanation", ""),
        }]

    first_variant = None
    for variant_data in variants:
        language = variant_data.get("language") or variant_data.get("programming_language") or "python"
        variant = Question(
            problem_id=problem.id,
            programming_language=language,
            starter_code=variant_data.get("starter_code", ""),
            solution=variant_data.get("solution", ""),
            solution_explanation=variant_data.get("solution_explanation", ""),
        )
        db.session.add(variant)
        db.session.flush()
        first_variant = first_variant or variant

    for tc_data in qd.get("test_cases", []):
        db.session.add(TestCase(
            problem_id=problem.id,
            input=tc_data.get("input", ""),
            expected_output=tc_data.get("expected_output", tc_data.get("expected", "")),
            is_hidden=tc_data.get("is_hidden", False),
            weight=tc_data.get("weight", 1.0),
        ))

    _maybe_index_problem(problem)

    return problem, first_variant


# ── POST /api/v1/ai/chat  (sync) ─────────────────────────────

@bp.route("/chat", methods=["POST"])
@require_auth
def chat():
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    message = (data.get("message") or "").strip()
    if not message:
        return _error_response("invalid_request", "message is required", 400)

    agent_type = _normalize_chat_agent_type(data)

    is_suspicious, pattern = detect_injection(message)
    if is_suspicious:
        logger.warning("Potential injection from user %d: pattern=%s", user.id, pattern)
        _log_audit(user.id, agent_type, "chat", message, True, pattern)

    message = sanitize_user_input(message)

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    try:
        resolved_agent_type, rl_info = _resolve_and_rate_limit(
            user.id, message, agent_type, user_role)
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    rl_headers = _rate_limit_headers(rl_info)

    try:
        conv = _get_or_create_conversation(user.id, agent_type, data.get("conversation_id"), context)
        context["conversation_id"] = conv.id
        history = _load_history(conv.id) if data.get("conversation_id") else []

        user_msg = AIMessage(conversation_id=conv.id, role="user", content=message)
        db.session.add(user_msg)
        db.session.flush()

        from langchain_core.messages import HumanMessage
        from graph.runner import AgentOrchestrator

        orch = AgentOrchestrator()
        state = orch.run({
            "messages": history + [HumanMessage(content=message)],
            "agent_type": resolved_agent_type,
            "user_id": user.id,
            "user_role": user_role,
            "context": context,
            "tool_results": [],
            "final_response": "",
        })

        resolved_agent_type = state.get("agent_type", resolved_agent_type)
        response_text = filter_output(state.get("final_response", ""), resolved_agent_type, user_role)

        assistant_msg = AIMessage(conversation_id=conv.id, role="assistant", content=response_text)
        db.session.add(assistant_msg)
        conv.title = conv.title or message[:80]
        conv.agent_type = resolved_agent_type
        db.session.commit()

        _maybe_generate_summary(conv.id)

        resp = jsonify({
            "conversation_id": conv.id,
            "message_id": assistant_msg.id,
            "agent_type": resolved_agent_type,
            "response": response_text,
        })
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp

    except ConfigError as e:
        db.session.rollback()
        logger.error("AI config error: %s", e)
        return _error_response("ai_config_error", e.user_message, 503)
    except AIError as e:
        db.session.rollback()
        logger.error("AI error: %s", e)
        return _error_response("ai_service_error", e.user_message, 500)
    except Exception as e:
        db.session.rollback()
        logger.exception("AI chat error")
        return _error_response("ai_service_error", "An unexpected error occurred. Please try again.", 500)


# ── POST /api/v1/ai/chat/stream  (SSE) ───────────────────────

@bp.route("/chat/stream", methods=["POST"])
@require_auth
def chat_stream():
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    message = (data.get("message") or "").strip()
    if not message:
        return _error_response("invalid_request", "message is required", 400)

    agent_type = _normalize_chat_agent_type(data)

    is_suspicious, pattern = detect_injection(message)
    if is_suspicious:
        logger.warning("Potential injection from user %d (stream): pattern=%s", user.id, pattern)
        _log_audit(user.id, agent_type, "chat_stream", message, True, pattern)

    message = sanitize_user_input(message)

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    try:
        routed_agent, rl_info = _resolve_and_rate_limit(
            user.id, message, agent_type, user_role)
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)

    try:
        conv = _get_or_create_conversation(user.id, agent_type, data.get("conversation_id"), context)
        history = _load_history(conv.id) if data.get("conversation_id") else []

        user_msg = AIMessage(conversation_id=conv.id, role="user", content=message)
        db.session.add(user_msg)
        db.session.flush()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to setup stream conversation")
        return _error_response("ai_service_error", "Failed to initialize conversation.", 500)

    conv_id = conv.id
    user_id = user.id
    context["conversation_id"] = conv_id

    def generate():
        from langchain_core.messages import HumanMessage
        from agents import TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent
        from graph.runner import MAX_HANDOFFS

        _AGENT_MAP = {
            "tutor": TutorAgent,
            "reviewer": ReviewerAgent,
            "generator": GeneratorAgent,
            "analytics": AnalyticsAgent,
        }

        # Phase 3: the concrete agent was already resolved (and rate-limited)
        # before the response started streaming.
        resolved_agent_type = routed_agent

        state = {
            "messages": history + [HumanMessage(content=message)],
            "agent_type": resolved_agent_type,
            "user_id": user_id,
            "user_role": user_role,
            "context": context,
            "tool_results": [],
            "final_response": "",
        }

        yield f"data: {json.dumps({'type': 'start', 'conversation_id': conv_id, 'agent_type': resolved_agent_type})}\n\n"

        if resolved_agent_type != agent_type:
            yield f"data: {json.dumps({'type': 'route', 'agent_type': resolved_agent_type})}\n\n"

        agent_cls = _AGENT_MAP.get(resolved_agent_type, TutorAgent)
        agent = agent_cls()
        full_response = ""
        last_event_time = time.monotonic()
        handoff_count = 0
        previous_agents = []
        try:
            for event in agent.stream(state):
                if event["type"] == "token":
                    full_response += event["content"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                now = time.monotonic()
                if now - last_event_time > 10:
                    yield ": heartbeat\n\n"
                last_event_time = now

            # ── Handle handoff: invoke the target agent if requested ──
            previous_agents.append(resolved_agent_type)
            while (state.get("handoff_to")
                   and handoff_count < MAX_HANDOFFS
                   and state["handoff_to"] in _AGENT_MAP
                   and state["handoff_to"] not in previous_agents):

                target_type = state["handoff_to"]
                handoff_reason = state.get("handoff_reason", "")
                state["handoff_to"] = None
                state["handoff_reason"] = None
                state["agent_type"] = target_type

                # Notify frontend of the handoff
                yield f"data: {json.dumps({'type': 'handoff_start', 'target': target_type, 'reason': handoff_reason})}\n\n"

                target_agent_cls = _AGENT_MAP.get(target_type, TutorAgent)
                target_agent = target_agent_cls()

                # Continue with accumulated messages from the previous agent
                full_response = ""
                for event in target_agent.stream(state):
                    if event["type"] == "token":
                        full_response += event["content"]
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    now = time.monotonic()
                    if now - last_event_time > 10:
                        yield ": heartbeat\n\n"
                    last_event_time = now

                previous_agents.append(target_type)
                resolved_agent_type = target_type
                handoff_count += 1

            if not full_response:
                full_response = state.get("final_response", "")

            filtered_response = filter_output(full_response, resolved_agent_type, user_role)
            assistant_msg = AIMessage(conversation_id=conv_id, role="assistant", content=filtered_response)
            db.session.add(assistant_msg)
            _conv = AIConversation.query.get(conv_id)
            if _conv and not _conv.title:
                _conv.title = message[:80]
            if _conv:
                _conv.agent_type = resolved_agent_type
            db.session.commit()

            _maybe_generate_summary(conv_id)

            done_payload = {'type': 'done', 'message_id': assistant_msg.id}

            # Auto-save draft when generator produces a valid question
            if resolved_agent_type == "generator":
                question_data = state.get("context", {}).get("generated_problem")
                if not question_data:
                    question_data = _try_parse_review_json(full_response)
                if question_data:
                    try:
                        from app.models.generated_question_draft import GeneratedQuestionDraft
                        draft = GeneratedQuestionDraft(
                            teacher_id=user_id,
                            conversation_id=conv_id,
                            question_data=question_data,
                            validation_status="passed" if question_data.get("verified") else "unverified",
                            status="pending_review",
                        )
                        db.session.add(draft)
                        db.session.commit()
                        done_payload["draft_id"] = draft.id
                        done_payload["draft_status"] = draft.validation_status
                    except Exception as e:
                        logger.warning("Auto-save draft failed: %s", e)

            yield f"data: {json.dumps(done_payload)}\n\n"
        except Exception as e:
            db.session.rollback()
            logger.exception("AI stream error")
            error_msg = e.user_message if isinstance(e, AIError) else "An unexpected error occurred."
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"

        yield "data: [DONE]\n\n"

    rl_headers = _rate_limit_headers(rl_info)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            **rl_headers,
        },
    )


# ── POST /api/v1/ai/chat/async  (async task) ──────────────────

@bp.route("/chat/async", methods=["POST"])
@require_auth
def chat_async():
    """Create an async chat task. Returns task_id immediately.

    The frontend should subscribe to /chat/task/<task_id>/stream for SSE events.
    """
    from app.api.v1.ai_proxy import is_proxy_enabled, proxy_chat_create

    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    message = (data.get("message") or "").strip()
    if not message:
        return _error_response("invalid_request", "message is required", 400)

    agent_type = _normalize_chat_agent_type(data)

    is_suspicious, pattern = detect_injection(message)
    if is_suspicious:
        logger.warning("Potential injection from user %d (async): pattern=%s", user.id, pattern)
        _log_audit(user.id, agent_type, "chat_async", message, True, pattern)

    message = sanitize_user_input(message)

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    try:
        resolved_agent_type, rl_info = _resolve_and_rate_limit(
            user.id, message, agent_type, user_role)
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    rl_headers = _rate_limit_headers(rl_info)

    if is_proxy_enabled():
        proxied_payload = dict(data)
        proxied_payload["message"] = message
        # Pass the already-resolved agent so the remote host skips re-routing
        # (and can't bypass the per-agent limit we just enforced).
        proxied_payload["agent_type"] = resolved_agent_type
        return proxy_chat_create(proxied_payload, extra_headers=rl_headers)

    try:
        conv = _get_or_create_conversation(
            user.id, agent_type, data.get("conversation_id"), context)

        user_msg = AIMessage(conversation_id=conv.id, role="user", content=message)
        db.session.add(user_msg)
        db.session.flush()

        from app.models.chat_task import ChatTask
        task = ChatTask(
            conversation_id=conv.id,
            user_id=user.id,
            user_message_id=user_msg.id,
            agent_type=agent_type,
            routed_agent=resolved_agent_type,
            status="pending",
        )
        db.session.add(task)
        db.session.flush()
        db.session.commit()

        # Submit to background worker
        from workers.chat import submit_chat_task
        submit_chat_task(task.id, current_app._get_current_object())

        resp = jsonify({
            "task_id": task.id,
            "conversation_id": conv.id,
        })
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp, 202

    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to create async chat task")
        return _error_response("ai_service_error",
                               "Failed to create chat task.", 500)


# ── GET /api/v1/ai/chat/task/<task_id>/stream  (SSE) ─────────

@bp.route("/chat/task/<task_id>/stream", methods=["GET"])
@require_auth
def chat_task_stream(task_id):
    """SSE stream for an async chat task. Supports catch-up via ?last_event=N."""
    from app.api.v1.ai_proxy import is_proxy_enabled, proxy_chat_stream
    if is_proxy_enabled():
        return proxy_chat_stream(task_id)

    user = get_current_user_or_401()

    from app.models.chat_task import ChatTask
    task = ChatTask.query.filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return _error_response("not_found", "Task not found", 404)

    last_event = request.args.get("last_event", 0, type=int)

    def generate():
        from workers.chat import (
            get_task_events, get_task_event_count, get_task_status_from_redis,
        )

        cursor = last_event
        done = False
        idle_count = 0
        max_idle = 300  # 5 minutes max wait

        while not done and idle_count < max_idle:
            events = get_task_events(task_id, start=cursor)

            if events:
                idle_count = 0
                for evt in events:
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    cursor += 1

                    if evt.get("type") in ("done", "error"):
                        done = True
                        break
            else:
                # Check if task is already finished (DB fallback)
                redis_info = get_task_status_from_redis(task_id)
                redis_status = redis_info.get("status")

                if redis_status in ("completed", "failed"):
                    # Drain any remaining events
                    remaining = get_task_events(task_id, start=cursor)
                    for evt in remaining:
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                        cursor += 1
                    done = True
                    break

                # Heartbeat and wait
                yield ": heartbeat\n\n"
                idle_count += 1
                time.sleep(0.3)

        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── GET /api/v1/ai/chat/task/<task_id>  (poll) ──────────────

@bp.route("/chat/task/<task_id>", methods=["GET"])
@require_auth
def chat_task_status(task_id):
    """Poll the status of an async chat task."""
    from app.api.v1.ai_proxy import is_proxy_enabled, proxy_chat_status
    if is_proxy_enabled():
        return proxy_chat_status(task_id)

    user = get_current_user_or_401()

    from app.models.chat_task import ChatTask
    task = ChatTask.query.filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return _error_response("not_found", "Task not found", 404)

    result = task.to_dict()

    # Include the final response content if completed
    if task.status == "completed" and task.result_message_id:
        result_msg = AIMessage.query.get(task.result_message_id)
        if result_msg:
            result["response"] = result_msg.content

    return jsonify({"task": result})


# ── GET /api/v1/ai/conversations ─────────────────────────────

@bp.route("/conversations", methods=["GET"])
@require_auth
def list_conversations():
    user = get_current_user_or_401()
    agent_type = request.args.get("agent_type")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = AIConversation.query.filter_by(user_id=user.id)
    if agent_type:
        query = query.filter_by(agent_type=agent_type)
    total = query.count()
    convs = query.order_by(AIConversation.updated_at.desc()).offset(offset).limit(limit).all()

    items = []
    for c in convs:
        msg_count = AIMessage.query.filter_by(conversation_id=c.id).count()
        items.append({
            "id": c.id,
            "agent_type": c.agent_type,
            "title": c.title,
            "context_type": c.context_type,
            "context_id": c.context_id,
            "message_count": msg_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return jsonify({"items": items, "total": total})


# ── GET /api/v1/ai/conversations/<id> ────────────────────────

@bp.route("/conversations/<int:conv_id>", methods=["GET"])
@require_auth
def get_conversation(conv_id):
    user = get_current_user_or_401()
    conv = AIConversation.query.filter_by(id=conv_id, user_id=user.id).first()
    if not conv:
        return _error_response("not_found", "Conversation not found", 404)

    msgs = AIMessage.query.filter_by(conversation_id=conv.id).order_by(AIMessage.id).all()
    return jsonify({
        "id": conv.id,
        "agent_type": conv.agent_type,
        "title": conv.title,
        "messages": [{
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tokens_used": m.tokens_used,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs],
    })


# ── DELETE /api/v1/ai/conversations/<id> ──────────────────────

@bp.route("/conversations/<int:conv_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conv_id):
    user = get_current_user_or_401()
    conv = AIConversation.query.filter_by(id=conv_id, user_id=user.id).first()
    if not conv:
        return _error_response("not_found", "Conversation not found", 404)
    db.session.delete(conv)
    db.session.commit()
    return "", 204


# ── POST /api/v1/ai/review ───────────────────────────────────

@bp.route("/review", methods=["POST"])
@require_auth
def review_code():
    """Structured code review. Returns JSON review report."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    code = (data.get("code") or "").strip()
    if not code:
        return _error_response("invalid_request", "code is required", 400)

    try:
        rl_info = _rate_limit_or_abort(user.id, "reviewer")
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    context["code"] = code
    rl_headers = _rate_limit_headers(rl_info)

    try:
        conv = _get_or_create_conversation(user.id, "reviewer", None, context)

        user_msg = AIMessage(conversation_id=conv.id, role="user",
                             content=f"Please review this code:\n```\n{code}\n```")
        db.session.add(user_msg)
        db.session.flush()

        from langchain_core.messages import HumanMessage
        from agents import ReviewerAgent

        agent = ReviewerAgent()
        state = {
            "messages": [HumanMessage(content="Please review the code provided in the context.")],
            "agent_type": "reviewer",
            "user_id": user.id,
            "user_role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "context": context,
            "tool_results": [],
            "final_response": "",
        }
        state = agent.invoke(state)
        response_text = state.get("final_response", "")

        assistant_msg = AIMessage(conversation_id=conv.id, role="assistant", content=response_text)
        db.session.add(assistant_msg)
        conv.title = conv.title or "Code Review"
        db.session.commit()

        review = _try_parse_review_json(response_text)

        resp = jsonify({
            "conversation_id": conv.id,
            "review": review if review else response_text,
        })
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp

    except ConfigError as e:
        db.session.rollback()
        return _error_response("ai_config_error", e.user_message, 503)
    except AIError as e:
        db.session.rollback()
        logger.error("AI review error: %s", e)
        return _error_response("ai_service_error", e.user_message, 500)
    except Exception as e:
        db.session.rollback()
        logger.exception("AI review error")
        return _error_response("ai_service_error", "An unexpected error occurred. Please try again.", 500)


# ── POST /api/v1/ai/generate ─────────────────────────────────

@bp.route("/generate", methods=["POST"])
@require_teacher
def generate_question():
    """AI question generation with self-validation. Teacher/Admin only."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return _error_response("invalid_request", "prompt is required", 400)

    try:
        rl_info = _rate_limit_or_abort(user.id, "generator")
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    context.setdefault("language", "python")
    context.setdefault("difficulty", "medium")
    context.setdefault("test_case_count", 5)
    rl_headers = _rate_limit_headers(rl_info)

    try:
        conv = _get_or_create_conversation(user.id, "generator", None, context)

        user_msg = AIMessage(conversation_id=conv.id, role="user", content=prompt)
        db.session.add(user_msg)
        db.session.flush()

        from langchain_core.messages import HumanMessage
        from agents import GeneratorAgent

        agent = GeneratorAgent()
        state = {
            "messages": [HumanMessage(content=prompt)],
            "agent_type": "generator",
            "user_id": user.id,
            "user_role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "context": context,
            "tool_results": [],
            "final_response": "",
        }
        state = agent.invoke(state)
        response_text = state.get("final_response", "")

        assistant_msg = AIMessage(conversation_id=conv.id, role="assistant", content=response_text)
        db.session.add(assistant_msg)
        conv.title = conv.title or f"AI Generate: {prompt[:60]}"
        db.session.commit()

        question_data = state.get("context", {}).get("generated_problem")
        draft_info = None
        if question_data:
            from app.models.generated_question_draft import GeneratedQuestionDraft
            draft = GeneratedQuestionDraft(
                teacher_id=user.id,
                conversation_id=conv.id,
                question_data=question_data,
                validation_status="passed" if question_data.get("verified") else "unverified",
                status="pending_review",
            )
            db.session.add(draft)
            db.session.commit()
            draft_info = draft.to_dict()

        if question_data:
            resp = jsonify({
                "conversation_id": conv.id,
                "question": question_data,
                "draft": draft_info,
            })
        else:
            resp = jsonify({"conversation_id": conv.id, "question": None, "raw_response": response_text})
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp

    except ConfigError as e:
        db.session.rollback()
        return _error_response("ai_config_error", e.user_message, 503)
    except AIError as e:
        db.session.rollback()
        logger.error("AI generate error: %s", e)
        return _error_response("ai_service_error", e.user_message, 500)
    except Exception as e:
        db.session.rollback()
        logger.exception("AI generate error")
        return _error_response("ai_service_error", "An unexpected error occurred. Please try again.", 500)


# ── POST /api/v1/ai/generate/save ────────────────────────────

@bp.route("/generate/save", methods=["POST"])
@require_teacher
def save_generated_question():
    """Save an AI-generated question to the database. Teacher/Admin only."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    conv_id = data.get("conversation_id")
    if not conv_id:
        return _error_response("invalid_request", "conversation_id is required", 400)

    conv = AIConversation.query.filter_by(id=conv_id, user_id=user.id, agent_type="generator").first()
    if not conv:
        return _error_response("not_found", "Generator conversation not found", 404)

    last_assistant = (AIMessage.query
                      .filter_by(conversation_id=conv.id, role="assistant")
                      .order_by(AIMessage.id.desc())
                      .first())
    if not last_assistant:
        return _error_response("not_found", "No generated question found", 404)

    question_json = _try_parse_review_json(last_assistant.content)
    if not question_json:
        return _error_response("invalid_request", "Could not parse question data from conversation", 400)

    if "question" in question_json:
        question_json = question_json["question"]

    try:
        problem, variant = _publish_question_data_as_problem(question_json, user.id)

        quiz_id = data.get("quiz_id")
        if quiz_id:
            from app.models.quiz import Quiz, QuizProblem
            quiz = Quiz.query.get(quiz_id)
            if quiz:
                max_order = (db.session.query(db.func.max(QuizProblem.order))
                             .filter_by(quiz_id=quiz_id).scalar() or 0)
                db.session.add(QuizProblem(quiz_id=quiz_id, problem_id=problem.id, order=max_order + 1))

        db.session.commit()

        return jsonify({
            "problem_id": problem.id,
            "question_id": variant.id if variant else None,
            "test_case_count": len(problem.test_cases),
            "message": "Problem saved successfully",
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.exception("Save generated question error")
        return _error_response("ai_service_error", "Failed to save question. Please try again.", 500)


# ── POST /api/v1/ai/generate/batch ──────────────────────────

@bp.route("/generate/batch", methods=["POST"])
@require_teacher
def generate_batch():
    """Batch question generation. Creates an AgentTask and runs sub-tasks."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    topic = (data.get("topic") or "").strip()
    if not topic:
        return _error_response("invalid_request", "topic is required", 400)

    count = min(int(data.get("count", 1)), 10)
    if count < 1:
        return _error_response("invalid_request", "count must be 1-10", 400)

    try:
        rl_info = _rate_limit_or_abort(user.id, "generator")
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    from app.models.agent_task import AgentTask
    from workers.batch import decompose_batch_params, BatchTaskRunner

    params = {
        "topic": topic,
        "language": data.get("language", "python"),
        "difficulty": data.get("difficulty", "medium"),
        "count": count,
        "test_case_count": int(data.get("test_case_count", 5)),
    }
    steps = decompose_batch_params(params)

    task = AgentTask(
        user_id=user.id,
        task_type="generate_batch",
        agent_type="generator",
        status="pending",
        input_params=params,
        plan_steps=steps,
        current_step=0,
        result=[],
    )
    db.session.add(task)
    db.session.commit()

    try:
        runner = BatchTaskRunner(task)
        runner.run()
    except Exception as e:
        logger.exception("Batch generation failed for task %s", task.id)
        task.status = "failed"
        task.error_detail = str(e)[:500]
        db.session.commit()

    db.session.refresh(task)
    rl_headers = _rate_limit_headers(rl_info)
    resp = jsonify({"task_id": task.id, "task": task.to_dict()})
    for k, v in rl_headers.items():
        resp.headers[k] = v
    return resp, 201


# ── POST /api/v1/ai/generate/pipeline ─────────────────────
# Phase 4: Multi-agent generation pipeline

@bp.route("/generate/pipeline", methods=["POST"])
@require_teacher
def generate_pipeline():
    """Run the multi-agent generation pipeline (generate → validate → dedup → quality review)."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    prompt = (data.get("prompt") or data.get("message") or "").strip()
    if not prompt:
        return _error_response("invalid_request", "prompt is required", 400)

    try:
        rl_info = _rate_limit_or_abort(user.id, "generator")
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    from memory.service import MemoryService
    teacher_ctx = MemoryService.get_memory_context(user.id, user_role)

    from workers.generation_pipeline import run_generation_workflow
    try:
        result = run_generation_workflow(
            teacher_id=user.id,
            prompt=prompt,
            language=data.get("language", "python"),
            difficulty=data.get("difficulty", "medium"),
            topic=data.get("topic", ""),
            test_case_count=int(data.get("test_case_count", 5)),
            conversation_id=data.get("conversation_id"),
            teacher_context=teacher_ctx,
        )

        draft_info = None
        final_draft = result.get("final_draft")
        if final_draft and final_draft.get("question_data"):
            from app.models.generated_question_draft import GeneratedQuestionDraft
            draft = GeneratedQuestionDraft(
                teacher_id=user.id,
                question_data=final_draft["question_data"],
                validation_status="passed" if final_draft.get("validation_passed") else "failed",
                validation_details={
                    "results": final_draft.get("validation_results", []),
                    "quality_review": final_draft.get("quality_review"),
                    "similar_problems": final_draft.get("similar_problems", []),
                },
                status="pending_review",
            )
            db.session.add(draft)
            db.session.commit()
            draft_info = draft.to_dict()

            _learn_teacher_preferences(user.id, data, final_draft["question_data"])

        rl_headers = _rate_limit_headers(rl_info)
        resp = jsonify({
            "status": result.get("status", "unknown"),
            "question": final_draft.get("question_data") if final_draft else None,
            "draft": draft_info,
            "pipeline_metadata": {
                "generate_attempts": result.get("generate_attempts", 0),
                "dedup_attempts": result.get("dedup_attempts", 0),
                "validation_passed": result.get("validation_passed", False),
                "quality_review": result.get("quality_review"),
                "similar_problems": result.get("similar_problems", []),
            },
            "error": result.get("error"),
        })
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp

    except ConfigError as e:
        db.session.rollback()
        return _error_response("ai_config_error", e.user_message, 503)
    except Exception as e:
        db.session.rollback()
        logger.exception("Generation pipeline error")
        return _error_response("ai_service_error", "Pipeline failed. Please try again.", 500)


# ── GET /api/v1/ai/tasks/<task_id> ─────────────────────────

@bp.route("/tasks/<task_id>", methods=["GET"])
@require_auth
def get_task(task_id):
    """Get status and results of an agent task."""
    user = get_current_user_or_401()
    from app.models.agent_task import AgentTask
    task = AgentTask.query.filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return _error_response("not_found", "Task not found", 404)
    return jsonify({"task": task.to_dict()})


# ── POST /api/v1/ai/tasks/<task_id>/retry ──────────────────

@bp.route("/tasks/<task_id>/retry", methods=["POST"])
@require_teacher
def retry_task(task_id):
    """Retry a failed task or a specific step within a batch."""
    user = get_current_user_or_401()
    from app.models.agent_task import AgentTask
    from workers.batch import BatchTaskRunner

    task = AgentTask.query.filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return _error_response("not_found", "Task not found", 404)
    if task.status != "failed":
        return _error_response("invalid_state", "Can only retry failed tasks", 400)

    data = request.get_json(silent=True) or {}
    step_index = data.get("step_index")

    task.attempt += 1
    task.status = "pending"
    task.error_detail = None
    if step_index is not None:
        task.current_step = step_index
    db.session.commit()

    try:
        runner = BatchTaskRunner(task)
        runner.run()
    except Exception as e:
        logger.exception("Retry failed for task %s", task.id)
        task.status = "failed"
        task.error_detail = str(e)[:500]
        db.session.commit()

    db.session.refresh(task)
    return jsonify({"task": task.to_dict()})


# ── GET /api/v1/ai/generate/drafts ─────────────────────────

@bp.route("/generate/drafts", methods=["GET"])
@require_teacher
def list_drafts():
    """List pending question drafts for review."""
    user = get_current_user_or_401()
    from app.models.generated_question_draft import GeneratedQuestionDraft

    status = request.args.get("status", "pending_review")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = GeneratedQuestionDraft.query.filter_by(teacher_id=user.id)
    if status != "all":
        query = query.filter_by(status=status)

    total = query.count()
    drafts = query.order_by(GeneratedQuestionDraft.created_at.desc()).offset(offset).limit(limit).all()
    return jsonify({
        "drafts": [d.to_dict() for d in drafts],
        "total": total,
    })


# ── GET /api/v1/ai/generate/drafts/<id> ────────────────────

@bp.route("/generate/drafts/<int:draft_id>", methods=["GET"])
@require_teacher
def get_draft(draft_id):
    """Get a single draft detail."""
    user = get_current_user_or_401()
    from app.models.generated_question_draft import GeneratedQuestionDraft
    draft = GeneratedQuestionDraft.query.filter_by(id=draft_id, teacher_id=user.id).first()
    if not draft:
        return _error_response("not_found", "Draft not found", 404)
    return jsonify({"draft": draft.to_dict()})


# ── POST /api/v1/ai/generate/drafts/<id>/review ────────────

@bp.route("/generate/drafts/<int:draft_id>/review", methods=["POST"])
@require_teacher
def review_draft(draft_id):
    """Teacher approves, rejects, or requests revision on a draft."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    notes = data.get("notes", "")

    if action not in ("approve", "reject", "request_revision"):
        return _error_response("invalid_request", "action must be approve, reject, or request_revision", 400)

    from app.models.generated_question_draft import GeneratedQuestionDraft
    draft = GeneratedQuestionDraft.query.filter_by(id=draft_id, teacher_id=user.id).first()
    if not draft:
        return _error_response("not_found", "Draft not found", 404)

    if action == "approve":
        try:
            problem, question = _publish_draft(draft, user.id)
            draft.published_problem_id = problem.id
            draft.published_question_id = question.id if question else None
            draft.status = "published"
            db.session.commit()
            return jsonify({
                "status": "published",
                "problem_id": problem.id,
                "question_id": question.id if question else None,
            })
        except Exception as e:
            db.session.rollback()
            logger.exception("Failed to publish draft %d", draft_id)
            return _error_response("ai_service_error", "Failed to publish question.", 500)

    elif action == "request_revision":
        draft.status = "revision_requested"
        draft.review_notes = notes
        db.session.commit()
        _trigger_revision(draft)
        db.session.refresh(draft)
        return jsonify({"status": "revising", "draft": draft.to_dict()})

    elif action == "reject":
        draft.status = "rejected"
        draft.review_notes = notes
        db.session.commit()
        return jsonify({"status": "rejected"})


def _publish_draft(draft, created_by: int):
    """Publish a draft to the problem bank."""
    return _publish_question_data_as_problem(draft.question_data, created_by)


def _trigger_revision(draft):
    """Use the Generator agent to revise based on teacher feedback."""
    from agents.generator.agent import GeneratorAgent
    from langchain_core.messages import HumanMessage as LCHumanMessage

    original_json = json.dumps(draft.question_data, indent=2, ensure_ascii=False)
    revision_prompt = (
        f"A teacher has reviewed your generated question and requested changes:\n\n"
        f"Teacher feedback: {draft.review_notes}\n\n"
        f"Original question:\n```json\n{original_json}\n```\n\n"
        f"Please revise the question based on the feedback and output the "
        f"complete updated JSON."
    )

    agent = GeneratorAgent()
    state = {
        "messages": [LCHumanMessage(content=revision_prompt)],
        "agent_type": "generator",
        "user_id": draft.teacher_id,
        "user_role": "teacher",
        "context": {
            "language": draft.question_data.get("programming_language", "python"),
        },
        "tool_results": [],
        "final_response": "",
    }

    try:
        result = agent.invoke(state)
        revised = result.get("context", {}).get("generated_problem")
        if revised:
            draft.question_data = revised
            draft.status = "pending_review"
            draft.revision_count += 1
        else:
            draft.status = "pending_review"
            draft.review_notes = (draft.review_notes or "") + "\n[Revision produced no valid output]"
        db.session.commit()
    except Exception as e:
        logger.exception("Revision failed for draft %d", draft.id)
        draft.status = "pending_review"
        draft.review_notes = (draft.review_notes or "") + f"\n[Revision failed: {e}]"
        db.session.commit()


# ── POST /api/v1/ai/generate/to-draft ──────────────────────

@bp.route("/generate/to-draft", methods=["POST"])
@require_teacher
def save_as_draft():
    """Save an AI-generated question as a draft for review instead of publishing directly."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    question_data = data.get("question_data")
    conversation_id = data.get("conversation_id")
    task_id = data.get("task_id")

    if not question_data:
        return _error_response("invalid_request", "question_data is required", 400)

    from app.models.generated_question_draft import GeneratedQuestionDraft

    verified = question_data.get("verified", False)
    draft = GeneratedQuestionDraft(
        teacher_id=user.id,
        conversation_id=conversation_id,
        task_id=task_id,
        question_data=question_data,
        validation_status="passed" if verified else "unverified",
        status="pending_review",
    )
    db.session.add(draft)
    db.session.commit()

    return jsonify({"draft": draft.to_dict()}), 201


# ── GET /api/v1/ai/traces ──────────────────────────────────

@bp.route("/traces", methods=["GET"])
@require_teacher
def list_traces():
    """List agent traces from the new agent_trace_* tables. Teacher/admin only."""
    user = get_current_user_or_401()
    from app.services.trace_query_service import TraceQueryService

    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    filters = {
        key: request.args.get(key)
        for key in (
            "agent_type",
            "status",
            "source",
            "eval_run_id",
            "conversation_id",
            "chat_task_id",
            "from",
            "to",
            "q",
        )
        if request.args.get(key) not in (None, "")
    }

    result = TraceQueryService().list_traces(
        viewer=user, filters=filters, limit=limit, offset=offset
    )
    return jsonify(result)


# ── GET /api/v1/ai/traces/<run_id> ─────────────────────────

@bp.route("/traces/<run_id>", methods=["GET"])
@require_teacher
def get_trace(run_id):
    """Get the complete trace tree (run/spans/events/artifacts/links).

    Reads the new agent_trace_* tables and falls back to a read-only view of a
    legacy ``agent_runs`` row until the Phase 7 backfill runs.
    """
    user = get_current_user_or_401()
    from app.services.trace_query_service import TraceQueryService

    trace = TraceQueryService().get_trace(run_id, viewer=user)
    if trace is None:
        return _error_response("not_found", "Trace not found", 404)
    return jsonify(trace)


# ── GET /api/v1/ai/analytics/<student_id> ────────────────────

@bp.route("/analytics/<int:student_id>", methods=["GET"])
@require_auth
def analytics_report(student_id):
    """Generate an AI learning analytics report for a student."""
    user = get_current_user_or_401()
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if user_role == "student" and user.id != student_id:
        return _error_response("forbidden", "Students can only view their own analytics", 403)

    try:
        rl_info = _rate_limit_or_abort(user.id, "analytics")
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    question_id = request.args.get("question_id", type=int)
    period = request.args.get("period", "30d")

    context = {"target_student_id": student_id, "period": period}
    if question_id:
        context["question_id"] = question_id

    prompt = f"Analyze the learning performance for student {student_id}"
    if question_id:
        prompt += f" on question {question_id}"
    prompt += f" over the last {period}."

    rl_headers = _rate_limit_headers(rl_info)

    try:
        conv = _get_or_create_conversation(user.id, "analytics", None, context)

        user_msg = AIMessage(conversation_id=conv.id, role="user", content=prompt)
        db.session.add(user_msg)
        db.session.flush()

        from langchain_core.messages import HumanMessage
        from agents import AnalyticsAgent

        agent = AnalyticsAgent()
        state = {
            "messages": [HumanMessage(content=prompt)],
            "agent_type": "analytics",
            "user_id": user.id,
            "user_role": user_role,
            "context": context,
            "tool_results": [],
            "final_response": "",
        }
        state = agent.invoke(state)
        response_text = state.get("final_response", "")

        assistant_msg = AIMessage(conversation_id=conv.id, role="assistant", content=response_text)
        db.session.add(assistant_msg)
        conv.title = conv.title or f"Analytics: Student {student_id}"
        db.session.commit()

        report = _try_parse_review_json(response_text)

        resp = jsonify({
            "conversation_id": conv.id,
            "report": report if report else response_text,
        })
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp

    except ConfigError as e:
        db.session.rollback()
        return _error_response("ai_config_error", e.user_message, 503)
    except AIError as e:
        db.session.rollback()
        logger.error("AI analytics error: %s", e)
        return _error_response("ai_service_error", e.user_message, 500)
    except Exception as e:
        db.session.rollback()
        logger.exception("AI analytics error")
        return _error_response("ai_service_error", "An unexpected error occurred. Please try again.", 500)


# ── GET /api/v1/ai/profile ────────────────────────────────
# Phase 3: Student profile / Teacher preference endpoints

@bp.route("/profile", methods=["GET"])
@require_auth
def get_profile():
    """Get the current user's AI learning profile or teacher preferences."""
    user = get_current_user_or_401()
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if user_role == "student":
        from app.models.student_profile import StudentProfile
        profile = StudentProfile.query.filter_by(student_id=user.id).first()
        if not profile:
            return jsonify({"profile": None, "message": "No profile yet. It builds over time."})
        return jsonify({"profile": profile.to_dict()})
    else:
        from app.models.student_profile import TeacherPreference
        pref = TeacherPreference.query.filter_by(teacher_id=user.id).first()
        if not pref:
            return jsonify({"preference": None, "message": "No preferences set yet."})
        return jsonify({"preference": pref.to_dict()})


@bp.route("/profile", methods=["PUT"])
@require_auth
def update_profile():
    """Update teacher preferences or student preferred language."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if user_role == "student":
        from app.models.student_profile import StudentProfile
        profile = StudentProfile.query.filter_by(student_id=user.id).first()
        if not profile:
            profile = StudentProfile(student_id=user.id)
            db.session.add(profile)
        if "preferred_language" in data:
            profile.preferred_language = data["preferred_language"]
        db.session.commit()
        return jsonify({"profile": profile.to_dict()})
    else:
        from app.models.student_profile import TeacherPreference
        pref = TeacherPreference.query.filter_by(teacher_id=user.id).first()
        if not pref:
            pref = TeacherPreference(teacher_id=user.id)
            db.session.add(pref)
        for field in ("preferred_difficulty", "preferred_language", "preferred_topics",
                       "style_notes", "class_weak_areas", "class_level"):
            if field in data:
                setattr(pref, field, data[field])
        db.session.commit()
        return jsonify({"preference": pref.to_dict()})


@bp.route("/profile/refresh", methods=["POST"])
@require_auth
def refresh_profile():
    """Rebuild the student learning profile from submission data."""
    user = get_current_user_or_401()
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if user_role != "student":
        return _error_response("forbidden", "Only students have learning profiles", 403)

    from memory.service import MemoryService
    try:
        MemoryService.update_student_profile(user.id)
        from app.models.student_profile import StudentProfile
        profile = StudentProfile.query.filter_by(student_id=user.id).first()
        return jsonify({"profile": profile.to_dict() if profile else None,
                        "message": "Profile refreshed from submission data."})
    except Exception as e:
        logger.exception("Profile refresh error")
        return _error_response("ai_service_error", "Failed to refresh profile.", 500)


# ── Phase 4: Teacher preference learning helpers ─────────

def _learn_teacher_preferences(teacher_id: int, request_params: dict, question_data: dict):
    """Background call to update teacher preferences after a successful generation."""
    try:
        from memory.preference import learn_from_generation
        learn_from_generation(teacher_id, request_params, question_data)
    except Exception as e:
        logger.debug("Preference learning skipped: %s", e)


@bp.route("/profile/refresh-style", methods=["POST"])
@require_teacher
def refresh_teacher_style():
    """Refresh the teacher's AI style summary based on generation history."""
    user = get_current_user_or_401()
    try:
        from memory.preference import refresh_teacher_style_summary
        refresh_teacher_style_summary(user.id)

        from app.models.student_profile import TeacherPreference
        pref = TeacherPreference.query.filter_by(teacher_id=user.id).first()
        return jsonify({
            "preference": pref.to_dict() if pref else None,
            "message": "Style summary refreshed from generation history.",
        })
    except Exception as e:
        logger.exception("Style refresh error")
        return _error_response("ai_service_error", "Failed to refresh style summary.", 500)


@bp.route("/profile/refresh-class-analysis", methods=["POST"])
@require_teacher
def refresh_class_analysis():
    """Analyze students' weak areas across teacher's classrooms."""
    user = get_current_user_or_401()
    try:
        from memory.preference import analyze_class_weak_areas
        analyze_class_weak_areas(user.id)

        from app.models.student_profile import TeacherPreference
        pref = TeacherPreference.query.filter_by(teacher_id=user.id).first()
        return jsonify({
            "preference": pref.to_dict() if pref else None,
            "message": "Class weak areas analysis completed.",
        })
    except Exception as e:
        logger.exception("Class analysis error")
        return _error_response("ai_service_error", "Failed to analyze class data.", 500)


# ── POST /api/v1/ai/knowledge/index ──────────────────────
# Phase 3: Knowledge base management

@bp.route("/knowledge/index", methods=["POST"])
@require_teacher
def index_problems():
    """Index all problems into the knowledge base vector store. Teacher/admin only."""
    try:
        from knowledge.store import index_all_problems
    except ImportError:
        return _error_response("kb_unavailable",
                               "Knowledge base is unavailable. Please install chromadb and sentence-transformers.", 503)
    try:
        count = index_all_problems()
        return jsonify({"message": f"Indexed {count} problems into the knowledge base."})
    except Exception as e:
        logger.exception("Knowledge base indexing error")
        return _error_response("ai_service_error", f"Failed to index problems: {e}", 500)


# ── Knowledge Base helpers ───────────────────────────────

_KB_UNAVAILABLE_MSG = (
    "Knowledge base is unavailable. Please install chromadb and sentence-transformers: "
    "pip install chromadb sentence-transformers"
)


def _get_kb_or_503():
    """Get the KnowledgeBase singleton, or return a 503 error response."""
    try:
        from knowledge.store import get_knowledge_base
        return get_knowledge_base(), None
    except ImportError:
        return None, _error_response("kb_unavailable", _KB_UNAVAILABLE_MSG, 503)
    except Exception as e:
        logger.warning("Knowledge base init failed: %s", e)
        return None, _error_response("kb_unavailable",
                                     f"Knowledge base initialization failed: {e}", 503)


@bp.route("/knowledge/stats", methods=["GET"])
@require_auth
def knowledge_stats():
    """Get knowledge base collection counts."""
    kb, err = _get_kb_or_503()
    if err:
        return err
    try:
        return jsonify({
            "knowledge_points": kb.knowledge.count(),
            "error_patterns": kb.error_patterns.count(),
            "questions": kb.questions.count(),
        })
    except Exception as e:
        logger.warning("Knowledge stats error: %s", e)
        return _error_response("ai_service_error", f"Failed to get stats: {e}", 500)


@bp.route("/knowledge/seed", methods=["POST"])
@require_teacher
def seed_knowledge():
    """Seed the knowledge base with built-in error patterns and knowledge points."""
    kb, err = _get_kb_or_503()
    if err:
        return err
    try:
        from scripts.seed_knowledge import seed_error_patterns, seed_knowledge_points
        err_count = seed_error_patterns(kb)
        kp_count = seed_knowledge_points(kb)
        return jsonify({
            "message": f"Seeded {err_count} error patterns, {kp_count} knowledge points.",
            "error_patterns_added": err_count,
            "knowledge_points_added": kp_count,
        })
    except Exception as e:
        logger.exception("Knowledge seed error")
        return _error_response("ai_service_error", f"Failed to seed knowledge base: {e}", 500)


# ── POST /api/v1/ai/knowledge/add ────────────────────────
# Phase D: Knowledge base management API

@bp.route("/knowledge/add", methods=["POST"])
@require_teacher
def add_knowledge():
    """Add a knowledge point or error pattern. Teacher/admin only."""
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    content = (data.get("content") or "").strip()
    category = (data.get("category") or "concept").strip()

    if not topic or not content:
        return _error_response("invalid_request", "topic and content are required", 400)

    kb, err = _get_kb_or_503()
    if err:
        return err

    try:
        user = get_current_user_or_401()
        scope = (data.get("scope") or "teacher").strip()
        if scope not in ("global", "teacher", "classroom"):
            scope = "teacher"

        if category == "error_pattern":
            error_type = data.get("error_type", "CE")
            kb.add_error_pattern(error_type, topic, content)
        else:
            kb.add_knowledge_point(topic, content, category,
                                   scope=scope, owner_id=user.id)

        return jsonify({
            "message": "Knowledge point added successfully.",
            "id": f"{category}_{topic}",
            "topic": topic,
            "category": category,
            "scope": scope,
        }), 201
    except Exception as e:
        logger.exception("Knowledge base add error")
        return _error_response("ai_service_error", f"Failed to add knowledge point: {e}", 500)


@bp.route("/knowledge/search", methods=["GET"])
@require_auth
def search_knowledge():
    """Search the knowledge base. Returns relevant knowledge points and/or error patterns."""
    query = (request.args.get("query") or "").strip()
    if not query:
        return _error_response("invalid_request", "query parameter is required", 400)

    n = min(int(request.args.get("n", 5)), 20)
    category = request.args.get("category")

    kb, err = _get_kb_or_503()
    if err:
        return err

    try:
        user = get_current_user_or_401()
        user_role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        scope_filter = None
        if user_role_str not in ("admin",):
            scope_filter = {"owner_id": user.id}

        results = {}
        if category in (None, "knowledge"):
            results["knowledge_points"] = kb.search_knowledge(query, n=n, scope_filter=scope_filter)
        if category in (None, "error_pattern"):
            results["error_patterns"] = kb.search_error_patterns(query, n=n)

        return jsonify(results)
    except Exception as e:
        logger.exception("Knowledge base search error")
        return _error_response("ai_service_error", f"Knowledge search failed: {e}", 500)


@bp.route("/knowledge/<path:knowledge_id>", methods=["DELETE"])
@require_teacher
def delete_knowledge(knowledge_id):
    """Delete a knowledge point by its ID. Teacher/admin only."""
    kb, err = _get_kb_or_503()
    if err:
        return err

    try:
        if knowledge_id.startswith("err_"):
            kb.error_patterns.delete(ids=[knowledge_id])
        else:
            kb.knowledge.delete(ids=[knowledge_id])

        return jsonify({"message": f"Knowledge point '{knowledge_id}' deleted."})
    except Exception as e:
        logger.exception("Knowledge base delete error")
        return _error_response("ai_service_error", f"Failed to delete knowledge point: {e}", 500)


# ── POST /api/v1/ai/evals/run ────────────────────────────
# Phase 3: Eval framework endpoints

@bp.route("/evals/run", methods=["POST"])
@require_teacher
def run_evals():
    """Run an eval suite. Teacher/admin only.

    Two modes:
    - ``selector`` (preferred): run dataset cases through the EvalHarness, which
      binds each case to a trace and persists ``EvalRun`` / ``EvalCaseRun`` /
      ``EvalCaseGraderResult`` through the runtime-neutral store.
    - ``suite`` (legacy): run the old ``evals/cases/*_evals.json`` files.
    """
    data = request.get_json(silent=True) or {}
    selector = data.get("selector")

    if selector:
        return _run_evals_harness(data, selector)

    suite = data.get("suite", "all")
    try:
        from evals.runner import EvalRunner, report_to_dict
        runner = EvalRunner(use_real_llm=True)

        if suite == "all":
            reports = runner.run_all_suites()
            results = [report_to_dict(r) for r in reports]
        else:
            import os
            suite_path = os.path.join("evals", "cases", f"{suite}_evals.json")
            if not os.path.exists(suite_path):
                return _error_response("not_found", f"Suite '{suite}' not found", 404)
            report = runner.run_suite(suite_path)
            results = [report_to_dict(report)]

        # Persist eval run results
        from app.models.eval_run import EvalRun
        for r in results:
            run = EvalRun(
                suite_name=r["suite_name"],
                model_name=data.get("model_name", "deepseek"),
                total_cases=r["total"],
                passed_cases=r["passed"],
                pass_rate=r["pass_rate"],
                results_json=r["results"],
                duration_seconds=r["duration_seconds"],
            )
            db.session.add(run)
        db.session.commit()

        return jsonify({"reports": results})
    except Exception as e:
        db.session.rollback()
        logger.exception("Eval run error")
        return _error_response("ai_service_error", f"Eval run failed: {e}", 500)


def _run_evals_harness(data: dict, selector: str):
    """Selector-based eval run via the EvalHarness (persists through core store)."""
    try:
        from evals.harness.eval_harness import EvalHarness

        budget = data.get("budget") or {}
        report = EvalHarness().run(
            selector=selector,
            model_name=data.get("model_name"),
            max_cases=budget.get("max_cases"),
        )
        return jsonify({"report": _eval_harness_report_to_dict(report)})
    except Exception as e:
        logger.exception("EvalHarness run error")
        return _error_response("ai_service_error", f"Eval run failed: {e}", 500)


def _eval_harness_report_to_dict(report) -> dict:
    return {
        "eval_run_id": report.eval_run_id,
        "selector": report.selector,
        "model_name": report.model_name,
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "errors": report.errors,
        "pass_rate": report.pass_rate,
        "cases": [
            {
                "case_id": c.case_id,
                "case_type": c.case_type,
                "suite": c.suite,
                "agent_type": c.agent_type,
                "trace_id": c.trace_id,
                "status": c.status,
                "passed": c.passed,
                "failure_type": c.failure_type,
                "duration_ms": c.duration_ms,
                "tokens_input": c.tokens_input,
                "tokens_output": c.tokens_output,
                "cost_cny": float(c.cost_cny) if c.cost_cny is not None else None,
                "output_preview": c.output_preview,
                "graders": [
                    {
                        "grader_type": g.grader_type,
                        "grader_name": g.grader_name,
                        "passed": g.passed,
                        "score": g.score,
                        "reason": g.reason,
                    }
                    for g in c.grader_results
                ],
            }
            for c in report.case_results
        ],
    }


@bp.route("/evals/history", methods=["GET"])
@require_teacher
def eval_history():
    """List past eval runs."""
    from app.models.eval_run import EvalRun
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = EvalRun.query.order_by(EvalRun.run_at.desc())
    total = query.count()
    runs = query.offset(offset).limit(limit).all()
    return jsonify({"runs": [r.to_dict() for r in runs], "total": total})


# ── Phase 2: Supervisor Workflow Endpoints ──────────────────


@bp.route("/workflows", methods=["POST"])
@require_auth
def create_workflow():
    """Create and execute a multi-step workflow via the Supervisor agent."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    goal = (data.get("goal") or data.get("message") or "").strip()
    if not goal:
        return _error_response("invalid_request", "goal is required", 400)

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    try:
        rl_info = _rate_limit_or_abort(user.id, "generator")
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    context.setdefault("language", data.get("language", "python"))
    context.setdefault("difficulty", data.get("difficulty", "medium"))
    context.setdefault("topic", data.get("topic", ""))
    context.setdefault("test_case_count", int(data.get("test_case_count", 5)))
    context["prompt"] = goal

    conversation_id = data.get("conversation_id")

    try:
        from graph import SupervisorAgent

        supervisor = SupervisorAgent()
        state = supervisor.run_workflow(
            user_id=user.id,
            user_role=user_role,
            goal=goal,
            context=context,
            conversation_id=conversation_id,
        )

        rl_headers = _rate_limit_headers(rl_info)
        resp = jsonify({
            "workflow_run_id": state.get("workflow_run_id"),
            "status": state.get("status"),
            "workflow_type": state.get("workflow_type"),
            "result": state.get("final_result"),
            "error": state.get("error"),
            "events": state.get("_events", []),
        })
        resp.status_code = 201 if state.get("status") != "failed" else 500
        for k, v in rl_headers.items():
            resp.headers[k] = v
        return resp

    except ConfigError as e:
        db.session.rollback()
        return _error_response("ai_config_error", e.user_message, 503)
    except Exception as e:
        db.session.rollback()
        logger.exception("Workflow creation failed")
        return _error_response("ai_service_error",
                               "Workflow execution failed. Please try again.", 500)


@bp.route("/workflows", methods=["GET"])
@require_auth
def list_workflows():
    """List the current user's workflow runs."""
    user = get_current_user_or_401()
    from app.models.workflow import WorkflowRun

    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    workflow_type = request.args.get("type")

    query = WorkflowRun.query.filter_by(user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    if workflow_type:
        query = query.filter_by(workflow_type=workflow_type)

    total = query.count()
    runs = query.order_by(WorkflowRun.created_at.desc()).offset(offset).limit(limit).all()

    return jsonify({
        "workflows": [r.to_dict() for r in runs],
        "total": total,
    })


@bp.route("/workflows/<workflow_run_id>", methods=["GET"])
@require_auth
def get_workflow(workflow_run_id):
    """Get detailed status of a workflow run including all steps."""
    user = get_current_user_or_401()
    from graph import SupervisorAgent

    supervisor = SupervisorAgent()
    result = supervisor.get_workflow_status(workflow_run_id)

    if result.get("error"):
        return _error_response("not_found", result["error"], 404)

    run_data = result.get("run", {})
    if run_data.get("user_id") != user.id:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role not in ("teacher", "admin"):
            return _error_response("forbidden", "Access denied", 403)

    return jsonify(result)


@bp.route("/workflows/<workflow_run_id>/approve", methods=["POST"])
@require_auth
def approve_workflow_step(workflow_run_id):
    """Approve or reject a workflow step at a human gate."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    from app.models.workflow import WorkflowRun
    run = WorkflowRun.query.get(workflow_run_id)
    if not run:
        return _error_response("not_found", "Workflow not found", 404)
    if run.user_id != user.id:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role not in ("teacher", "admin"):
            return _error_response("forbidden", "Access denied", 403)
    if run.status != "waiting_approval":
        return _error_response("invalid_state",
                               f"Workflow is in '{run.status}' state, not waiting_approval", 400)

    approved = data.get("approved", data.get("action") == "approve")
    feedback = data.get("feedback", data.get("notes", ""))

    try:
        from graph import SupervisorAgent
        supervisor = SupervisorAgent()
        state = supervisor.resume_workflow(workflow_run_id, approved, feedback)

        return jsonify({
            "workflow_run_id": workflow_run_id,
            "status": state.get("status"),
            "result": state.get("final_result"),
            "error": state.get("error"),
        })
    except Exception as e:
        db.session.rollback()
        logger.exception("Workflow approval failed")
        return _error_response("ai_service_error",
                               "Failed to process approval.", 500)
