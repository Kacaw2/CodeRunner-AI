"""Trace API endpoints for the FastAPI Agent Host.

Proxies to the Flask backend's trace endpoints via HTTP adapter.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.services import agent_client
from core.auth.caller import TokenPayload, require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
def list_traces(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent_type: str | None = Query(None),
    status: str | None = Query(None),
    source: str | None = Query(None),
    eval_run_id: int | None = Query(None),
    conversation_id: int | None = Query(None),
    chat_task_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    q: str | None = Query(None),
    user: TokenPayload = Depends(require_auth),
):
    """List agent trace records from the new agent_trace_* tables (proxied)."""
    token = _extract_token(request)
    filters = {
        "agent_type": agent_type,
        "status": status,
        "source": source,
        "eval_run_id": eval_run_id,
        "conversation_id": conversation_id,
        "chat_task_id": chat_task_id,
        "from": from_,
        "to": to,
        "q": q,
    }
    try:
        return agent_client.list_traces(
            token, limit=limit, offset=offset, filters=filters
        )
    except Exception as e:
        logger.warning("Failed to fetch traces: %s", e)
        raise HTTPException(status_code=502, detail="Failed to fetch traces from backend")


@router.get("/{run_id}")
def get_trace(
    run_id: str,
    request: Request,
    user: TokenPayload = Depends(require_auth),
):
    """Get a single agent trace (proxied from Flask)."""
    token = _extract_token(request)
    try:
        result = agent_client.get_trace(token, run_id)
    except Exception as e:
        logger.warning("Failed to fetch trace %s: %s", run_id, e)
        raise HTTPException(status_code=502, detail="Failed to fetch trace from backend")

    if result is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return result


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("auth_token", "")
