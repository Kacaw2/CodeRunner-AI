# app/models/user.py
from app.core.extensions import db
from app.core.timezone import now_china
from enum import Enum

class UserRole(Enum):
    """User role enumeration"""
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"

class User(db.Model):
    """User model"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    role = db.Column(db.Enum(UserRole), default=UserRole.STUDENT, nullable=False)
    created_at = db.Column(db.DateTime, default=now_china)
    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)
    
    # Relationships - using back_populates instead of backref
    # Classrooms taught by teacher
    taught_classrooms = db.relationship(
        'Classroom', 
        back_populates='teacher',
        foreign_keys='Classroom.teacher_id',
        lazy=True
    )
    
    # Student's enrollment records
    enrollments = db.relationship(
        'Enrollment', 
        back_populates='student',
        lazy=True,
        cascade='all, delete-orphan'
    )
    
    # Student's submission records
    submissions = db.relationship(
        'Submission', 
        back_populates='student',
        lazy=True
    )
    
    # Quizzes created by teacher
    created_quizzes = db.relationship(
        'Quiz',
        back_populates='creator',
        lazy=True
    )
    
    # Quizzes assigned by teacher (as assigner)
    assigned_classroom_quizzes = db.relationship(
        'ClassroomQuiz',
        back_populates='assigner',
        lazy=True
    )
    
    # Student's quiz attempt records
    quiz_attempts = db.relationship(
        'QuizAttempt',
        back_populates='student',
        lazy=True
    )
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def to_dict(self):
        """Convert to dictionary"""
        def format_datetime(dt):
            """Safely format datetime object"""
            if dt is None:
                return None
            # If it's a datetime object, convert to ISO format
            if isinstance(dt, datetime):
                return dt.isoformat()
            # If it's already a string, return as is
            return str(dt)
        
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role.value if isinstance(self.role, UserRole) else self.role,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
