# app/api/v1/auth.py
"""Authentication API Routes"""
from flask_smorest import Blueprint
from flask import g, make_response, jsonify
from app.schemas.user_schema import (
    RegisterIn,
    UserOut,
    LoginIn,
    LoginOut,
    RefreshOut
)
from app.services.auth_service import AuthService
from app.auth import require_auth

bp = Blueprint("auth", __name__, description="Auth APIs", url_prefix="/api/v1/auth")


@bp.post("/register")
@bp.arguments(RegisterIn)
@bp.response(201, UserOut)
def register(payload):
    """
    Register a new user
    
    Request Body:
        - username: Username (1-64 characters)
        - password: Password (6-128 characters)
        - email: Email (optional)
        - role: Role (student/teacher, default: student)
    
    Returns:
        - 201: User created successfully
        - 400: Username already exists/Email already registered/Invalid role
    """
    user = AuthService.register_user(
        username=payload["username"],
        password=payload["password"],
        email=payload.get("email"),
        role=payload.get("role", "student")
    )
    
    return AuthService.get_user_info(user)


@bp.post("/login")
@bp.arguments(LoginIn)
def login(payload):
    """
    User login
    
    Request Body:
        - username: Username or email
        - password: Password
    
    Returns:
        - 200: Login successful, returns token and user info, sets HttpOnly Cookie
        - 401: Invalid credentials
    """
    user, token = AuthService.login_user(
        username=payload["username"],
        password=payload["password"]
    )
    
    # Build response data
    response_data = {
        "token": token,
        "user": AuthService.get_user_info(user)
    }
    
    # Create response and set Cookie
    response = make_response(jsonify(response_data), 200)
    
    # Set HttpOnly Cookie (browser will automatically include it in all requests)
    response.set_cookie(
        'auth_token',           # Cookie name
        token,                  # Token value
        httponly=True,          # Prevent XSS attacks (JS cannot read it)
        secure=False,           # Set to True in production (requires HTTPS)
        samesite='Lax',         # Prevent CSRF attacks
        max_age=7*24*60*60,     # Expires in 7 days
        path='/'                # Send this Cookie for all paths
    )
    
    return response


@bp.get("/me")
@bp.response(200, UserOut)
@require_auth
def me():
    """
    Get current user information
    
    Requires authentication:
        - Authorization: Bearer <token>
        - Or Cookie: auth_token
    
    Returns:
        - 200: Current user information
        - 401: Unauthorized
    """
    current_user = g.current_user
    return AuthService.get_user_info(current_user)


@bp.post("/refresh")
@require_auth
def refresh():
    """
    Refresh JWT token
    
    Requires authentication:
        - Authorization: Bearer <token>
        - Or Cookie: auth_token
    
    Returns:
        - 200: New token, also updates Cookie
        - 401: Unauthorized
    """
    current_user = g.current_user
    token = AuthService.refresh_token(current_user)
    
    # Build response data
    response_data = {"token": token}
    
    # Create response and update Cookie
    response = make_response(jsonify(response_data), 200)
    
    # Update token in Cookie
    response.set_cookie(
        'auth_token',
        token,
        httponly=True,
        secure=False,
        samesite='Lax',
        max_age=7*24*60*60,
        path='/'
    )
    
    return response


@bp.post("/logout")
def logout():
    """
    User logout
    
    Returns:
        - 200: Logout successful, clears Cookie
    """
    response = make_response(jsonify({
        "message": "Logged out successfully"
    }), 200)
    
    # Clear Cookie
    response.set_cookie(
        'auth_token',
        '',                     # Empty value
        httponly=True,
        secure=False,
        samesite='Lax',
        expires=0,              # Expire immediately
        path='/'
    )
    
    return response
