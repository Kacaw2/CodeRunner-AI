"""Compatibility re-export for the eval run domain mapping."""

from app.models._query_compat import enable_legacy_query
from domain.models.observability import EvalRun

enable_legacy_query(EvalRun)

__all__ = ["EvalRun"]
