"""MCP API Key model — shared between Flask (management) and MCP Server (verification)."""

from app.core.extensions import db
from app.core.timezone import now_china


class McpApiKey(db.Model):
    __tablename__ = "mcp_api_keys"

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    key_hash = db.Column(db.String(128), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    scopes = db.Column(db.JSON, nullable=True)
    rate_limit_rpm = db.Column(db.Integer, default=30)
    created_at = db.Column(db.DateTime, default=now_china)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="mcp_api_keys")
