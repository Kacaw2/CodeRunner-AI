"""Formalized eval datasets (Phase 5, Task 5).

Canonical eval cases live under ``evals/datasets/<case_type>/<suite>.json`` and
are loaded via :class:`evals.datasets.store.DatasetStore`.
"""

from ai.evals.datasets.schema import EvalCase, EvalCaseInput, GraderSpec
from ai.evals.datasets.store import DatasetStore

__all__ = ["DatasetStore", "EvalCase", "EvalCaseInput", "GraderSpec"]
