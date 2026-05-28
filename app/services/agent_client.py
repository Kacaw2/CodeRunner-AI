"""HTTP adapter for calling the Flask backend's AI endpoints.

Per the architecture plan (section 9.1), the FastAPI Agent Host uses HTTP
adapters to invoke existing Flask services rather than importing Flask code
directly.  This avoids Flask app-context coupling.
"""

import json
import logging
from typing import Generator

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return get_settings().FLASK_BASE_URL.rstrip("/")


def _auth_headers(jwt_token: str) -> dict:
    return {"Authorization": f"Bearer {jwt_token}"}


# ── Synchronous chat via Flask ─────────────────────────────────

def create_chat_sync(
    jwt_token: str,
    message: str,
    agent_type: str = "auto",
    conversation_id: int | None = None,
) -> dict:
    """Call Flask POST /api/v1/ai/chat (synchronous, blocking)."""
    url = f"{_base_url()}/api/v1/ai/chat"
    payload = {"message": message, "agent_type": agent_type}
    if conversation_id:
        payload["conversation_id"] = conversation_id

    resp = httpx.post(
        url, json=payload, headers=_auth_headers(jwt_token), timeout=60
    )
    resp.raise_for_status()
    return resp.json()


# ── Async chat task via Flask ──────────────────────────────────

def create_chat_task(
    jwt_token: str,
    message: str,
    agent_type: str = "auto",
    conversation_id: int | None = None,
) -> dict:
    """Call Flask POST /api/v1/ai/chat/async to create a background task.

    Returns {"task_id": ..., "conversation_id": ...}.
    """
    url = f"{_base_url()}/api/v1/ai/chat/async"
    payload = {"message": message, "agent_type": agent_type}
    if conversation_id:
        payload["conversation_id"] = conversation_id

    resp = httpx.post(
        url, json=payload, headers=_auth_headers(jwt_token), timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def poll_chat_task(jwt_token: str, task_id: str) -> dict:
    """Call Flask GET /api/v1/ai/chat/task/<task_id> to poll task status."""
    url = f"{_base_url()}/api/v1/ai/chat/task/{task_id}"
    resp = httpx.get(url, headers=_auth_headers(jwt_token), timeout=10)
    resp.raise_for_status()
    return resp.json()


def stream_chat_task(
    jwt_token: str, task_id: str, last_event: int = 0
) -> Generator[dict, None, None]:
    """Consume Flask GET /api/v1/ai/chat/task/<task_id>/stream SSE and
    yield parsed event dicts.
    """
    url = f"{_base_url()}/api/v1/ai/chat/task/{task_id}/stream"
    params = {"last_event": last_event} if last_event else {}

    with httpx.stream(
        "GET", url, headers=_auth_headers(jwt_token), params=params, timeout=330
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or line.startswith(":"):
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    return
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning("Bad SSE payload: %.200s", data_str)


# ── Workflows ──────────────────────────────────────────────────

def create_workflow(
    jwt_token: str,
    goal: str,
    workflow_type: str = "general",
    conversation_id: int | None = None,
    context: dict | None = None,
) -> dict:
    """Call Flask POST /api/v1/ai/workflows to create and execute a workflow."""
    url = f"{_base_url()}/api/v1/ai/workflows"
    payload: dict = {"goal": goal}
    if workflow_type:
        payload["workflow_type"] = workflow_type
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if context:
        payload.update(context)

    resp = httpx.post(
        url, json=payload, headers=_auth_headers(jwt_token), timeout=120
    )
    resp.raise_for_status()
    return resp.json()


def get_workflow(jwt_token: str, workflow_run_id: str) -> dict | None:
    """Call Flask GET /api/v1/ai/workflows/<run_id>."""
    url = f"{_base_url()}/api/v1/ai/workflows/{workflow_run_id}"
    resp = httpx.get(url, headers=_auth_headers(jwt_token), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def approve_workflow(
    jwt_token: str, workflow_run_id: str, approved: bool, feedback: str = ""
) -> dict:
    """Call Flask POST /api/v1/ai/workflows/<run_id>/approve."""
    url = f"{_base_url()}/api/v1/ai/workflows/{workflow_run_id}/approve"
    payload = {"approved": approved, "feedback": feedback}
    resp = httpx.post(
        url, json=payload, headers=_auth_headers(jwt_token), timeout=60
    )
    resp.raise_for_status()
    return resp.json()


# ── Traces ─────────────────────────────────────────────────────

def get_trace(jwt_token: str, run_id: str) -> dict | None:
    """Call Flask GET /api/v1/ai/traces/<run_id>."""
    url = f"{_base_url()}/api/v1/ai/traces/{run_id}"
    resp = httpx.get(url, headers=_auth_headers(jwt_token), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def list_traces(jwt_token: str, limit: int = 20, offset: int = 0) -> dict:
    """Call Flask GET /api/v1/ai/traces."""
    url = f"{_base_url()}/api/v1/ai/traces"
    resp = httpx.get(
        url,
        headers=_auth_headers(jwt_token),
        params={"limit": limit, "offset": offset},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
