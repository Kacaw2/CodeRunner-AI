# app/schemas/teacher_stats_schema.py
"""
Teacher Statistics API
API endpoints for teacher statistics data
"""
from flask import request
from flask_smorest import Blueprint, abort

from app.auth import require_auth
from app.services.teacher_stats_service import TeacherStatsService
from marshmallow import Schema, fields


# Schema definitions
class TeacherStatsOut(Schema):
    """Teacher statistics output"""
    questions_count = fields.Int()
    classrooms_count = fields.Int()
    students_count = fields.Int()
    submissions_count = fields.Int()


class SubmissionItem(Schema):
    """Submission record item"""
    id = fields.Int()
    student_name = fields.Str()
    student_id = fields.Int()
    question_title = fields.Str()
    question_id = fields.Int()
    status = fields.Str()
    score = fields.Int(allow_none=True)
    submitted_at = fields.Str(allow_none=True)


class RecentSubmissionsOut(Schema):
    """Recent submissions list"""
    items = fields.List(fields.Nested(SubmissionItem))
    total = fields.Int()


class StudentItem(Schema):
    """Student item"""
    id = fields.Int()
    username = fields.Str()
    email = fields.Str()
    classroom_count = fields.Int()


class StudentsListOut(Schema):
    """Students list"""
    items = fields.List(fields.Nested(StudentItem))
    total = fields.Int()
