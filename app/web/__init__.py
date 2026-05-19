# app/web/__init__.py
from .main import main_bp
from .auth import auth_bp
from .student import student_bp
from .teacher import teacher_bp

__all__ = ['main_bp', 'auth_bp', 'student_bp', 'teacher_bp']
