"""Unit-test grader (Phase 6, Task 7 — stable interface).

Runs visible unit tests against code in an agent response using the project's
sandbox/executor. The full sandbox wiring is a later increment; until a sandbox
runner is supplied this grader returns a neutral ``skipped`` result (never a
silent pass or a false failure) so the harness and reports stay stable.
"""

from __future__ import annotations

import time

from evals.graders.base import GraderResult, skipped_result, split_grader_type
from evals.graders.static_checks import extract_code

GRADER_TYPE = "unit_tests"


def run_unit_test_grader(
    grader_type: str,
    response: str,
    params: dict | None = None,
    *,
    trace_id: str | None = None,
) -> GraderResult:
    _, name = split_grader_type(grader_type)
    params = params or {}
    start = time.perf_counter()

    code = extract_code(response)
    tests = params.get("tests")
    sandbox = params.get("sandbox")

    if sandbox is None:
        result = skipped_result(
            GRADER_TYPE,
            name,
            "no sandbox runner available",
            metadata={"has_code": code is not None, "has_tests": bool(tests)},
            trace_id=trace_id,
        )
        result.latency_ms = int((time.perf_counter() - start) * 1000)
        return result

    outcome = sandbox.run_tests(code or "", tests or "")
    passed = bool(outcome.get("passed"))
    return GraderResult(
        grader_type=GRADER_TYPE,
        grader_name=name,
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=outcome.get("reason", ""),
        metadata={
            "stdout": (outcome.get("stdout") or "")[:2000],
            "stderr": (outcome.get("stderr") or "")[:2000],
        },
        latency_ms=int((time.perf_counter() - start) * 1000),
        trace_id=trace_id,
    )
