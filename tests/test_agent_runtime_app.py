"""FastAPI agent runtime: app factory, health, and internal-command auth.

These tests exercise the runtime shell in isolation (no MySQL/Redis required):
the async session dependency is overridden with an in-memory sqlite+aiosqlite
session, and Redis is overridden with None.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Importing the model modules registers their tables on the single DomainBase
# metadata used to build the in-memory schema.
import domain.models.chat  # noqa: F401
import domain.models.user  # noqa: F401
from agent_runtime.dependencies import get_redis, get_session
from agent_runtime.main import create_app
from core.auth.service_tokens import mint_service_token
from domain.base import DomainBase

try:
    from starlette.testclient import TestClient
except Exception:  # pragma: no cover
    from fastapi.testclient import TestClient


@pytest.fixture()
def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield engine


@pytest.fixture()
def app_client(async_engine):
    """A TestClient with DB/Redis dependencies overridden for isolation."""
    import asyncio

    async def _create_schema():
        async with async_engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(_create_schema())

    factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_redis] = lambda: None
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_health_live_is_unauthenticated(app_client):
    resp = app_client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_ready_reports_checks(app_client):
    resp = app_client.get("/health/ready")
    # DB is reachable (sqlite) so ready returns 200; redis is None -> unavailable.
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["redis"] == "unavailable"


def test_process_runtime_bootstrap_wires_tool_runtime(monkeypatch):
    import agent_runtime.main as runtime_main

    calls = {}

    def _fake_bootstrap(*, session_factory=None):
        calls["session_factory"] = session_factory
        return object()

    monkeypatch.setattr(
        "mcp_gateway.bootstrap.bootstrap_tool_runtime", _fake_bootstrap
    )
    monkeypatch.setattr("sqlalchemy.orm.configure_mappers", lambda: None)

    runtime_main._bootstrap_process_runtime()

    assert calls["session_factory"].__name__ == "get_session"


def test_only_expected_routes_registered():
    app = create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/internal/v1/chat-tasks/{task_id}:start" in paths
    assert "/internal/v1/chat-tasks/{task_id}" in paths
    assert "/internal/v1/chat-tasks/{task_id}/events" in paths
    assert "/internal/v1/workflows/{workflow_run_id}:start" in paths
    assert "/internal/v1/workflows/{workflow_run_id}" in paths
    assert "/internal/v1/workflows/{workflow_run_id}/events" in paths
    # No revived agent-host routes.
    assert not any(p.startswith("/api/v1/agents") for p in paths)


def test_internal_route_requires_token(app_client):
    resp = app_client.get("/internal/v1/chat-tasks/some-task")
    assert resp.status_code == 401


def test_internal_route_rejects_user_jwt_without_audience(app_client, app):
    """A plain user-style JWT (no dedicated audience) must be rejected."""
    import jwt

    from core.config import get_settings

    settings = get_settings()
    user_token = jwt.encode(
        {"user_id": 1, "role": "student"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = app_client.get(
        "/internal/v1/chat-tasks/some-task",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 401


def test_internal_route_rejects_token_for_other_task(app_client, app):
    token = mint_service_token(subject="coderunner-web", task_id="task-A")
    resp = app_client.get(
        "/internal/v1/chat-tasks/task-B",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_internal_route_accepts_valid_service_token(app_client, app):
    token = mint_service_token(subject="coderunner-web", task_id="missing-task")
    resp = app_client.get(
        "/internal/v1/chat-tasks/missing-task",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Auth passes; task does not exist -> 404 (not 401).
    assert resp.status_code == 404
