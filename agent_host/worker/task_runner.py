"""Background task runner for the FastAPI Agent Host.

Phase 1 approach: delegates actual agent execution to the Flask backend via
HTTP adapter (see section 9.1 of the architecture plan).  The runner manages
ChatTask lifecycle, streams events from Flask into the shared Redis buffer,
and persists final status to the database.

In Phase 2, direct agent invocation will replace the HTTP adapter path.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from agent_host.adapters import flask_client
from agent_host.core.config import get_settings
from agent_host.core.db import db_session
from agent_host.models.chat_task import ChatTask
from agent_host.models.workflow import WorkflowRun
from agent_host.worker import redis_buffer

logger = logging.getLogger(__name__)

_CHINA_TZ = timezone(timedelta(hours=8))

_executor: ThreadPoolExecutor | None = None


def _now() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        settings = get_settings()
        _executor = ThreadPoolExecutor(
            max_workers=settings.WORKER_MAX_THREADS,
            thread_name_prefix="agent-worker",
        )
    return _executor


def shutdown():
    global _executor
    if _executor:
        _executor.shutdown(wait=False)
        _executor = None


# ── Chat task ──────────────────────────────────────────────────

def submit_chat_task(task_id: str, jwt_token: str, message: str):
    """Submit a chat task for background execution."""
    get_executor().submit(_run_chat_task, task_id, jwt_token, message)


def _run_chat_task(task_id: str, jwt_token: str, message: str):
    """Execute a chat task by delegating to the Flask backend.

    1. Mark task as processing in DB + Redis.
    2. Call Flask async chat endpoint, which creates its own ChatTask.
    3. Stream events from Flask into our Redis buffer.
    4. Mark task completed/failed.
    """
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if not task:
                logger.error("ChatTask %s not found", task_id)
                return

            task.status = "processing"
            task.started_at = _now()
            session.flush()

            redis_buffer.ct_set_status(task_id, "processing")
            redis_buffer.ct_push_event(task_id, {
                "type": "start",
                "conversation_id": task.conversation_id,
                "agent_type": task.agent_type,
            })

            conversation_id = task.conversation_id if task.conversation_id else None
            agent_type = task.agent_type

        _delegate_to_flask(task_id, jwt_token, message, agent_type, conversation_id)

    except Exception as e:
        logger.exception("ChatTask %s failed", task_id)
        _fail_task(task_id, str(e)[:500])


def _delegate_to_flask(
    task_id: str,
    jwt_token: str,
    message: str,
    agent_type: str,
    conversation_id: int | None,
):
    """Call Flask's async chat endpoint and mirror events into our Redis buffer."""
    try:
        flask_result = flask_client.create_chat_task(
            jwt_token=jwt_token,
            message=message,
            agent_type=agent_type,
            conversation_id=conversation_id,
        )
        flask_task_id = flask_result.get("task_id")
        if not flask_task_id:
            raise RuntimeError("Flask did not return a task_id")

        for event in flask_client.stream_chat_task(jwt_token, flask_task_id):
            redis_buffer.ct_push_event(task_id, event)

            evt_type = event.get("type")
            if evt_type == "route":
                _update_routed_agent(task_id, event.get("agent_type"))
            elif evt_type == "done":
                _complete_task(
                    task_id,
                    result_message_id=event.get("message_id"),
                    routed_agent=event.get("agent_type"),
                )
                return
            elif evt_type == "error":
                _fail_task(task_id, event.get("message", "Agent error"))
                return

        _complete_task(task_id)

    except Exception as e:
        logger.exception("Flask delegation failed for task %s", task_id)
        redis_buffer.ct_push_event(task_id, {
            "type": "error",
            "message": "Agent execution failed. Please try again.",
        })
        _fail_task(task_id, str(e)[:500])


def _update_routed_agent(task_id: str, agent_type: str | None):
    if not agent_type:
        return
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if task:
                task.routed_agent = agent_type
        redis_buffer.ct_set_status(task_id, "processing", agent_type)
    except Exception as e:
        logger.warning("Failed to update routed_agent for %s: %s", task_id, e)


