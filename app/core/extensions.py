# app/core/extensions.py
"""
Flask Extensions Initialization

All extensions are initialized here and then registered to the app in create_app()
"""
from flask_sqlalchemy import SQLAlchemy
from flask_smorest import Api
from flask_login import LoginManager
from flask_migrate import Migrate
import redis as _redis

# Initialize Flask-Login
login_manager = LoginManager()

# Initialize database
db = SQLAlchemy()

# Initialize API (Flask-Smorest)
api = Api()

# Initialize Flask-Migrate
migrate = Migrate()

# Redis client (initialized lazily in init_extensions)
redis_client: _redis.Redis = None

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
        from app.models.ai_conversation import AIConversation, AIMessage  # noqa: F401
        from app.models.agent_task import AgentTask  # noqa: F401
        from app.models.agent_trace import AgentRun, AgentRunStep  # noqa: F401
        from app.models.ai_audit_log import AIAuditLog  # noqa: F401
        from app.models.student_profile import StudentProfile, TeacherPreference  # noqa: F401
        from app.models.eval_run import EvalRun  # noqa: F401
        from app.models.chat_task import ChatTask  # noqa: F401
        from app.models.workflow import WorkflowRun, WorkflowStep  # noqa: F401

    # Initialize Redis
    global redis_client
    redis_url = app.config.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        redis_client = _redis.from_url(redis_url, decode_responses=True)
    except Exception:
        redis_client = None

    # Initialize Flask-Migrate for database migrations
    migrate.init_app(app, db)
