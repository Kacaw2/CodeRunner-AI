from flask import Blueprint, render_template, request
from app.auth import web_login_required, web_teacher_required

ai_chat_bp = Blueprint("ai_chat", __name__, url_prefix="/ai")


@ai_chat_bp.route("/chat")
@web_login_required
def chat_page():
    question_id = request.args.get("question_id", type=int)
    submission_id = request.args.get("submission_id", type=int)
    conversation_id = request.args.get("conversation_id", type=int)
    agent_type = request.args.get("agent_type", "tutor")
    return render_template(
        "ai/chat.html",
        question_id=question_id,
        submission_id=submission_id,
        conversation_id=conversation_id,
        agent_type=agent_type,
    )


@ai_chat_bp.route("/review-queue")
@web_teacher_required
def review_queue_page():
    return render_template("ai/review_queue.html")


@ai_chat_bp.route("/traces")
@web_teacher_required
def traces_page():
    return render_template("ai/traces.html")