def _complete_task(
    task_id: str,
    result_message_id: int | None = None,
    routed_agent: str | None = None,
):
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if task:
                task.status = "completed"
                task.completed_at = _now()
                if result_message_id:
                    task.result_message_id = result_message_id
                if routed_agent:
                    task.routed_agent = routed_agent
        redis_buffer.ct_set_status(task_id, "completed", routed_agent)
    except Exception as e:
        logger.error("Failed to mark task %s completed: %s", task_id, e)


def _fail_task(task_id: str, error: str = "Unknown error"):
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if task:
                task.status = "failed"
                task.error_detail = error
                task.completed_at = _now()
        redis_buffer.ct_push_event(task_id, {"type": "error", "message": error})
        redis_buffer.ct_set_status(task_id, "failed")
    except Exception as e:
        logger.error("Failed to mark task %s failed: %s", task_id, e)


# ── Workflow ───────────────────────────────────────────────────

def submit_workflow(run_id: str, jwt_token: str, goal: str, context: dict | None = None):
    """Submit a workflow run for background execution."""
    get_executor().submit(_run_workflow, run_id, jwt_token, goal, context)


def _run_workflow(run_id: str, jwt_token: str, goal: str, context: dict | None = None):
    """Execute a workflow by delegating to Flask's Supervisor endpoint.

    Flask's POST /api/v1/ai/workflows invokes SupervisorAgent which plans
    and executes through the WorkflowEngine.  We mirror status/events into
    our Redis buffer so the agent_host SSE stream stays live.
    """
    try:
        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if not run:
                logger.error("WorkflowRun %s not found", run_id)
                return

            run.status = "executing"
            run.started_at = _now()
            session.flush()

        redis_buffer.wf_set_status(run_id, "executing")
        redis_buffer.wf_push_event(run_id, {
            "type": "workflow_start",
            "workflow_id": run_id,
        })

        flask_result = flask_client.create_workflow(
            jwt_token=jwt_token,
            goal=goal,
            context=context,
        )

        flask_status = flask_result.get("status", "unknown")
        flask_events = flask_result.get("events", [])
        flask_run_id = flask_result.get("workflow_run_id")

        for evt in flask_events:
            redis_buffer.wf_push_event(run_id, evt)

        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if not run:
                return

            if flask_run_id:
                run.chat_task_id = flask_run_id

            if flask_status in ("completed", "failed", "cancelled", "waiting_approval"):
                run.status = flask_status
                run.completed_at = _now() if flask_status != "waiting_approval" else None
                run.result = flask_result.get("result")
                if flask_result.get("error"):
                    run.error_detail = flask_result["error"]
            else:
                run.status = "completed"
                run.completed_at = _now()
                run.result = flask_result.get("result")

            if flask_status == "waiting_approval":
                redis_buffer.wf_set_status(run_id, "waiting_approval")
                redis_buffer.wf_push_event(run_id, {
                    "type": "workflow_waiting_approval",
                    "workflow_id": run_id,
                    "flask_run_id": flask_run_id,
                })
            elif flask_status == "failed":
                _fail_workflow(run_id, flask_result.get("error", "Workflow failed"))
            else:
                _complete_workflow(run_id, result=flask_result.get("result"))

    except Exception as e:
        logger.exception("WorkflowRun %s failed", run_id)
        _fail_workflow(run_id, str(e)[:500])


def _complete_workflow(run_id: str, result: dict | None = None):
    try:
        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at = _now()
                if result:
                    run.result = result
        redis_buffer.wf_push_event(run_id, {
            "type": "workflow_done",
            "workflow_id": run_id,
        })
        redis_buffer.wf_set_status(run_id, "completed")
    except Exception as e:
        logger.error("Failed to complete workflow %s: %s", run_id, e)


def _fail_workflow(run_id: str, error: str = "Unknown error"):
    try:
        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if run:
                run.status = "failed"
                run.error_detail = error
                run.completed_at = _now()
        redis_buffer.wf_push_event(run_id, {
            "type": "workflow_error",
            "message": error,
        })
        redis_buffer.wf_set_status(run_id, "failed")
    except Exception as e:
        logger.error("Failed to mark workflow %s failed: %s", run_id, e)
