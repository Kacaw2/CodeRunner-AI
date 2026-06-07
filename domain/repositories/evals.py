"""Eval repositories for sync and async SQLAlchemy sessions."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from domain.models.observability import (
    EvalCaseGraderResult,
    EvalCaseRun,
    EvalRun,
)


class SyncEvalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, **values) -> EvalRun:
        run = EvalRun(**values)
        self.session.add(run)
        return run

    def get_run(self, eval_run_id: int):
        return self.session.get(EvalRun, eval_run_id)

    def list_runs(self, *, offset: int = 0, limit: int = 20) -> list[EvalRun]:
        return list(
            self.session.execute(
                select(EvalRun)
                .order_by(EvalRun.run_at.desc())
                .offset(offset)
                .limit(limit)
            ).scalars()
        )

    def count_runs(self) -> int:
        return self.session.execute(
            select(func.count(EvalRun.id))
        ).scalar_one()

    def finalize_run(self, eval_run_id: int, **values) -> bool:
        run = self.get_run(eval_run_id)
        if run is None:
            return False
        for key, value in values.items():
            setattr(run, key, value)
        return True

    def create_case_run(self, **values) -> EvalCaseRun:
        row = EvalCaseRun(**values)
        self.session.add(row)
        return row

    def create_grader_result(self, **values) -> EvalCaseGraderResult:
        row = EvalCaseGraderResult(**values)
        self.session.add(row)
        return row

    def load_run_with_cases(
        self, eval_run_id: int
    ) -> tuple[EvalRun | None, list[EvalCaseRun]]:
        run = self.get_run(eval_run_id)
        cases = list(
            self.session.execute(
                select(EvalCaseRun)
                .where(EvalCaseRun.eval_run_id == eval_run_id)
                .order_by(EvalCaseRun.created_at)
            ).scalars()
        )
        return run, cases

    def list_grader_results(
        self, case_run_ids: list[str]
    ) -> list[EvalCaseGraderResult]:
        if not case_run_ids:
            return []
        return list(
            self.session.execute(
                select(EvalCaseGraderResult).where(
                    EvalCaseGraderResult.case_run_id.in_(case_run_ids)
                )
            ).scalars()
        )

    def get_case_by_trace(self, trace_id: str):
        return self.session.execute(
            select(EvalCaseRun)
            .where(EvalCaseRun.trace_id == trace_id)
            .order_by(EvalCaseRun.created_at.desc())
        ).scalars().first()


class AsyncEvalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def create_run(self, **values) -> EvalRun:
        run = EvalRun(**values)
        self.session.add(run)
        return run

    async def get_run(self, eval_run_id: int):
        return await self.session.get(EvalRun, eval_run_id)

    def create_case_run(self, **values) -> EvalCaseRun:
        row = EvalCaseRun(**values)
        self.session.add(row)
        return row

    def create_grader_result(self, **values) -> EvalCaseGraderResult:
        row = EvalCaseGraderResult(**values)
        self.session.add(row)
        return row
