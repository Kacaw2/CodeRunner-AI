"""FastAPI app factory for the agent runtime.

Registers ONLY:
    GET  /health/live
    GET  /health/ready
    POST /internal/v1/chat-tasks/{task_id}:start
    GET  /internal/v1/chat-tasks/{task_id}
    GET  /internal/v1/chat-tasks/{task_id}/events

``/health/*`` are unauthenticated; the internal command routes require a signed
service token (dedicated audience) enforced per-route by the route dependencies.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import importlib

from fastapi import FastAPI

from agent_runtime.api import chat_tasks, health, workflows


def _bootstrap_process_runtime() -> None:
    """Register ORM mappings and the ToolRuntime for this process.

    The FastAPI runtime executes the same agent/tool kernel as the former
    worker process. It therefore needs the shared ToolRuntime catalog and
    handlers locally, even though the MCP Gateway remains a separate service.
    """
    importlib.import_module("domain.models")
    importlib.import_module("app.models")

    from sqlalchemy.orm import configure_mappers

    configure_mappers()

    from core.db.session import get_session
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime(session_factory=get_session)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _bootstrap_process_runtime()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="CodeRunner Agent Runtime",
        version="1.0.0",
        description="Async agent execution runtime on the shared SQLAlchemy domain.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(chat_tasks.router)
    app.include_router(workflows.router)
    return app


app = create_app()
