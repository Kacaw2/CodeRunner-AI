import logging
from datetime import datetime

from app.core.extensions import db

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
        task.updated_at = datetime.utcnow()

    db.session.commit()
    logger.info("Recovered %d orphaned tasks", len(orphaned))
    return len(orphaned)
