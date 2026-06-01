"""Eval grader system (Phase 5, Task 7).

Uniform :class:`GraderResult` protocol with a family dispatcher
(:func:`run_grader`). The ``deterministic`` family wraps the judge registry in
:mod:`evals.judges.judges`.
"""

from evals.graders.base import GraderResult, run_grader
from evals.graders.deterministic import (
    available_graders,
    run_deterministic_grader,
)

__all__ = [
    "GraderResult",
    "run_grader",
    "run_deterministic_grader",
    "available_graders",
]
