# app/models/classroom.py
"""Classroom and enrollment related models"""
from app.core.extensions import db
from app.core.timezone import now_china


class Classroom(db.Model):
    """Classroom model"""
    __tablename__ = 'classrooms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False)  # Invitation code
    description = db.Column(db.Text)
    
    # Teacher ID
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=now_china)
    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)
    
    # Relationships - Fixed: using back_populates instead of backref
    teacher = db.relationship('User', back_populates='taught_classrooms')
    enrollments = db.relationship('Enrollment', 
                                 back_populates='classroom',
                                 cascade='all, delete-orphan')
    
    # Quiz relationships 
    quiz_assignments = db.relationship('ClassroomQuiz',
                                      back_populates='classroom',
                                      cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Classroom {self.id}: {self.name}>'


class Enrollment(db.Model):
    """Student enrollment model (Student-Classroom association)"""
    __tablename__ = 'enrollments'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'), nullable=False)
    
    # Enrollment time
    enrolled_at = db.Column(db.DateTime, default=now_china)
    
    # Relationships - Fixed: using back_populates instead of backref
    student = db.relationship('User', back_populates='enrollments')
    classroom = db.relationship('Classroom', back_populates='enrollments')
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('student_id', 'classroom_id', name='unique_student_classroom'),
    )
    
    def __repr__(self):
        return f'<Enrollment student={self.student_id} classroom={self.classroom_id}>'
