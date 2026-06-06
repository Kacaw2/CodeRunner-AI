"""Internal command API for chat tasks.

All routes require a valid signed internal service token (dedicated audience)
and act only on the task named in the path. The Flask side has already created
the task + user message (status ``pending``); ``:start`` claims and executes it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agent_runtime.dependencies import (
    get_redis,
    get_session,
    require_task_token,
)
from agent_runtime.schemas import (
    ChatTaskEventsResponse,
    ChatTaskStartResponse,
    ChatTaskStatusResponse,
)
from agent_runtime.services.chat_runner import AsyncChatRunner, RedisSSEWriter
from domain.repositories.chat import AsyncChatRepository

router = APIRouter(prefix="/internal/v1/chat-tasks", tags=["chat-tasks"])


@router.post("/{task_id}:start", response_model=ChatTaskStartResponse)
async def start_chat_task(
    task_id: str,
    session=Depends(get_session),
    redis_client=Depends(get_redis),
    _claims: dict = Depends(require_task_token),
) -> ChatTaskStartResponse:
    runner = AsyncChatRunner(session, redis_client=redis_client)
    result = await runner.run(task_id)
    if result["status"] == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return ChatTaskStartResponse(
        task_id=task_id,
        status=result["status"],
        claimed=result["claimed"],
        agent_type=result["agent_type"],
        result_message_id=result["result_message_id"],
    )


@router.get("/{task_id}", response_model=ChatTaskStatusResponse)
async def get_chat_task(
    task_id: str,
    session=Depends(get_session),
    _claims: dict = Depends(require_task_token),
) -> ChatTaskStatusResponse:
    task = await AsyncChatRepository(session).get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return ChatTaskStatusResponse(
        task_id=task.id,
        conversation_id=task.conversation_id,
        status=task.status,
        agent_type=task.agent_type,
        routed_agent=task.routed_agent,
        result_message_id=task.result_message_id,
        error_detail=task.error_detail,
    )


@router.get("/{task_id}/events", response_model=ChatTaskEventsResponse)
async def get_chat_task_events(
    task_id: str,
    last_event: int = 0,
    redis_client=Depends(get_redis),
    _claims: dict = Depends(require_task_token),
) -> ChatTaskEventsResponse:
    sse = RedisSSEWriter(redis_client)
    status_info = sse.read_status(task_id)
    return ChatTaskEventsResponse(
        task_id=task_id,
        status=status_info.get("status"),
        agent=status_info.get("agent"),
        events=sse.read_events(task_id, start=last_event),
    )
