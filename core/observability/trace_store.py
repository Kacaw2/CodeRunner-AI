"""Runtime-neutral trace persistence.

Writes trace run/span/event/artifact/link rows through plain SQLAlchemy
(``core.db.session``). This module MUST NOT import ``app.core.extensions.db``
or any ``app.models.*`` — that is exactly what triggered the Flask mapper
configuration failure (``TRACE_SAVE_FAIL``) inside worker processes.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from core.db.models.agent_trace import (
    AgentTraceArtifact,
    AgentTraceEvent,
    AgentTraceLink,
    AgentTraceRun,
    AgentTraceSpan,
)
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

    def save_run(
        self,
        run: TraceRunRecord,
        spans: list[TraceSpanRecord] | None = None,
        events: list[TraceEventRecord] | None = None,
        artifacts: list[TraceArtifactRecord] | None = None,
        links: list[TraceLinkRecord] | None = None,
    ) -> None:
        with db_session() as session:
            session.add(AgentTraceRun(**asdict(run)))
            session.add_all([AgentTraceSpan(**asdict(s)) for s in (spans or [])])
            session.add_all([AgentTraceEvent(**asdict(e)) for e in (events or [])])
            session.add_all(
                [AgentTraceArtifact(**asdict(a)) for a in (artifacts or [])]
            )
            session.add_all([AgentTraceLink(**asdict(link)) for link in (links or [])])
