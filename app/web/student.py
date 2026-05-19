# app/web/student.py
from flask import Blueprint, render_template, redirect, url_for
from app.auth import web_student_required  # Web decorater

student_bp = Blueprint('student', __name__, url_prefix='/student')


@student_bp.get('/')
@web_student_required
def student_redirect():
    """redirect to profile"""
    return redirect(url_for('student.profile'))


@student_bp.get('/profile')
@web_student_required
def profile():
    """student info profile"""
    return render_template('student/student_profile.html', page='student-profile')

@student_bp.route('/quizzes')
@web_student_required
def quizzes():
    """student Quiz list"""
    return render_template('student/student_quizzes.html')
