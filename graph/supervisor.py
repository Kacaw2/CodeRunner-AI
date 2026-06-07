"""
SupervisorAgent — the top-level coordinator for multi-agent workflows.

Responsibilities:
1. Receives a user goal (from chat or direct API)
2. Invokes the planner to produce a structured plan
3. Hands the plan to the WorkflowEngine for execution
4. Returns the final result or status (for async/human-gate flows)

The Supervisor does NOT execute steps itself — it delegates planning and
execution to dedicated components, maintaining separation of concerns.
"""

import logging

from graph.engine import WorkflowEngine
from graph.planner import create_plan
from graph.state import WorkflowState

logger = logging.getLogger(__name__)


# ── Entry-point boundary (T4) ──────────────────────────────────
#
# The single decision for "multi-step task -> WorkflowEngine" vs
# "single conversational turn -> orchestrator/harness". This is the one place
# that classifies a chat message, so the boundary lives in code, not scattered
# heuristics.
#
# Boundary rule:
#   * A single conversational turn (one user message -> one answer, allowing the
#     bounded <= MAX_HANDOFFS intra-turn specialist delegation) stays on the
#     streaming/sync agent path (AgentOrchestrator / AgentHarness). Intra-turn
#     handoff is delegation, NOT a multi-step workflow.
#   * Only an explicit multi-step task (teacher problem generation pipeline,
#     "generate then review", batch/multi operations, or anything requiring a
#     human gate) escalates to WorkflowEngine, where it gains trace/approval/
#     resume coverage.
#
# Interactive request/response endpoints (/ai/chat, /ai/chat/stream) deliberately
# do NOT escalate to workflow: a multi-step plan would block the request. Only
# the async chat worker consults this function and may escalate.

_GENERATION_TRIGGERS = (
    "生成", "出题", "创建题目", "generate", "create problem",
    "create a problem", "出一道", "新题",
)

_MULTI_STEP_TRIGGERS = (
    "然后", "接着", "之后", "and then", "followed by",
    "批量", "batch", "多个", "multiple",
)


def should_use_workflow(message: str, user_role: str) -> bool:
    """Classify whether a chat message warrants a multi-step workflow.

    Returns True for messages that should escalate to ``WorkflowEngine``
    (teacher generation requests, explicit multi-step phrasing, batch ops);
    False for single conversational turns that the orchestrator/harness handles
    (including bounded intra-turn handoff). See the module boundary note above.
    """
    msg_lower = message.lower()

    if user_role == "teacher" and any(t in msg_lower for t in _GENERATION_TRIGGERS):
        return True

    return any(t in msg_lower for t in _MULTI_STEP_TRIGGERS)


class SupervisorAgent:
    """Orchestrates multi-step workflows by planning then executing."""

    name = "supervisor"
    description = "Coordinates multi-agent workflows via structured planning and execution"

    def __init__(self, session=None):
        self._session = session

    def run_workflow(
        self,
        user_id: int,
        user_role: str,
        goal: str,
        context: dict = None,
        conversation_id: int = None,
        chat_task_id: str = None,
        workflow_run_id: str = None,
    ) -> WorkflowState:
        """Plan and execute a workflow for the given goal.

        Returns the final WorkflowState which includes status, outputs, and events.
        """
        logger.info("Supervisor starting workflow: user=%d goal=%.80s", user_id, goal)

        plan = create_plan(goal, user_role, context)
        if not plan:
            logger.error("Planner returned no plan for goal: %s", goal)
            return {
                "workflow_run_id": None,
                "user_id": user_id,
                "user_role": user_role,
                "goal": goal,
                "workflow_type": "unknown",
                "plan": None,
                "current_step_index": 0,
                "step_outputs": {},
                "status": "failed",
                "error": "Failed to generate execution plan",
                "final_result": None,
                "context": context or {},
            }

        logger.info("Plan generated: type=%s steps=%d",
                    plan.get("workflow_type"), len(plan.get("steps", [])))

        engine = WorkflowEngine(session=self._session)
        state = engine.execute(
            plan=plan,
            user_id=user_id,
            user_role=user_role,
            conversation_id=conversation_id,
            chat_task_id=chat_task_id,
            workflow_run_id=workflow_run_id,
        )

        state["_events"] = engine.events
        return state

    def resume_workflow(
        self,
        workflow_run_id: str,
        approved: bool,
        feedback: str = "",
        approver_user_id: int | None = None,
    ) -> WorkflowState:
        """Resume a workflow paused at a human gate."""
        logger.info("Supervisor resuming workflow %s: approved=%s", workflow_run_id, approved)
        engine = WorkflowEngine(session=self._session)
        return engine.resume_after_approval(
            workflow_run_id, approved, feedback, approver_user_id=approver_user_id
        )

    def get_workflow_status(self, workflow_run_id: str) -> dict:
        """Query current status of a workflow run."""
        from core.db.session import get_session
        from domain.repositories.workflows import SyncWorkflowRepository

        session = self._session or get_session()
        repo = SyncWorkflowRepository(session)
        run = repo.get_run(workflow_run_id)
        if not run:
            return {"error": "Workflow not found"}
        steps = repo.list_steps(workflow_run_id)

        return {
            "run": run.to_dict(),
            "steps": [s.to_dict() for s in steps],
        }

    def invoke_from_chat(
        self,
        user_id: int,
        user_role: str,
        message: str,
        conversation_id: int = None,
        chat_task_id: str = None,
        context: dict = None,
    ) -> dict:
        """Entry point when called from the chat system.

        Determines if the message warrants a multi-step workflow or should be
        handled by the simple orchestrator. Returns a dict with either the
        workflow result or a flag to fall through to single-agent handling.
        """
        if not self._should_use_workflow(message, user_role):
            return {"use_workflow": False}

        state = self.run_workflow(
            user_id=user_id,
            user_role=user_role,
            goal=message,
            context=context,
            conversation_id=conversation_id,
            chat_task_id=chat_task_id,
        )

        return {
            "use_workflow": True,
            "workflow_run_id": state.get("workflow_run_id"),
            "status": state.get("status"),
            "result": state.get("final_result"),
            "error": state.get("error"),
            "events": state.get("_events", []),
        }

    @staticmethod
    def _should_use_workflow(message: str, user_role: str) -> bool:
        """Back-compat shim — delegates to the module-level boundary function."""
        return should_use_workflow(message, user_role)
