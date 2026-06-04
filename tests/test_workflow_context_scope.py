"""T5 (Phase 4): downstream steps only see declared-dependency upstream outputs.

``select_step_outputs`` trims the residue passed to a step's handler to exactly
its ``depends_on`` (plus the ``validates_step`` a validation targets). Steps with
no declared dependency get a bounded summary instead of the full upstream dict.
"""

from graph.engine import select_step_outputs
from graph.handoff import HANDOFF_SUMMARY_LIMIT


def test_depends_on_passes_only_declared_upstream_in_full():
    full = {0: {"problem_data": {"x": 1}}, 1: {"v": True}, 2: {"dup": False}}

    view = select_step_outputs({"step_index": 3, "depends_on": [0]}, full)

    assert set(view.keys()) == {0}
    # Same object reference — in-place mutation behavior is preserved.
    assert view[0] is full[0]


def test_multiple_declared_dependencies_all_passed():
    full = {0: {"a": 1}, 1: {"b": 2}, 2: {"c": 3}}

    view = select_step_outputs({"depends_on": [0, 2]}, full)

    assert set(view.keys()) == {0, 2}


def test_validates_step_is_an_implicit_dependency():
    full = {0: {"review": "text"}, 1: {"other": "noise"}}

    view = select_step_outputs({"validates_step": 0}, full)

    assert set(view.keys()) == {0}
    assert view[0] is full[0]


def test_no_declared_dependency_gets_summary_not_full_residue():
    full = {0: {"problem_data": {"x": 1}}, 1: {"secret_residue": "y"}}

    view = select_step_outputs({"step_index": 0}, full)

    # Values are truncated strings, never the raw upstream dicts.
    assert view[0] != full[0]
    assert isinstance(view[0], str)
    assert isinstance(view[1], str)


def test_summary_truncates_to_handoff_limit():
    full = {0: {"blob": "z" * (HANDOFF_SUMMARY_LIMIT * 2)}}

    view = select_step_outputs({}, full)

    assert len(view[0]) <= HANDOFF_SUMMARY_LIMIT + len("…[truncated]")
    assert view[0].endswith("…[truncated]")


def test_missing_upstream_index_is_skipped():
    full = {0: {"a": 1}}

    # Declares a dependency that has not produced output yet.
    view = select_step_outputs({"depends_on": [0, 5]}, full)

    assert set(view.keys()) == {0}


def test_engine_trims_step_outputs_end_to_end(app, db_session, teacher_user):
    with app.app_context():
        from graph.engine import WorkflowEngine
        from graph.node_registry import register_step_handler

        seen: dict[int, dict] = {}

        def _producer(_step_def, _context):
            return {"success": True, "payload": "upstream-data"}

        def _dependent(step_def, context):
            seen[step_def["step_index"]] = dict(context.get("step_outputs", {}))
            return {"success": True}

        register_step_handler("scope_producer", _producer)
        register_step_handler("scope_dependent", _dependent)

        engine = WorkflowEngine()
        state = engine.execute(
            plan={
                "goal": "scope",
                "workflow_type": "general",
                "steps": [
                    {"step_index": 0, "step_type": "scope_producer", "instruction": "make"},
                    {"step_index": 1, "step_type": "scope_dependent",
                     "instruction": "needs 0", "depends_on": [0]},
                    {"step_index": 2, "step_type": "scope_dependent",
                     "instruction": "needs nothing"},
                ],
            },
            user_id=teacher_user.id,
            user_role="teacher",
            workflow_run_id="scope-run",
        )

        assert state["status"] == "completed"

        # Step 1 declared depends_on [0]: sees step 0's full output.
        assert 0 in seen[1]
        assert seen[1][0].get("payload") == "upstream-data"

        # Step 2 declared no deps: sees only a truncated summary, not the raw dict.
        assert isinstance(seen[2].get(0), str)
        assert 1 not in seen[2] or isinstance(seen[2].get(1), str)
