"""Flask API endpoints for MCP API Key management (teacher/admin only)."""

import secrets
import uuid

from flask import Blueprint, g, jsonify, request

from app.auth.decorators import require_teacher
from app.core.extensions import db
from app.core.timezone import now_china
from mcp_server.auth import hash_api_key
from mcp_server.models.api_key import McpApiKey

bp = Blueprint("mcp_keys", __name__, url_prefix="/api/v1/mcp/keys")

KEY_PREFIX = "mcp-"


@bp.route("", methods=["POST"])
@require_teacher
def create_key():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "Default Key").strip()[:100]
    scopes = data.get("scopes")
    rate_limit_rpm = data.get("rate_limit_rpm", 30)

    user = g.current_user
    user_role = user.role.value if hasattr(user.role, "value") else user.role

    raw_key = KEY_PREFIX + secrets.token_urlsafe(40)
    key_id = str(uuid.uuid4())

    record = McpApiKey(
        id=key_id,
        user_id=user.id,
        key_hash=hash_api_key(raw_key),
        name=name,
        role=user_role,
        scopes=scopes,
        rate_limit_rpm=rate_limit_rpm,
        created_at=now_china(),
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({
        "id": key_id,
        "name": name,
        "key": raw_key,
        "role": user_role,
        "scopes": scopes,
        "rate_limit_rpm": rate_limit_rpm,
        "message": "Save this key now — it will not be shown again.",
    }), 201


@bp.route("", methods=["GET"])
@require_teacher
def list_keys():
    user = g.current_user
    keys = McpApiKey.query.filter_by(user_id=user.id).order_by(McpApiKey.created_at.desc()).all()
    return jsonify([
        {
            "id": k.id,
            "name": k.name,
            "role": k.role,
            "scopes": k.scopes,
            "rate_limit_rpm": k.rate_limit_rpm,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked": k.revoked_at is not None,
        }
        for k in keys
    ])


@bp.route("/<key_id>", methods=["DELETE"])
@require_teacher
def revoke_key(key_id: str):
    user = g.current_user
    key = McpApiKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not key:
        return jsonify({"error": "Key not found"}), 404
    if key.revoked_at:
        return jsonify({"error": "Key already revoked"}), 400
    key.revoked_at = now_china()
    db.session.commit()
    return jsonify({"message": "Key revoked", "id": key_id})
