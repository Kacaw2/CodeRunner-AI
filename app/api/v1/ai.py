import json
import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context
from app.auth.decorators import require_auth, require_teacher, get_current_user_or_401
from app.core.extensions import db, redis_client
from app.models.ai_conversation import AIConversation, AIMessage
from app.agents.config import AGENT_RATE_LIMITS
from app.agents.exceptions import AIError, RateLimitError, ConfigError
from app.agents.security import detect_injection, sanitize_user_input, filter_output

logger = logging.getLogger(__name__)

bp = Blueprint("ai", __name__, url_prefix="/api/v1/ai")


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

    agent_type = data.get("agent_type", "tutor")

    is_suspicious, pattern = detect_injection(message)
    if is_suspicious:
        logger.warning("Potential injection from user %d: pattern=%s", user.id, pattern)
        _log_audit(user.id, agent_type, "chat", message, True, pattern)

    message = sanitize_user_input(message)

    try:
        rl_info = _rate_limit_or_abort(user.id, agent_type)
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    rl_headers = _rate_limit_headers(rl_info)
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    try:
        conv = _get_or_create_conversation(user.id, agent_type, data.get("conversation_id"), context)
        history = _load_history(conv.id) if data.get("conversation_id") else []

        user_msg = AIMessage(conversation_id=conv.id, role="user", content=message)
        db.session.add(user_msg)
        db.session.flush()

        from langchain_core.messages import HumanMessage
        from app.agents import AgentOrchestrator

        orch = AgentOrchestrator()
        state = orch.run({
            "messages": history + [HumanMessage(content=message)],
            "agent_type": agent_type,
            "user_id": user.id,
            "user_role": user_role,
            "context": context,
            "tool_results": [],
            "final_response": "",
        })

        response_text = filter_output(state.get("final_response", ""), agent_type, user_role)

        assistant_msg = AIMessage(conversation_id=conv.id, role="assistant", content=response_text)
        db.session.add(assistant_msg)
        conv.title = conv.title or message[:80]
        db.session.commit()

        resp = jsonify({
            "conversation_id": conv.id,
            "message_id": assistant_msg.id,
            "agent_type": agent_type,
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

    agent_type = data.get("agent_type", "tutor")

    is_suspicious, pattern = detect_injection(message)
    if is_suspicious:
        logger.warning("Potential injection from user %d (stream): pattern=%s", user.id, pattern)
        _log_audit(user.id, agent_type, "chat_stream", message, True, pattern)

    message = sanitize_user_input(message)

    try:
        rl_info = _rate_limit_or_abort(user.id, agent_type)
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
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    def generate():
        from langchain_core.messages import HumanMessage
        from app.agents.agents import TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent

        _AGENT_MAP = {
            "tutor": TutorAgent,
            "reviewer": ReviewerAgent,
            "generator": GeneratorAgent,
            "analytics": AnalyticsAgent,
        }

        yield f"data: {json.dumps({'type': 'start', 'conversation_id': conv_id, 'agent_type': agent_type})}\n\n"

        state = {
            "messages": history + [HumanMessage(content=message)],
            "agent_type": agent_type,
            "user_id": user_id,
            "user_role": user_role,
            "context": context,
            "tool_results": [],
            "final_response": "",
        }

        agent_cls = _AGENT_MAP.get(agent_type, TutorAgent)
        agent = agent_cls()
        full_response = ""
        try:
            for event in agent.stream(state):
                if event["type"] == "token":
                    full_response += event["content"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if not full_response:
                full_response = state.get("final_response", "")

            assistant_msg = AIMessage(conversation_id=conv_id, role="assistant", content=full_response)
            db.session.add(assistant_msg)
            _conv = AIConversation.query.get(conv_id)
            if _conv and not _conv.title:
                _conv.title = message[:80]
            db.session.commit()

            yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg.id})}\n\n"
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
            **rl_headers,
        },
    )


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
        from app.agents.agents import ReviewerAgent

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
        from app.agents.agents import GeneratorAgent

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

        question_data = state.get("context", {}).get("generated_question")
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
    from app.agents.batch_runner import decompose_batch_params, BatchTaskRunner

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

    from app.agents.memory import MemoryService
    teacher_ctx = MemoryService.get_memory_context(user.id, user_role)

    from app.agents.generation_pipeline import run_generation_pipeline
    try:
        result = run_generation_pipeline(
            teacher_id=user.id,
            prompt=prompt,
            language=data.get("language", "python"),
            difficulty=data.get("difficulty", "medium"),
            topic=data.get("topic", ""),
            test_case_count=int(data.get("test_case_count", 5)),
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
                    "similar_questions": final_draft.get("similar_questions", []),
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
                "similar_questions": result.get("similar_questions", []),
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
    from app.agents.batch_runner import BatchTaskRunner

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
    from app.agents.agents.generator import GeneratorAgent
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
        revised = result.get("context", {}).get("generated_question")
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
    """List agent run traces. Teacher/admin only."""
    user = get_current_user_or_401()
    from app.models.agent_trace import AgentRun

    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    agent_type = request.args.get("agent_type")

    query = AgentRun.query
    if agent_type:
        query = query.filter_by(agent_type=agent_type)

    total = query.count()
    runs = query.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit).all()
    return jsonify({
        "traces": [r.to_dict() for r in runs],
        "total": total,
    })


# ── GET /api/v1/ai/traces/<run_id> ─────────────────────────

@bp.route("/traces/<run_id>", methods=["GET"])
@require_teacher
def get_trace(run_id):
    """Get detailed trace for a single agent run."""
    from app.models.agent_trace import AgentRun, AgentRunStep
    run = AgentRun.query.get(run_id)
    if not run:
        return _error_response("not_found", "Trace not found", 404)
    steps = AgentRunStep.query.filter_by(run_id=run_id).order_by(AgentRunStep.step_index).all()
    return jsonify({
        "run": run.to_dict(),
        "steps": [s.to_dict() for s in steps],
    })


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
        from app.agents.agents import AnalyticsAgent

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

    from app.agents.memory import MemoryService
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
        from app.agents.preference_learner import learn_from_generation
        learn_from_generation(teacher_id, request_params, question_data)
    except Exception as e:
        logger.debug("Preference learning skipped: %s", e)


@bp.route("/profile/refresh-style", methods=["POST"])
@require_teacher
def refresh_teacher_style():
    """Refresh the teacher's AI style summary based on generation history."""
    user = get_current_user_or_401()
    try:
        from app.agents.preference_learner import refresh_teacher_style_summary
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
        from app.agents.preference_learner import analyze_class_weak_areas
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
def index_questions():
    """Index all questions into the knowledge base vector store. Teacher/admin only."""
    try:
        from app.agents.knowledge_base import index_all_questions
        count = index_all_questions()
        return jsonify({"message": f"Indexed {count} questions into the knowledge base."})
    except Exception as e:
        logger.exception("Knowledge base indexing error")
        return _error_response("ai_service_error", f"Failed to index questions: {e}", 500)


# ── POST /api/v1/ai/evals/run ────────────────────────────
# Phase 3: Eval framework endpoints

@bp.route("/evals/run", methods=["POST"])
@require_teacher
def run_evals():
    """Run an eval suite. Teacher/admin only."""
    data = request.get_json(silent=True) or {}
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
