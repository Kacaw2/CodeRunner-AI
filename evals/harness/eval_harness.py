"""EvalHarness — batch-run dataset cases bound to traces (Phase 6, Task 6).

Responsibilities:

- load dataset cases via :class:`~evals.datasets.store.DatasetStore`;
- create an ``EvalRun`` and one ``EvalCaseRun`` per case;
- drive each case through an :class:`~evals.harness.agent_harness.AgentHarness`,
  binding ``eval_run_id`` / ``eval_case_id`` onto the case's trace;
- read the resulting trace for tokens / cost / latency;
- enforce a *soft* budget (token / cost / timeout limits checked after the run,
  never interrupting the agent loop — see plan DP-A);
- run graders and persist ``EvalCaseGraderResult`` rows.

Persistence uses the shared Domain mappings through trace/eval repositories.
The harness receives a session scope so tests and non-Flask runtimes can bind
the same repository contract to their own engine.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal

from core.db.session import db_session
from domain.repositories.evals import SyncEvalRepository
from domain.repositories.traces import SyncTraceRepository
from evals.datasets.store import DatasetStore
from evals.graders.base import run_grader

logger = logging.getLogger(__name__)


@dataclass
class EvalCaseResult:
    case_id: str
    case_type: str
    suite: str
    agent_type: str
    trace_id: str
    status: str
    passed: bool
    failure_type: str | None = None
    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_cny: Decimal | None = None
    output_preview: str = ""
    grader_results: list = field(default_factory=list)


@dataclass
class EvalRunReport:
    eval_run_id: int
    selector: str
    model_name: str
    total: int
    passed: int
    failed: int
    errors: int
    pass_rate: float
    case_results: list = field(default_factory=list)


class EvalHarness:
    """Run dataset cases through the agent harness and persist eval results."""

    def __init__(
        self,
        agent_harness=None,
        dataset_store: DatasetStore | None = None,
        session_scope=db_session,
    ):
        if agent_harness is None:
            from evals.harness.agent_harness import AgentHarness

            agent_harness = AgentHarness()
        self.agent_harness = agent_harness
        self.dataset_store = dataset_store or DatasetStore()
        self.session_scope = session_scope

    def run(
        self,
        *,
        selector: str = "all",
        model_name: str | None = None,
        max_cases: int | None = None,
    ) -> EvalRunReport:
        cases = self.dataset_store.load_cases(selector)
        if max_cases is not None:
            cases = cases[:max_cases]

        suite_name = self._suite_name(selector, cases)
        eval_run_id = self._create_eval_run(suite_name, model_name, len(cases))

        case_results: list[EvalCaseResult] = []
        for case in cases:
            case_results.append(self._run_case(case, eval_run_id))

        passed = sum(1 for c in case_results if c.passed)
        errors = sum(1 for c in case_results if c.status == "error")
        total = len(case_results)
        failed = total - passed
        pass_rate = passed / total if total else 0.0

        self._finalize_eval_run(eval_run_id, total, passed, pass_rate, case_results)

        return EvalRunReport(
            eval_run_id=eval_run_id,
            selector=selector,
            model_name=model_name or "",
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            pass_rate=pass_rate,
            case_results=case_results,
        )

    # ── Case execution ─────────────────────────────────────────

    def _run_case(self, case, eval_run_id: int) -> EvalCaseResult:
        context = dict(case.input.context)
        context["eval_run_id"] = eval_run_id
        context["eval_case_id"] = case.id

        started = time.monotonic()
        trace_id = ""
        response = ""
        agent_status = "completed"
        agent_error = ""
        try:
            result = self.agent_harness.run(
                agent_type=case.agent_type,
                message=case.input.message,
                user_id=case.input.user_id,
                user_role=case.input.user_role,
                source="eval",
                context=context,
                budget=case.budget,
            )
            trace_id = result.trace_id
            response = result.response or ""
            agent_status = result.status
        except Exception as exc:  # noqa: BLE001 — harness boundary
            agent_error = str(exc)[:500]
            logger.warning("Eval case %s agent run failed: %s", case.id, exc)

        wall_ms = int((time.monotonic() - started) * 1000)
        tokens_in, tokens_out, cost, trace_latency = self._read_trace_metrics(trace_id)
        duration_ms = trace_latency or wall_ms

        grader_results = [
            run_grader(g.to_dict(), response, trace_id=trace_id or None)
            for g in case.graders
        ]

        status, passed, failure_type = self._classify(
            case,
            agent_status=agent_status,
            agent_error=agent_error,
            tokens_total=tokens_in + tokens_out,
            cost=cost,
            duration_ms=duration_ms,
            grader_results=grader_results,
        )

        case_run_id = self._persist_case_run(
            eval_run_id=eval_run_id,
            case=case,
            trace_id=trace_id,
            status=status,
            passed=passed,
            failure_type=failure_type,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            duration_ms=duration_ms,
            response=response,
            grader_results=grader_results,
        )

        return EvalCaseResult(
            case_id=case.id,
            case_type=case.case_type,
            suite=case.suite,
            agent_type=case.agent_type,
            trace_id=trace_id,
            status=status,
            passed=passed,
            failure_type=failure_type,
            duration_ms=duration_ms,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            cost_cny=cost,
            output_preview=(response or "")[:200],
            grader_results=grader_results,
        )

    def _classify(
        self,
        case,
        *,
        agent_status: str,
        agent_error: str,
        tokens_total: int,
        cost,
        duration_ms: int,
        grader_results: list,
    ) -> tuple[str, bool, str | None]:
        """Decide (status, passed, failure_type) — see plan §8 failure types."""
        if agent_error or agent_status in {"failed", "error"}:
            return "error", False, "agent_error"

        budget = case.budget or {}
        max_tokens = budget.get("max_tokens")
        if max_tokens and tokens_total > max_tokens:
            return "budget_exceeded", False, "budget_exceeded"

        max_cost = budget.get("max_cost_cny")
        if max_cost and cost is not None and float(cost) > float(max_cost):
            return "budget_exceeded", False, "budget_exceeded"

        timeout = budget.get("timeout_seconds")
        if timeout and duration_ms > int(timeout) * 1000:
            return "budget_exceeded", False, "timeout"

        if not grader_results:
            return "failed", False, "no_graders"

        if all(g.passed for g in grader_results):
            return "passed", True, None
        return "failed", False, "grader_failed"

    # ── Trace read-back ────────────────────────────────────────

    def _read_trace_metrics(self, trace_id: str):
        if not trace_id:
            return 0, 0, None, 0
        with self.session_scope() as session:
            run = SyncTraceRepository(session).get_run(trace_id)
            if run is None:
                return 0, 0, None, 0
            return (
                run.tokens_input or 0,
                run.tokens_output or 0,
                run.cost_cny,
                run.total_latency_ms or 0,
            )

    # ── Persistence ────────────────────────────────────────────

    def _create_eval_run(self, suite_name: str, model_name: str | None, total: int) -> int:
        with self.session_scope() as session:
            repo = SyncEvalRepository(session)
            run = repo.create_run(
                suite_name=suite_name,
                model_name=model_name,
                total_cases=total,
                passed_cases=0,
                pass_rate=0.0,
                duration_seconds=0.0,
            )
            session.flush()
            return run.id

    def _finalize_eval_run(
        self,
        eval_run_id: int,
        total: int,
        passed: int,
        pass_rate: float,
        case_results: list,
    ) -> None:
        duration_seconds = sum(c.duration_ms for c in case_results) / 1000.0
        with self.session_scope() as session:
            SyncEvalRepository(session).finalize_run(
                eval_run_id,
                total_cases=total,
                passed_cases=passed,
                pass_rate=pass_rate,
                duration_seconds=round(duration_seconds, 3),
                results_json=[
                    {
                        "case_id": c.case_id,
                        "status": c.status,
                        "passed": c.passed,
                        "failure_type": c.failure_type,
                        "trace_id": c.trace_id,
                    }
                    for c in case_results
                ],
            )

    def _persist_case_run(
        self,
        *,
        eval_run_id: int,
        case,
        trace_id: str,
        status: str,
        passed: bool,
        failure_type: str | None,
        tokens_in: int,
        tokens_out: int,
        cost,
        duration_ms: int,
        response: str,
        grader_results: list,
    ) -> str:
        with self.session_scope() as session:
            repo = SyncEvalRepository(session)
            case_run = repo.create_case_run(
                eval_run_id=eval_run_id,
                case_id=case.id,
                case_type=case.case_type,
                suite=case.suite,
                agent_type=case.agent_type,
                trace_id=trace_id or None,
                status=status,
                passed=passed,
                failure_type=failure_type,
                input_preview=(case.input.message or "")[:2000],
                output_preview=(response or "")[:2000],
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                cost_cny=cost,
                duration_ms=duration_ms,
            )
            session.flush()
            case_run_id = case_run.id

            for g in grader_results:
                repo.create_grader_result(
                    case_run_id=case_run_id,
                    grader_type=g.grader_type,
                    grader_name=g.grader_name,
                    passed=g.passed,
                    score=g.score,
                    reason=g.reason,
                    metadata_json=g.metadata or None,
                    latency_ms=g.latency_ms,
                    cost_cny=g.cost_cny,
                    trace_id=g.trace_id,
                )
            return case_run_id

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _suite_name(selector: str, cases: list) -> str:
        if cases:
            suites = {c.suite for c in cases}
            if len(suites) == 1:
                return next(iter(suites))
        return selector or "all"
