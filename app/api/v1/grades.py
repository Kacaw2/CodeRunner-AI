# app/api/v1/grades.py
"""Grade Report API - Fixed Version"""
from datetime import datetime

from flask import g, request, make_response
from flask_smorest import Blueprint, abort
from sqlalchemy import func, case, and_, desc, select

import csv
import io

from app.auth import require_teacher
from app.core.extensions import db
from app.models.submission import Submission
from app.models.problem import Problem
from app.models.question import Question
from app.models.user import User, UserRole
from app.models.classroom import Classroom, Enrollment

blp = Blueprint(
    "grades",
    __name__,
    description="Grade Report APIs",
    url_prefix="/api/v1/grades"
)


def _get_teacher_student_ids(teacher_id):
    """Get IDs of students enrolled in this teacher's classrooms"""
    classroom_ids = db.session.query(Classroom.id).filter_by(teacher_id=teacher_id).subquery()
    student_ids = db.session.query(Enrollment.student_id).filter(
        Enrollment.classroom_id.in_(db.session.query(classroom_ids))
    ).distinct().subquery()
    return student_ids


@blp.get("/submissions")
@require_teacher
def get_all_submissions():
    """
    Get all student submission records
    Teachers can view all student submissions
    For each student-question combination, only show the last submission
    
    Query Parameters:
        - student_id: Filter by specific student
        - problem_id: Filter by specific problem
        - status: Filter by status (completed/error)
        - limit: Return limit (default 100)
        - offset: Offset (default 0)
    """
    current_user = g.current_user

    # Get query parameters
    student_id = request.args.get('student_id', type=int)
    question_id = request.args.get('question_id', type=int)
    problem_id = request.args.get('problem_id', type=int)
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    # Tenant isolation: only students in this teacher's classrooms
    teacher_student_ids = _get_teacher_student_ids(current_user.id)

    # Create subquery with window function
    ranked_submissions = (
        db.session.query(
            Submission.id,
            Submission.student_id,
            Submission.question_id,
            Submission.status,
            Submission.score,
            Submission.submitted_at,
            Question.problem_id,
            func.row_number().over(
                partition_by=[Submission.student_id, Question.problem_id],
                order_by=desc(Submission.id)
            ).label('rn')
        )
        .join(Question, Submission.question_id == Question.id)
        .join(User, Submission.student_id == User.id)
        .filter(User.role == UserRole.STUDENT)
        .filter(Submission.student_id.in_(db.session.query(teacher_student_ids)))
        .subquery()
    )
    
    # Build main query, only select records with rn = 1 (i.e., the latest submission)
    query = (
        db.session.query(
            ranked_submissions.c.id,
            ranked_submissions.c.student_id,
            User.username.label('student_name'),
            User.email.label('student_email'),
            ranked_submissions.c.problem_id,
            ranked_submissions.c.question_id,
            Question.programming_language.label('language'),
            Problem.title.label('question_title'),
            ranked_submissions.c.status,
            ranked_submissions.c.score,
            ranked_submissions.c.submitted_at
        )
        .join(User, ranked_submissions.c.student_id == User.id)
        .join(Question, ranked_submissions.c.question_id == Question.id)
        .join(Problem, ranked_submissions.c.problem_id == Problem.id)
        .filter(ranked_submissions.c.rn == 1)  # Only select the first in each group (latest)
        .order_by(desc(ranked_submissions.c.submitted_at))
    )
    
    # Apply filters
    if student_id:
        query = query.filter(ranked_submissions.c.student_id == student_id)
    if question_id:
        query = query.filter(ranked_submissions.c.question_id == question_id)
    if problem_id:
        variant_ids = select(Question.id).where(Question.problem_id == problem_id)
        query = query.filter(ranked_submissions.c.question_id.in_(variant_ids))
    if status:
        query = query.filter(ranked_submissions.c.status == status)
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    items = query.limit(limit).offset(offset).all()
    
    # Format results
    submissions = []
    for item in items:
        submissions.append({
            'id': item.id,
            'student_id': item.student_id,
            'student_name': item.student_name,
            'student_email': item.student_email,
            'problem_id': item.problem_id,
            'question_id': item.question_id,
            'question_title': item.question_title,
            'language': item.language,
            'status': item.status,
            'score': item.score,
            'submitted_at': item.submitted_at.isoformat() if item.submitted_at else None
        })
    
    return {
        'items': submissions,
        'total': total,
        'limit': limit,
        'offset': offset
    }


