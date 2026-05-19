# app/models/question.py
from app.core.extensions import db
from datetime import datetime

class Question(db.Model):
    """Question model"""
    __tablename__ = 'questions'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    starter_code = db.Column(db.Text)  # Initial code template
    solution = db.Column(db.Text)  # Reference solution
    solution_explanation = db.Column(db.Text)
    points = db.Column(db.Integer, default=10)
    order = db.Column(db.Integer, default=0)
    programming_language = db.Column(db.String(20), default='python')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Many-to-many relationship through association table
    quiz_associations = db.relationship('QuizQuestion', 
                                       back_populates='question',
                                       lazy=True,
                                       cascade='all, delete-orphan')
    
    test_cases = db.relationship('TestCase', back_populates='question', lazy=True, 
                                cascade='all, delete-orphan')
    submissions = db.relationship('Submission', back_populates='question', lazy=True)
    
    def __repr__(self):
        return f'<Question {self.title}>'
    
    def to_dict(self, include_solution=False):
        """Convert to dictionary"""
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'starter_code': self.starter_code,
            'points': self.points,
            'order': self.order,
            'programming_language': self.programming_language,
            'created_at': self.created_at,
        }
        if include_solution:
            data['solution'] = self.solution
            data['solution_explanation'] = self.solution_explanation
        return data


class TestCase(db.Model):
    """Test case model"""
    __tablename__ = 'test_cases'
    
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    input = db.Column(db.Text, nullable=False)
    expected_output = db.Column(db.Text, nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)  # Whether it's a hidden test case
    weight = db.Column(db.Float, default=1.0)  # Weight
    
    # Relationships - using back_populates
    question = db.relationship('Question', back_populates='test_cases')
    test_results = db.relationship('TestResult', back_populates='test_case', lazy=True)
    
    def __repr__(self):
        return f'<TestCase question_id={self.question_id} hidden={self.is_hidden}>'
    
    def to_dict(self, include_expected=True):
        """Convert to dictionary"""
        data = {
            'id': self.id,
            'question_id': self.question_id,
            'input': self.input,
            'is_hidden': self.is_hidden,
            'weight': self.weight
        }
        # Only teachers or grading systems can see expected output
        if include_expected:
            data['expected_output'] = self.expected_output
        return data
