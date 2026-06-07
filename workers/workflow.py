"""Flask-native workflow worker for async Supervisor workflows."""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.core.extensions import db
from app.core.timezone import now_china
from workers import redis_buffer

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow-worker")


def submit_workflow(run_id: str, app, goal: str, context: dict | None = None):
    """Submit a workflow run to the thread pool for async execution."""
    return _executor.submit(_run_workflow, run_id, app, goal, context)


def _run_workflow(run_id: str, app, goal: str, context: dict | None = None):
    """Execute a workflow run inside a Flask app context."""
    with app.app_context():
        from domain.repositories.workflows import SyncWorkflowRepository

        repo = SyncWorkflowRepository(db.session)
        run = repo.get_run(run_id)
        if not run:
            logger.error("WorkflowRun %s not found", run_id)
            return

        if not repo.transition_run(
            run_id,
            "planning",
            "executing",
            started_at=now_china(),
            completed_at=None,
            error_detail=None,
        ):
            logger.info("WorkflowRun %s was already claimed", run_id)
            db.session.rollback()
            return
        db.session.commit()

        redis_buffer.wf_set_status(run_id, "executing")
        redis_buffer.wf_push_event(
            run_id,
            {
                "type": "workflow_start",
                "workflow_id": run_id,
            },
        )

        try:
            from app.models.user import User

            user = db.session.get(User, run.user_id)
            if user and hasattr(user.role, "value"):
                user_role = user.role.value
            elif user:
                user_role = str(user.role)
            else:
                user_role = "teacher"

            from mcp_gateway.client import (
                InProcessMCPToolClient,
                configure_mcp_client_from_env,
            )

            mcp_client = configure_mcp_client_from_env()
            if isinstance(mcp_client, InProcessMCPToolClient):
                from mcp_gateway.bootstrap import bootstrap_tool_runtime

                bootstrap_tool_runtime(session_factory=lambda: db.session)

            try:
                plan = run.plan_json if isinstance(run.plan_json, dict) else None
                if plan and plan.get("steps"):
                    from graph.engine import WorkflowEngine

                    state = WorkflowEngine(session=db.session).execute(
                        plan=plan,
                        user_id=run.user_id,
                        user_role=user_role,
                        conversation_id=run.conversation_id,
                        chat_task_id=run.chat_task_id,
                        workflow_run_id=run_id,
                    )
                else:
                    from graph.supervisor import SupervisorAgent

                    supervisor = SupervisorAgent(session=db.session)
                    state = supervisor.run_workflow(
                        user_id=run.user_id,
                        user_role=user_role,
                        goal=goal,
                        context=context,
                        conversation_id=run.conversation_id,
                        chat_task_id=run.chat_task_id,
                        workflow_run_id=run_id,
                    )

                for event in state.get("_events", []):
                    redis_buffer.wf_push_event(run_id, event)

                final_status = state.get("status", "completed")
                if final_status == "completed":
                    _complete_workflow(run_id, result=state.get("final_result"))
                elif final_status == "waiting_approval":
                    redis_buffer.wf_set_status(run_id, "waiting_approval")
                    redis_buffer.wf_push_event(
                        run_id,
                        {
                            "type": "workflow_waiting_approval",
                            "workflow_id": run_id,
                        },
                    )
                else:
                    _fail_workflow(run_id, state.get("error", "Workflow failed"))
            finally:
                from tools.protocol.runtime import reset_tool_runtime

                reset_tool_runtime()

        except Exception as exc:  # noqa: BLE001 - worker boundary persists failure.
            db.session.rollback()
            logger.exception("WorkflowRun %s failed", run_id)
            _fail_workflow(run_id, str(exc)[:500])


def _complete_workflow(run_id: str, result: dict | None = None):
    from domain.repositories.workflows import SyncWorkflowRepository

    repo = SyncWorkflowRepository(db.session)
    run = repo.get_run(run_id)
    if run:
        values = {"completed_at": now_china()}
        if result is not None:
            values["result"] = result
        repo.transition_run(
            run_id,
            ("executing", "completed"),
            "completed",
            **values,
        )
        db.session.commit()

    redis_buffer.wf_push_event(
        run_id,
        {
            "type": "workflow_done",
            "workflow_id": run_id,
        },
    )
    redis_buffer.wf_set_status(run_id, "completed")


def _fail_workflow(run_id: str, error: str = "Unknown error"):
    from domain.repositories.workflows import SyncWorkflowRepository

    repo = SyncWorkflowRepository(db.session)
    run = repo.get_run(run_id)
    if run:
        repo.transition_run(
            run_id,
            ("planning", "executing", "waiting_approval", "failed"),
            "failed",
            error_detail=error,
            completed_at=now_china(),
        )
        db.session.commit()

    redis_buffer.wf_push_event(
        run_id,
        {
            "type": "workflow_error",
            "workflow_id": run_id,
            "message": error,
        },
    )
    redis_buffer.wf_set_status(run_id, "failed")
