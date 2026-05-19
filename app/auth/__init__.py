# app/auth/__init__.py
"""auth module"""
from app.auth.decorators import (
    require_auth,
    require_role,
    require_teacher,
    require_student,
    require_admin,
    optional_auth,
    get_current_user_or_none,
)

from app.auth.web_decorators import (
    web_login_required,
    web_student_required,
    web_teacher_required,
    web_admin_required,
)

from app.auth.utils import (
    hash_password,
    verify_password,
    generate_auth_token,
    verify_auth_token
)

__all__ = [
    # API Decorators（return JSON error）
    'require_auth',
    'require_role',
    'require_teacher',
    'require_student',
    'require_admin',
    'optional_auth',
    'get_current_user_or_none',
    # Web Decorators（redirect to login page）
    'web_login_required',
    'web_student_required',
    'web_teacher_required',
    # Utils
    'hash_password',
    'verify_password',
    'generate_auth_token',
    'verify_auth_token'
]
