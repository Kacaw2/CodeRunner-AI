from app.core.extensions import db
from app.core.timezone import now_china


class StudentProfile(db.Model):
    """Persistent learning profile built from submission data and AI interactions."""
    __tablename__ = "student_profiles"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    error_patterns = db.Column(db.JSON, default=dict)
    knowledge_map = db.Column(db.JSON, default=dict)
    recent_topics = db.Column(db.JSON, default=list)
    recent_questions = db.Column(db.JSON, default=list)
    current_hint_level = db.Column(db.JSON, default=dict)
    learning_summary = db.Column(db.Text, nullable=True)
    preferred_language = db.Column(db.String(20), default="python")

    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)

    student = db.relationship("User", backref=db.backref("profile", uselist=False, lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "error_patterns": self.error_patterns,
            "knowledge_map": self.knowledge_map,
            "recent_topics": self.recent_topics,
            "recent_questions": self.recent_questions,
            "current_hint_level": self.current_hint_level,
            "learning_summary": self.learning_summary,
            "preferred_language": self.preferred_language,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TeacherPreference(db.Model):
    """Teacher-specific AI preferences."""
    __tablename__ = "teacher_preferences"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    preferred_difficulty = db.Column(db.String(20), default="medium")
    preferred_language = db.Column(db.String(20), default="python")
    preferred_topics = db.Column(db.JSON, default=list)
    style_notes = db.Column(db.Text, nullable=True)
    class_weak_areas = db.Column(db.JSON, default=list)
    class_level = db.Column(db.String(20), default="intermediate")

    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)

    teacher = db.relationship("User", backref=db.backref("preference", uselist=False, lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "preferred_difficulty": self.preferred_difficulty,
            "preferred_language": self.preferred_language,
            "preferred_topics": self.preferred_topics,
            "style_notes": self.style_notes,
            "class_weak_areas": self.class_weak_areas,
            "class_level": self.class_level,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
