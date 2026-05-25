"""
Workflow execution engine — runs plans step-by-step with persistence and retry.

Responsibilities:
- Persists WorkflowRun and WorkflowStep records
- Dispatches each step to the appropriate handler via the registry
- Handles retries, errors, and human-gate pauses
- Tracks tokens and latency
- Emits events for SSE streaming
"""

import logging
import time
from uuid import uuid4

from app.agents.workflow.registry import get_step_handler
from app.agents.workflow.state import WorkflowPlan, WorkflowState

logger = logging.getLogger(__name__)

MAX_WORKFLOW_STEPS = 10
DEFAULT_TIMEOUT_SECONDS = 300


class WorkflowEngine:
    """Executes a structured workflow plan with full persistence."""

    def __init__(self, session=None):
        self._events: list[dict] = []
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        from app.core.extensions import db
        return db.session

    @property
    def events(self) -> list[dict]:
        return self._events

    def execute(
        self,
        plan: WorkflowPlan,
        user_id: int,
        user_role: str,
        conversation_id: int = None,
        chat_task_id: str = None,
        workflow_run_id: str = None,
    ) -> WorkflowState:
        """Execute a complete workflow plan and return final state."""
        from app.core.timezone import now_china
        from app.models.workflow import WorkflowRun, WorkflowStep

        session = self._get_session()
        run_id = workflow_run_id or str(uuid4())
        steps_def = plan.get("steps", [])

        if len(steps_def) > MAX_WORKFLOW_STEPS:
            steps_def = steps_def[:MAX_WORKFLOW_STEPS]

        workflow_run = session.get(WorkflowRun, run_id) if workflow_run_id else None
        if workflow_run is None:
            workflow_run = WorkflowRun(
                id=run_id,
                user_id=user_id,
                conversation_id=conversation_id,
                chat_task_id=chat_task_id,
            )
            session.add(workflow_run)
        else:
            (
                session.query(WorkflowStep)
                .filter_by(workflow_run_id=run_id)
                .delete(synchronize_session=False)
            )

        workflow_run.user_id = user_id
        workflow_run.conversation_id = conversation_id
        workflow_run.chat_task_id = chat_task_id
        workflow_run.goal = plan.get("goal", "")
        workflow_run.workflow_type = plan.get("workflow_type", "general")
        workflow_run.status = "executing"
        workflow_run.plan_json = plan
        workflow_run.current_step_index = 0
        workflow_run.total_steps = len(steps_def)
        workflow_run.result = None
        workflow_run.error_detail = None
        workflow_run.started_at = now_china()
        workflow_run.completed_at = None

        db_steps = []
        for step_def in steps_def:
            db_step = WorkflowStep(
                id=str(uuid4()),
                workflow_run_id=run_id,
                step_index=step_def.get("step_index", 0),
                step_type=step_def.get("step_type", "llm_call"),
                agent_type=step_def.get("agent_type"),
                instruction=step_def.get("instruction", ""),
                risk_level=step_def.get("risk_level", "low"),
                requires_approval=step_def.get("requires_approval", False),
                input_data=step_def.get("input_data"),
                depends_on=step_def.get("depends_on"),
            )
            session.add(db_step)
            db_steps.append(db_step)

        session.commit()

        self._emit("workflow_started", {"run_id": run_id, "total_steps": len(steps_def)})

        state: WorkflowState = {
            "workflow_run_id": run_id,
            "user_id": user_id,
            "user_role": user_role,
            "goal": plan.get("goal", ""),
            "workflow_type": plan.get("workflow_type", "general"),
            "plan": plan,
            "current_step_index": 0,
            "step_outputs": {},
            "status": "executing",
            "error": None,
            "final_result": None,
            "context": plan.get("context", {}),
        }

        context = {
            "user_id": user_id,
            "user_role": user_role,
            "step_outputs": state["step_outputs"],
            "agent_context": plan.get("context", {}),
            "workflow_run_id": run_id,
        }

        total_tokens = 0
        start_time = time.monotonic()

        for i, step_def in enumerate(steps_def):
            db_step = db_steps[i]
            state["current_step_index"] = i
            workflow_run.current_step_index = i

            if db_step.requires_approval:
                db_step.status = "waiting_approval"
                workflow_run.status = "waiting_approval"
                session.commit()
                self._emit("step_waiting_approval", {
                    "step_index": i,
                    "instruction": db_step.instruction,
                })
                state["status"] = "waiting_approval"
                break

            success = self._execute_step(db_step, step_def, context, state)
            total_tokens += db_step.tokens_used or 0

            if not success:
                workflow_run.status = "failed"
                workflow_run.error_detail = db_step.error_detail
                workflow_run.completed_at = now_china()
                workflow_run.total_tokens_used = total_tokens
                workflow_run.total_latency_ms = int((time.monotonic() - start_time) * 1000)
                session.commit()
                state["status"] = "failed"
                state["error"] = db_step.error_detail
                self._emit("workflow_failed", {"run_id": run_id, "error": db_step.error_detail})
                return state

        if state["status"] != "waiting_approval":
            workflow_run.status = "completed"
            workflow_run.completed_at = now_china()
            workflow_run.result = state["step_outputs"]
            workflow_run.total_tokens_used = total_tokens
            workflow_run.total_latency_ms = int((time.monotonic() - start_time) * 1000)
            session.commit()
            state["status"] = "completed"
            state["final_result"] = state["step_outputs"]
            self._emit("workflow_completed", {"run_id": run_id})

        return state

    def resume_after_approval(self, workflow_run_id: str, approved: bool, feedback: str = "") -> WorkflowState:
        """Resume a workflow that was paused at a human_gate step."""
        from app.core.timezone import now_china
        from app.models.workflow import WorkflowRun, WorkflowStep

        session = self._get_session()

        workflow_run = session.get(WorkflowRun, workflow_run_id)
        if not workflow_run or workflow_run.status != "waiting_approval":
            return {"status": "error", "error": "Workflow not in waiting_approval state"}

        current_index = workflow_run.current_step_index
        current_step = (
            session.query(WorkflowStep)
            .filter_by(workflow_run_id=workflow_run_id, step_index=current_index)
            .first()
        )

        if not approved:
            current_step.status = "failed"
            current_step.error_detail = f"Rejected: {feedback}" if feedback else "Rejected by user"
            current_step.completed_at = now_china()
            workflow_run.status = "cancelled"
            workflow_run.completed_at = now_china()
            workflow_run.error_detail = "Cancelled at human gate"
            session.commit()
            return {"status": "cancelled", "error": "Workflow cancelled by user"}

        current_step.status = "completed"
        current_step.output_data = {"approved": True, "feedback": feedback}
        current_step.completed_at = now_china()

        plan = workflow_run.plan_json
        steps_def = plan.get("steps", [])
        remaining_steps = steps_def[current_index + 1:]

        if not remaining_steps:
            workflow_run.status = "completed"
            workflow_run.completed_at = now_china()
            session.commit()
            return {"status": "completed", "workflow_run_id": workflow_run_id}

        workflow_run.status = "executing"
        workflow_run.current_step_index = current_index + 1
        session.commit()

        all_db_steps = (
            session.query(WorkflowStep)
            .filter_by(workflow_run_id=workflow_run_id)
            .order_by(WorkflowStep.step_index)
            .all()
        )

        step_outputs = {}
        for s in all_db_steps:
            if s.output_data and s.status == "completed":
                step_outputs[s.step_index] = s.output_data

        context = {
            "user_id": workflow_run.user_id,
            "user_role": "teacher",
            "step_outputs": step_outputs,
            "agent_context": plan.get("context", {}),
            "workflow_run_id": workflow_run_id,
        }

        state: WorkflowState = {
            "workflow_run_id": workflow_run_id,
            "user_id": workflow_run.user_id,
            "user_role": "teacher",
            "goal": workflow_run.goal,
            "workflow_type": workflow_run.workflow_type,
            "plan": plan,
            "current_step_index": current_index + 1,
            "step_outputs": step_outputs,
            "status": "executing",
            "error": None,
            "final_result": None,
            "context": plan.get("context", {}),
        }

        for step_def in remaining_steps:
            idx = step_def.get("step_index", 0)
            db_step = next((s for s in all_db_steps if s.step_index == idx), None)
            if not db_step:
                continue

            if db_step.requires_approval:
                db_step.status = "waiting_approval"
                workflow_run.status = "waiting_approval"
                workflow_run.current_step_index = idx
                session.commit()
                state["status"] = "waiting_approval"
                return state

            success = self._execute_step(db_step, step_def, context, state)
            if not success:
                workflow_run.status = "failed"
                workflow_run.error_detail = db_step.error_detail
                workflow_run.completed_at = now_china()
                session.commit()
                state["status"] = "failed"
                state["error"] = db_step.error_detail
                return state

        workflow_run.status = "completed"
        workflow_run.completed_at = now_china()
        workflow_run.result = state["step_outputs"]
        session.commit()
        state["status"] = "completed"
        state["final_result"] = state["step_outputs"]
        return state

    def _execute_step(self, db_step, step_def: dict, context: dict, state: WorkflowState) -> bool:
        """Execute a single workflow step with retry logic. Returns True on success."""
        from app.core.timezone import now_china

        session = self._get_session()
        step_type = step_def.get("step_type", "llm_call")
        handler = get_step_handler(step_type)

        if not handler:
            db_step.status = "failed"
            db_step.error_detail = f"No handler for step_type: {step_type}"
            db_step.completed_at = now_china()
            session.commit()
            self._emit("step_failed", {
                "step_index": db_step.step_index,
                "error": db_step.error_detail,
            })
            return False

        max_attempts = db_step.max_attempts or 2
        last_error = None

        for attempt in range(max_attempts):
            db_step.status = "running"
            db_step.attempt = attempt + 1
            db_step.started_at = now_china()
            session.commit()

            self._emit("step_started", {
                "step_index": db_step.step_index,
                "step_type": step_type,
                "agent_type": db_step.agent_type,
                "attempt": attempt + 1,
            })

            step_start = time.monotonic()

            try:
                enriched_def = dict(step_def)
                enriched_def["input_data"] = db_step.input_data
                context["step_outputs"] = state["step_outputs"]

                output = handler(enriched_def, context)

                latency = int((time.monotonic() - step_start) * 1000)
                db_step.latency_ms = latency

                if output.get("success") is False:
                    last_error = output.get("error", "Step returned success=False")
                    if attempt < max_attempts - 1:
                        logger.warning("Step %d failed (attempt %d): %s",
                                       db_step.step_index, attempt + 1, last_error)
                        continue
                    db_step.status = "failed"
                    db_step.error_detail = last_error
                    db_step.completed_at = now_china()
                    session.commit()
                    self._emit("step_failed", {
                        "step_index": db_step.step_index,
                        "error": last_error,
                    })
                    return False

                db_step.status = "completed"
                db_step.output_data = output
                db_step.completed_at = now_china()
                session.commit()

                state["step_outputs"][db_step.step_index] = output
                self._emit("step_completed", {
                    "step_index": db_step.step_index,
                    "latency_ms": latency,
                })
                return True

            except Exception as e:
                last_error = str(e)
                logger.warning("Step %d exception (attempt %d): %s",
                               db_step.step_index, attempt + 1, e)
                if attempt < max_attempts - 1:
                    time.sleep(1)
                    continue

                db_step.status = "failed"
                db_step.error_detail = last_error
                db_step.completed_at = now_china()
                session.commit()
                self._emit("step_failed", {
                    "step_index": db_step.step_index,
                    "error": last_error,
                })
                return False

        return False

    def _emit(self, event_type: str, data: dict):
        event = {"type": event_type, **data}
        self._events.append(event)
        logger.info("WORKFLOW_EVENT: %s %s", event_type, data)
