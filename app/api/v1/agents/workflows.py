"""Workflow API endpoints for the FastAPI Agent Host.

  POST /api/workflows               -> create a workflow run
  GET  /api/workflows               -> list workflow runs
  GET  /api/workflows/{id}          -> get workflow status + steps
  GET  /api/workflows/{id}/stream   -> SSE stream of workflow events
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from core.auth.caller import TokenPayload, require_auth
from core.db.session import get_db
from core.db.models.workflow import WorkflowRun, WorkflowStep
from workers import redis_buffer
from workers.task_runner import submit_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])


# ── Schemas ────────────────────────────────────────────────────

class StepInput(BaseModel):
    step_type: str = "agent_call"
    agent_type: str | None = None
    instruction: str
    risk_level: str = "low"
    requires_approval: bool = False
    depends_on: list[int] | None = None


class WorkflowCreateRequest(BaseModel):
    goal: str
    workflow_type: str = "general"
    steps: list[StepInput] = []
    conversation_id: int | None = None
    max_steps: int = 10
    timeout_seconds: int = 300
    language: str = "python"
    difficulty: str = "medium"
    topic: str = ""


class WorkflowCreated(BaseModel):
    workflow_id: str
    status: str


# ── POST /api/workflows ───────────────────────────────────────

@router.post("", response_model=WorkflowCreated, status_code=202)
def create_workflow(
    body: WorkflowCreateRequest,
    request: Request,
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Create a new workflow run with optional pre-defined steps."""
    goal = body.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")

    run = WorkflowRun(
        user_id=user.user_id,
        conversation_id=body.conversation_id,
        goal=goal,
        workflow_type=body.workflow_type,
        status="planning",
        max_steps=body.max_steps,
        timeout_seconds=body.timeout_seconds,
        total_steps=len(body.steps),
    )
    db.add(run)
    db.flush()

    plan_steps = []
    for idx, step_input in enumerate(body.steps):
        step = WorkflowStep(
            workflow_run_id=run.id,
            step_index=idx,
            step_type=step_input.step_type,
            agent_type=step_input.agent_type,
            instruction=step_input.instruction,
            risk_level=step_input.risk_level,
            requires_approval=step_input.requires_approval,
            depends_on=step_input.depends_on,
            status="pending",
        )
        db.add(step)
        plan_steps.append({
            "step_index": idx,
            "step_type": step_input.step_type,
            "agent_type": step_input.agent_type,
            "instruction": step_input.instruction,
            "risk_level": step_input.risk_level,
            "requires_approval": step_input.requires_approval,
        })

    run.plan_json = {"goal": goal, "steps": plan_steps}
    db.commit()
    db.refresh(run)

    token = _extract_token(request)
    wf_context = {
        "language": body.language,
        "difficulty": body.difficulty,
        "topic": body.topic,
    }
    submit_workflow(run.id, token, goal, wf_context)

    return WorkflowCreated(workflow_id=run.id, status=run.status)


# ── GET /api/workflows ────────────────────────────────────────

@router.get("")
def list_workflows(
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List workflow runs for the current user."""
    q = db.query(WorkflowRun).filter_by(user_id=user.user_id)
    if status:
        q = q.filter_by(status=status)
    total = q.count()
    runs = q.order_by(WorkflowRun.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "workflows": [r.to_dict() for r in runs],
    }


# ── GET /api/workflows/{workflow_id} ──────────────────────────

@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: str,
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Get workflow run details including steps."""
    run = (
        db.query(WorkflowRun)
        .filter_by(id=workflow_id, user_id=user.user_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return run.to_dict()


# ── GET /api/workflows/{workflow_id}/stream ───────────────────

@router.get("/{workflow_id}/stream")
async def stream_workflow(
    workflow_id: str,
    last_event: int = Query(0, ge=0),
    user: TokenPayload = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """SSE stream for workflow events.  Supports catch-up."""
    run = (
        db.query(WorkflowRun)
        .filter_by(id=workflow_id, user_id=user.user_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Workflow not found")

    async def event_generator():
        cursor = last_event
        idle = 0
        max_idle = 1000

        while idle < max_idle:
            events = redis_buffer.wf_get_events(workflow_id, start=cursor)

            if events:
                idle = 0
                for evt in events:
                    yield {"data": json.dumps(evt, ensure_ascii=False)}
                    cursor += 1

                    if evt.get("type") in ("workflow_done", "workflow_error"):
                        return
            else:
                wf_status = redis_buffer.wf_get_status(workflow_id)
                if wf_status in ("completed", "failed"):
                    remaining = redis_buffer.wf_get_events(workflow_id, start=cursor)
                    for evt in remaining:
                        yield {"data": json.dumps(evt, ensure_ascii=False)}
                    return

                yield {"comment": "heartbeat"}
                idle += 1
                await asyncio.sleep(0.5)

        yield {"data": json.dumps({"type": "error", "message": "Stream timeout"})}

    return EventSourceResponse(event_generator())


# ── helpers ────────────────────────────────────────────────────

def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("auth_token", "")
