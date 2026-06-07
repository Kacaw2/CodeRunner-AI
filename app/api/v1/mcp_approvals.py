"""Flask API endpoints for MCP tool approval management (teacher/admin only)."""

from flask import Blueprint, g, jsonify, request

from app.auth.decorators import require_teacher
from app.core.extensions import db
from app.core.timezone import now_china
from domain.repositories.mcp import SyncMcpRepository

bp = Blueprint("mcp_approvals", __name__, url_prefix="/api/v1/mcp/approvals")


@bp.route("", methods=["GET"])
@require_teacher
def list_approvals():
    status_filter = request.args.get("status", "pending")
    approvals = SyncMcpRepository(db.session).list_approvals(
        status=None if status_filter == "all" else status_filter,
        limit=50,
    )
    result = []
    for a in approvals:
        a.check_expiration()
        result.append(a.to_dict())
    db.session.commit()
    return jsonify(result)


@bp.route("/<approval_id>", methods=["GET"])
@require_teacher
def get_approval(approval_id: str):
    approval = SyncMcpRepository(db.session).get_approval(approval_id)
    if not approval:
        return jsonify({"error": "Approval not found"}), 404
    approval.check_expiration()
    db.session.commit()
    return jsonify(approval.to_dict())


@bp.route("/<approval_id>/approve", methods=["POST"])
@require_teacher
def approve(approval_id: str):
    approval = SyncMcpRepository(db.session).get_approval(approval_id)
    if not approval:
        return jsonify({"error": "Approval not found"}), 404

    approval.check_expiration()
    if approval.status != "pending":
        return jsonify({"error": f"Cannot approve — current status is '{approval.status}'"}), 400

    data = request.get_json(silent=True) or {}
    approval.status = "approved"
    approval.reviewer_id = g.current_user.id
    approval.review_notes = data.get("notes")
    approval.reviewed_at = now_china()
    db.session.commit()

    return jsonify({"message": "Approved", "id": approval_id, "status": "approved"})


@bp.route("/<approval_id>/reject", methods=["POST"])
@require_teacher
def reject(approval_id: str):
    approval = SyncMcpRepository(db.session).get_approval(approval_id)
    if not approval:
        return jsonify({"error": "Approval not found"}), 404

    approval.check_expiration()
    if approval.status != "pending":
        return jsonify({"error": f"Cannot reject — current status is '{approval.status}'"}), 400

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "")
    approval.status = "rejected"
    approval.reviewer_id = g.current_user.id
    approval.review_notes = reason
    approval.reviewed_at = now_china()
    db.session.commit()

    return jsonify({"message": "Rejected", "id": approval_id, "status": "rejected"})
