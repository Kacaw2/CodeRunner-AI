"""Trace repositories for sync and async SQLAlchemy sessions."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from domain.models.observability import (
    AgentTraceArtifact,
    AgentTraceEvent,
    AgentTraceLink,
    AgentTraceRun,
    AgentTraceSpan,
)

_EQ_FILTERS = (
    "agent_type",
    "status",
    "source",
    "eval_run_id",
    "conversation_id",
    "chat_task_id",
)


def _trace_conditions(filters: dict, *, viewer_user_id: int | None = None):
    conditions = []
    for key in _EQ_FILTERS:
        value = filters.get(key)
        if value not in (None, ""):
            conditions.append(getattr(AgentTraceRun, key) == value)
    if filters.get("from"):
        conditions.append(AgentTraceRun.created_at >= filters["from"])
    if filters.get("to"):
        conditions.append(AgentTraceRun.created_at <= filters["to"])
    if filters.get("q"):
        like = f"%{filters['q']}%"
        conditions.append(
            AgentTraceRun.input_preview.like(like)
            | AgentTraceRun.output_preview.like(like)
            | AgentTraceRun.trace_id.like(like)
        )
    if viewer_user_id is not None:
        conditions.append(AgentTraceRun.user_id == viewer_user_id)
    return conditions


class SyncTraceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_trace(
        self, run, *, spans, events, artifacts, links
    ) -> None:
        self.session.add(AgentTraceRun(**asdict(run)))
        self.session.add_all([AgentTraceSpan(**asdict(row)) for row in spans])
        self.session.add_all([AgentTraceEvent(**asdict(row)) for row in events])
        self.session.add_all(
            [AgentTraceArtifact(**asdict(row)) for row in artifacts]
        )
        self.session.add_all([AgentTraceLink(**asdict(row)) for row in links])

    def get_run(self, trace_id: str):
        return self.session.execute(
            select(AgentTraceRun).where(
                or_(
                    AgentTraceRun.trace_id == trace_id,
                    AgentTraceRun.id == trace_id,
                    AgentTraceRun.legacy_run_id == trace_id,
                )
            )
        ).scalar_one_or_none()

    def get_trace_bundle(self, trace_id: str) -> dict:
        return {
            "run": self.get_run(trace_id),
            "spans": list(
                self.session.execute(
                    select(AgentTraceSpan)
                    .where(AgentTraceSpan.trace_id == trace_id)
                    .order_by(AgentTraceSpan.sequence, AgentTraceSpan.started_at)
                ).scalars()
            ),
            "events": list(
                self.session.execute(
                    select(AgentTraceEvent)
                    .where(AgentTraceEvent.trace_id == trace_id)
                    .order_by(AgentTraceEvent.created_at)
                ).scalars()
            ),
            "artifacts": list(
                self.session.execute(
                    select(AgentTraceArtifact)
                    .where(AgentTraceArtifact.trace_id == trace_id)
                    .order_by(AgentTraceArtifact.created_at)
                ).scalars()
            ),
            "links": list(
                self.session.execute(
                    select(AgentTraceLink)
                    .where(AgentTraceLink.trace_id == trace_id)
                    .order_by(AgentTraceLink.created_at)
                ).scalars()
            ),
        }

    def list_runs(
        self,
        *,
        filters: dict,
        viewer_user_id: int | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentTraceRun], int]:
        conditions = _trace_conditions(
            filters, viewer_user_id=viewer_user_id
        )
        stmt = select(AgentTraceRun)
        count_stmt = select(func.count(AgentTraceRun.id))
        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
        total = self.session.execute(count_stmt).scalar() or 0
        rows = list(
            self.session.execute(
                stmt.order_by(AgentTraceRun.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).scalars()
        )
        return rows, total

    def tool_span_counts(self, trace_ids: list[str]) -> dict[str, int]:
        if not trace_ids:
            return {}
        rows = self.session.execute(
            select(AgentTraceSpan.trace_id, func.count(AgentTraceSpan.id))
            .where(AgentTraceSpan.trace_id.in_(trace_ids))
            .where(AgentTraceSpan.span_type.in_(("tool", "mcp")))
            .group_by(AgentTraceSpan.trace_id)
        ).all()
        return dict(rows)


class AsyncTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def save_trace(self, run, *, spans, events, artifacts, links) -> None:
        self.session.add(AgentTraceRun(**asdict(run)))
        self.session.add_all([AgentTraceSpan(**asdict(row)) for row in spans])
        self.session.add_all([AgentTraceEvent(**asdict(row)) for row in events])
        self.session.add_all(
            [AgentTraceArtifact(**asdict(row)) for row in artifacts]
        )
        self.session.add_all([AgentTraceLink(**asdict(row)) for row in links])

    async def get_run(self, trace_id: str):
        result = await self.session.execute(
            select(AgentTraceRun).where(
                or_(
                    AgentTraceRun.trace_id == trace_id,
                    AgentTraceRun.id == trace_id,
                    AgentTraceRun.legacy_run_id == trace_id,
                )
            )
        )
        return result.scalar_one_or_none()
