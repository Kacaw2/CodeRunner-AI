# app/models/quiz.py
"""Quiz related database models"""
from app.core.extensions import db
from app.core.timezone import now_china


class Quiz(db.Model):
    """Quiz model"""
    __tablename__ = 'quizzes'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    # Creator (teacher)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Time configuration
    duration_minutes = db.Column(db.Integer)  # Duration in minutes
    
    # Whether published (only published quizzes are visible to students)
    is_published = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=now_china)
    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)
    
    # Relationships - Fixed: using back_populates instead of backref
    creator = db.relationship('User', back_populates='created_quizzes')
    
    quiz_problems = db.relationship(
        'QuizProblem',
        back_populates='quiz',
        cascade='all, delete-orphan',
        order_by='QuizProblem.order'
    )
    
    classroom_assignments = db.relationship('ClassroomQuiz',
                                          back_populates='quiz',
                                          cascade='all, delete-orphan')
    attempts = db.relationship('QuizAttempt',
                              back_populates='quiz',
                              lazy=True)
    
    def __repr__(self):
        return f'<Quiz {self.id}: {self.title}>'
    
    @property
    def question_count(self):
        return len(self.quiz_problems)
    
    @property
    def total_points(self):
        return sum(qp.points for qp in self.quiz_problems)

    @property
    def quiz_questions(self):
        return self.quiz_problems


class QuizProblem(db.Model):
    """Association table for Quiz and Problem."""

    __tablename__ = 'quiz_problems'

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    points = db.Column(db.Integer, default=10)
    added_at = db.Column(db.DateTime, default=now_china)

    quiz = db.relationship('Quiz', back_populates='quiz_problems')
    problem = db.relationship('Problem', back_populates='quiz_associations')

    __table_args__ = (
        db.UniqueConstraint('quiz_id', 'problem_id', name='unique_quiz_problem'),
    )

    def __repr__(self):
        return f'<QuizProblem quiz={self.quiz_id} problem={self.problem_id} order={self.order}>'


QuizQuestion = QuizProblem


class ClassroomQuiz(db.Model):
    """Association table for Classroom and Quiz (quiz assignments)"""
    __tablename__ = 'classroom_quizzes'
    
    id = db.Column(db.Integer, primary_key=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    
    # Assignment time and due date
    assigned_at = db.Column(db.DateTime, default=now_china)
    due_date = db.Column(db.DateTime)  # Due date
    
    # Whether late submission is allowed
    allow_late_submission = db.Column(db.Boolean, default=False)
    
    # Assigner (usually the teacher)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships - Fixed: using back_populates instead of backref
    classroom = db.relationship('Classroom', back_populates='quiz_assignments')
    quiz = db.relationship('Quiz', back_populates='classroom_assignments')
    assigner = db.relationship('User', back_populates='assigned_classroom_quizzes')
    attempts = db.relationship('QuizAttempt',
                              back_populates='classroom_quiz',
                              lazy=True)
    
    # Unique constraint: same quiz cannot be assigned to the same classroom twice
    __table_args__ = (
        db.UniqueConstraint('classroom_id', 'quiz_id', name='unique_classroom_quiz'),
    )
    
    def __repr__(self):
        return f'<ClassroomQuiz classroom={self.classroom_id} quiz={self.quiz_id}>'
    
    @property
    def is_overdue(self):
        """Check if quiz is overdue"""
        if not self.due_date:
            return False
        return now_china() > self.due_date


class QuizAttempt(db.Model):
    """Student's quiz attempt record"""
    __tablename__ = 'quiz_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Associations
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    classroom_quiz_id = db.Column(db.Integer, db.ForeignKey('classroom_quizzes.id'))
    
    # Start and end times
    started_at = db.Column(db.DateTime, default=now_china)
    completed_at = db.Column(db.DateTime)
    
    # Status
    status = db.Column(db.String(20), default='in_progress')  # in_progress, completed, abandoned
    
    # Scores
    score = db.Column(db.Float)  # Total score
    max_score = db.Column(db.Float)  # Maximum score
    
    # Relationships - Fixed: using back_populates instead of backref
    quiz = db.relationship('Quiz', back_populates='attempts')
    student = db.relationship('User', back_populates='quiz_attempts')
    classroom_quiz = db.relationship('ClassroomQuiz', back_populates='attempts')
    
    def __repr__(self):
        return f'<QuizAttempt {self.id}: student={self.student_id} quiz={self.quiz_id}>'
    
    @property
    def percentage(self):
        """Calculate percentage score"""
        if self.max_score and self.max_score > 0:
            return (self.score / self.max_score) * 100
        return 0
    
    @property
    def duration_minutes(self):
        """Calculate duration in minutes"""
        if self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() / 60
        return None
