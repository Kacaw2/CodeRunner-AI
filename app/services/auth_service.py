# app/services/auth_service.py
"""Authentication service layer"""
from flask_smorest import abort
from app.models.user import User, UserRole
from app.core.extensions import db
from app.auth.utils import (
    hash_password,
    verify_password,
    generate_auth_token
)

class AuthService:
    """Authentication service class"""
    
    @staticmethod
    def register_user(username, password, email=None, role="student"):
        """
        Register a new user
        
        Args:
            username: Username
            password: Password (plain text)
            email: Email (optional)
            role: Role (student/teacher)
            
        Returns:
            User: Created user object
            
        Raises:
            400: Username already exists, email already registered, or role is invalid
        """
        # Check if the username already exists
        if User.query.filter_by(username=username).first():
            abort(400, message="Username already exists")
        
        # Check if the email already exists
        if email and User.query.filter_by(email=email).first():
            abort(400, message="Email already registered")
        
        # Parse role
        role_str = role.upper()
        try:
            user_role = UserRole[role_str]
        except KeyError:
            abort(400, message=f"Invalid role: {role_str}. Must be student or teacher")
        
        # Create user (hash the password)
        user = User(
            username=username,
            password=hash_password(password),
            email=email,
            role=user_role
        )
        
        db.session.add(user)
        db.session.commit()
        
        return user
    
    @staticmethod
    def login_user(username, password):
        """
        User login
        
        Args:
            username: Username or email
            password: Password (plain text)
            
        Returns:
            tuple: (user, token)
            
        Raises:
            401: Invalid credentials
        """
        # Look up user by username or email
        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()
        
        if not user or not verify_password(password, user.password):
            abort(401, message="Invalid credentials")
        
        # Generate JWT token (valid for 24 hours)
        token = generate_auth_token(user, expires_in=86400)
        
        return user, token
    
    @staticmethod
    def refresh_token(user):
        """
        Refresh JWT token
        
        Args:
            user: Current user object
            
        Returns:
            str: New JWT token
        """
        # Generate new token (valid for 24 hours)
        token = generate_auth_token(user, expires_in=86400)
        return token
    
    @staticmethod
    def get_user_info(user):
        """
        Get user information
        
        Args:
            user: User object
            
        Returns:
            dict: User info dictionary
        """
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value
        }
