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

from domain.base import DomainBase

# Initialize Flask-Login
login_manager = LoginManager()

# Initialize database
# Bind Flask-SQLAlchemy to the single application-wide DeclarativeBase so that
# ``db.Model.registry`` / ``db.Model.metadata`` are the same objects as
# ``DomainBase.registry`` / ``DomainBase.metadata`` (one registry, one metadata).
db = SQLAlchemy(model_class=DomainBase)

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
        from domain.models.user import User
        return db.session.get(User, int(user_id))
    
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
        from domain.models.chat import (  # noqa: F401
            AIConversation,
            AIMessage,
            ChatTask,
        )
        from app.models.agent_task import AgentTask  # noqa: F401
        from app.models.agent_trace import AgentRun, AgentRunStep  # noqa: F401
        from app.models.ai_audit_log import AIAuditLog  # noqa: F401
        from app.models.student_profile import StudentProfile, TeacherPreference  # noqa: F401
        from domain.models.observability import EvalRun  # noqa: F401
        from domain.models.workflow import WorkflowRun, WorkflowStep  # noqa: F401
        from domain.models.mcp import (  # noqa: F401
            McpApiKey,
            McpAuditLog,
            McpToolApproval,
        )
        from domain.models.memory import MemoryItemRecord  # noqa: F401

    # Initialize Redis
    global redis_client
    redis_url = app.config.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        redis_client = _redis.from_url(redis_url, decode_responses=True)
    except Exception:
        redis_client = None

    # Initialize Flask-Migrate for database migrations
    migrate.init_app(app, db)
