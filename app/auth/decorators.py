# app/auth/decorators.py
"""Authentication decorators for API endpoints"""
from functools import wraps
from flask import g, session, request, jsonify
from werkzeug.exceptions import Unauthorized, Forbidden
from app.auth.utils import verify_auth_token


def get_current_user_or_none():
    """
    Get current user if available, without raising exceptions
    Used for optional authentication scenarios
    Supports authentication from Session, Authorization Header, or Cookie
    """
    # Check if user is already in g context
    if hasattr(g, 'current_user') and g.current_user:
        return g.current_user
    
    # Try to get user from various sources
    user = _try_get_user_from_sources()
    
    if user:
        g.current_user = user
    
    return user


def get_current_user_or_401():
    """
    Get current user or raise 401 Unauthorized
    Supports authentication from Session, Authorization Header, or Cookie
    """
    # Check if user is already in g context
    if hasattr(g, 'current_user') and g.current_user:
        return g.current_user
    
    # Try to get user from various sources
    user = _try_get_user_from_sources()
    
    if user:
        g.current_user = user
        return user
    
    raise Unauthorized("Authentication required")


def _try_get_user_from_sources():
    """
    Helper function to try getting user from multiple authentication sources
    Returns User object or None
    
    Priority order:
    1. Session (user_id)
    2. Authorization header (Bearer token)
    3. Cookie (auth_token)
    """
    from app.core.extensions import db
    from domain.repositories.users import SyncUserRepository

    user_repo = SyncUserRepository(db.session)

    # Method 1: Get from session
    user_id = session.get('user_id')
    if user_id:
        user = user_repo.get_by_id(user_id)
        if user:
            return user
    
    # Method 2: Get from Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]  # Use split with maxsplit for safety
        user = verify_auth_token(token)
        if user:
            return user
    
    # Method 3: Get from Cookie
    token = request.cookies.get('auth_token')
    if token:
        user = verify_auth_token(token)
        if user:
            return user
    
    return None


def optional_auth(f):
    """
    Optional authentication decorator
    Validates token and sets g.current_user if present, but doesn't fail if absent
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user_or_none()
        if user:
            g.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def require_auth(f):
    """Authentication required decorator"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            user = get_current_user_or_401()
            g.current_user = user
            return f(*args, **kwargs)
        except Unauthorized as e:
            return jsonify({"message": str(e)}), 401
    return decorated_function


def require_role(*allowed_roles):
    """Decorator requiring specific role(s)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                user = get_current_user_or_401()
                g.current_user = user
                
                # Handle both enum and string role types
                user_role = user.role.value if hasattr(user.role, 'value') else user.role
                
                if user_role not in allowed_roles:
                    raise Forbidden("Access denied: Insufficient permissions")
                
                return f(*args, **kwargs)
            except Unauthorized as e:
                return jsonify({"message": str(e)}), 401
            except Forbidden as e:
                return jsonify({"message": str(e)}), 403
        return decorated_function
    return decorator


def require_teacher(f):
    """Teacher permission decorator"""
    return require_role('teacher', 'admin')(f)


def require_student(f):
    """Student permission decorator (accessible by students, teachers, and admins)"""
    return require_role('student', 'teacher', 'admin')(f)


def require_admin(f):
    """Administrator permission decorator"""
    return require_role('admin')(f)
