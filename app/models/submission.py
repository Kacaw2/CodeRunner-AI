# app/models/submission.py
from app.core.extensions import db
from datetime import datetime

class Submission(db.Model):
    """Submission record model"""
    __tablename__ = 'submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    code = db.Column(db.Text, nullable=False)
    score = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, error
    error_message = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    execution_time = db.Column(db.Float)  # Execution time in seconds
    memory_used = db.Column(db.Integer)  # Memory usage in KB
    
    # Relationships - using back_populates
    student = db.relationship('User', back_populates='submissions')
    question = db.relationship('Question', back_populates='submissions')
    test_results = db.relationship('TestResult', back_populates='submission', lazy=True, 
                                  cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Submission id={self.id} student={self.student_id} question={self.question_id}>'
    
    def to_dict(self, include_code=True):
        """Convert to dictionary"""
        data = {
            'id': self.id,
            'student_id': self.student_id,
            'question_id': self.question_id,
            'score': self.score,
            'status': self.status,
            'error_message': self.error_message,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'execution_time': self.execution_time,
            'memory_used': self.memory_used
        }
        if include_code:
            data['code'] = self.code
        return data
    
    @property
    def is_completed(self):
        """Check if submission is completed"""
        return self.status == 'completed'
    
    @property
    def is_error(self):
        """Check if submission has errors"""
        return self.status == 'error'


class TestResult(db.Model):
    """Test result model"""
    __tablename__ = 'test_results'
    
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_cases.id'), nullable=False)
    passed = db.Column(db.Boolean, default=False)
    actual_output = db.Column(db.Text)
    error_message = db.Column(db.Text)
    execution_time = db.Column(db.Float)
    
    # Relationships - using back_populates
    submission = db.relationship('Submission', back_populates='test_results')
    test_case = db.relationship('TestCase', back_populates='test_results')
    
    def __repr__(self):
        return f'<TestResult submission={self.submission_id} test_case={self.test_case_id} passed={self.passed}>'
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'submission_id': self.submission_id,
            'test_case_id': self.test_case_id,
            'passed': self.passed,
            'actual_output': self.actual_output,
            'error_message': self.error_message,
            'execution_time': self.execution_time
        }
