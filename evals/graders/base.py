"""Grader protocol and dispatcher (Phase 5, Task 7).

A grader scores an agent response and returns a uniform :class:`GraderResult`.
Grader types are namespaced as ``<family>.<name>`` (e.g.
``deterministic.answer_leak``); :func:`run_grader` dispatches on the family.

Only the ``deterministic`` family is wired in this phase. ``unit_tests``,
``static_checks`` and ``llm_judge`` families are reserved for a later phase and
currently resolve to an explicit error result rather than silently passing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class GraderResult:
    grader_type: str
    grader_name: str
    passed: bool
    score: float | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    cost_cny: Decimal | None = None
    trace_id: str | None = None


def error_result(
    grader_type: str,
    grader_name: str,
    reason: str,
    *,
    trace_id: str | None = None,
) -> GraderResult:
    """A failed result for unknown/unsupported graders (never a silent pass)."""
    return GraderResult(
        grader_type=grader_type,
        grader_name=grader_name,
        passed=False,
        score=0.0,
        reason=reason,
        metadata={"error": "grader_unavailable"},
        latency_ms=0,
        trace_id=trace_id,
    )


def split_grader_type(grader_type: str) -> tuple[str, str]:
    """Split ``<family>.<name>`` into ``(family, name)``.

    A bare type with no dot is treated as a ``deterministic`` grader so legacy
    judge names keep working.
    """
    if "." in grader_type:
        family, name = grader_type.split(".", 1)
        return family, name
    return "deterministic", grader_type


def run_grader(
    grader_spec: dict,
    response: str,
    *,
    trace_id: str | None = None,
) -> GraderResult:
    """Dispatch a grader spec to its family implementation."""
    grader_type = grader_spec.get("type", "")
    family, name = split_grader_type(grader_type)
    params = {k: v for k, v in grader_spec.items() if k != "type"}

    if family == "deterministic":
        from evals.graders.deterministic import run_deterministic_grader

        return run_deterministic_grader(
            grader_type, response, params, trace_id=trace_id
        )

    return error_result(
        family,
        name,
        f"Unsupported grader family: {family!r}",
        trace_id=trace_id,
    )
