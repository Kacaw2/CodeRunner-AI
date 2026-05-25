"""Chat API endpoints for the FastAPI Agent Host.

Mirrors the Flask async chat flow but runs inside FastAPI:
  POST /api/chat          -> create async chat task
  GET  /api/chat/task/{id}       -> poll task status
  GET  /api/chat/task/{id}/stream -> SSE with catch-up
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from agent_host.core.auth import TokenPayload, require_auth
from agent_host.core.db import get_db
from agent_host.models.chat_task import ChatTask
from agent_host.worker import redis_buffer
from agent_host.worker.task_runner import submit_chat_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Request / Response schemas ─────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    agent_type: str = "auto"
    conversation_id: int | None = None


class ChatTaskCreated(BaseModel):
    task_id: str
    conversation_id: int | None = None


class ChatTaskStatus(BaseModel):
    id: str
    status: str
    agent_type: str | None = None
    routed_agent: str | None = None
    result_message_id: int | None = None
    error_detail: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


# ── POST /api/chat ─────────────────────────────────────────────

@router.post("", response_model=ChatTaskCreated, status_code=202)
def create_chat_task(
    body: ChatRequest,
    request: Request,
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Create an async chat task.  Returns task_id immediately."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    if body.agent_type == "generator" and user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=403, detail="Only teachers can use the generator agent."
        )

    task = ChatTask(
        conversation_id=body.conversation_id,
        user_id=user.user_id,
        agent_type=body.agent_type,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    token = _extract_raw_token(request)
    submit_chat_task(task.id, token, message)

    return ChatTaskCreated(
        task_id=task.id,
        conversation_id=body.conversation_id,
    )


# ── GET /api/chat/task/{task_id} ───────────────────────────────

@router.get("/task/{task_id}", response_model=ChatTaskStatus)
def get_chat_task(
    task_id: str,
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Poll task status."""
    task = db.query(ChatTask).filter_by(id=task_id, user_id=user.user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    redis_info = redis_buffer.ct_get_status(task_id)
    status = redis_info.get("status") or task.status
    routed = redis_info.get("agent") or task.routed_agent

    return ChatTaskStatus(
        id=task.id,
        status=status,
        agent_type=task.agent_type,
        routed_agent=routed,
        result_message_id=task.result_message_id,
        error_detail=task.error_detail,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


# ── GET /api/chat/task/{task_id}/stream ────────────────────────

@router.get("/task/{task_id}/stream")
async def stream_chat_task(
    task_id: str,
    last_event: int = Query(0, ge=0),
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """SSE stream for a chat task.  Supports catch-up via ?last_event=N."""
    task = db.query(ChatTask).filter_by(id=task_id, user_id=user.user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        cursor = last_event
        idle = 0
        max_idle = 1000  # ~300 s at 0.3 s interval

        while idle < max_idle:
            events = redis_buffer.ct_get_events(task_id, start=cursor)

            if events:
                idle = 0
                for evt in events:
                    yield {"data": json.dumps(evt, ensure_ascii=False)}
                    cursor += 1

                    if evt.get("type") in ("done", "error"):
                        return
            else:
                info = redis_buffer.ct_get_status(task_id)
                if info.get("status") in ("completed", "failed"):
                    remaining = redis_buffer.ct_get_events(task_id, start=cursor)
                    for evt in remaining:
                        yield {"data": json.dumps(evt, ensure_ascii=False)}
                    return

                yield {"comment": "heartbeat"}
                idle += 1
                await asyncio.sleep(0.3)

        yield {"data": json.dumps({"type": "error", "message": "Stream timeout"})}

    return EventSourceResponse(event_generator())


# ── helpers ────────────────────────────────────────────────────

def _extract_raw_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("auth_token", "")
