from datetime import datetime

from app.core.extensions import db


class AIAuditLog(db.Model):
    __tablename__ = "ai_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    agent_type = db.Column(db.String(20))
    action = db.Column(db.String(50))
    input_preview = db.Column(db.String(200))
    injection_detected = db.Column(db.Boolean, default=False)
    injection_pattern = db.Column(db.String(100), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
