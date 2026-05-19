# app/schemas/user_schema.py
"""Data validation schemas related to users"""
from marshmallow import Schema, fields, validate

class RegisterIn(Schema):
    """User registration input schema"""
    username = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    password = fields.Str(required=True, validate=validate.Length(min=6, max=128))
    email = fields.Email(load_default=None)
    role = fields.Str(load_default="student")  # student/teacher

class UserOut(Schema):
    """User output schema"""
    id = fields.Int()
    username = fields.Str()
    email = fields.Email()
    role = fields.Str()

class LoginIn(Schema):
    """Login input schema"""
    username = fields.Str(required=True)
    password = fields.Str(required=True)

class LoginOut(Schema):
    """Login output schema"""
    token = fields.Str()
    user = fields.Nested(UserOut)

class RefreshOut(Schema):
    """Refresh token output schema"""
    token = fields.Str()
