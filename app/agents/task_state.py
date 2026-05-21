import enum


class TaskStatus(enum.Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    VALIDATING = "validating"
    REVIEW = "review"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TRANSITIONS = {
    TaskStatus.PENDING:    [TaskStatus.PLANNING, TaskStatus.EXECUTING, TaskStatus.CANCELLED],
    TaskStatus.PLANNING:   [TaskStatus.EXECUTING, TaskStatus.FAILED],
    TaskStatus.EXECUTING:  [TaskStatus.VALIDATING, TaskStatus.FAILED],
    TaskStatus.VALIDATING: [TaskStatus.COMPLETED, TaskStatus.REVIEW, TaskStatus.EXECUTING, TaskStatus.FAILED],
    TaskStatus.REVIEW:     [TaskStatus.COMPLETED, TaskStatus.REVISING, TaskStatus.CANCELLED],
    TaskStatus.REVISING:   [TaskStatus.VALIDATING, TaskStatus.FAILED],
    TaskStatus.COMPLETED:  [],
    TaskStatus.FAILED:     [TaskStatus.PENDING],
    TaskStatus.CANCELLED:  [],
}


def validate_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in TRANSITIONS.get(current, [])
