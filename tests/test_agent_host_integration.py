"""Integration checks for the FastAPI Agent Host boundary."""

from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]


def test_agent_host_image_includes_packages_used_by_worker():
    dockerfile = (ROOT / "docker" / "Dockerfile.agent_host").read_text(encoding="utf-8")

    assert "COPY --chown=appuser:appuser app/ ./app/" in dockerfile
    assert "COPY --chown=appuser:appuser mcp_server/ ./mcp_server/" in dockerfile


def test_agent_host_chat_task_model_matches_flask_conversation_contract():
    pytest = __import__("pytest")
    pytest.importorskip("dotenv")

    from agent_host.models.chat_task import ChatTask

    assert ChatTask.__table__.c.conversation_id.nullable is False


def test_agent_host_chat_create_persists_conversation_user_message_and_task():
    pytest = __import__("pytest")
    pytest.importorskip("dotenv")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agent_host.core.auth import TokenPayload, require_auth
    from agent_host.core.db import Base, get_db
    from agent_host.main import app
    from agent_host.models.ai_conversation import AIConversation, AIMessage
    from agent_host.models.chat_task import ChatTask

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    def override_auth():
        return TokenPayload(user_id=7, username="teacher", role="teacher")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_auth] = override_auth
    try:
        with patch("agent_host.api.chat.submit_chat_task") as submit:
            client = TestClient(app)
            resp = client.post("/api/chat", json={"message": "Create a Python array problem"})

        assert resp.status_code == 202
        data = resp.json()
        assert data["conversation_id"] is not None

        with SessionLocal() as session:
            conv = session.get(AIConversation, data["conversation_id"])
            assert conv is not None
            assert conv.user_id == 7
            assert conv.agent_type == "auto"

            task = session.get(ChatTask, data["task_id"])
            assert task is not None
            assert task.conversation_id == conv.id
            assert task.user_message_id is not None

            user_msg = session.get(AIMessage, task.user_message_id)
            assert user_msg is not None
            assert user_msg.role == "user"
            assert user_msg.content == "Create a Python array problem"

        submit.assert_called_once()
    finally:
        app.dependency_overrides.clear()
