"""Flask workflow route tests for the Agent Host collapse."""

from unittest.mock import patch

from app.core.extensions import db
from app.models.workflow import WorkflowRun


def test_create_workflow_persists_run_and_submits_worker(
    client, db_session, mock_auth_teacher
):
    payload = {
        "goal": "Generate a binary-search problem",
        "workflow_type": "general",
        "steps": [
            {
                "step_type": "agent_call",
                "agent_type": "generator",
                "instruction": "Draft the problem",
                "risk_level": "low",
                "requires_approval": False,
            }
        ],
        "language": "python",
        "difficulty": "medium",
        "topic": "binary search",
    }

    with patch("workers.workflow.submit_workflow") as submit_workflow:
        response = client.post("/api/v1/ai/workflows", json=payload)

    assert response.status_code == 202
    data = response.get_json()
    run = db.session.get(WorkflowRun, data["workflow_id"])
    assert data == {"workflow_id": run.id, "status": "planning"}
    assert run.user_id == mock_auth_teacher.id
    assert run.goal == payload["goal"]
    assert run.total_steps == 1
    assert run.plan_json["steps"][0]["instruction"] == "Draft the problem"
    assert submit_workflow.call_count == 1


def test_list_workflows_returns_current_user_runs(client, db_session, mock_auth_teacher):
    owned = WorkflowRun(
        id="owned-workflow",
        user_id=mock_auth_teacher.id,
        goal="owned",
        workflow_type="general",
        status="planning",
    )
    other = WorkflowRun(
        id="other-workflow",
        user_id=mock_auth_teacher.id + 100,
        goal="other",
        workflow_type="general",
        status="planning",
    )
    db_session.add_all([owned, other])
    db_session.commit()

    response = client.get("/api/v1/ai/workflows")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert [run["id"] for run in data["workflows"]] == ["owned-workflow"]


def test_get_workflow_returns_run_and_steps(client, db_session, mock_auth_teacher):
    from app.models.workflow import WorkflowStep

    run = WorkflowRun(
        id="workflow-with-step",
        user_id=mock_auth_teacher.id,
        goal="with step",
        workflow_type="general",
        status="planning",
    )
    step = WorkflowStep(
        id="workflow-with-step-0",
        workflow_run_id=run.id,
        step_index=0,
        step_type="agent_call",
        instruction="do it",
        status="pending",
    )
    db_session.add_all([run, step])
    db_session.commit()

    response = client.get(f"/api/v1/ai/workflows/{run.id}")

    assert response.status_code == 200
    data = response.get_json()
    assert data["run"]["id"] == run.id
    assert data["steps"][0]["instruction"] == "do it"


def test_stream_workflow_is_sse(client, db_session, mock_auth_teacher):
    run = WorkflowRun(
        id="stream-workflow",
        user_id=mock_auth_teacher.id,
        goal="stream",
        workflow_type="general",
        status="completed",
    )
    db_session.add(run)
    db_session.commit()

    response = client.get(f"/api/v1/ai/workflows/{run.id}/stream")

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert b"[DONE]" in response.data
