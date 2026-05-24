from app.core.extensions import db
from app.core.timezone import now_china


class EvalRun(db.Model):
    """Tracks eval suite run results over time."""
    __tablename__ = "eval_runs"

    id = db.Column(db.Integer, primary_key=True)
    suite_name = db.Column(db.String(50), nullable=False)
    run_at = db.Column(db.DateTime, default=now_china)
    model_name = db.Column(db.String(50))
    total_cases = db.Column(db.Integer)
    passed_cases = db.Column(db.Integer)
    pass_rate = db.Column(db.Float)
    results_json = db.Column(db.JSON)
    duration_seconds = db.Column(db.Float)

    def to_dict(self):
        return {
            "id": self.id,
            "suite_name": self.suite_name,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "model_name": self.model_name,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "pass_rate": self.pass_rate,
            "results_json": self.results_json,
            "duration_seconds": self.duration_seconds,
        }
