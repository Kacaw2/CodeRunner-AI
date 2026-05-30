"""Prometheus metrics for agent runs (F2).

A thin, dependency-tolerant wrapper around ``prometheus_client``. If the library
is not installed (e.g. a stripped-down environment), every function degrades to
a no-op and ``metrics_response`` returns a 501-style body, so importing this
module never breaks the app.

Exposed series:

    agent_runs_total{agent_type,status}          counter
    agent_run_latency_seconds{agent_type}        histogram
    agent_tokens_total{agent_type,direction}     counter   (direction=input|output)
    agent_cost_cny_total{agent_type,model}       counter
    agent_tool_calls_total{agent_type}           counter

Call ``record_agent_run(...)`` once per finished agent run (wired from
``TraceCollector.save``) and serve ``metrics_response()`` from a ``/metrics``
endpoint on each process you want scraped.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dep is absent
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

# A dedicated registry keeps these metrics isolated from the global default,
# which makes the module safe to import repeatedly (e.g. in tests).
if _PROM_AVAILABLE:
    REGISTRY = CollectorRegistry()

    AGENT_RUNS = Counter(
        "agent_runs_total",
        "Total agent runs by type and terminal status.",
        ["agent_type", "status"],
        registry=REGISTRY,
    )
    AGENT_RUN_LATENCY = Histogram(
        "agent_run_latency_seconds",
        "End-to-end agent run latency in seconds.",
        ["agent_type"],
        registry=REGISTRY,
    )
    AGENT_TOKENS = Counter(
        "agent_tokens_total",
        "LLM tokens consumed by agent runs.",
        ["agent_type", "direction"],
        registry=REGISTRY,
    )
    AGENT_COST = Counter(
        "agent_cost_cny_total",
        "Estimated LLM cost in CNY by agent type and model.",
        ["agent_type", "model"],
        registry=REGISTRY,
    )
    AGENT_TOOL_CALLS = Counter(
        "agent_tool_calls_total",
        "Tool invocations performed during agent runs.",
        ["agent_type"],
        registry=REGISTRY,
    )
else:  # pragma: no cover
    REGISTRY = None


def record_agent_run(
    agent_type: str,
    status: str,
    *,
    latency_ms: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    tool_calls: int = 0,
    cost_cny: float | None = None,
    model: str | None = None,
) -> None:
    """Record one finished agent run. No-op if prometheus_client is missing."""
    if not _PROM_AVAILABLE:
        return
    try:
        agent_type = agent_type or "unknown"
        AGENT_RUNS.labels(agent_type=agent_type, status=status or "unknown").inc()
        if latency_ms:
            AGENT_RUN_LATENCY.labels(agent_type=agent_type).observe(latency_ms / 1000.0)
        if input_tokens:
            AGENT_TOKENS.labels(agent_type=agent_type, direction="input").inc(input_tokens)
        if output_tokens:
            AGENT_TOKENS.labels(agent_type=agent_type, direction="output").inc(output_tokens)
        if tool_calls:
            AGENT_TOOL_CALLS.labels(agent_type=agent_type).inc(tool_calls)
        if cost_cny:
            AGENT_COST.labels(agent_type=agent_type, model=model or "unknown").inc(cost_cny)
    except Exception:  # never let metrics break a request path
        logger.debug("record_agent_run failed", exc_info=True)


def metrics_response() -> tuple[bytes, int, str]:
    """Return ``(body, status_code, content_type)`` for a /metrics endpoint."""
    if not _PROM_AVAILABLE:
        return (
            b"# prometheus_client not installed\n",
            501,
            "text/plain; charset=utf-8",
        )
    return generate_latest(REGISTRY), 200, CONTENT_TYPE_LATEST
