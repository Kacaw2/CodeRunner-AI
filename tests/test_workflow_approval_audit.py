"""T2 (Phase 4): human-gate decisions produce an immutable approval audit record.

The approver identity + decision + feedback live in ``workflow_approvals``, not in
``WorkflowStep.output_data``. Both approve and reject paths leave a trail.
"""

from sqlalchemy import select


def _seed_gated_run(db_session, user_id, run_id):
    from domain.models.workflow import WorkflowRun, WorkflowStep

    run = WorkflowRun(
        id=run_id,
        user_id=user_id,
        goal="needs approval",
        workflow_type="general",
        status="waiting_approval",
        current_step_index=0,
        total_steps=1,
        plan_json={
            "goal": "needs approval",
            "workflow_type": "general",
            "steps": [{
                "step_index": 0,
                "step_type": "human_gate",
                "instruction": "approve this?",
                "requires_approval": True,
            }],
        },
    )
    db_session.add(run)
    db_session.add(WorkflowStep(
        id=f"{run_id}-step-0",
        workflow_run_id=run_id,
        step_index=0,
        step_type="human_gate",
        instruction="approve this?",
        status="waiting_approval",
        requires_approval=True,
    ))
    db_session.commit()
    return run


def test_approval_creates_audit_record(app, db_session, teacher_user):
    with app.app_context():
        from graph.engine import WorkflowEngine
        from domain.models.workflow import WorkflowApproval, WorkflowStep

        run = _seed_gated_run(db_session, teacher_user.id, "approve-run")

        engine = WorkflowEngine()
        state = engine.resume_after_approval(
            "approve-run", approved=True, feedback="looks good",
            approver_user_id=teacher_user.id,
        )

        assert state["status"] == "completed"

        approval = db_session.execute(
            select(WorkflowApproval).where(
                WorkflowApproval.workflow_run_id == "approve-run"
            )
        ).scalar_one()
        assert approval.decision == "approved"
        assert approval.approver_user_id == teacher_user.id
        assert approval.feedback == "looks good"
        assert approval.step_index == 0

        # Feedback is NOT the step output trail anymore.
        step = db_session.execute(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == "approve-run",
                WorkflowStep.step_index == 0,
            )
        ).scalar_one()
        assert step.status == "completed"
        assert "feedback" not in (step.output_data or {})


def test_rejection_is_also_audited(app, db_session, teacher_user):
    with app.app_context():
        from graph.engine import WorkflowEngine
        from domain.models.workflow import WorkflowApproval, WorkflowRun

        _seed_gated_run(db_session, teacher_user.id, "reject-run")

        engine = WorkflowEngine()
        state = engine.resume_after_approval(
            "reject-run", approved=False, feedback="not acceptable",
            approver_user_id=teacher_user.id,
        )

        assert state["status"] == "cancelled"

        approval = db_session.execute(
            select(WorkflowApproval).where(
                WorkflowApproval.workflow_run_id == "reject-run"
            )
        ).scalar_one()
        assert approval.decision == "rejected"
        assert approval.approver_user_id == teacher_user.id
        assert approval.feedback == "not acceptable"

        run = db_session.get(WorkflowRun, "reject-run")
        assert run.status == "cancelled"
