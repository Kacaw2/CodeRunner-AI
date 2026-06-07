"""3-state dispatcher for the chat command path.

Sits between the Flask ``chat_async`` endpoint and task execution. The mode
comes from config (``Settings.AGENT_RUNTIME_MODE``, default ``"embedded"``):

    embedded  default: call ``workers.chat.submit_chat_task`` — current
              behavior, byte-for-byte unchanged.
    shadow    embedded executes the task AND remote readiness/contract is
              verified (a /health/ready probe). No second LLM call, no double
              delivery — the remote side is only pinged, never asked to run.
    remote    Flask has already created the task + message (status pending); the
              dispatcher sends a signed POST .../{task_id}:start to the runtime,
              which claims & executes. On dispatch failure the task is marked
              failed via CAS — never a silent fallback to a hidden embedded run.

This module imports ``workers.chat`` as a module (not the function symbol) so
existing tests that ``patch("workers.chat.submit_chat_task")`` keep working.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _mode() -> str:
    from core.config import get_settings

    return (get_settings().AGENT_RUNTIME_MODE or "embedded").strip().lower()


def _submit_embedded(task_id: str, app) -> None:
    """Run the task on the embedded Flask worker (unchanged behavior).

    Imports the module and calls the attribute so ``patch(
    "workers.chat.submit_chat_task")`` in tests still intercepts the call.
    """
    import workers.chat as chat_worker

    chat_worker.submit_chat_task(task_id, app)


def _probe_remote_ready() -> bool:
    """Ping the runtime's /health/ready. Returns True iff it reports ready.

    Best-effort and never raises: shadow mode must not affect the embedded run.
    """
    try:
        import httpx

        from core.config import get_settings

        settings = get_settings()
        url = settings.AGENT_RUNTIME_URL.rstrip("/") + "/health/ready"
        resp = httpx.get(url, timeout=settings.AGENT_RUNTIME_TIMEOUT)
        return resp.status_code == 200
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Shadow readiness probe failed: %s", exc)
        return False


def _dispatch_remote(task_id: str) -> None:
    """Send a signed start command to the runtime.

    Raises on any failure so the caller can mark the task failed.
    """
    import httpx

    from core.auth.service_tokens import mint_service_token
    from core.config import get_settings

    settings = get_settings()
    token = mint_service_token(subject=settings.SERVICE_TOKEN_ISSUER, task_id=task_id)
    url = f"{settings.AGENT_RUNTIME_URL.rstrip('/')}/internal/v1/chat-tasks/{task_id}:start"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.AGENT_RUNTIME_TIMEOUT,
    )
    resp.raise_for_status()


def _dispatch_remote_workflow(run_id: str) -> None:
    """Send a signed workflow start command to the runtime."""
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
    """Mark a task failed via the sync CAS repository (remote dispatch failure)."""
    from app.core.extensions import db
    from domain.repositories.chat import SyncChatRepository

    try:
        repo = SyncChatRepository(db.session)
        if repo.mark_failed(task_id, error_detail=detail[:500]):
            db.session.commit()
    except Exception:  # pragma: no cover - defensive
        db.session.rollback()
        logger.exception("Failed to mark task %s failed after dispatch error", task_id)


def _mark_workflow_failed(run_id: str, detail: str) -> None:
    from app.core.extensions import db
    from domain.repositories.workflows import SyncWorkflowRepository

    try:
        repo = SyncWorkflowRepository(db.session)
        if repo.transition_run(
            run_id,
            ("planning", "executing"),
            "failed",
            error_detail=detail[:500],
        ):
            db.session.commit()
    except Exception:  # pragma: no cover - defensive
        db.session.rollback()
        logger.exception(
            "Failed to mark workflow %s failed after dispatch error", run_id
        )


def dispatch_chat_task(task_id: str, app) -> str:
    """Route a freshly-created chat task according to the configured mode.

    Returns the mode that was actually used. ``app`` is the Flask application
    object (needed by the embedded worker's app context).
    """
    mode = _mode()

    if mode == "remote":
        try:
            _dispatch_remote(task_id)
        except Exception as exc:
            logger.exception("Remote dispatch failed for task %s", task_id)
            _mark_task_failed(task_id, f"remote dispatch failed: {exc}")
        return "remote"

    # embedded + shadow both run the embedded worker.
    _submit_embedded(task_id, app)

    if mode == "shadow":
        ready = _probe_remote_ready()
        logger.info("Shadow mode: remote runtime ready=%s for task %s", ready, task_id)
        return "shadow"

    return "embedded"


def dispatch_workflow(
    run_id: str,
    app,
    goal: str,
    context: dict | None = None,
) -> str:
    """Route a workflow command through embedded/shadow/remote mode."""
    mode = _mode()
    if mode == "remote":
        try:
            _dispatch_remote_workflow(run_id)
        except Exception as exc:
            logger.exception("Remote workflow dispatch failed for %s", run_id)
            _mark_workflow_failed(
                run_id, f"remote workflow dispatch failed: {exc}"
            )
        return "remote"

    import workers.workflow as workflow_worker

    workflow_worker.submit_workflow(run_id, app, goal, context)
    if mode == "shadow":
        ready = _probe_remote_ready()
        logger.info(
            "Shadow mode: remote runtime ready=%s for workflow %s",
            ready,
            run_id,
        )
        return "shadow"
    return "embedded"
