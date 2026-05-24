# app/web/teacher.py
from flask import Blueprint, render_template, redirect, url_for
from app.auth import web_teacher_required

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')


@teacher_bp.get('/')
@web_teacher_required
def teacher_redirect():
    """redirect to teacher profile"""
    return redirect(url_for('teacher.profile'))


@teacher_bp.get('/profile')
@web_teacher_required
def profile():
    """teacher profile"""
    return render_template('teacher/teacher_profile.html', page='teacher-profile')

@teacher_bp.get('/quizzes')
@web_teacher_required
def quizzes():
    """teachers' Quiz manage page"""
    return render_template('teacher/quizzes.html', page='quizzes')

@teacher_bp.get('/questions/create')
@web_teacher_required
def questions_create():
    """create and manage question page"""
    return render_template('teacher/teacher_questions_create.html', page='questions')


@teacher_bp.get('/classrooms')
@web_teacher_required
def classrooms():
    """classroom management page"""
    return render_template('teacher/classrooms.html', page='classrooms')


@teacher_bp.get('/students')
@web_teacher_required
def students():
    """教师的学生管理页面teacher's student management page"""
    return render_template('teacher/teacher_students.html', page='students')

@teacher_bp.get('/students/<int:student_id>')
@web_teacher_required
def student_detail(student_id):
    """check specific student's detail page"""
    return render_template(
        'teacher/teacher_student_detail.html',
        page='students',
        student_id=student_id
    )


@teacher_bp.get('/submissions')
@web_teacher_required
def submissions():
    """check all submissions"""
    return render_template('teacher/teacher_submissions.html', page='submissions')

@teacher_bp.get('/knowledge')
@web_teacher_required
def knowledge():
    """knowledge base management page"""
    return render_template('teacher/knowledge_manage.html', page='knowledge')


@teacher_bp.get('/grades')
@web_teacher_required
def grades():
    """student grades report"""
    return render_template('teacher/grades.html', page='grades')

@teacher_bp.get('/questions/<int:question_id>/manage')
@web_teacher_required
def question_manage(question_id):
    """Compatibility redirect from variant management to parent problem management."""
    from app.models.question import Question

    question = Question.query.get(question_id)
    if question and question.problem_id:
        return redirect(url_for('teacher.problem_manage', problem_id=question.problem_id))
    return redirect(url_for('teacher.questions_create'))


@teacher_bp.get('/problems/<int:problem_id>/manage')
@web_teacher_required
def problem_manage(problem_id):
    """manage single problem and shared test cases"""
    return render_template(
        'teacher/teacher_questions_manage.html',
        page='questions',
        problem_id=problem_id
    )
