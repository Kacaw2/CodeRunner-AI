# app/models/__init__.py
"""
Database Model Module

All models are imported here for convenient use by other modules
"""

from .user import User, UserRole
from .classroom import Classroom, Enrollment
from .quiz import Quiz, QuizQuestion, ClassroomQuiz, QuizAttempt 
from .question import Question, TestCase
from .submission import Submission, TestResult

__all__ = [
    # User models
    'User',
    'UserRole',
    
    # Classroom models
    'Classroom',
    'Enrollment',
    
    # Quiz models
    'Quiz',
    'QuizQuestion',     
    'ClassroomQuiz',    
    'QuizAttempt', 
    
    # Question models
    'Question',
    'TestCase',
    
    # Submission models
    'Submission',
    'TestResult',
]
