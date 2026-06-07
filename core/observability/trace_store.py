"""Runtime-neutral trace persistence.

Writes trace run/span/event/artifact/link rows through plain SQLAlchemy
(``core.db.session``). This module MUST NOT import ``app.core.extensions.db``
or any ``app.models.*`` — that is exactly what triggered the Flask mapper
configuration failure (``TRACE_SAVE_FAIL``) inside worker processes.
"""

from __future__ import annotations

import logging

from core.db.session import db_session
from core.observability.trace_schema import (
    TraceArtifactRecord,
    TraceEventRecord,
    TraceLinkRecord,
    TraceRunRecord,
    TraceSpanRecord,
)

logger = logging.getLogger(__name__)


class TraceStore:
    """Persists a complete trace in a single transaction."""

    def __init__(self, repository=None) -> None:
        self.repository = repository

    def save_run(
        self,
        run: TraceRunRecord,
        spans: list[TraceSpanRecord] | None = None,
        events: list[TraceEventRecord] | None = None,
        artifacts: list[TraceArtifactRecord] | None = None,
        links: list[TraceLinkRecord] | None = None,
    ) -> None:
        spans = spans or []
        events = events or []
        artifacts = artifacts or []
        links = links or []
        if self.repository is not None:
            self.repository.save_trace(
                run,
                spans=spans,
                events=events,
                artifacts=artifacts,
                links=links,
            )
            return

        from domain.repositories.traces import SyncTraceRepository

        with db_session() as session:
            SyncTraceRepository(session).save_trace(
                run,
                spans=spans,
                events=events,
                artifacts=artifacts,
                links=links,
            )
