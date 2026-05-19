# app/services/profile_service.py
"""User Profile Service"""
from flask_smorest import abort
from app.models.user import User
from app.core.extensions import db
from app.auth.utils import hash_password, verify_password


class ProfileService:
    """Profile management service"""
    
    @staticmethod
    def update_email(user, new_email):
        """
        Update user email address
        
        Args:
            user: Current user object
            new_email: New email address
            
        Returns:
            User: Updated user object
            
        Raises:
            400: Email already registered / Same as current email
        """
        # Check if email is same as current
        if user.email == new_email:
            abort(400, message="New email is the same as current email")
        
        # Check if email already exists
        existing_user = User.query.filter_by(email=new_email).first()
        if existing_user and existing_user.id != user.id:
            abort(400, message="Email already registered")
        
        # Update email
        user.email = new_email
        db.session.commit()
        
        return user
    
    @staticmethod
    def update_username(user, new_username, password):
        """
        Update username
        
        Args:
            user: Current user object
            new_username: New username
            password: Current password for verification
            
        Returns:
            User: Updated user object
            
        Raises:
            400: Username already exists / Same as current username
            401: Invalid password
        """
        # Verify current password
        if not verify_password(password, user.password):
            abort(401, message="Invalid current password")
        
        # Check if username is same as current
        if user.username == new_username:
            abort(400, message="New username is the same as current username")
        
        # Check if username already exists
        existing_user = User.query.filter_by(username=new_username).first()
        if existing_user and existing_user.id != user.id:
            abort(400, message="Username already exists")
        
        # Update username
        user.username = new_username
        db.session.commit()
        
        return user
    
    @staticmethod
    def update_password(user, current_password, new_password):
        """
        Update password
        
        Args:
            user: Current user object
            current_password: Current password for verification
            new_password: New password
            
        Returns:
            User: Updated user object
            
        Raises:
            401: Invalid current password
            400: New password same as current password
        """
        # Verify current password
        if not verify_password(current_password, user.password):
            abort(401, message="Invalid current password")
        
        # Check if new password is different from current
        if verify_password(new_password, user.password):
            abort(400, message="New password must be different from current password")
        
        # Update password
        user.password = hash_password(new_password)
        db.session.commit()
        
        return user
