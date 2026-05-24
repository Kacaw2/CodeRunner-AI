from app.core.extensions import db
from app.core.timezone import now_china

class Question(db.Model):
    """Language-specific executable variant for a parent Problem."""

    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    programming_language = db.Column(db.String(20), nullable=False, default='python')
    starter_code = db.Column(db.Text)
    solution = db.Column(db.Text)
    solution_explanation = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_china)
    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)

    problem = db.relationship('Problem', back_populates='variants')
    submissions = db.relationship('Submission', back_populates='question', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('problem_id', 'programming_language', name='uq_question_problem_language'),
    )

    @property
    def title(self):
        return self.problem.title if self.problem else None

    @property
    def description(self):
        return self.problem.description if self.problem else None

    @property
    def points(self):
        return self.problem.points if self.problem else None

    @property
    def order(self):
        return self.problem.order if self.problem else None

    @property
    def created_by(self):
        return self.problem.created_by if self.problem else None

    def __repr__(self):
        return f'<Question variant problem={self.problem_id} language={self.programming_language}>'

    def to_dict(self, include_solution=False):
        data = {
            'id': self.id,
            'problem_id': self.problem_id,
            'starter_code': self.starter_code,
            'programming_language': self.programming_language,
            'created_at': self.created_at,
        }
        if include_solution:
            data['solution'] = self.solution
            data['solution_explanation'] = self.solution_explanation
        return data


class TestCase(db.Model):
    """Shared problem-level test case used by every language variant."""

    __tablename__ = 'test_cases'

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    input = db.Column(db.Text, nullable=False)
    expected_output = db.Column(db.Text, nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)
    weight = db.Column(db.Float, default=1.0)

    problem = db.relationship('Problem', back_populates='test_cases')
    test_results = db.relationship('TestResult', back_populates='test_case', lazy=True)

    def __repr__(self):
        return f'<TestCase problem_id={self.problem_id} hidden={self.is_hidden}>'

    def to_dict(self, include_expected=True):
        data = {
            'id': self.id,
            'problem_id': self.problem_id,
            'input': self.input,
            'is_hidden': self.is_hidden,
            'weight': self.weight
        }
        if include_expected:
            data['expected_output'] = self.expected_output
        return data
