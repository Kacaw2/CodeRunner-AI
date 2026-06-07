"""Remote-only dispatcher for Agent Runtime commands.

Flask persists the task or workflow first, then sends one signed command to the
FastAPI runtime. Dispatch failures are persisted on the task/run and are never
retried through a hidden in-process execution path.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _dispatch_remote(task_id: str) -> None:
    import httpx

    from core.auth.service_tokens import mint_service_token
    from core.config import get_settings

    settings = get_settings()
    token = mint_service_token(
        subject=settings.SERVICE_TOKEN_ISSUER,
        task_id=task_id,
    )
    url = (
        f"{settings.AGENT_RUNTIME_URL.rstrip('/')}"
        f"/internal/v1/chat-tasks/{task_id}:start"
    )
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.AGENT_RUNTIME_TIMEOUT,
    )
    response.raise_for_status()


def _dispatch_remote_workflow(run_id: str) -> None:
    import httpx

    from core.auth.service_tokens import mint_service_token
    from core.config import get_settings

    settings = get_settings()
    token = mint_service_token(
        subject=settings.SERVICE_TOKEN_ISSUER,
        task_id=run_id,
    )
    url = (
        f"{settings.AGENT_RUNTIME_URL.rstrip('/')}"
        f"/internal/v1/workflows/{run_id}:start"
    )
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.AGENT_RUNTIME_TIMEOUT,
    )
    response.raise_for_status()


def _mark_task_failed(task_id: str, detail: str) -> None:
    from app.core.extensions import db
    from domain.repositories.chat import SyncChatRepository

    try:
        repository = SyncChatRepository(db.session)
        if repository.mark_failed(task_id, error_detail=detail[:500]):
            db.session.commit()
    except Exception:  # pragma: no cover - defensive persistence boundary
        db.session.rollback()
        logger.exception(
            "Failed to mark task %s failed after dispatch error", task_id
        )


def _mark_workflow_failed(run_id: str, detail: str) -> None:
    from app.core.extensions import db
    from domain.repositories.workflows import SyncWorkflowRepository

    try:
        repository = SyncWorkflowRepository(db.session)
        if repository.transition_run(
            run_id,
            ("planning", "executing"),
            "failed",
            error_detail=detail[:500],
        ):
            db.session.commit()
    except Exception:  # pragma: no cover - defensive persistence boundary
        db.session.rollback()
        logger.exception(
            "Failed to mark workflow %s failed after dispatch error", run_id
        )


def dispatch_chat_task(task_id: str, _app=None) -> str:
    try:
        _dispatch_remote(task_id)
    except Exception as exc:
        logger.exception("Remote dispatch failed for task %s", task_id)
        _mark_task_failed(task_id, f"remote dispatch failed: {exc}")
    return "remote"


def dispatch_workflow(
    run_id: str,
    _app=None,
    _goal: str = "",
    _context: dict | None = None,
) -> str:
    try:
        _dispatch_remote_workflow(run_id)
    except Exception as exc:
        logger.exception("Remote workflow dispatch failed for %s", run_id)
        _mark_workflow_failed(
            run_id, f"remote workflow dispatch failed: {exc}"
        )
    return "remote"
