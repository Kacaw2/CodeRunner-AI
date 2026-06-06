"""Flask workflow worker lifecycle tests."""

from unittest.mock import patch

from app.core.extensions import db
from app.models.workflow import WorkflowRun


def _make_run(user_id: int) -> str:
    run = WorkflowRun(
        user_id=user_id,
        goal="Generate a binary-search problem",
        workflow_type="general",
        status="planning",
        plan_json={"goal": "g", "steps": []},
        total_steps=0,
    )
    db.session.add(run)
    db.session.commit()
    return run.id


def test_worker_marks_run_completed(app, db_session, teacher_user):
    run_id = _make_run(teacher_user.id)

    fake_state = {
        "status": "completed",
        "final_result": {"ok": True},
        "_events": [
            {"type": "workflow_start", "workflow_id": run_id},
        ],
    }

    from workers import workflow as wf

    with patch("graph.supervisor.SupervisorAgent") as mock_supervisor:
        mock_supervisor.return_value.run_workflow.return_value = fake_state
        wf._run_workflow(run_id, app, "g", None)

    run = db.session.get(WorkflowRun, run_id)
    assert run.status == "completed"
    assert run.result == {"ok": True}
    assert run.started_at is not None
    assert run.completed_at is not None


def test_worker_marks_run_failed_on_exception(app, db_session, teacher_user):
    run_id = _make_run(teacher_user.id)

    from workers import workflow as wf

    with patch("graph.supervisor.SupervisorAgent") as mock_supervisor:
        mock_supervisor.return_value.run_workflow.side_effect = RuntimeError("boom")
        wf._run_workflow(run_id, app, "g", None)

    run = db.session.get(WorkflowRun, run_id)
    assert run.status == "failed"
    assert "boom" in (run.error_detail or "")