@blp.get("/students/summary")
@require_teacher
def get_students_summary():
    """
    Get student grade summary
    Group by student, calculate total submissions, average score, etc. for each student
    For each student-question combination, only count the last submission
    """
    current_user = g.current_user
    teacher_student_ids = _get_teacher_student_ids(current_user.id)

    # Create subquery with window function to mark latest submissions, only select rn=1 records
    latest_submissions_only = (
        db.session.query(
            Submission.id,
            Submission.student_id,
            Submission.question_id,
            Submission.status,
            Submission.score,
            func.row_number().over(
                partition_by=[Submission.student_id, Submission.question_id],
                order_by=desc(Submission.id)
            ).label('rn')
        )
        .join(User, Submission.student_id == User.id)
        .filter(User.role == UserRole.STUDENT)
        .filter(Submission.student_id.in_(db.session.query(teacher_student_ids)))
    ).subquery()
    
    # Create another subquery that only includes rn=1 records
    latest_only = (
        db.session.query(
            latest_submissions_only.c.id,
            latest_submissions_only.c.student_id,
            latest_submissions_only.c.question_id,
            latest_submissions_only.c.status,
            latest_submissions_only.c.score
        )
        .filter(latest_submissions_only.c.rn == 1)
        .subquery()
    )
    
    # Get statistics for latest submissions
    results = (
        db.session.query(
            User.id.label('student_id'),
            User.username.label('student_name'),
            User.email.label('student_email'),
            func.count(latest_only.c.id).label('total_submissions'),
            func.avg(latest_only.c.score).label('average_score'),
            func.max(latest_only.c.score).label('highest_score'),
            func.min(latest_only.c.score).label('lowest_score'),
            func.sum(
                case(
                    (latest_only.c.status == 'completed', 1),
                    else_=0
                )
            ).label('completed_count')
        )
        .join(latest_only, User.id == latest_only.c.student_id)
        .filter(User.role == UserRole.STUDENT)
        .group_by(User.id, User.username, User.email)
        .order_by(desc(func.avg(latest_only.c.score)))
        .all()
    )
    
    students = []
    for row in results:
        students.append({
            'student_id': row.student_id,
            'student_name': row.student_name,
            'student_email': row.student_email,
            'total_submissions': row.total_submissions,
            'average_score': round(float(row.average_score), 2) if row.average_score else 0,
            'highest_score': float(row.highest_score) if row.highest_score else 0,
            'lowest_score': float(row.lowest_score) if row.lowest_score else 0,
            'completed_count': int(row.completed_count) if row.completed_count else 0
        })
    
    return {'items': students, 'total': len(students)}


@blp.get("/export/csv")
@require_teacher
def export_csv():
    """
    Export grade report as CSV file
    For each student-question combination, only export the last submission
    """
    current_user = g.current_user
    teacher_student_ids = _get_teacher_student_ids(current_user.id)

    # Create subquery with window function
    ranked_submissions = (
        db.session.query(
            Submission.id,
            Submission.student_id,
            Submission.question_id,
            Submission.status,
            Submission.score,
            Submission.submitted_at,
            Question.problem_id,
            func.row_number().over(
                partition_by=[Submission.student_id, Question.problem_id],
                order_by=desc(Submission.id)
            ).label('rn')
        )
        .join(Question, Submission.question_id == Question.id)
        .join(User, Submission.student_id == User.id)
        .filter(User.role == UserRole.STUDENT)
        .filter(Submission.student_id.in_(db.session.query(teacher_student_ids)))
        .subquery()
    )
    
    # Get all latest submission records
    submissions = (
        db.session.query(
            ranked_submissions.c.id,
            User.username,
            User.email,
            Problem.title,
            ranked_submissions.c.status,
            ranked_submissions.c.score,
            ranked_submissions.c.submitted_at
        )
        .join(User, ranked_submissions.c.student_id == User.id)
        .join(Question, ranked_submissions.c.question_id == Question.id)
        .join(Problem, ranked_submissions.c.problem_id == Problem.id)
        .filter(ranked_submissions.c.rn == 1)
        .order_by(User.username, desc(ranked_submissions.c.submitted_at))
        .all()
    )
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Submission ID',
        'Student Username',
        'Student Email',
        'Question Title',
        'Status',
        'Score',
        'Submitted At'
    ])
    
    # Write data
    for sub in submissions:
        writer.writerow([
            sub.id,
            sub.username,
            sub.email,
            sub.title,
            sub.status,
            sub.score if sub.score is not None else 'N/A',
            sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if sub.submitted_at else 'N/A'
        ])
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=grade_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response
