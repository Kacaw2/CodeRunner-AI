"""Eval report generator (Phase 7, Task 8).

Reads persisted eval rows (``EvalRun`` / ``EvalCaseRun`` / ``EvalCaseGraderResult``)
through the runtime-neutral ``core.db.session`` and assembles a structured
:class:`EvalReport` covering quality, cost, latency, token distribution, failure
types, top failed cases, grader pass rates and — when a comparison run is given —
case-level regressions.

The report has no Flask dependency so it can run from CI (``evals/ci.py``) or be
shaped into an API payload by the web layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.db.models.agent_trace import (
    EvalRun,
    EvalCaseRun,
    EvalCaseGraderResult,
)
from core.db.session import db_session
from evals.reports.regression import detect_new_failures, detect_regressions


@dataclass
class EvalReport:
    eval_run_id: int
    summary: dict = field(default_factory=dict)
    cases: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "eval_run_id": self.eval_run_id,
            "summary": self.summary,
            "cases": self.cases,
        }

    def to_markdown(self) -> str:
        s = self.summary
        cost = s.get("cost_cny", {})
        lat = s.get("latency_ms", {})
        lines = [
            "# Eval Report",
            "",
            f"- Run: `{self.eval_run_id}` ({s.get('suite_name', '')})",
            f"- Model: `{s.get('model_name', '')}`",
            f"- Cases: {s.get('passed_cases', 0)}/{s.get('total_cases', 0)} "
            f"passed ({s.get('pass_rate', 0.0):.1%})",
            f"- Cost: total ¥{cost.get('total', 0.0):.4f}, "
            f"avg ¥{cost.get('avg', 0.0):.4f}, p95 ¥{cost.get('p95', 0.0):.4f}",
            f"- Latency: avg {lat.get('avg', 0)}ms, "
            f"p50 {lat.get('p50', 0)}ms, p95 {lat.get('p95', 0)}ms",
            "",
            "## Grader pass rates",
        ]
        grader_rates = s.get("grader_pass_rates", {})
        if grader_rates:
            for family, rate in sorted(grader_rates.items()):
                lines.append(f"- {family}: {rate:.1%}")
        else:
            lines.append("- (none)")

        lines += ["", "## Failure types"]
        failure_types = s.get("failure_types", {})
        if failure_types:
            for ft, count in sorted(failure_types.items()):
                lines.append(f"- {ft}: {count}")
        else:
            lines.append("- (none)")

        lines += ["", "## Regressions"]
        regressions = s.get("regressions", [])
        if regressions:
            for r in regressions:
                lines.append(f"- {r['case_id']} ({r.get('failure_type') or 'failed'})")
        else:
            lines.append("- (none)")

        top_failed = s.get("top_failed_cases", [])
        if top_failed:
            lines += ["", "## Top failed cases"]
            for c in top_failed:
                lines.append(
                    f"- {c['case_id']} [{c.get('failure_type') or 'failed'}] "
                    f"trace={c.get('trace_id') or '-'}"
                )
        return "\n".join(lines)


class ReportGenerator:
    """Build a structured :class:`EvalReport` from persisted eval rows."""

    def build(self, *, eval_run_id: int, compare_to_eval_run_id: int = 0) -> EvalReport:
        run, cases = self._load_run(eval_run_id)
        case_dicts = [self._case_to_dict(c) for c in cases]
        grader_rows = self._load_grader_rows(case_dicts)

        baseline_cases: list[dict] = []
        if compare_to_eval_run_id:
            _, base_cases = self._load_run(compare_to_eval_run_id)
            baseline_cases = [self._case_to_dict(c) for c in base_cases]

        summary = self._summarize(run, case_dicts, grader_rows, baseline_cases)
        return EvalReport(eval_run_id=eval_run_id, summary=summary, cases=case_dicts)

    # ── Loading ────────────────────────────────────────────────

    def _load_run(self, eval_run_id: int):
        with db_session() as session:
            run = session.query(EvalRun).filter_by(id=eval_run_id).first()
            cases = (
                session.query(EvalCaseRun)
                .filter_by(eval_run_id=eval_run_id)
                .order_by(EvalCaseRun.created_at)
                .all()
            )
            session.expunge_all()
            return run, cases

    def _load_grader_rows(self, case_dicts: list[dict]) -> list[dict]:
        case_run_ids = [c["case_run_id"] for c in case_dicts if c.get("case_run_id")]
        if not case_run_ids:
            return []
        with db_session() as session:
            rows = (
                session.query(EvalCaseGraderResult)
                .filter(EvalCaseGraderResult.case_run_id.in_(case_run_ids))
                .all()
            )
            return [
                {
                    "grader_type": r.grader_type,
                    "grader_name": r.grader_name,
                    "passed": r.passed,
                    "score": r.score,
                }
                for r in rows
            ]

    # ── Summarizing ────────────────────────────────────────────

    def _summarize(
        self,
        run,
        case_dicts: list[dict],
        grader_rows: list[dict],
        baseline_cases: list[dict],
    ) -> dict:
        total = len(case_dicts)
        passed = sum(1 for c in case_dicts if c.get("passed"))
        pass_rate = passed / total if total else 0.0

        costs = [c["cost_cny"] for c in case_dicts if c.get("cost_cny") is not None]
        latencies = [c["duration_ms"] for c in case_dicts if c.get("duration_ms") is not None]
        tokens_in = [c["tokens_input"] or 0 for c in case_dicts]
        tokens_out = [c["tokens_output"] or 0 for c in case_dicts]

        failure_types: dict[str, int] = {}
        for c in case_dicts:
            if c.get("passed"):
                continue
            ft = c.get("failure_type") or "failed"
            failure_types[ft] = failure_types.get(ft, 0) + 1

        regressions = detect_regressions(case_dicts, baseline_cases)
        new_failures = detect_new_failures(case_dicts, baseline_cases)

        top_failed = [
            {
                "case_id": c["case_id"],
                "suite": c.get("suite"),
                "failure_type": c.get("failure_type"),
                "trace_id": c.get("trace_id"),
            }
            for c in case_dicts
            if not c.get("passed")
        ][:10]

        return {
            "suite_name": getattr(run, "suite_name", None),
            "model_name": getattr(run, "model_name", None),
            "total_cases": total,
            "passed_cases": passed,
            "pass_rate": round(pass_rate, 4),
            "cost_cny": {
                "total": round(sum(costs), 6),
                "avg": round(sum(costs) / len(costs), 6) if costs else 0.0,
                "p95": round(_percentile(costs, 0.95), 6),
            },
            "latency_ms": {
                "total": sum(latencies),
                "avg": int(sum(latencies) / len(latencies)) if latencies else 0,
                "p50": int(_percentile(latencies, 0.50)),
                "p95": int(_percentile(latencies, 0.95)),
            },
            "tokens": {
                "input_total": sum(tokens_in),
                "output_total": sum(tokens_out),
                "avg_total": int((sum(tokens_in) + sum(tokens_out)) / total) if total else 0,
            },
            "grader_pass_rates": _grader_pass_rates(grader_rows),
            "failure_types": failure_types,
            "top_failed_cases": top_failed,
            "regressions": regressions,
            "new_failures": new_failures,
        }

    # ── Row shaping ────────────────────────────────────────────

    @staticmethod
    def _case_to_dict(c) -> dict:
        return {
            "case_run_id": c.id,
            "case_id": c.case_id,
            "case_type": c.case_type,
            "suite": c.suite,
            "agent_type": c.agent_type,
            "trace_id": c.trace_id,
            "status": c.status,
            "passed": bool(c.passed),
            "failure_type": c.failure_type,
            "tokens_input": c.tokens_input,
            "tokens_output": c.tokens_output,
            "cost_cny": float(c.cost_cny) if c.cost_cny is not None else None,
            "duration_ms": c.duration_ms,
        }


def _percentile(values: list, q: float) -> float:
    """Nearest-rank percentile; tolerant of empty input."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = q * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return float(ordered[lo]) + (float(ordered[hi]) - float(ordered[lo])) * frac


def _grader_pass_rates(grader_rows: list[dict]) -> dict[str, float]:
    """Pass rate per grader family (deterministic / static_checks / ...).

    Skipped graders (``passed is None``) are excluded from the denominator so a
    family that only ever skipped does not appear as 0%.
    """
    buckets: dict[str, list[bool]] = {}
    for r in grader_rows:
        if r.get("passed") is None:
            continue
        family = (r.get("grader_type") or "unknown").split(".")[0]
        buckets.setdefault(family, []).append(bool(r["passed"]))
    return {
        family: round(sum(1 for p in flags if p) / len(flags), 4)
        for family, flags in buckets.items()
        if flags
    }
