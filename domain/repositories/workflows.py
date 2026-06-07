"""Session-bound workflow repositories. Callers own commit/rollback."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from domain.models.workflow import WorkflowApproval, WorkflowRun, WorkflowStep
from domain.statements.workflows import (
    delete_steps,
    select_run,
    select_run_count_for_user,
    select_run_for_user,
    select_runs_for_user,
    select_step,
    select_steps,
    update_run_status_cas,
    update_step_status_cas,
)


class SyncWorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, **values) -> WorkflowRun:
        run = WorkflowRun(**values)
        self.session.add(run)
        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        return self.session.execute(select_run(run_id)).scalar_one_or_none()

    def get_run_for_user(self, run_id: str, user_id: int) -> Optional[WorkflowRun]:
        return self.session.execute(
            select_run_for_user(run_id, user_id)
        ).scalar_one_or_none()

    def list_runs_for_user(
        self,
        user_id: int,
        *,
        status: str | None = None,
        workflow_type: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[WorkflowRun]:
        stmt = select_runs_for_user(
            user_id, status=status, workflow_type=workflow_type
        ).offset(offset).limit(limit)
        return list(self.session.execute(stmt).scalars())

    def count_runs_for_user(
        self,
        user_id: int,
        *,
        status: str | None = None,
        workflow_type: str | None = None,
    ) -> int:
        return self.session.execute(
            select_run_count_for_user(
                user_id, status=status, workflow_type=workflow_type
            )
        ).scalar_one()

    def create_step(self, **values) -> WorkflowStep:
        step = WorkflowStep(**values)
        self.session.add(step)
        return step

    def get_step(self, run_id: str, step_index: int) -> Optional[WorkflowStep]:
        return self.session.execute(
            select_step(run_id, step_index)
        ).scalar_one_or_none()

    def list_steps(self, run_id: str) -> list[WorkflowStep]:
        return list(self.session.execute(select_steps(run_id)).scalars())

    def replace_steps(self, run_id: str, step_values: list[dict]) -> list[WorkflowStep]:
        self.session.execute(delete_steps(run_id))
        return [
            self.create_step(workflow_run_id=run_id, **values)
            for values in step_values
        ]

    def add_approval(self, **values) -> WorkflowApproval:
        approval = WorkflowApproval(**values)
        self.session.add(approval)
        return approval

    def transition_run(
        self,
        run_id: str,
        expected_status: str | Iterable[str],
        new_status: str,
        **values,
    ) -> bool:
        result = self.session.execute(
            update_run_status_cas(
                run_id, expected_status, new_status, **values
            )
        )
        return result.rowcount == 1

    def transition_step(
        self,
        step_id: str,
        expected_status: str | Iterable[str],
        new_status: str,
        **values,
    ) -> bool:
        result = self.session.execute(
            update_step_status_cas(
                step_id, expected_status, new_status, **values
            )
        )
        return result.rowcount == 1


class AsyncWorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def create_run(self, **values) -> WorkflowRun:
        run = WorkflowRun(**values)
        self.session.add(run)
        return run

    async def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        result = await self.session.execute(select_run(run_id))
        return result.scalar_one_or_none()

    async def get_run_for_user(
        self, run_id: str, user_id: int
    ) -> Optional[WorkflowRun]:
        result = await self.session.execute(select_run_for_user(run_id, user_id))
        return result.scalar_one_or_none()

    async def list_runs_for_user(
        self,
        user_id: int,
        *,
        status: str | None = None,
        workflow_type: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[WorkflowRun]:
        stmt = select_runs_for_user(
            user_id, status=status, workflow_type=workflow_type
        ).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    def create_step(self, **values) -> WorkflowStep:
        step = WorkflowStep(**values)
        self.session.add(step)
        return step

    async def list_steps(self, run_id: str) -> list[WorkflowStep]:
        result = await self.session.execute(select_steps(run_id))
        return list(result.scalars())

    def add_approval(self, **values) -> WorkflowApproval:
        approval = WorkflowApproval(**values)
        self.session.add(approval)
        return approval

    async def transition_run(
        self,
        run_id: str,
        expected_status: str | Iterable[str],
        new_status: str,
        **values,
    ) -> bool:
        result = await self.session.execute(
            update_run_status_cas(
                run_id, expected_status, new_status, **values
            )
        )
        return result.rowcount == 1

    async def transition_step(
        self,
        step_id: str,
        expected_status: str | Iterable[str],
        new_status: str,
        **values,
    ) -> bool:
        result = await self.session.execute(
            update_step_status_cas(
                step_id, expected_status, new_status, **values
            )
        )
        return result.rowcount == 1
