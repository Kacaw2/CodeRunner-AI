from app.core.extensions import db
from app.core.timezone import now_china


class Problem(db.Model):
    """Parent problem shown in dashboard, quizzes, and problem runner."""

    __tablename__ = "problems"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), nullable=False, unique=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(20), default="easy")
    points = db.Column(db.Integer, default=10)
    order = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)
    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)

    variants = db.relationship(
        "Question",
        back_populates="problem",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Question.programming_language",
    )
    test_cases = db.relationship(
        "TestCase",
        back_populates="problem",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="TestCase.id",
    )
    quiz_associations = db.relationship(
        "QuizProblem",
        back_populates="problem",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="QuizProblem.order",
    )

    def __repr__(self):
        return f"<Problem {self.id}: {self.title}>"

    def variant_for(self, language):
        target = (language or "python").lower()
        for variant in self.variants:
            if (variant.programming_language or "").lower() == target:
                return variant
        return None
