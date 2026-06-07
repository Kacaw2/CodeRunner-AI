"""Backfill historical ``agent_runs`` into the new ``agent_trace_*`` tables.

Legacy runs were written by the pre-trace agent loop into ``agent_runs`` /
``agent_run_steps``. The complete trace UI and API read the runtime-neutral
``agent_trace_runs`` / ``agent_trace_spans`` tables, so this script copies old
rows forward:

- old ``agent_runs.id`` -> new ``legacy_run_id`` and reused verbatim as ``trace_id``;
- ``agent_run_steps`` -> spans (``llm_call`` -> ``llm`` spans, otherwise ``tool``);
- ``error_*`` / ``tokens_*`` / ``*_latency_ms`` -> run fields.

Reads go through the Flask ORM (legacy models live there); writes go through the
runtime-neutral ``core.db.session`` so they never trigger Flask mapper config.
The copy is idempotent: a run whose id already exists as a ``trace_id`` is skipped.

Usage:
    python -m scripts.backfill_agent_traces            # copy up to 500 runs
    python -m scripts.backfill_agent_traces --limit 50
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

logger = logging.getLogger("scripts.backfill_agent_traces")


def backfill(limit: int = 500) -> int:
    """Copy up to *limit* legacy ``agent_runs`` into the trace tables.

    Returns the number of runs newly copied (already-backfilled runs are skipped).
    """
    from app.core.extensions import db
    from app.models.agent_trace import AgentRun, AgentRunStep
    from core.db.session import db_session
    from domain.models.observability import AgentTraceRun, AgentTraceSpan

    legacy_runs = (
        db.session.execute(
            select(AgentRun).order_by(AgentRun.created_at).limit(limit)
        )
        .scalars()
        .all()
    )

    copied = 0
    for run in legacy_runs:
        steps = (
            db.session.execute(
                select(AgentRunStep)
                .where(AgentRunStep.run_id == run.id)
                .order_by(AgentRunStep.step_index)
            )
            .scalars()
            .all()
        )

        with db_session() as session:
            already = (
                session.query(AgentTraceRun)
                .filter_by(trace_id=run.id)
                .first()
            )
            if already is not None:
                continue

            session.add(_run_to_trace(run, AgentTraceRun))
            for step in steps:
                session.add(_step_to_span(run.id, step, AgentTraceSpan))

        copied += 1
        logger.info("Backfilled trace %s (%d spans)", run.id, len(steps))

    return copied


def _run_to_trace(run, AgentTraceRun):
    return AgentTraceRun(
        trace_id=run.id,
        legacy_run_id=run.id,
        source="agent",
        agent_type=run.agent_type,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        message_id=run.message_id,
        status=run.status or "completed",
        input_preview=run.input_message,
        output_preview=run.output_response,
        error_type=run.error_type,
        error_message=run.error_message,
        tokens_input=run.tokens_input or 0,
        tokens_output=run.tokens_output or 0,
        total_latency_ms=run.total_latency_ms,
        llm_latency_ms=run.llm_latency_ms,
        tool_latency_ms=run.tool_latency_ms,
        started_at=run.created_at,
        created_at=run.created_at,
        metadata_json={"backfilled": True},
    )


def _step_to_span(trace_id: str, step, AgentTraceSpan):
    span_type = "llm" if step.step_type == "llm_call" else "tool"
    return AgentTraceSpan(
        trace_id=trace_id,
        span_type=span_type,
        name=step.tool_name or step.step_type or "step",
        status="failed" if step.tool_success is False else "completed",
        sequence=step.step_index or 0,
        input_preview=(str(step.tool_input) if step.tool_input is not None else None),
        output_preview=step.tool_output_preview,
        error_message=step.error,
        tokens_input=step.llm_prompt_tokens,
        tokens_output=step.llm_completion_tokens,
        latency_ms=step.latency_ms,
        started_at=step.created_at,
        ended_at=step.created_at,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Backfill legacy agent_runs into traces.")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)

    from app import create_app

    app = create_app()
    with app.app_context():
        copied = backfill(limit=args.limit)
    print(f"Backfilled {copied} legacy agent run(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
