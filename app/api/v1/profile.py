# app/api/v1/profile.py
"""User Profile Management API Routes"""
from flask_smorest import Blueprint, abort
from flask import g
from app.auth import require_auth
from app.services.profile_service import ProfileService
from marshmallow import Schema, fields

bp = Blueprint("profile", __name__, description="Profile Management APIs", url_prefix="/api/v1/profile")


# Request/Response Schemas
class UpdateEmailIn(Schema):
    email = fields.Email(required=True, metadata={"description": "New email address"})


class UpdateUsernameIn(Schema):
    new_username = fields.Str(
        required=True, 
        validate=lambda x: 3 <= len(x) <= 64,
        metadata={"description": "New username (3-64 characters)"}
    )
    password = fields.Str(
        required=True,
        metadata={"description": "Current password for verification"}
    )


class UpdatePasswordIn(Schema):
    current_password = fields.Str(
        required=True,
        metadata={"description": "Current password"}
    )
    new_password = fields.Str(
        required=True,
        validate=lambda x: 6 <= len(x) <= 128,
        metadata={"description": "New password (6-128 characters)"}
    )


class MessageOut(Schema):
    message = fields.Str()


@bp.put("/email")
@bp.arguments(UpdateEmailIn)
@bp.response(200, MessageOut)
@require_auth
def update_email(payload):
    """
    Update user email address
    
    Requires authentication.
    
    Request Body:
        - email: New email address (must be valid and not already registered)
    
    Returns:
        - 200: Email updated successfully
        - 400: Email already registered / Invalid email format
        - 401: Unauthorized
    """
    current_user = g.current_user
    new_email = payload["email"]
    
    ProfileService.update_email(current_user, new_email)
    
    return {"message": "Email updated successfully"}


@bp.put("/username")
@bp.arguments(UpdateUsernameIn)
@bp.response(200, MessageOut)
@require_auth
def update_username(payload):
    """
    Update username
    
    Requires authentication and current password verification.
    Note: After username change, user must log in again with new username.
    
    Request Body:
        - new_username: New username (3-64 characters, must be unique)
        - password: Current password for verification
    
    Returns:
        - 200: Username updated successfully
        - 400: Username already exists / Username same as current
        - 401: Unauthorized / Invalid password
    """
    current_user = g.current_user
    new_username = payload["new_username"]
    password = payload["password"]
    
    ProfileService.update_username(current_user, new_username, password)
    
    return {"message": "Username updated successfully. Please log in again."}


@bp.put("/password")
@bp.arguments(UpdatePasswordIn)
@bp.response(200, MessageOut)
@require_auth
def update_password(payload):
    """
    Update password
    
    Requires authentication and current password verification.
    Note: After password change, user must log in again.
    
    Request Body:
        - current_password: Current password for verification
        - new_password: New password (6-128 characters)
    
    Returns:
        - 200: Password updated successfully
        - 401: Unauthorized / Invalid current password
    """
    current_user = g.current_user
    current_password = payload["current_password"]
    new_password = payload["new_password"]
    
    ProfileService.update_password(current_user, current_password, new_password)
    
    return {"message": "Password updated successfully. Please log in again."}
