"""Formalized eval datasets (Phase 5, Task 5).

Canonical eval cases live under ``evals/datasets/<case_type>/<suite>.json`` and
are loaded via :class:`evals.datasets.store.DatasetStore`.
"""

from evals.datasets.schema import EvalCase, EvalCaseInput, GraderSpec
from evals.datasets.store import DatasetStore

__all__ = ["DatasetStore", "EvalCase", "EvalCaseInput", "GraderSpec"]
