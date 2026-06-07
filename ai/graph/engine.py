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

from ai.graph.handoff import HANDOFF_SUMMARY_LIMIT
from ai.graph.node_registry import get_step_handler
from ai.graph.state import WorkflowPlan, WorkflowState

logger = logging.getLogger(__name__)

MAX_WORKFLOW_STEPS = 10
DEFAULT_TIMEOUT_SECONDS = 300


def _summarize_step_outputs(full_outputs: dict) -> dict:
    """Truncated, read-only view of upstream outputs for steps with no declared deps.

    A step that declares no ``depends_on`` (and no ``validates_step``) must not see
    the full residue of every prior step. It gets a per-step truncated string
    instead, aligned with the agent-handoff summary limit, so downstream context
    stays bounded.
    """
    summary: dict = {}
    for idx, output in full_outputs.items():
        text = str(output)
        if len(text) > HANDOFF_SUMMARY_LIMIT:
            text = text[:HANDOFF_SUMMARY_LIMIT] + "…[truncated]"
        summary[idx] = text
    return summary


def select_step_outputs(step_def: dict, full_outputs: dict) -> dict:
    """Build the upstream-output view a step is allowed to see.

    Only outputs the step declares a dependency on (``depends_on`` plus the
    ``validates_step`` a validation step targets) are passed through in full —
    by reference, so existing in-place mutation behavior is preserved. A step
    with no declared dependency gets a truncated summary instead of the full
    residue, never the raw upstream dict.
    """
    allowed = set(step_def.get("depends_on") or [])
    validates = step_def.get("validates_step")
    if validates is not None:
        allowed.add(validates)

    if allowed:
        return {idx: full_outputs[idx] for idx in allowed if idx in full_outputs}
    return _summarize_step_outputs(full_outputs)


