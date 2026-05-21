"""Shared test fixtures for the AI agents test suite."""
import pytest
from unittest.mock import MagicMock, patch

from app import create_app
from app.core.extensions import db as _db
from app.models.user import User, UserRole


@pytest.fixture(scope="session")
def app():
    """Create a Flask app configured for testing."""
    application = create_app("testing")
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    application.config["SERVER_NAME"] = "localhost"
    application.config["REDIS_URL"] = "redis://localhost:6379/15"
    yield application


@pytest.fixture(scope="session")
def _setup_db(app):
    """Create all tables once for the session."""
    with app.app_context():
        _db.create_all()
        yield
        _db.drop_all()


@pytest.fixture()
def db_session(app, _setup_db):
    """Provide a database session that rolls back after each test."""
    with app.app_context():
        yield _db.session
        _db.session.rollback()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


@pytest.fixture()
def client(app, db_session):
    """Flask test client with database session."""
    return app.test_client()


@pytest.fixture()
def student_user(db_session):
    """Create a student user."""
    user = User(username="teststudent", password="hashed", email="student@test.com", role=UserRole.STUDENT)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def teacher_user(db_session):
    """Create a teacher user."""
    user = User(username="testteacher", password="hashed", email="teacher@test.com", role=UserRole.TEACHER)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def auth_headers(student_user):
    """Return dict that patches get_current_user_or_401 to return student_user."""
    return {"X-Test-User-Id": str(student_user.id)}


@pytest.fixture()
def mock_auth_student(student_user):
    """Patch auth to return student_user for any request."""
    with patch("app.auth.decorators.get_current_user_or_401", return_value=student_user), \
         patch("app.auth.decorators._try_get_user_from_sources", return_value=student_user):
        yield student_user


@pytest.fixture()
def mock_auth_teacher(teacher_user):
    """Patch auth to return teacher_user for any request."""
    with patch("app.auth.decorators.get_current_user_or_401", return_value=teacher_user), \
         patch("app.auth.decorators._try_get_user_from_sources", return_value=teacher_user):
        yield teacher_user


@pytest.fixture()
def mock_redis():
    """Mock Redis client for rate limiting tests."""
    mock = MagicMock()
    mock.incr.return_value = 1
    mock.expire.return_value = True
    mock.ttl.return_value = 60
    with patch("app.api.v1.ai.redis_client", mock):
        yield mock


@pytest.fixture()
def mock_llm_response():
    """Create a mock LLM response."""
    def _make_response(content="Test response", tool_calls=None):
        resp = MagicMock()
        resp.content = content
        resp.tool_calls = tool_calls or []
        return resp
    return _make_response


@pytest.fixture()
def sample_agent_state():
    """Create a sample AgentState for testing."""
    from langchain_core.messages import HumanMessage
    return {
        "messages": [HumanMessage(content="Help me with this problem")],
        "agent_type": "tutor",
        "user_id": 1,
        "user_role": "student",
        "context": {"question_id": 1},
        "tool_results": [],
        "final_response": "",
    }
