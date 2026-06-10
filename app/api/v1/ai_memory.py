"""Governed memory lifecycle API.

Subject-scoped governance over ``memory_items``: list a subject's active and
candidate items, approve a candidate (promote to active), reject it, or suppress
an active item ("forget"). A student may only touch ``student`` items they own,
a teacher only their own ``teacher`` items; admins may operate on any subject.
Suppression is a status change, never a physical delete, so the audit trail is
preserved.
"""

from flask import Blueprint, jsonify
from werkzeug.exceptions import Unauthorized

from app.auth.decorators import get_current_user_or_401

bp = Blueprint("ai_memory", __name__, url_prefix="/api/v1/ai/memory")


def _role_of(user) -> str:
    return user.role.value if hasattr(user.role, "value") else user.role


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _serialize(item) -> dict:
    return {
        "id": item.id,
        "subject_type": item.subject_type,
        "subject_id": item.subject_id,
        "memory_kind": item.memory_kind,
        "memory_key": item.memory_key,
        "value_json": item.value_json,
        "status": item.status,
        "confidence": item.confidence,
        "sensitivity": item.sensitivity,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "reason": item.reason,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
    }


def _can_access(user, item) -> bool:
    role = _role_of(user)
    if role == "admin":
        return True
    return item.subject_type == role and str(item.subject_id) == str(user.id)


def _current_user_or_error():
    try:
        return get_current_user_or_401(), None
    except Unauthorized:
        return None, _error("memory_unauthorized", "Authentication required", 401)


@bp.route("/", methods=["GET"], strict_slashes=False)
def list_memory_items():
    user, err = _current_user_or_error()
    if err:
        return err

    from app.core.extensions import db
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db.session)
    role = _role_of(user)
    subject_type = "teacher" if role == "teacher" else "student"
    subject_id = str(user.id)

    active = repo.active_for_subject(subject_type, subject_id)
    candidates = repo.candidates_for_subject(subject_type, subject_id)
    db.session.commit()

    items = [_serialize(item) for item in (*active, *candidates)]
    return jsonify({"items": items}), 200


def _mutate(item_id: str, action: str):
    user, err = _current_user_or_error()
    if err:
        return err

    from app.core.extensions import db
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db.session)
    item = repo.get(item_id)
    if item is None:
        return _error("memory_not_found", "Memory item not found", 404)
    if not _can_access(user, item):
        return _error(
            "memory_forbidden",
            "You cannot govern this memory item",
            403,
        )

    if action == "approve":
        result = repo.promote(item_id)
    elif action == "reject":
        result = repo.reject(item_id)
    else:
        result = repo.suppress(item_id)

    db.session.commit()
    return jsonify(_serialize(result)), 200


@bp.route("/<item_id>/approve", methods=["POST"])
def approve_memory_item(item_id):
    return _mutate(item_id, "approve")


@bp.route("/<item_id>/reject", methods=["POST"])
def reject_memory_item(item_id):
    return _mutate(item_id, "reject")


@bp.route("/<item_id>", methods=["DELETE"])
def suppress_memory_item(item_id):
    return _mutate(item_id, "suppress")
