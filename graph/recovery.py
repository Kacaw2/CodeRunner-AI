import logging

from app.core.extensions import db
from app.core.timezone import now_china
from sqlalchemy import select, update

logger = logging.getLogger(__name__)


def recover_orphaned_tasks():
    """Called during app startup. Resume tasks that were running when server crashed."""
    from app.models.agent_task import AgentTask

    orphaned = AgentTask.query.filter(
        AgentTask.status.in_(["executing", "validating", "planning"])
    ).all()

    if not orphaned:
        return 0

    for task in orphaned:
        logger.warning("Recovering orphaned task %s (was %s)", task.id, task.status)
        if task.attempt < task.max_attempts:
            task.status = "pending"
            task.attempt += 1
            task.error_detail = f"Recovered after server restart (was {task.status})"
        else:
            task.status = "failed"
            task.error_detail = "Server restart during execution; max retries exhausted"
        task.updated_at = now_china()

    db.session.commit()
    logger.info("Recovered %d orphaned tasks", len(orphaned))
    return len(orphaned)


# Active states a WorkflowRun can be left in when the server crashes mid-run.
# `waiting_approval` is an intentional pause (human gate), not an orphan.
_ORPHAN_WORKFLOW_STATES = ["planning", "executing", "validating"]


def recover_orphaned_workflows():
    """Called during app startup. Fail workflows that were running when the server crashed.

    Mid-workflow resume is not safe (a step may have partially executed with side
    effects), so orphaned runs and their in-flight steps are marked failed rather
    than retried. Returns the number of workflow runs recovered.
    """
    from domain.models.workflow import WorkflowRun, WorkflowStep

    orphaned = list(
        db.session.execute(
            select(WorkflowRun).where(
                WorkflowRun.status.in_(_ORPHAN_WORKFLOW_STATES)
            )
        ).scalars()
    )

    if not orphaned:
        return 0

    for run in orphaned:
        logger.warning("Recovering orphaned workflow %s (was %s)", run.id, run.status)
        run.status = "failed"
        run.error_detail = f"Server restart during execution (was {run.status})"
        run.completed_at = now_china()

        db.session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.workflow_run_id == run.id,
                WorkflowStep.status.in_(["pending", "running"]),
            )
            .values(
                status="failed",
                error_detail="Server restart during execution",
                completed_at=now_china(),
            )
        )

    db.session.commit()
    logger.info("Recovered %d orphaned workflows", len(orphaned))
    return len(orphaned)
