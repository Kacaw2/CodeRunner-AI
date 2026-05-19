# app/auth/web_decorators.py
"""
Web page authentication decorators
Used for web pages that need to redirect to login (instead of returning JSON)
"""
from functools import wraps
from flask import g, request, redirect, url_for
from flask_login import current_user
from app.auth.utils import verify_auth_token


def _get_web_user():
    """
    Helper function to get authenticated user from various sources
    Used by web decorators to avoid code duplication
    
    Returns:
        User: Authenticated user object or None
    """
    # Method 1: Check Flask-Login session
    if current_user.is_authenticated:
        return current_user
    
    # Method 2: Check JWT token in Cookie
    token = request.cookies.get('auth_token')
    
    # Method 3: Check Authorization header (for AJAX requests)
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1]  # Use maxsplit for safety
    
    # Verify token if found
    if token:
        user = verify_auth_token(token)
        if user:
            return user
    
    return None


def web_login_required(f):
    """
    Web page login decorator
    Redirects to login page if not authenticated, instead of returning JSON error
    Supports Flask-Login Session, JWT Token (Cookie or Header)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _get_web_user()
        
        if user:
            g.current_user = user
            return f(*args, **kwargs)
        
        # Not authenticated - redirect to login page
        next_url = request.url
        return redirect(url_for('web_auth.login_page', next=next_url))
    
    return decorated_function


def web_student_required(f):
    """
    Web page student permission decorator
    Checks if user has student role, redirects if not logged in, returns 403 if wrong role
    Accessible by: student, teacher, admin
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _get_web_user()
        
        # Not authenticated - redirect to login
        if not user:
            next_url = request.url
            return redirect(url_for('web_auth.login_page', next=next_url))
        
        # Check role
        user_role = user.role.value if hasattr(user.role, 'value') else user.role
        if user_role not in ['student', 'teacher', 'admin']:
            return "Access denied: Student access required", 403
        
        g.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function


def web_teacher_required(f):
    """
    Web page teacher permission decorator
    Checks if user has teacher role
    Accessible by: teacher, admin
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _get_web_user()
        
        # Not authenticated - redirect to login
        if not user:
            next_url = request.url
            return redirect(url_for('web_auth.login_page', next=next_url))
        
        # Check role
        user_role = user.role.value if hasattr(user.role, 'value') else user.role
        if user_role not in ['teacher', 'admin']:
            return "Access denied: Teacher access required", 403
        
        g.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function


def web_admin_required(f):
    """
    Web page admin permission decorator
    Checks if user has admin role
    Accessible by: admin only
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _get_web_user()
        
        # Not authenticated - redirect to login
        if not user:
            next_url = request.url
            return redirect(url_for('web_auth.login_page', next=next_url))
        
        # Check role
        user_role = user.role.value if hasattr(user.role, 'value') else user.role
        if user_role != 'admin':
            return "Access denied: Administrator access required", 403
        
        g.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function
