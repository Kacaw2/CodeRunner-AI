"""Tests for Supervisor workflow persistence behavior."""


def test_workflow_engine_can_execute_into_existing_run(app, db_session, teacher_user):
    with app.app_context():
        from graph.engine import WorkflowEngine
        from graph.node_registry import register_step_handler
        from app.models.workflow import WorkflowRun, WorkflowStep

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
        assert WorkflowRun.query.count() == 1
        assert WorkflowStep.query.filter_by(workflow_run_id=run.id).count() == 1

        db_session.refresh(run)
        assert run.goal == "new goal"
        assert run.status == "completed"
        assert run.total_steps == 1
