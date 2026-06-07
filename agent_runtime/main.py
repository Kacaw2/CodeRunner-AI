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

from fastapi import FastAPI

from agent_runtime.api import chat_tasks, health, workflows


def create_app() -> FastAPI:
    app = FastAPI(
        title="CodeRunner Agent Runtime",
        version="1.0.0",
        description="Async agent execution runtime on the shared SQLAlchemy domain.",
    )
    app.include_router(health.router)
    app.include_router(chat_tasks.router)
    app.include_router(workflows.router)
    return app


app = create_app()
