"""MCP audit log model."""

from app.core.extensions import db
from app.core.timezone import now_china


class McpAuditLog(db.Model):
    __tablename__ = "mcp_audit_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    api_key_id = db.Column(db.String(36), db.ForeignKey("mcp_api_keys.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    tool_name = db.Column(db.String(50), nullable=False)
    tool_args = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), nullable=False)
    latency_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)
