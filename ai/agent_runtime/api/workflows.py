"""Internal workflow command, status, and event API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ai.agent_runtime.dependencies import (
    get_redis,
    get_session,
    require_workflow_token,
)
from ai.agent_runtime.schemas import (
    WorkflowEventsResponse,
    WorkflowStartResponse,
    WorkflowStatusResponse,
)
from ai.agent_runtime.services.workflow_runner import (
    AsyncWorkflowRunner,
    WorkflowRedisWriter,
)
from domain.repositories.workflows import AsyncWorkflowRepository

router = APIRouter(prefix="/internal/v1/workflows", tags=["workflows"])


@router.post("/{workflow_run_id}:start", response_model=WorkflowStartResponse)
async def start_workflow(
    workflow_run_id: str,
    session=Depends(get_session),
    redis_client=Depends(get_redis),
    _claims: dict = Depends(require_workflow_token),
) -> WorkflowStartResponse:
    result = await AsyncWorkflowRunner(session, redis_client).run(workflow_run_id)
    if result["status"] == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )
    return WorkflowStartResponse(
        workflow_run_id=workflow_run_id,
        status=result["status"],
        claimed=result["claimed"],
    )


@router.get("/{workflow_run_id}", response_model=WorkflowStatusResponse)
async def get_workflow(
    workflow_run_id: str,
    session=Depends(get_session),
    _claims: dict = Depends(require_workflow_token),
) -> WorkflowStatusResponse:
    repo = AsyncWorkflowRepository(session)
    run = await repo.get_run(workflow_run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )
    steps = await repo.list_steps(workflow_run_id)
    return WorkflowStatusResponse(
        workflow_run_id=workflow_run_id,
        status=run.status,
        run=run.to_dict(),
        steps=[step.to_dict() for step in steps],
    )


@router.get("/{workflow_run_id}/events", response_model=WorkflowEventsResponse)
async def get_workflow_events(
    workflow_run_id: str,
    last_event: int = 0,
    redis_client=Depends(get_redis),
    _claims: dict = Depends(require_workflow_token),
) -> WorkflowEventsResponse:
    sse = WorkflowRedisWriter(redis_client)
    return WorkflowEventsResponse(
        workflow_run_id=workflow_run_id,
        status=sse.read_status(workflow_run_id),
        events=sse.read_events(workflow_run_id, start=last_event),
    )
