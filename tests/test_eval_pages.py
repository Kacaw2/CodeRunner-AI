"""Tests for the eval page route and eval report/case API (Task 10)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from domain.models.observability import EvalRun
from domain.models.observability import EvalCaseRun, EvalCaseGraderResult
from core.db.session import db_session


def _seed_run() -> tuple[int, str]:
    """Seed one eval run with a failed, trace-bound case; return (run_id, trace_id)."""
    trace_id = "trace-eval-page-1"
    with db_session() as session:
        run = EvalRun(
            suite_name="tutor",
            model_name="deepseek-chat",
            total_cases=1,
            passed_cases=0,
            pass_rate=0.0,
        )
        session.add(run)
        session.flush()
        run_id = run.id

        case = EvalCaseRun(
            eval_run_id=run_id,
            case_id="tutor::page-1",
            case_type="golden",
            suite="tutor",
            agent_type="tutor",
            trace_id=trace_id,
            status="failed",
            passed=False,
            failure_type="grader_failed",
            cost_cny=Decimal("0.02"),
            duration_ms=1200,
        )
        session.add(case)
        session.flush()
        session.add(
            EvalCaseGraderResult(
                case_run_id=case.id,
                grader_type="deterministic",
                grader_name="contains",
                passed=False,
                score=0.0,
                reason="missing keyword",
            )
        )
        return run_id, trace_id


def test_evals_page_renders(client, teacher_user):
    with patch("app.auth.web_decorators._get_web_user", return_value=teacher_user):
        resp = client.get("/ai/evals")
    assert resp.status_code == 200
    assert b"Agent Evals" in resp.data
    assert b"evals.js" in resp.data


def test_eval_run_report_endpoint(client, mock_auth_teacher):
    run_id, _ = _seed_run()
    resp = client.get(f"/api/v1/ai/evals/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["eval_run_id"] == run_id
    assert "pass_rate" in body["summary"]
    assert "failure_types" in body["summary"]
    assert len(body["cases"]) == 1


def test_eval_case_by_trace_endpoint(client, mock_auth_teacher):
    _, trace_id = _seed_run()
    resp = client.get(f"/api/v1/ai/evals/cases/by-trace/{trace_id}")
    assert resp.status_code == 200
    case = resp.get_json()["case"]
    assert case is not None
    assert case["case_id"] == "tutor::page-1"
    assert case["passed"] is False
    assert case["graders"][0]["grader_type"] == "deterministic"


def test_eval_case_by_trace_missing_returns_null(client, mock_auth_teacher):
    resp = client.get("/api/v1/ai/evals/cases/by-trace/does-not-exist")
    assert resp.status_code == 200
    assert resp.get_json()["case"] is None
