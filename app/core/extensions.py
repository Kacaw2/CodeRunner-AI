# app/core/extensions.py
"""
Flask Extensions Initialization

All extensions are initialized here and then registered to the app in create_app()
"""
from flask_sqlalchemy import SQLAlchemy
from flask_smorest import Api
from flask_login import LoginManager
from flask_migrate import Migrate

# Initialize Flask-Login
login_manager = LoginManager()

# Initialize database
db = SQLAlchemy()

# Initialize API (Flask-Smorest)
api = Api()

# Initialize Flask-Migrate
migrate = Migrate()

def init_extensions(app):
    """
    Initialize all extensions
    
    Args:
        app: Flask application instance
    """
    # Initialize database
    db.init_app(app)
    
    # Initialize API
    api.init_app(app)

    # Initialize Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = 'web_auth.login_page'  
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.query.get(int(user_id))
    
    # Import all models within app context to ensure they are registered
    # This is required for Flask-Migrate to detect model changes
    # Note: Flask-Migrate handles table creation, not db.create_all()
    with app.app_context():
        from app.models import (
            User, UserRole,
            Classroom, Enrollment,
            Quiz,
            Question, TestCase,
            Submission, TestResult
        )
    
    # Initialize Flask-Migrate for database migrations
    migrate.init_app(app, db)
