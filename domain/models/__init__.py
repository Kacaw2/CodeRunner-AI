"""Domain mapped models (pure SQLAlchemy 2.0, runtime-neutral).

Every class here inherits :class:`domain.base.DomainBase` — the single
mapped-class registry shared with the remaining Flask ``db.Model`` classes.
"""

from domain.models.user import User, UserRole
from domain.models.workflow import WorkflowApproval, WorkflowRun, WorkflowStep

__all__ = [
    "User",
    "UserRole",
    "WorkflowRun",
    "WorkflowStep",
    "WorkflowApproval",
]
