"""MCP tool approval model — Human Gate for high-risk tool calls."""

from datetime import timedelta

from app.core.extensions import db
from app.core.timezone import now_china

APPROVAL_TIMEOUT_MINUTES = 30


class McpToolApproval(db.Model):
    __tablename__ = "mcp_tool_approvals"

    id = db.Column(db.String(36), primary_key=True)
    api_key_id = db.Column(db.String(36), db.ForeignKey("mcp_api_keys.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    tool_name = db.Column(db.String(50), nullable=False)
    tool_args = db.Column(db.JSON, nullable=False)
    risk_level = db.Column(db.String(10), default="high")
    status = db.Column(db.String(20), default="pending")
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    result = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])

    @staticmethod
    def default_expiry():
        return now_china() + timedelta(minutes=APPROVAL_TIMEOUT_MINUTES)

    def check_expiration(self):
        if self.status == "pending" and self.expires_at and now_china() > self.expires_at:
            self.status = "expired"

    def to_dict(self):
        self.check_expiration()
        return {
            "id": self.id,
            "api_key_id": self.api_key_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "risk_level": self.risk_level,
            "status": self.status,
            "reviewer_id": self.reviewer_id,
            "review_notes": self.review_notes,
            "result": self.result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
