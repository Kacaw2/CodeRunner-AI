"""Shared SQL statements for workflow sync and async repositories."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, Update, delete, func, select, update

from domain.models.workflow import WorkflowRun, WorkflowStep


def select_run(run_id: str) -> Select:
    return select(WorkflowRun).where(WorkflowRun.id == run_id)


def select_run_for_user(run_id: str, user_id: int) -> Select:
    return select(WorkflowRun).where(
        WorkflowRun.id == run_id,
        WorkflowRun.user_id == user_id,
    )


def select_runs_for_user(
    user_id: int,
    *,
    status: str | None = None,
    workflow_type: str | None = None,
) -> Select:
    stmt = select(WorkflowRun).where(WorkflowRun.user_id == user_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    if workflow_type:
        stmt = stmt.where(WorkflowRun.workflow_type == workflow_type)
    return stmt.order_by(WorkflowRun.created_at.desc())


def select_run_count_for_user(
    user_id: int,
    *,
    status: str | None = None,
    workflow_type: str | None = None,
) -> Select:
    stmt = select(func.count(WorkflowRun.id)).where(WorkflowRun.user_id == user_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    if workflow_type:
        stmt = stmt.where(WorkflowRun.workflow_type == workflow_type)
    return stmt


def select_steps(run_id: str) -> Select:
    return (
        select(WorkflowStep)
        .where(WorkflowStep.workflow_run_id == run_id)
        .order_by(WorkflowStep.step_index)
    )


def select_step(run_id: str, step_index: int) -> Select:
    return select(WorkflowStep).where(
        WorkflowStep.workflow_run_id == run_id,
        WorkflowStep.step_index == step_index,
    )


def delete_steps(run_id: str):
    return delete(WorkflowStep).where(WorkflowStep.workflow_run_id == run_id)


def _status_filter(column, expected: str | Iterable[str]):
    if isinstance(expected, str):
        return column == expected
    return column.in_(tuple(expected))


def update_run_status_cas(
    run_id: str,
    expected_status: str | Iterable[str],
    new_status: str,
    **values,
) -> Update:
    return (
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            _status_filter(WorkflowRun.status, expected_status),
        )
        .values(status=new_status, **values)
    )


def update_step_status_cas(
    step_id: str,
    expected_status: str | Iterable[str],
    new_status: str,
    **values,
) -> Update:
    return (
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step_id,
            _status_filter(WorkflowStep.status, expected_status),
        )
        .values(status=new_status, **values)
    )
