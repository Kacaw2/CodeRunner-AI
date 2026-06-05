"""Phase 8 CI/docs contract checks."""

from __future__ import annotations

from pathlib import Path


def test_tests_workflow_runs_pytest_and_js_syntax_checks():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "python -m pytest -q --tb=short" in workflow
    assert "node --check app/static/js/traces.js" in workflow
    assert "node --check app/static/js/evals.js" in workflow


def test_traces_mcp_tab_renders_current_tool_spans():
    traces_js = Path("app/static/js/traces.js").read_text(encoding="utf-8")

    assert "isMcpOrToolSpan" in traces_js
    assert "s.span_type === 'tool'" in traces_js
    assert "s.span_type === 'mcp'" in traces_js


def test_evals_workflow_uploads_full_report_artifacts():
    workflow = Path(".github/workflows/evals.yml").read_text(encoding="utf-8")

    assert "python -m evals.ci --use-harness --bootstrap-schema" in workflow
    assert "eval-report.json" in workflow
    assert "eval-report.md" in workflow
    assert "eval-regressions.json" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_architecture_docs_mark_observability_eval_loop_complete():
    docs = Path("docs/architecture/ai-agents.md").read_text(encoding="utf-8")

    assert "| 架构 Phase G | Observability 和评估闭环 | ✅ 完成 |" in docs
    assert "runtime-neutral" in docs
    assert "ReportGenerator" in docs
