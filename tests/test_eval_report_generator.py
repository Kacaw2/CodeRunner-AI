"""Tests for the eval report generator and regression comparison (Task 8)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.models.observability import EvalRun
from domain.models.observability import EvalCaseRun, EvalCaseGraderResult
from core.db.session import db_session


def _seed_run(
    *,
    suite: str,
    cases: list[dict],
) -> int:
    """Insert one EvalRun plus its case/grader rows; return the eval_run_id."""
    with db_session() as session:
        run = EvalRun(
            suite_name=suite,
            model_name="deepseek-chat",
            total_cases=len(cases),
            passed_cases=sum(1 for c in cases if c["passed"]),
            pass_rate=(sum(1 for c in cases if c["passed"]) / len(cases)) if cases else 0.0,
        )
        session.add(run)
        session.flush()
        run_id = run.id

        for c in cases:
            case_run = EvalCaseRun(
                eval_run_id=run_id,
                case_id=c["case_id"],
                case_type=c.get("case_type", "golden"),
                suite=suite,
                agent_type=c.get("agent_type", "tutor"),
                trace_id=c.get("trace_id"),
                status=c["status"],
                passed=c["passed"],
                failure_type=c.get("failure_type"),
                tokens_input=c.get("tokens_input", 100),
                tokens_output=c.get("tokens_output", 50),
                cost_cny=Decimal(str(c.get("cost_cny", "0.01"))),
                duration_ms=c.get("duration_ms", 1000),
            )
            session.add(case_run)
            session.flush()
            for g in c.get("graders", []):
                session.add(
                    EvalCaseGraderResult(
                        case_run_id=case_run.id,
                        grader_type=g["grader_type"],
                        grader_name=g.get("grader_name", "g"),
                        passed=g["passed"],
                        score=g.get("score"),
                        reason=g.get("reason", ""),
                    )
                )
        return run_id


@pytest.mark.usefixtures("app", "db_session")
def test_report_contains_quality_cost_latency_and_regression():
    from evals.reports.generator import ReportGenerator

    report = ReportGenerator().build(eval_run_id=1, compare_to_eval_run_id=0)

    assert "pass_rate" in report.summary
    assert "cost_cny" in report.summary
    assert "latency_ms" in report.summary
    assert "failure_types" in report.summary
    assert "regressions" in report.summary


@pytest.mark.usefixtures("app", "db_session")
def test_report_computes_metrics_from_seeded_run():
    from evals.reports.generator import ReportGenerator

    run_id = _seed_run(
        suite="tutor",
        cases=[
            {
                "case_id": "tutor::1",
                "status": "passed",
                "passed": True,
                "duration_ms": 1000,
                "cost_cny": "0.02",
                "graders": [{"grader_type": "deterministic", "passed": True, "score": 1.0}],
            },
            {
                "case_id": "tutor::2",
                "status": "failed",
                "passed": False,
                "failure_type": "grader_failed",
                "duration_ms": 3000,
                "cost_cny": "0.04",
                "graders": [{"grader_type": "deterministic", "passed": False, "score": 0.0}],
            },
        ],
    )

    report = ReportGenerator().build(eval_run_id=run_id, compare_to_eval_run_id=0)

    assert report.summary["total_cases"] == 2
    assert report.summary["pass_rate"] == 0.5
    assert report.summary["failure_types"].get("grader_failed") == 1
    assert report.summary["cost_cny"]["total"] == pytest.approx(0.06)
    assert report.summary["latency_ms"]["total"] == 4000
    # one deterministic grader passed, one failed -> 0.5 pass rate
    assert report.summary["grader_pass_rates"]["deterministic"] == 0.5
    assert report.summary["regressions"] == []
    assert len(report.cases) == 2


@pytest.mark.usefixtures("app", "db_session")
def test_report_detects_regressions_against_previous_run():
    from evals.reports.generator import ReportGenerator

    baseline_id = _seed_run(
        suite="tutor",
        cases=[
            {"case_id": "tutor::1", "status": "passed", "passed": True},
            {"case_id": "tutor::2", "status": "passed", "passed": True},
        ],
    )
    current_id = _seed_run(
        suite="tutor",
        cases=[
            {"case_id": "tutor::1", "status": "passed", "passed": True},
            {
                "case_id": "tutor::2",
                "status": "failed",
                "passed": False,
                "failure_type": "grader_failed",
            },
        ],
    )

    report = ReportGenerator().build(
        eval_run_id=current_id, compare_to_eval_run_id=baseline_id
    )

    regressions = report.summary["regressions"]
    assert any(r["case_id"] == "tutor::2" for r in regressions)
    # a case that stayed passing must NOT be a regression
    assert all(r["case_id"] != "tutor::1" for r in regressions)


@pytest.mark.usefixtures("app", "db_session")
def test_report_renders_markdown():
    from evals.reports.generator import ReportGenerator

    run_id = _seed_run(
        suite="tutor",
        cases=[{"case_id": "tutor::1", "status": "passed", "passed": True}],
    )
    report = ReportGenerator().build(eval_run_id=run_id, compare_to_eval_run_id=0)

    md = report.to_markdown()
    assert "# Eval Report" in md
    assert "tutor" in md
    payload = report.to_dict()
    assert payload["summary"]["pass_rate"] == 1.0
