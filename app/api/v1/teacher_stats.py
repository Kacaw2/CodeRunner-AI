# app/api/v1/teacher_stats.py
"""
Teacher Statistics API
API endpoints for teacher statistics data
"""
from flask import request, g
from flask_smorest import Blueprint, abort

from app.auth import require_auth
from app.services.teacher_stats_service import TeacherStatsService
from marshmallow import Schema, fields
from app.schemas.teacher_stats_schema import (
    TeacherStatsOut, RecentSubmissionsOut,
    StudentsListOut,
)

# Blueprint
blp = Blueprint(
    "teacher_stats",
    __name__,
    description="Teacher Statistics APIs",
    url_prefix="/api/v1/teacher"
)


@blp.get("/stats")
@blp.response(200, TeacherStatsOut)
@require_auth
def get_teacher_stats():
    """
    Get all statistics for the current teacher
    
    Returns:
    - questions_count: Number of published questions
    - classrooms_count: Number of active classrooms
    - students_count: Total number of students
    - submissions_count: Total number of submissions
    """
    current_user = g.current_user
    
    # Use role.value to get the string value
    if current_user.role.value.lower() not in ['teacher', 'admin']:
        abort(403, message="Only teachers can access statistics")
    
    stats = TeacherStatsService.get_teacher_stats(current_user.id)
    return stats


@blp.get("/submissions/recent")
@blp.response(200, RecentSubmissionsOut)
@require_auth
def get_recent_submissions():
    """
    Get recent submission records for teacher's questions
    
    Query Parameters:
    - limit: Number of records to return (default: 10)
    """
    current_user = g.current_user
    
    # Use role.value to get the string value
    if current_user.role.value.lower() not in ['teacher', 'admin']:
        abort(403, message="Only teachers can access submissions")
    
    limit = request.args.get('limit', 10, type=int)
    limit = min(max(limit, 1), 50)  # Limit between 1-50
    
    items = TeacherStatsService.get_recent_submissions(current_user.id, limit=limit)
    
    return {
        "items": items,
        "total": len(items)
    }


@blp.get("/students")
@blp.response(200, StudentsListOut)
@require_auth
def get_students_list():
    """
    Get the teacher's student list
    
    Query Parameters:
    - limit: Number of records to return (default: 100)
    - offset: Offset for pagination (default: 0)
    """
    current_user = g.current_user
    
    # Use role.value to get the string value
    if current_user.role.value.lower() not in ['teacher', 'admin']:
        abort(403, message="Only teachers can access student list")
    
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    limit = min(max(limit, 1), 200)  # Limit between 1-200
    offset = max(offset, 0)
    
    result = TeacherStatsService.get_students_list(current_user.id, limit=limit, offset=offset)
    return result