class WorkflowEngine:
    """Executes a structured workflow plan with full persistence."""

    def __init__(self, session=None, repository=None):
        from domain.repositories.workflows import SyncWorkflowRepository

        self._events: list[dict] = []
        if repository is None:
            if session is None:
                from core.db.session import get_session

                session = get_session()
            repository = SyncWorkflowRepository(session)
        self._repository = repository
        self._session = repository.session

    def _get_session(self):
        return self._session

    def _transition_run(self, run, new_status: str, expected_status=None, **values):
        expected = run.status if expected_status is None else expected_status
        if not self._repository.transition_run(
            run.id, expected, new_status, **values
        ):
            raise RuntimeError(
                f"WorkflowRun {run.id} state changed while transitioning "
                f"{expected!r} -> {new_status!r}"
            )

    def _transition_step(self, step, new_status: str, expected_status=None, **values):
        expected = step.status if expected_status is None else expected_status
        if not self._repository.transition_step(
            step.id, expected, new_status, **values
        ):
            raise RuntimeError(
                f"WorkflowStep {step.id} state changed while transitioning "
                f"{expected!r} -> {new_status!r}"
            )

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
        session = self._get_session()
        run_id = workflow_run_id or str(uuid4())
        steps_def = plan.get("steps", [])

        if len(steps_def) > MAX_WORKFLOW_STEPS:
            steps_def = steps_def[:MAX_WORKFLOW_STEPS]

        workflow_run = (
            self._repository.get_run(run_id) if workflow_run_id else None
        )
        if workflow_run is None:
            workflow_run = self._repository.create_run(
                id=run_id,
                user_id=user_id,
                conversation_id=conversation_id,
                chat_task_id=chat_task_id,
                goal=plan.get("goal", ""),
                workflow_type=plan.get("workflow_type", "general"),
                status="executing",
            )
        else:
            self._repository.replace_steps(run_id, [])

        workflow_run.user_id = user_id
        workflow_run.conversation_id = conversation_id
        workflow_run.chat_task_id = chat_task_id
        workflow_run.goal = plan.get("goal", "")
        workflow_run.workflow_type = plan.get("workflow_type", "general")
        workflow_run.plan_json = plan
        workflow_run.current_step_index = 0
        workflow_run.total_steps = len(steps_def)
        workflow_run.result = None
        workflow_run.error_detail = None
        workflow_run.started_at = now_china()
        workflow_run.completed_at = None
        session.flush()
        if workflow_run.status != "executing":
            self._transition_run(
                workflow_run,
                "executing",
                expected_status=("planning", "failed"),
                started_at=workflow_run.started_at,
                completed_at=None,
                error_detail=None,
            )

        db_steps = []
        for step_def in steps_def:
            db_step = self._repository.create_step(
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
        timeout_seconds = workflow_run.timeout_seconds or DEFAULT_TIMEOUT_SECONDS

        for i, step_def in enumerate(steps_def):
            db_step = db_steps[i]
            state["current_step_index"] = i
            workflow_run.current_step_index = i

            elapsed = time.monotonic() - start_time
            if elapsed > timeout_seconds:
                error_detail = (
                    f"Workflow exceeded timeout of {timeout_seconds}s before step {i}"
                )
                self._transition_run(
                    workflow_run,
                    "failed",
                    expected_status="executing",
                    error_detail=error_detail,
                    completed_at=now_china(),
                    total_tokens_used=total_tokens,
                    total_latency_ms=int(elapsed * 1000),
                )
                session.commit()
                state["status"] = "failed"
                state["error"] = error_detail
                self._emit("workflow_failed", {"run_id": run_id, "error": error_detail})
                return state

            if db_step.requires_approval:
                self._transition_step(
                    db_step, "waiting_approval", expected_status="pending"
                )
                self._transition_run(
                    workflow_run, "waiting_approval", expected_status="executing"
                )
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
                self._transition_run(
                    workflow_run,
                    "failed",
                    expected_status="executing",
                    error_detail=db_step.error_detail,
                    completed_at=now_china(),
                    total_tokens_used=total_tokens,
                    total_latency_ms=int((time.monotonic() - start_time) * 1000),
                )
                session.commit()
                state["status"] = "failed"
                state["error"] = db_step.error_detail
                self._emit("workflow_failed", {"run_id": run_id, "error": db_step.error_detail})
                return state

        if state["status"] != "waiting_approval":
            self._transition_run(
                workflow_run,
                "completed",
                expected_status="executing",
                completed_at=now_china(),
                result=state["step_outputs"],
                total_tokens_used=total_tokens,
                total_latency_ms=int((time.monotonic() - start_time) * 1000),
            )
            session.commit()
            state["status"] = "completed"
            state["final_result"] = state["step_outputs"]
            self._emit("workflow_completed", {"run_id": run_id})

        return state

    def resume_after_approval(
        self,
        workflow_run_id: str,
        approved: bool,
        feedback: str = "",
        approver_user_id: int | None = None,
    ) -> WorkflowState:
        """Resume a workflow that was paused at a human_gate step."""
        from app.core.timezone import now_china
        session = self._get_session()

        workflow_run = self._repository.get_run(workflow_run_id)
        if not workflow_run or workflow_run.status != "waiting_approval":
            return {"status": "error", "error": "Workflow not in waiting_approval state"}

        current_index = workflow_run.current_step_index
        current_step = self._repository.get_step(workflow_run_id, current_index)

        # Immutable audit record of the decision (approver, decision, feedback).
        # The authoritative approval trail lives here, not in step.output_data.
        self._repository.add_approval(
            workflow_run_id=workflow_run_id,
            step_index=current_index,
            approver_user_id=approver_user_id,
            decision="approved" if approved else "rejected",
            feedback=feedback or None,
        )

        if not approved:
            self._transition_step(
                current_step,
                "failed",
                expected_status="waiting_approval",
                error_detail=(
                    f"Rejected: {feedback}" if feedback else "Rejected by user"
                ),
                completed_at=now_china(),
            )
            self._transition_run(
                workflow_run,
                "cancelled",
                expected_status="waiting_approval",
                completed_at=now_china(),
                error_detail="Cancelled at human gate",
            )
            session.commit()
            return {"status": "cancelled", "error": "Workflow cancelled by user"}

        self._transition_step(
            current_step,
            "completed",
            expected_status="waiting_approval",
            output_data={"approved": True},
            completed_at=now_china(),
        )

        plan = workflow_run.plan_json
        steps_def = plan.get("steps", [])
        remaining_steps = steps_def[current_index + 1:]

        if not remaining_steps:
            self._transition_run(
                workflow_run,
                "completed",
                expected_status="waiting_approval",
                completed_at=now_china(),
            )
            session.commit()
            return {"status": "completed", "workflow_run_id": workflow_run_id}

        self._transition_run(
            workflow_run, "executing", expected_status="waiting_approval"
        )
        workflow_run.current_step_index = current_index + 1
        session.commit()

        all_db_steps = self._repository.list_steps(workflow_run_id)

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

        return self._run_remaining_steps(
            workflow_run, remaining_steps, all_db_steps, context, state)

    def resume_from_last_completed_step(
        self,
        workflow_run_id: str,
        user_role: str = "teacher",
    ) -> WorkflowState:
        """Resume an interrupted run from the step after its last completed one.

        This is the bounded "resume from breakpoint" semantics for Phase 4: it
        rebuilds ``step_outputs`` from already-completed steps and continues at
        ``last_completed + 1``. It deliberately does NOT replay arbitrary steps
        (that needs step idempotency, deferred to Phase 6) and does not re-run any
        step already marked completed. ``recovery.py`` still fails orphaned runs on
        startup; this is an explicit, opt-in continuation, not an automatic one.
        """
        from app.core.timezone import now_china
        session = self._get_session()

        workflow_run = self._repository.get_run(workflow_run_id)
        if not workflow_run:
            return {"status": "error", "error": "Workflow run not found"}
        if workflow_run.status in ("completed", "cancelled"):
            return {"status": workflow_run.status,
                    "error": "Workflow already finished; nothing to resume"}
        if workflow_run.status == "waiting_approval":
            return {"status": "error",
                    "error": "Run is at a human gate; use resume_after_approval"}

        plan = workflow_run.plan_json or {}
        steps_def = plan.get("steps", [])

        all_db_steps = self._repository.list_steps(workflow_run_id)

        completed = [s for s in all_db_steps if s.status == "completed"]
        last_completed = max((s.step_index for s in completed), default=-1)
        resume_index = last_completed + 1

        step_outputs = {
            s.step_index: s.output_data for s in completed if s.output_data
        }

        remaining_steps = [
            sd for sd in steps_def if sd.get("step_index", 0) >= resume_index
        ]

        if not remaining_steps:
            self._transition_run(
                workflow_run,
                "completed",
                expected_status=("planning", "executing", "failed"),
                completed_at=now_china(),
                result=step_outputs,
            )
            session.commit()
            return {"status": "completed", "workflow_run_id": workflow_run_id}

        # Clear stale state on not-yet-completed steps so they execute cleanly.
        for s in all_db_steps:
            if s.step_index >= resume_index and s.status != "completed":
                self._transition_step(
                    s,
                    "pending",
                    expected_status=s.status,
                    error_detail=None,
                    completed_at=None,
                )

        self._transition_run(
            workflow_run,
            "executing",
            expected_status=workflow_run.status,
            error_detail=None,
            completed_at=None,
        )
        workflow_run.current_step_index = resume_index
        session.commit()

        context = {
            "user_id": workflow_run.user_id,
            "user_role": user_role,
            "step_outputs": step_outputs,
            "agent_context": plan.get("context", {}),
            "workflow_run_id": workflow_run_id,
        }

        state: WorkflowState = {
            "workflow_run_id": workflow_run_id,
            "user_id": workflow_run.user_id,
            "user_role": user_role,
            "goal": workflow_run.goal,
            "workflow_type": workflow_run.workflow_type,
            "plan": plan,
            "current_step_index": resume_index,
            "step_outputs": step_outputs,
            "status": "executing",
            "error": None,
            "final_result": None,
            "context": plan.get("context", {}),
        }

        return self._run_remaining_steps(
            workflow_run, remaining_steps, all_db_steps, context, state)

    def _run_remaining_steps(
        self, workflow_run, remaining_steps, all_db_steps, context, state: WorkflowState
    ) -> WorkflowState:
        """Execute the tail of a plan, shared by both resume paths.

        Re-gates any not-yet-completed step that requires approval, fails the run
        on the first failing step, and otherwise marks it completed. Already
        completed steps are never re-run (they are not in ``remaining_steps``).
        """
        from app.core.timezone import now_china

        session = self._get_session()

        for step_def in remaining_steps:
            idx = step_def.get("step_index", 0)
            db_step = next((s for s in all_db_steps if s.step_index == idx), None)
            if not db_step:
                continue

            if db_step.requires_approval and db_step.status != "completed":
                self._transition_step(
                    db_step,
                    "waiting_approval",
                    expected_status=db_step.status,
                )
                self._transition_run(
                    workflow_run,
                    "waiting_approval",
                    expected_status="executing",
                )
                workflow_run.current_step_index = idx
                session.commit()
                state["status"] = "waiting_approval"
                return state

            success = self._execute_step(db_step, step_def, context, state)
            if not success:
                self._transition_run(
                    workflow_run,
                    "failed",
                    expected_status="executing",
                    error_detail=db_step.error_detail,
                    completed_at=now_china(),
                )
                session.commit()
                state["status"] = "failed"
                state["error"] = db_step.error_detail
                return state

        self._transition_run(
            workflow_run,
            "completed",
            expected_status="executing",
            completed_at=now_china(),
            result=state["step_outputs"],
        )
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
            error_detail = f"No handler for step_type: {step_type}"
            self._transition_step(
                db_step,
                "failed",
                expected_status=db_step.status,
                error_detail=error_detail,
                completed_at=now_china(),
            )
            session.commit()
            self._emit("step_failed", {
                "step_index": db_step.step_index,
                "error": error_detail,
            })
            return False

        max_attempts = db_step.max_attempts or 2
        last_error = None

        for attempt in range(max_attempts):
            self._transition_step(
                db_step,
                "running",
                expected_status=db_step.status,
                attempt=attempt + 1,
                started_at=now_china(),
            )
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
                context["step_outputs"] = select_step_outputs(step_def, state["step_outputs"])
                context["step_index"] = db_step.step_index

                output = handler(enriched_def, context)

                latency = int((time.monotonic() - step_start) * 1000)
                db_step.latency_ms = latency

                if output.get("success") is False:
                    last_error = output.get("error", "Step returned success=False")
                    if attempt < max_attempts - 1:
                        logger.warning("Step %d failed (attempt %d): %s",
                                       db_step.step_index, attempt + 1, last_error)
                        continue
                    self._transition_step(
                        db_step,
                        "failed",
                        expected_status="running",
                        error_detail=last_error,
                        completed_at=now_china(),
                    )
                    session.commit()
                    self._emit("step_failed", {
                        "step_index": db_step.step_index,
                        "error": last_error,
                    })
                    return False

                from ai.graph.critic import WorkflowCritic
                criteria = step_def.get("validation_criteria", "")
                verdict = WorkflowCritic().validate_step(
                    step_type, db_step.agent_type, output, criteria)

                if not verdict.get("passed", True) and attempt < max_attempts - 1:
                    last_error = "; ".join(verdict.get("issues", [])) or "critic rejected output"
                    context["critic_feedback"] = last_error  # next attempt's handler can read this
                    logger.info("Step %d rejected by critic (attempt %d): %s",
                                db_step.step_index, attempt + 1, last_error)
                    self._emit("step_critic_rejected", {
                        "step_index": db_step.step_index,
                        "issues": verdict.get("issues", []),
                    })
                    continue

                self._transition_step(
                    db_step,
                    "completed",
                    expected_status="running",
                    output_data={**output, "critic": verdict},
                    trace_id=output.get("trace_id"),
                    completed_at=now_china(),
                    latency_ms=latency,
                )
                session.commit()

                state["step_outputs"][db_step.step_index] = output
                self._emit("step_completed", {
                    "step_index": db_step.step_index,
                    "latency_ms": latency,
                    "critic_score": verdict.get("score"),
                })
                return True

            except Exception as e:
                last_error = str(e)
                logger.warning("Step %d exception (attempt %d): %s",
                               db_step.step_index, attempt + 1, e)
                if attempt < max_attempts - 1:
                    time.sleep(1)
                    continue

                self._transition_step(
                    db_step,
                    "failed",
                    expected_status="running",
                    error_detail=last_error,
                    completed_at=now_china(),
                )
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
