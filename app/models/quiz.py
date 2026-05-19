# app/models/quiz.py
"""Quiz related database models"""
from app.core.extensions import db
from datetime import datetime


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - Fixed: using back_populates instead of backref
    creator = db.relationship('User', back_populates='created_quizzes')
    
    # Many-to-many relationship through association table
    quiz_questions = db.relationship('QuizQuestion', 
                                    back_populates='quiz',
                                    cascade='all, delete-orphan',
                                    order_by='QuizQuestion.order')
    
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
        """Get question count"""
        return len(self.quiz_questions)
    
    @property
    def total_points(self):
        """Get total points"""
        return sum(qq.points for qq in self.quiz_questions)


class QuizQuestion(db.Model):
    """Association table for Quiz and Question (many-to-many with order and points)"""
    __tablename__ = 'quiz_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    
    # Order of question in quiz
    order = db.Column(db.Integer, nullable=False, default=0)
    
    # Points for this question in this quiz (can differ from question's default points)
    points = db.Column(db.Integer, default=10)
    
    # Timestamp
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - Fixed: using back_populates instead of backref
    quiz = db.relationship('Quiz', back_populates='quiz_questions')
    question = db.relationship('Question', back_populates='quiz_associations')
    
    # Unique constraint: same question cannot be added to the same quiz twice
    __table_args__ = (
        db.UniqueConstraint('quiz_id', 'question_id', name='unique_quiz_question'),
    )
    
    def __repr__(self):
        return f'<QuizQuestion quiz={self.quiz_id} question={self.question_id} order={self.order}>'


class ClassroomQuiz(db.Model):
    """Association table for Classroom and Quiz (quiz assignments)"""
    __tablename__ = 'classroom_quizzes'
    
    id = db.Column(db.Integer, primary_key=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    
    # Assignment time and due date
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
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
        return datetime.utcnow() > self.due_date


class QuizAttempt(db.Model):
    """Student's quiz attempt record"""
    __tablename__ = 'quiz_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Associations
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    classroom_quiz_id = db.Column(db.Integer, db.ForeignKey('classroom_quizzes.id'))
    
    # Start and end times
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
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
