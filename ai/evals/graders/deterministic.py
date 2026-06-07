"""Deterministic graders (Phase 5, Task 7).

These wrap the existing judge functions in :mod:`evals.judges.judges` and adapt
their ``{"passed", "reason"}`` output to the uniform :class:`GraderResult`. The
judge registry stays the single source of truth; this module is the canonical
entry point the eval harness calls.
"""

from __future__ import annotations

import time
from typing import Any

from ai.evals.graders.base import GraderResult, error_result, split_grader_type
from ai.evals.judges.judges import JUDGE_REGISTRY

GRADER_TYPE = "deterministic"


def available_graders() -> list[str]:
    """Canonical ``deterministic.<name>`` ids for every wrapped judge."""
    return [f"{GRADER_TYPE}.{name}" for name in JUDGE_REGISTRY]


def run_deterministic_grader(
    grader_type: str,
    response: str,
    params: dict[str, Any] | None = None,
    *,
    trace_id: str | None = None,
) -> GraderResult:
    """Run a single deterministic grader by ``deterministic.<judge_name>`` id."""
    _, name = split_grader_type(grader_type)
    params = params or {}

    judge_fn = JUDGE_REGISTRY.get(name)
    if judge_fn is None:
        return error_result(
            GRADER_TYPE,
            name,
            f"Unknown deterministic grader: {name!r}",
            trace_id=trace_id,
        )

    start = time.perf_counter()
    verdict = judge_fn(response, params)
    latency_ms = int((time.perf_counter() - start) * 1000)

    passed = bool(verdict.get("passed"))
    return GraderResult(
        grader_type=GRADER_TYPE,
        grader_name=name,
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=verdict.get("reason", ""),
        metadata={k: v for k, v in verdict.items() if k not in ("passed", "reason")},
        latency_ms=latency_ms,
        trace_id=trace_id,
    )
