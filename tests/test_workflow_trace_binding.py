"""T1 (Phase 4): workflow step <-> agent trace bidirectional binding.

Verifies that:
- the engine injects ``workflow_run_id`` + ``step_index`` into each step's context,
- the engine persists each step's returned ``trace_id`` onto ``workflow_steps.trace_id``,
- an agent run inside a workflow records its owning ``workflow_run_id`` on the trace.
"""

from sqlalchemy import select


def test_engine_persists_step_trace_id_and_injects_context(app, db_session, teacher_user):
    with app.app_context():
        from graph.engine import WorkflowEngine
        from graph.node_registry import register_step_handler
        from app.models.workflow import WorkflowStep

        seen = {}

        def _capture(step_def, context):
            seen["workflow_run_id"] = context.get("workflow_run_id")
            seen["step_index"] = context.get("step_index")
            return {"success": True, "trace_id": "trace-step-0"}

        register_step_handler("capture_trace", _capture)

        engine = WorkflowEngine()
        state = engine.execute(
            plan={
                "goal": "bind trace",
                "workflow_type": "general",
                "steps": [{
                    "step_index": 0,
                    "step_type": "capture_trace",
                    "instruction": "run",
                }],
            },
            user_id=teacher_user.id,
            user_role="teacher",
            workflow_run_id="trace-bind-run",
        )

        assert state["status"] == "completed"
        # Context injection reached the handler.
        assert seen["workflow_run_id"] == "trace-bind-run"
        assert seen["step_index"] == 0

        step = WorkflowStep.query.filter_by(workflow_run_id="trace-bind-run", step_index=0).first()
        assert step is not None
        assert step.trace_id == "trace-step-0"


def test_agent_call_binds_workflow_run_to_trace(app, db_session, teacher_user, monkeypatch):
    """An agent_call step records workflow_run_id on its agent trace, and the step
    records that trace_id back — closing the workflow <-> trace loop without an LLM."""
    with app.app_context():
        from graph.engine import WorkflowEngine
        from graph import runner as runner_module
        from app.models.workflow import WorkflowStep
        from core.db.models.agent_trace import AgentTraceRun
        import core.db.session as core_session

        captured_state = {}

        class _FakeAgent:
            def invoke(self, state):
                # Mirror AgentRuntime: open a real trace seeded with link keys
                # pulled from the agent state's context (workflow_run_id lives there).
                from core.observability.tracing import acquire_trace, finalize_trace
                from agents.base import _trace_links_from_state

                captured_state["context"] = dict(state.get("context", {}))
                trace, owns = acquire_trace(
                    agent_type=state.get("agent_type", "tutor"),
                    user_id=state.get("user_id", 0),
                    links=_trace_links_from_state(state),
                    input_message="hi",
                    input_context=state.get("context"),
                )
                finalize_trace(trace, owns, status="completed", response="done")
                return {"final_response": "done", "trace_id": trace.run_id}

        monkeypatch.setitem(runner_module._AGENTS, "tutor", _FakeAgent())

        engine = WorkflowEngine()
        state = engine.execute(
            plan={
                "goal": "agent trace bind",
                "workflow_type": "general",
                "steps": [{
                    "step_index": 0,
                    "step_type": "agent_call",
                    "agent_type": "tutor",
                    "instruction": "tutor please",
                }],
            },
            user_id=teacher_user.id,
            user_role="teacher",
            workflow_run_id="agent-trace-run",
        )

        assert state["status"] == "completed"

        # The agent saw workflow_run_id + step_index in its context.
        assert captured_state["context"].get("workflow_run_id") == "agent-trace-run"
        assert captured_state["context"].get("step_index") == 0

        step = WorkflowStep.query.filter_by(workflow_run_id="agent-trace-run", step_index=0).first()
        assert step is not None and step.trace_id

        # Forward: the persisted trace carries the owning workflow_run_id, and its
        # trace_id matches what the step recorded.
        with core_session._SessionLocal() as s:
            trace_row = s.execute(
                select(AgentTraceRun).where(AgentTraceRun.trace_id == step.trace_id)
            ).scalar_one_or_none()

        assert trace_row is not None
        assert trace_row.workflow_run_id == "agent-trace-run"
