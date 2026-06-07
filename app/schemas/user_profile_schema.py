# app/schemas/user_profile_schema.py
from flask import g
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields, validate, ValidationError

from app.auth import require_auth
from app.core.extensions import db
from domain.models.user import User
from app.auth.utils import hash_password, verify_password
class UserProfileOut(Schema):
    """user info output"""
    id = fields.Int()
    username = fields.Str()
    email = fields.Str()
    role = fields.Str()
    created_at = fields.DateTime()


class UpdateProfileIn(Schema):
    """update personal info input"""
    email = fields.Str(validate=validate.Email(), allow_none=True)


class UpdateUsernameIn(Schema):
    """update username input"""
    new_username = fields.Str(required=True, validate=validate.Length(min=3, max=80))
    password = fields.Str(required=True)  # need to validate curruent pwd


class UpdatePasswordIn(Schema):
    """update password input"""
    current_password = fields.Str(required=True)
    new_password = fields.Str(required=True, validate=validate.Length(min=6, max=100))


class MessageOut(Schema):
    """info output"""
    message = fields.Str()
