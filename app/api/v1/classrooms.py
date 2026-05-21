# app/api/v1/classrooms.py
"""Classroom Management API - Adapted for Enrollment architecture"""
from flask import g, request
from flask_smorest import Blueprint, abort
from app.auth import require_teacher, require_auth
from app.core.extensions import db
from app.models.classroom import Classroom, Enrollment
from app.models.user import User
from app.schemas.classroom_schema import (
    ClassroomCreateSchema, 
    ClassroomUpdateSchema, 
    ClassroomSchema,
    ClassroomListSchema
)
from sqlalchemy import func
import random
import string

blp = Blueprint(
    "classrooms",
    __name__,
    description="Classroom Management APIs",
    url_prefix="/api/v1/classrooms"
)


def generate_classroom_code():
    """Generate a unique classroom invitation code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Classroom.query.filter_by(code=code).first():
            return code


@blp.get("/mine")
@require_teacher
def get_my_classrooms():
    """
    Get the current teacher's classroom list
    """
    current_user = g.current_user
    
    classrooms = Classroom.query.filter_by(teacher_id=current_user.id).all()
    
    items = []
    for classroom in classrooms:
        # Count number of students (through Enrollment)
        student_count = Enrollment.query.filter_by(classroom_id=classroom.id).count()
        
        items.append({
            'id': classroom.id,
            'name': classroom.name,
            'code': classroom.code,
            'description': classroom.description,
            'teacher_id': classroom.teacher_id,
            'created_at': classroom.created_at.isoformat() if classroom.created_at else None,
            'student_count': student_count
        })
    
    return {'items': items, 'total': len(items)}


@blp.post("")
@require_teacher
def create_classroom():
    """
    Create a new classroom
    
    Request Body:
        - name: Classroom name (required)
        - description: Classroom description (optional)
    """
    current_user = g.current_user
    data = request.get_json()
    
    name = data.get('name', '').strip()
    if not name:
        abort(400, message="Classroom name is required")
    
    # Generate unique invitation code
    code = generate_classroom_code()
    
    classroom = Classroom(
        name=name,
        code=code,
        description=data.get('description', ''),
        teacher_id=current_user.id
    )
    
    db.session.add(classroom)
    db.session.commit()
    
    return {
        'id': classroom.id,
        'name': classroom.name,
        'code': classroom.code,
        'description': classroom.description,
        'teacher_id': classroom.teacher_id,
        'created_at': classroom.created_at.isoformat() if classroom.created_at else None,
        'student_count': 0
    }, 201


@blp.get("/<int:classroom_id>")
@require_auth
def get_classroom(classroom_id):
    """
    Get classroom details
    Only the owning teacher or enrolled students can view.
    """
    current_user = g.current_user
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        abort(404, message="Classroom not found")

    # Ownership / enrollment check
    user_role = current_user.role.value if hasattr(current_user.role, 'value') else current_user.role
    if user_role in ('teacher', 'admin'):
        if user_role == 'teacher' and classroom.teacher_id != current_user.id:
            abort(403, message="You can only view your own classrooms")
    else:
        enrolled = Enrollment.query.filter_by(
            student_id=current_user.id, classroom_id=classroom.id
        ).first()
        if not enrolled:
            abort(403, message="You are not enrolled in this classroom")

    # Count number of students
    student_count = Enrollment.query.filter_by(classroom_id=classroom.id).count()

    # Only show invitation code to the owning teacher
    code = classroom.code if classroom.teacher_id == current_user.id else None

    return {
        'id': classroom.id,
        'name': classroom.name,
        'code': code,
        'description': classroom.description,
        'teacher_id': classroom.teacher_id,
        'created_at': classroom.created_at.isoformat() if classroom.created_at else None,
        'student_count': student_count
    }


@blp.put("/<int:classroom_id>")
@require_teacher
def update_classroom(classroom_id):
    """
    Update classroom information
    
    Request Body:
        - name: Classroom name
        - description: Classroom description
    """
    current_user = g.current_user
    classroom = Classroom.query.get(classroom_id)
    
    if not classroom:
        abort(404, message="Classroom not found")
    
    if classroom.teacher_id != current_user.id:
        abort(403, message="You can only edit your own classrooms")
    
    data = request.get_json()
    
    if 'name' in data:
        name = data['name'].strip()
        if not name:
            abort(400, message="Classroom name cannot be empty")
        classroom.name = name
    
    if 'description' in data:
        classroom.description = data['description']
    
    db.session.commit()
    
    return {
        'id': classroom.id,
        'name': classroom.name,
        'code': classroom.code,
        'description': classroom.description,
        'teacher_id': classroom.teacher_id
    }


@blp.delete("/<int:classroom_id>")
@require_teacher
def delete_classroom(classroom_id):
    """
    Delete a classroom
    """
    current_user = g.current_user
    classroom = Classroom.query.get(classroom_id)
    
    if not classroom:
        abort(404, message="Classroom not found")
    
    if classroom.teacher_id != current_user.id:
        abort(403, message="You can only delete your own classrooms")
    
    # Delete all enrollment records (cascade should handle this automatically)
    db.session.delete(classroom)
    db.session.commit()
    
    return {'message': 'Classroom deleted successfully'}


@blp.get("/<int:classroom_id>/students")
@require_teacher
def get_classroom_students(classroom_id):
    """
    Get the list of students in a classroom (teacher only, must own the classroom)
    """
    current_user = g.current_user
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        abort(404, message="Classroom not found")

    if classroom.teacher_id != current_user.id:
        abort(403, message="You can only view students in your own classrooms")

    # Get students through Enrollment
    enrollments = Enrollment.query.filter_by(classroom_id=classroom_id).all()
    
    items = []
    for enrollment in enrollments:
        student = User.query.get(enrollment.student_id)
        if student:
            # Count submissions for this student
            from app.models.submission import Submission
            submission_count = Submission.query.filter_by(student_id=student.id).count()
            
            items.append({
                'id': student.id,
                'username': student.username,
                'email': student.email,
                'enrolled_at': enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
                'submission_count': submission_count
            })
    
    return {'items': items, 'total': len(items)}


@blp.post("/<int:classroom_id>/students/<int:student_id>")
@require_teacher
def add_student_to_classroom(classroom_id, student_id):
    """
    Add a student to a classroom
    """
    current_user = g.current_user
    
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        abort(404, message="Classroom not found")
    
    if classroom.teacher_id != current_user.id:
        abort(403, message="You can only manage your own classrooms")
    
    student = User.query.get(student_id)
    if not student:
        abort(404, message="Student not found")
    
    if student.role.value != 'student':
        abort(400, message="User is not a student")
    
    # Check if already in the classroom
    existing = Enrollment.query.filter_by(
        student_id=student_id,
        classroom_id=classroom_id
    ).first()
    
    if existing:
        abort(400, message="Student is already in this classroom")
    
    # Create enrollment
    enrollment = Enrollment(
        student_id=student_id,
        classroom_id=classroom_id
    )
    
    db.session.add(enrollment)
    db.session.commit()
    
    return {'message': 'Student added to classroom successfully'}


@blp.delete("/<int:classroom_id>/students/<int:student_id>")
@require_teacher
def remove_student_from_classroom(classroom_id, student_id):
    """
    Remove a student from a classroom
    """
    current_user = g.current_user
    
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        abort(404, message="Classroom not found")
    
    if classroom.teacher_id != current_user.id:
        abort(403, message="You can only manage your own classrooms")
    
    # Find enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=student_id,
        classroom_id=classroom_id
    ).first()
    
    if not enrollment:
        abort(400, message="Student is not in this classroom")
    
    db.session.delete(enrollment)
    db.session.commit()
    
    return {'message': 'Student removed from classroom successfully'}


@blp.get("/all-students")
@require_teacher
def get_all_students():
    """
    Get students in this teacher's classrooms (for adding students to classroom)
    Includes information about which of this teacher's classrooms students are in
    """
    from app.models.user import UserRole

    current_user = g.current_user

    # Get this teacher's classroom IDs
    my_classroom_ids = [
        c.id for c in Classroom.query.filter_by(teacher_id=current_user.id).all()
    ]

    if not my_classroom_ids:
        return {'items': [], 'total': 0}

    # Get students enrolled in this teacher's classrooms
    enrolled_student_ids = db.session.query(Enrollment.student_id).filter(
        Enrollment.classroom_id.in_(my_classroom_ids)
    ).distinct().all()
    enrolled_student_ids = [sid for (sid,) in enrolled_student_ids]

    if not enrolled_student_ids:
        return {'items': [], 'total': 0}

    students = User.query.filter(
        User.id.in_(enrolled_student_ids),
        User.role == UserRole.STUDENT
    ).all()

    items = []
    for student in students:
        # Only show enrollments in this teacher's classrooms
        enrollments = Enrollment.query.filter(
            Enrollment.student_id == student.id,
            Enrollment.classroom_id.in_(my_classroom_ids)
        ).all()
        classrooms = []

        for enrollment in enrollments:
            classroom = Classroom.query.get(enrollment.classroom_id)
            if classroom:
                classrooms.append({
                    'id': classroom.id,
                    'name': classroom.name
                })

        items.append({
            'id': student.id,
            'username': student.username,
            'email': student.email,
            'classrooms': classrooms,
            'classroom_count': len(classrooms),
            'created_at': student.created_at.isoformat() if student.created_at else None
        })

    return {'items': items, 'total': len(items)}


@blp.post("/join")
@require_auth
def join_classroom_by_code():
    """
    Student joins a classroom using invitation code
    
    Request Body:
        - code: Classroom invitation code
    """
    current_user = g.current_user
    
    if current_user.role.value != 'student':
        abort(403, message="Only students can join classrooms")
    
    data = request.get_json()
    code = data.get('code', '').strip().upper()
    
    if not code:
        abort(400, message="Classroom code is required")
    
    # Find classroom
    classroom = Classroom.query.filter_by(code=code).first()
    if not classroom:
        abort(404, message="Invalid classroom code")
    
    # Check if already in the classroom
    existing = Enrollment.query.filter_by(
        student_id=current_user.id,
        classroom_id=classroom.id
    ).first()
    
    if existing:
        abort(400, message="You are already in this classroom")
    
    # Create enrollment
    enrollment = Enrollment(
        student_id=current_user.id,
        classroom_id=classroom.id
    )
    
    db.session.add(enrollment)
    db.session.commit()
    
    return {
        'message': 'Successfully joined classroom',
        'classroom': {
            'id': classroom.id,
            'name': classroom.name,
            'description': classroom.description
        }
    }


@blp.get("/my-enrollments")
@require_auth
def get_my_enrollments():
    """
    Get all classrooms the current student has joined
    """
    current_user = g.current_user
    
    if current_user.role.value != 'student':
        abort(403, message="Only students can view enrollments")
    
    enrollments = Enrollment.query.filter_by(student_id=current_user.id).all()
    
    items = []
    for enrollment in enrollments:
        classroom = Classroom.query.get(enrollment.classroom_id)
        if classroom:
            teacher = User.query.get(classroom.teacher_id)
            
            items.append({
                'id': enrollment.id,
                'classroom_id': classroom.id,
                'classroom_name': classroom.name,
                'classroom_code': classroom.code,
                'classroom_description': classroom.description,
                'teacher_name': teacher.username if teacher else None,
                'enrolled_at': enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None
            })
    
    return {'items': items, 'total': len(items)}


@blp.delete("/enrollments/<int:enrollment_id>")
@require_auth
def leave_classroom(enrollment_id):
    """
    Student leaves a classroom
    """
    current_user = g.current_user
    
    enrollment = Enrollment.query.get(enrollment_id)
    if not enrollment:
        abort(404, message="Enrollment not found")
    
    if enrollment.student_id != current_user.id:
        abort(403, message="You can only leave your own enrollments")
    
    db.session.delete(enrollment)
    db.session.commit()
    
    return {'message': 'Successfully left classroom'}
