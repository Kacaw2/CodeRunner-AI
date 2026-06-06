"""Phase 6 / Task 6: EvalHarness binds each case run to a trace.

The harness loads dataset cases, drives each one through an AgentHarness, reads
the resulting trace for cost/latency/tokens, runs graders, and persists
``EvalRun`` / ``EvalCaseRun`` / ``EvalCaseGraderResult`` rows through the
runtime-neutral ``core.db.session`` (never a Flask app context).
"""
import uuid
from decimal import Decimal

from core.db.session import db_session as core_db_session


class _FakeAgentHarness:
    """Stand-in for AgentHarness: writes a trace row and returns a result.

    Mirrors the real harness contract closely enough for the eval harness:
    it persists an ``AgentTraceRun`` (so cost/latency/token read-back works and
    eval links are bound) and returns an ``AgentResult``.
    """

    def __init__(
        self,
        response="Here is a small hint to guide your thinking.",
        status="completed",
        tokens_input=12,
        tokens_output=8,
        cost_cny=Decimal("0.0010"),
        latency_ms=42,
    ):
        self._response = response
        self._status = status
        self._ti = tokens_input
        self._to = tokens_output
        self._cost = cost_cny
        self._latency = latency_ms

    def run(self, *, agent_type, message, user_id, user_role,
            source="agent", context=None, budget=None, history=None):
        from core.db.models.agent_trace import AgentTraceRun
        from app.core.timezone import now_china
        from evals.harness.agent_harness import AgentResult

        context = context or {}
        trace_id = uuid.uuid4().hex
        with core_db_session() as session:
            session.add(AgentTraceRun(
                id=trace_id,
                trace_id=trace_id,
                source=source,
                status=self._status,
                agent_type=agent_type,
                user_id=user_id,
                conversation_id=context.get("conversation_id"),
                eval_run_id=context.get("eval_run_id"),
                eval_case_id=context.get("eval_case_id"),
                tokens_input=self._ti,
                tokens_output=self._to,
                cost_cny=self._cost,
                total_latency_ms=self._latency,
                started_at=now_china(),
                created_at=now_china(),
            ))
        return AgentResult(
            trace_id=trace_id,
            status=self._status,
            agent_type=agent_type,
            response=self._response,
        )


def test_eval_harness_creates_case_runs_with_trace_ids(app, db_session):
    from evals.harness.eval_harness import EvalHarness
    from app.models.eval_run import EvalRun
    from core.db.models.agent_trace import EvalCaseRun, EvalCaseGraderResult

    with app.app_context():
        report = EvalHarness(agent_harness=_FakeAgentHarness()).run(
            selector="golden:tutor",
            model_name="fake-model",
        )

        assert report.total > 0
        assert all(c.trace_id for c in report.case_results)
        assert all(
            c.status in {"passed", "failed", "error"}
            for c in report.case_results
        )

        with core_db_session() as session:
            run = session.query(EvalRun).filter_by(id=report.eval_run_id).one()
            assert run.suite_name
            assert run.total_cases == report.total

            case_runs = (
                session.query(EvalCaseRun)
                .filter_by(eval_run_id=report.eval_run_id)
                .all()
            )
            assert len(case_runs) == report.total
            assert all(cr.trace_id for cr in case_runs)

            case_run_ids = {cr.id for cr in case_runs}
            grader_rows = (
                session.query(EvalCaseGraderResult)
                .filter(EvalCaseGraderResult.case_run_id.in_(case_run_ids))
                .all()
            )
            assert len(grader_rows) >= 1
            assert all(g.grader_type for g in grader_rows)


def test_eval_harness_marks_budget_exceeded_on_token_overrun(app, db_session):
    from evals.harness.eval_harness import EvalHarness
    from core.db.models.agent_trace import EvalCaseRun

    fake = _FakeAgentHarness(tokens_input=5000, tokens_output=5000)

    with app.app_context():
        report = EvalHarness(agent_harness=fake).run(
            selector="golden:tutor",
            model_name="fake-model",
        )

        assert any(
            c.status == "budget_exceeded" and c.failure_type == "budget_exceeded"
            for c in report.case_results
        )

        with core_db_session() as session:
            rows = (
                session.query(EvalCaseRun)
                .filter_by(eval_run_id=report.eval_run_id, failure_type="budget_exceeded")
                .all()
            )
            assert rows
