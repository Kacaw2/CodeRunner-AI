"""T6 (Phase 4): bounded resume — continue from the step after the last completed one.

The engine supports resuming an interrupted run from its last completed step. It
does NOT replay already-completed steps and does not promise arbitrary-step replay
(that is deferred to Phase 6). ``recovery.py`` keeps failing orphaned runs on
startup; this resume is an explicit, opt-in continuation.
"""


def _seed_partial_run(db_session, user_id, run_id):
    """A 3-step run where step 0 completed, steps 1-2 never ran (failed/orphaned)."""
    from domain.models.workflow import WorkflowRun, WorkflowStep

    plan = {
        "goal": "partial",
        "workflow_type": "general",
        "steps": [
            {"step_index": 0, "step_type": "resume_done", "instruction": "did 0"},
            {"step_index": 1, "step_type": "resume_run", "instruction": "do 1"},
            {"step_index": 2, "step_type": "resume_run", "instruction": "do 2"},
        ],
    }
    run = WorkflowRun(
        id=run_id,
        user_id=user_id,
        goal="partial",
        workflow_type="general",
        status="failed",
        current_step_index=1,
        total_steps=3,
        plan_json=plan,
    )
    db_session.add(run)
    db_session.add(WorkflowStep(
        id=f"{run_id}-s0", workflow_run_id=run_id, step_index=0,
        step_type="resume_done", instruction="did 0",
        status="completed", output_data={"success": True, "value": "step0"},
    ))
    db_session.add(WorkflowStep(
        id=f"{run_id}-s1", workflow_run_id=run_id, step_index=1,
        step_type="resume_run", instruction="do 1", status="failed",
        error_detail="Server restart during execution",
    ))
    db_session.add(WorkflowStep(
        id=f"{run_id}-s2", workflow_run_id=run_id, step_index=2,
        step_type="resume_run", instruction="do 2", status="pending",
    ))
    db_session.commit()
    return run


def test_resume_continues_after_last_completed_step(app, db_session, teacher_user):
    with app.app_context():
        from ai.graph.engine import WorkflowEngine
        from ai.graph.node_registry import register_step_handler
        from domain.models.workflow import WorkflowRun, WorkflowStep

        ran: list[int] = []

        def _done(_step_def, _context):
            ran.append(_step_def["step_index"])
            return {"success": True}

        def _run(step_def, _context):
            ran.append(step_def["step_index"])
            return {"success": True, "value": f"step{step_def['step_index']}"}

        register_step_handler("resume_done", _done)
        register_step_handler("resume_run", _run)

        _seed_partial_run(db_session, teacher_user.id, "resume-run")

        engine = WorkflowEngine()
        state = engine.resume_from_last_completed_step("resume-run")

        assert state["status"] == "completed"
        # Step 0 was already completed -> not re-run. Only 1 and 2 execute.
        assert ran == [1, 2]

        run = db_session.get(WorkflowRun, "resume-run")
        assert run.status == "completed"

        from sqlalchemy import select

        steps = list(
            db_session.execute(
                select(WorkflowStep)
                .where(WorkflowStep.workflow_run_id == "resume-run")
                .order_by(WorkflowStep.step_index)
            ).scalars()
        )
        assert [s.status for s in steps] == ["completed", "completed", "completed"]


def test_resume_rejects_finished_run(app, db_session, teacher_user):
    with app.app_context():
        from ai.graph.engine import WorkflowEngine
        from domain.models.workflow import WorkflowRun

        db_session.add(WorkflowRun(
            id="done-run", user_id=teacher_user.id, goal="g",
            workflow_type="general", status="completed", total_steps=0,
        ))
        db_session.commit()

        result = WorkflowEngine().resume_from_last_completed_step("done-run")
        assert result["status"] == "completed"
        assert "already finished" in result["error"]


def test_resume_rejects_waiting_approval_run(app, db_session, teacher_user):
    with app.app_context():
        from ai.graph.engine import WorkflowEngine
        from domain.models.workflow import WorkflowRun

        db_session.add(WorkflowRun(
            id="gated-run", user_id=teacher_user.id, goal="g",
            workflow_type="general", status="waiting_approval",
            current_step_index=0, total_steps=1,
        ))
        db_session.commit()

        result = WorkflowEngine().resume_from_last_completed_step("gated-run")
        assert result["status"] == "error"
        assert "human gate" in result["error"]


def test_resume_re_gates_downstream_approval_step(app, db_session, teacher_user):
    """A not-yet-completed downstream step that requires approval re-pauses the run."""
    with app.app_context():
        from ai.graph.engine import WorkflowEngine
        from ai.graph.node_registry import register_step_handler
        from domain.models.workflow import WorkflowRun, WorkflowStep

        register_step_handler("resume_done", lambda _s, _c: {"success": True})

        plan = {
            "goal": "gate-after-resume",
            "workflow_type": "general",
            "steps": [
                {"step_index": 0, "step_type": "resume_done", "instruction": "did 0"},
                {"step_index": 1, "step_type": "human_gate",
                 "instruction": "approve", "requires_approval": True},
            ],
        }
        db_session.add(WorkflowRun(
            id="regate-run", user_id=teacher_user.id, goal="gate-after-resume",
            workflow_type="general", status="failed", current_step_index=1,
            total_steps=2, plan_json=plan,
        ))
        db_session.add(WorkflowStep(
            id="regate-s0", workflow_run_id="regate-run", step_index=0,
            step_type="resume_done", instruction="did 0", status="completed",
            output_data={"success": True},
        ))
        db_session.add(WorkflowStep(
            id="regate-s1", workflow_run_id="regate-run", step_index=1,
            step_type="human_gate", instruction="approve", status="pending",
            requires_approval=True,
        ))
        db_session.commit()

        state = WorkflowEngine().resume_from_last_completed_step("regate-run")

        assert state["status"] == "waiting_approval"
        run = db_session.get(WorkflowRun, "regate-run")
        assert run.status == "waiting_approval"
        assert run.current_step_index == 1
