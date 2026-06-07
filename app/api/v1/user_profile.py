# app/api/v1/user_profile.py
"""
User Profile API
User personal information management endpoints
"""
import logging
from flask import g
from flask_smorest import Blueprint, abort
from sqlalchemy import select

from app.auth import require_auth
from app.core.extensions import db
from domain.models.user import User
from app.auth.utils import hash_password, verify_password

from app.schemas.user_profile_schema import (
    UserProfileOut, UpdateProfileIn, UpdateUsernameIn, MessageOut, UpdatePasswordIn
)

# Setup logger
logger = logging.getLogger(__name__)

# Blueprint
blp = Blueprint(
    "user_profile",
    __name__,
    description="User Profile APIs",
    url_prefix="/api/v1/profile"
)


@blp.get("/me")
@blp.response(200, UserProfileOut)
@require_auth
def get_my_profile():
    """
    Get current user's personal information
    """
    current_user = g.current_user
    # Return User object directly, let Marshmallow handle serialization
    # This properly handles datetime objects
    return current_user


@blp.put("/email")
@blp.arguments(UpdateProfileIn)
@blp.response(200, UserProfileOut)
@require_auth
def update_email(payload):
    """
    Update email address
    
    Request Body:
    - email: New email address
    """
    current_user = g.current_user
    new_email = payload.get('email')
    
    if not new_email:
        abort(400, message="Email is required")
    
    # Check if email is already in use
    existing_user = db.session.execute(
        select(User).where(
            User.email == new_email,
            User.id != current_user.id,
        )
    ).scalar_one_or_none()
    
    if existing_user:
        abort(400, message="Email already in use")
    
    # Update email
    current_user.email = new_email
    db.session.commit()
    
    logger.info(f"User {current_user.id} updated email")
    
    # Return object directly instead of to_dict()
    return current_user


@blp.put("/username")
@blp.arguments(UpdateUsernameIn)
@blp.response(200, UserProfileOut)
@require_auth
def update_username(payload):
    """
    Update username (requires password verification)
    
    Request Body:
    - new_username: New username
    - password: Current password (for verification)
    """
    current_user = g.current_user
    new_username = payload.get('new_username')
    password = payload.get('password')
    
    # Verify current password
    if not verify_password(password, current_user.password):
        logger.warning(f"Failed password verification for user {current_user.id} during username update")
        abort(400, message="Current password is incorrect")
    
    # Check if username is already taken
    existing_user = db.session.execute(
        select(User).where(
            User.username == new_username,
            User.id != current_user.id,
        )
    ).scalar_one_or_none()
    
    if existing_user:
        abort(400, message="Username already taken")
    
    # Update username
    old_username = current_user.username
    current_user.username = new_username
    db.session.commit()
    
    logger.info(f"User {current_user.id} updated username from '{old_username}' to '{new_username}'")
    
    # Return object directly instead of to_dict()
    return current_user


@blp.put("/password")
@blp.arguments(UpdatePasswordIn)
@blp.response(200, MessageOut)
@require_auth
def update_password(payload):
    """
    Update password
    
    Request Body:
    - current_password: Current password
    - new_password: New password
    """
    current_user = g.current_user
    current_password = payload.get('current_password')
    new_password = payload.get('new_password')
    
    # Verify current password
    if not verify_password(current_password, current_user.password):
        logger.warning(f"Failed password verification for user {current_user.id} during password update")
        abort(400, message="Current password is incorrect")
    
    # Check new password is different from current password
    if verify_password(new_password, current_user.password):
        abort(400, message="New password must be different from current password")
    
    # Update password
    current_user.password = hash_password(new_password)
    db.session.commit()
    
    logger.info(f"User {current_user.id} successfully updated password")
    
    return {"message": "Password updated successfully"}
