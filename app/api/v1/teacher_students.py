# app/api/v1/teacher_students.py
"""
API endpoints for teachers to view student information
"""
from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from app.core.extensions import db
from domain.models.user import User
from app.models.submission import Submission
from app.models.classroom import Enrollment
from app.auth import require_teacher

# Create blueprint
blp = Blueprint(
    'teacher_students',
    __name__,
    url_prefix='/api/v1/teacher/students',
    description='Teacher student management endpoints'
)


def check_teacher_permission():
    """Check if current user has teacher role"""
    user = g.current_user
    if not user:
        abort(401, message="Authentication required")
    
    user_role = user.role.value if hasattr(user.role, 'value') else user.role
    if user_role not in ['teacher', 'admin']:
        abort(403, message="Access denied. Teacher role required.")
    
    return user


@blp.route('/<int:student_id>')
class TeacherStudentDetail(MethodView):
    """Get detailed information for a single student"""
    
    @require_teacher 
    def get(self, student_id):
        """
        Get student detailed information
        ---
        Requires teacher permission
        """
        check_teacher_permission()
        
        # Query student information
        student = db.session.get(User, student_id)
        if not student:
            abort(404, message="Student not found")
        
        student_role = student.role.value if hasattr(student.role, 'value') else student.role
        if student_role != 'student':
            abort(404, message="Student not found")
        
        # Get count of classrooms the student is enrolled in
        classroom_count = db.session.query(func.count(Enrollment.id))\
            .filter(Enrollment.student_id == student_id)\
            .scalar() or 0
        
        return {
            'id': student.id,
            'username': student.username,
            'email': student.email,
            'role': student_role,
            'created_at': student.created_at.isoformat() if student.created_at else None,
            'classroom_count': classroom_count
        }


@blp.route('/<int:student_id>/submissions')
class TeacherStudentSubmissions(MethodView):
    """Get student's submission records"""
    
    @require_teacher
    def get(self, student_id):
        """
        Get submission records for specified student
        ---
        Requires teacher permission
        Query Parameters:
        - limit: Number of records to return (default: 20)
        - offset: Offset for pagination (default: 0)
        """
        from flask import request
        
        check_teacher_permission()
        
        # Verify student exists
        student = db.session.get(User, student_id)
        if not student:
            abort(404, message="Student not found")
        
        student_role = student.role.value if hasattr(student.role, 'value') else student.role
        if student_role != 'student':
            abort(404, message="Student not found")
        
        # Get query parameters
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Query student's submission records
        query = db.session.query(Submission)\
            .filter(Submission.student_id == student_id)\
            .order_by(Submission.submitted_at.desc())
        
        total = query.count()
        submissions = query.limit(limit).offset(offset).all()
        
        # Build response data
        items = []
        for sub in submissions:
            # Get question title
            question_title = None
            if sub.question:
                question_title = sub.question.title
            
            items.append({
                'id': sub.id,
                'question_id': sub.question_id,
                'question_title': question_title,
                'status': sub.status,
                'score': sub.score,
                'submitted_at': sub.submitted_at.isoformat() if sub.submitted_at else None,
                'time_ms': getattr(sub, 'time_ms', None),
                'elapsed_ms': getattr(sub, 'elapsed_ms', None)
            })
        
        return {
            'items': items,
            'total': total,
            'limit': limit,
            'offset': offset
        }


@blp.route('')
class TeacherStudentsList(MethodView):
    """Get list of all students for the teacher"""
    
    @require_teacher 
    def get(self):
        """
        Get teacher's student list
        ---
        Query Parameters:
        - limit: Number of records to return (default: 50)
        - offset: Offset for pagination (default: 0)
        """
        from flask import request
        
        teacher = check_teacher_permission()
        
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Get list of all classroom IDs for this teacher
        teacher_classroom_ids = [c.id for c in teacher.taught_classrooms]
        
        if not teacher_classroom_ids:
            return {
                'items': [],
                'total': 0,
                'limit': limit,
                'offset': offset
            }
        
        # Query students in teacher's classrooms through Enrollment
        # Fixed: Handle role comparison properly for both enum and string types
        from domain.models.user import UserRole
        
        students_query = db.session.query(User)\
            .join(Enrollment, Enrollment.student_id == User.id)\
            .filter(Enrollment.classroom_id.in_(teacher_classroom_ids))\
            .filter(User.role == UserRole.STUDENT)\
            .distinct()\
            .order_by(User.username)
        
        total = students_query.count()
        students = students_query.limit(limit).offset(offset).all()
        
        # Build response data
        items = []
        for student in students:
            # Get student's classroom count
            classroom_count = db.session.query(func.count(Enrollment.id))\
                .filter(Enrollment.student_id == student.id)\
                .scalar() or 0
            
            student_role = student.role.value if hasattr(student.role, 'value') else student.role
            
            items.append({
                'id': student.id,
                'username': student.username,
                'email': student.email,
                'role': student_role,
                'classroom_count': classroom_count
            })
        
        return {
            'items': items,
            'total': total,
            'limit': limit,
            'offset': offset
        }
