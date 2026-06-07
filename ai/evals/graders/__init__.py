"""Eval grader system (Phase 5-6, Task 7).

Uniform :class:`GraderResult` protocol with a family dispatcher
(:func:`run_grader`). Families:

- ``deterministic`` — wraps the judge registry in :mod:`evals.judges.judges`.
- ``static_checks`` — sandbox-free AST analysis.
- ``unit_tests`` — visible test execution (stable interface; skips without a sandbox).
- ``llm_judge`` — rubric-based quality scoring (skips without an API key).
"""

from ai.evals.graders.base import GraderResult, run_grader, error_result, skipped_result
from ai.evals.graders.deterministic import (
    available_graders,
    run_deterministic_grader,
)
from ai.evals.graders.static_checks import run_static_check_grader
from ai.evals.graders.unit_tests import run_unit_test_grader
from ai.evals.graders.llm_judge import run_llm_judge_grader

__all__ = [
    "GraderResult",
    "run_grader",
    "error_result",
    "skipped_result",
    "run_deterministic_grader",
    "available_graders",
    "run_static_check_grader",
    "run_unit_test_grader",
    "run_llm_judge_grader",
]
