"""Tests for Supervisor workflow persistence behavior."""

from sqlalchemy import func, select
from types import SimpleNamespace


def test_workflow_tool_call_grants_agent_scopes(monkeypatch):
    from graph.node_registry import _handle_tool_call

    captured = {}

    class FakeRuntime:
        def call_sync(self, tool_name, args, ctx):
            captured["tool_name"] = tool_name
            captured["args"] = args
            captured["ctx"] = ctx
            return SimpleNamespace(ok=True, data={"status": "ok"})

    monkeypatch.setattr(
        "tools.protocol.get_tool_runtime", lambda: FakeRuntime()
    )

    result = _handle_tool_call(
        {
            "tool_name": "coderunner.code.execute_internal",
            "tool_args": {"code": "print(2 + 2)", "language": "python"},
            "agent_type": "generator",
        },
        {"user_id": 2, "user_role": "teacher"},
    )

    assert result["success"] is True
    assert captured["ctx"].granted_scopes
    assert "code:execute_internal" in captured["ctx"].granted_scopes


def test_workflow_engine_can_execute_into_existing_run(app, db_session, teacher_user):
    with app.app_context():
        from graph.engine import WorkflowEngine
        from graph.node_registry import register_step_handler
        from domain.models.workflow import WorkflowRun, WorkflowStep

        run = WorkflowRun(
            id="existing-workflow-run",
            user_id=teacher_user.id,
            goal="old goal",
            workflow_type="general",
            status="planning",
            total_steps=0,
        )
        db_session.add(run)
        db_session.commit()

        register_step_handler(
            "test_noop",
            lambda _step_def, _context: {"success": True, "value": "ok"},
        )

        engine = WorkflowEngine()
        state = engine.execute(
            plan={
                "goal": "new goal",
                "workflow_type": "general",
                "steps": [{
                    "step_index": 0,
                    "step_type": "test_noop",
                    "instruction": "run this",
                }],
            },
            user_id=teacher_user.id,
            user_role="teacher",
            workflow_run_id=run.id,
        )

        assert state["workflow_run_id"] == run.id
        assert db_session.scalar(
            select(func.count()).select_from(WorkflowRun)
        ) == 1
        assert db_session.scalar(
            select(func.count())
            .select_from(WorkflowStep)
            .where(WorkflowStep.workflow_run_id == run.id)
        ) == 1

        db_session.refresh(run)
        assert run.goal == "new goal"
        assert run.status == "completed"
        assert run.total_steps == 1


def test_workflow_aborts_when_wall_clock_timeout_exceeded(
    app, db_session, teacher_user, monkeypatch
):
    with app.app_context():
        from graph import engine as engine_module
        from graph.engine import WorkflowEngine
        from graph.node_registry import register_step_handler
        from domain.models.workflow import WorkflowRun

        register_step_handler(
            "timeout_noop",
            lambda _step_def, _context: {"success": True, "value": "ok"},
        )

        # First monotonic() call sets start_time; the loop's elapsed check then
        # sees a clock that has jumped far past the workflow timeout.
        ticks = iter([0.0, 10_000.0])
        monkeypatch.setattr(engine_module.time, "monotonic", lambda: next(ticks))

        run = WorkflowRun(
            id="timeout-run",
            user_id=teacher_user.id,
            goal="slow goal",
            workflow_type="general",
            status="planning",
            total_steps=0,
            timeout_seconds=300,
        )
        db_session.add(run)
        db_session.commit()

        engine = WorkflowEngine()
        state = engine.execute(
            plan={
                "goal": "slow goal",
                "workflow_type": "general",
                "steps": [{
                    "step_index": 0,
                    "step_type": "timeout_noop",
                    "instruction": "run this",
                }],
            },
            user_id=teacher_user.id,
            user_role="teacher",
            workflow_run_id=run.id,
        )

        assert state["status"] == "failed"
        assert "timeout" in state["error"].lower()

        db_session.refresh(run)
        assert run.status == "failed"


class TestWorkflowCrashRecovery:
    def test_recovers_orphaned_workflow(self, app, db_session, teacher_user):
        with app.app_context():
            from domain.models.workflow import WorkflowRun, WorkflowStep
            from graph.recovery import recover_orphaned_workflows

            run = WorkflowRun(
                id="orphan-run",
                user_id=teacher_user.id,
                goal="interrupted goal",
                workflow_type="general",
                status="executing",
                total_steps=1,
            )
            db_session.add(run)
            db_session.add(WorkflowStep(
                id="orphan-step",
                workflow_run_id="orphan-run",
                step_index=0,
                step_type="llm_call",
                instruction="do work",
                status="running",
            ))
            db_session.commit()

            recovered = recover_orphaned_workflows()
            assert recovered == 1

            db_session.refresh(run)
            assert run.status == "failed"
            assert run.error_detail and "restart" in run.error_detail.lower()

            step = db_session.execute(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_run_id == "orphan-run"
                )
            ).scalar_one_or_none()
            assert step.status == "failed"

    def test_preserves_waiting_approval(self, app, db_session, teacher_user):
        with app.app_context():
            from domain.models.workflow import WorkflowRun
            from graph.recovery import recover_orphaned_workflows

            run = WorkflowRun(
                id="gated-run",
                user_id=teacher_user.id,
                goal="gated goal",
                workflow_type="general",
                status="waiting_approval",
                total_steps=1,
            )
            db_session.add(run)
            db_session.commit()

            recover_orphaned_workflows()

            db_session.refresh(run)
            assert run.status == "waiting_approval"


class TestPlannerFallback:
    def test_general_fallback_when_llm_returns_none(self, app, monkeypatch):
        with app.app_context():
            from graph import planner as planner_module

            monkeypatch.setattr(planner_module, "plan_with_llm", lambda *a, **k: None)

            plan = planner_module.create_plan("do something arbitrary", "student")

            assert plan is not None
            assert plan["workflow_type"] == "general"
            assert len(plan["steps"]) == 1
            assert plan["steps"][0]["step_type"] == "llm_call"
