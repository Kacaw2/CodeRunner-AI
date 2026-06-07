"""Eval reporting (Phase 7, Task 8).

:class:`~evals.reports.generator.ReportGenerator` builds a structured report
(quality / cost / latency / failure types / regressions) from persisted eval
runs, and :mod:`evals.reports.regression` compares two runs case-by-case.
"""

from ai.evals.reports.generator import EvalReport, ReportGenerator
from ai.evals.reports.regression import detect_regressions

__all__ = ["EvalReport", "ReportGenerator", "detect_regressions"]
