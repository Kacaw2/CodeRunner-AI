# app/auth/utils.py
"""Authentication utility functions"""
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from datetime import timedelta
from flask import current_app
from app.core.timezone import aware_now_china


def hash_password(password):
    """
    Hash a password using Werkzeug's security functions
    
    Args:
        password (str): Plain text password
        
    Returns:
        str: Hashed password
    """
    return generate_password_hash(password)


def verify_password(password, password_hash):
    """
    Verify a password against its hash
    
    Args:
        password (str): Plain text password to verify
        password_hash (str): Hashed password to compare against
        
    Returns:
        bool: True if password matches, False otherwise
    """
    return check_password_hash(password_hash, password)


def generate_auth_token(user, expires_in=3600):
    """
    Generate JWT authentication token
    
    Args:
        user: User object
        expires_in (int): Token expiration time in seconds (default: 3600 = 1 hour)
        
    Returns:
        str: JWT token
    """
    now = aware_now_china()
    payload = {
        'user_id': user.id,
        'username': user.username,
        'role': user.role.value if hasattr(user.role, 'value') else user.role,
        'exp': now + timedelta(seconds=expires_in),
        'iat': now
    }
    secret_key = current_app.config.get('SECRET_KEY')
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return token


def verify_auth_token(token):
    """
    Verify JWT authentication token
    
    Args:
        token (str): JWT token to verify
        
    Returns:
        User: User object if token is valid, None otherwise
    """
    try:
        secret_key = current_app.config.get('SECRET_KEY')
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])

        user_id = payload.get('user_id')
        if not user_id:
            return None

        from app.core.extensions import db
        from domain.repositories.users import SyncUserRepository

        return SyncUserRepository(db.session).get_by_id(user_id)
    except jwt.ExpiredSignatureError:
        # Token has expired
        return None
    except jwt.InvalidTokenError:
        # Token is invalid
        return None
    except Exception:
        # Catch any other unexpected errors
        return None
