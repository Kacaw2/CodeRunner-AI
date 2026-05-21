import json
import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context
from app.auth.decorators import require_auth, require_teacher, get_current_user_or_401
from app.core.extensions import db, redis_client
from app.models.ai_conversation import AIConversation, AIMessage
from app.agents.config import AGENT_RATE_LIMITS
from app.agents.exceptions import AIError, RateLimitError, ConfigError

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

    try:
        rl_info = _rate_limit_or_abort(user.id, agent_type)
    except RateLimitError as e:
        return _error_response("ai_rate_limit", e.user_message, 429,
                               {"Retry-After": str(e.retry_after)})

    context = _build_context(data)
    rl_headers = _rate_limit_headers(rl_info)

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
            "user_role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "context": context,
            "tool_results": [],
            "final_response": "",
        })

        response_text = state.get("final_response", "")

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
        if question_data:
            resp = jsonify({"conversation_id": conv.id, "question": question_data})
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
        from app.models.question import Question, TestCase

        q = Question(
            title=question_json.get("title", "AI Generated Question"),
            description=question_json.get("description", ""),
            starter_code=question_json.get("starter_code", ""),
            solution=question_json.get("solution", ""),
            solution_explanation=question_json.get("solution_explanation", ""),
            programming_language=question_json.get("programming_language", "python"),
            created_by=user.id,
        )
        db.session.add(q)
        db.session.flush()

        tc_count = 0
        for tc_data in question_json.get("test_cases", []):
            tc = TestCase(
                question_id=q.id,
                input=tc_data.get("input", ""),
                expected_output=tc_data.get("expected_output", ""),
                is_hidden=tc_data.get("is_hidden", False),
                weight=tc_data.get("weight", 1.0),
            )
            db.session.add(tc)
            tc_count += 1

        quiz_id = data.get("quiz_id")
        if quiz_id:
            from app.models.quiz import QuizQuestion, Quiz
            quiz = Quiz.query.get(quiz_id)
            if quiz:
                max_order = (db.session.query(db.func.max(QuizQuestion.order))
                             .filter_by(quiz_id=quiz_id).scalar() or 0)
                qq = QuizQuestion(quiz_id=quiz_id, question_id=q.id, order=max_order + 1)
                db.session.add(qq)

        db.session.commit()

        return jsonify({
            "question_id": q.id,
            "test_case_count": tc_count,
            "message": "Question saved successfully",
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.exception("Save generated question error")
        return _error_response("ai_service_error", "Failed to save question. Please try again.", 500)


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
