"""Compatibility re-export for workflow domain mappings."""

from app.models._query_compat import enable_legacy_query
from domain.models.workflow import WorkflowApproval, WorkflowRun, WorkflowStep

enable_legacy_query(WorkflowRun)
enable_legacy_query(WorkflowStep)
enable_legacy_query(WorkflowApproval)

__all__ = ["WorkflowRun", "WorkflowStep", "WorkflowApproval"]
