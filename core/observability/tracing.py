import contextvars
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

logger = logging.getLogger(__name__)

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


# Progressive single-trace model: the AgentHarness owns one logical trace per
# chat task / workflow run / eval case / handoff chain and exposes it here as
# the "current" trace. BaseAgent writes spans/events into this ambient trace
# instead of owning its own lifecycle; when no ambient trace is set (direct
# agent.invoke()/stream(), legacy eval runner, unit tests) the agent falls back
# to owning and saving its own TraceCollector.
_current_trace: contextvars.ContextVar = contextvars.ContextVar(
    "current_trace", default=None
)


def get_current_trace():
    """Return the ambient TraceCollector for this execution context, or None."""
    return _current_trace.get()


@contextmanager
def use_current_trace(trace):
    """Bind ``trace`` as the ambient/current trace for the enclosed block."""
    token = _current_trace.set(trace)
    try:
        yield trace
    finally:
        _current_trace.reset(token)


def acquire_trace(
    *,
    agent_type,
    user_id,
    conversation_id=None,
    source="agent",
    links=None,
    input_message="",
    input_context=None,
):
    """Acquire the trace an agent should write into (progressive single-trace).

    If a harness has bound an ambient trace, reuse it and return
    ``owns_trace=False`` — the agent only contributes spans/tokens and must not
    overwrite the owner's input fields. Otherwise create a fresh owned
    TraceCollector seeded with this agent's input, returning ``owns_trace=True``.
    """
    current = get_current_trace()
    if current is not None:
        return current, False
    trace = TraceCollector(
        agent_type=agent_type,
        user_id=user_id,
        conversation_id=conversation_id,
        source=source,
        links=links,
    )
    trace.input_message = input_message
    trace.input_context = input_context
    return trace, True


def finalize_trace(trace, owns_trace, *, status, response="", error=None):
    """Persist (owner) or hand the outcome to the owner (non-owner).

    The owner saves the trace once. A non-owner records a non-completed status
    so the owning harness flushes the correct terminal status for the whole
    chain instead of a misleading ``completed``.
    """
    if owns_trace:
        trace.save(status=status, response=response, error=error)
        return
    if status != "completed":
        trace.pending_status = status
        if error is not None:
            trace.pending_error = error


# Known link keys that map directly onto agent_trace_runs columns, plus the
# business table each points at (used to also emit agent_trace_links rows).
_LINK_TARGET_TABLES = {
    "chat_task_id": "chat_tasks",
    "workflow_run_id": "workflow_runs",
    "conversation_id": "ai_conversations",
    "message_id": "ai_messages",
    "eval_run_id": "eval_runs",
}


class TraceCollector:
    """Collects one agent/eval execution and persists it to the complete trace
    tables through the runtime-neutral :class:`TraceStore`.

    The constructor keeps the historical ``(agent_type, user_id,
    conversation_id)`` signature so existing agent callers are untouched, and
    adds optional context (``source``, ``message_id``, ``links``, ``budget``,
    ``metadata``) used by workers / eval harness.
    """

    def __init__(
        self,
        agent_type: str,
        user_id: int,
        conversation_id: int = None,
        source: str = "agent",
        message_id: int = None,
        links: dict = None,
        budget: dict = None,
        metadata: dict = None,
        model_name: str = None,
    ):
        self.run_id = str(uuid4())
        self.agent_type = agent_type
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.source = source
        self.message_id = message_id
        self.links = dict(links or {})
        self.budget = dict(budget or {})
        self.metadata = dict(metadata or {})
        self.model_name = model_name
        self.steps = []
        self.start_time = time.monotonic()
        self.llm_total_ms = 0
        self.tool_total_ms = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.tool_call_count = 0
        # Aggregate LLM-call counter shared across every agent that writes into
        # this trace (handoff chain / workflow / chat task), used by BaseAgent
        # as a cross-agent total-call guardrail.
        self.llm_call_count = 0
        self.input_message = ""
        self.input_context = None
        # Set by execution units (agents) that write into this trace without
        # owning its lifecycle, so the owner (harness) saves the right status.
        self.pending_status = None
        self.pending_error = None

    @contextmanager
    def trace_llm_call(self):
        step = {"step_type": "llm_call", "step_index": len(self.steps)}
        self.llm_call_count += 1
        start = time.monotonic()
        try:
            yield step
        finally:
            step["latency_ms"] = int((time.monotonic() - start) * 1000)
            self.llm_total_ms += step["latency_ms"]
            self.steps.append(step)

    @contextmanager
    def trace_tool_call(self, tool_name: str, tool_input: dict):
        step = {
            "step_type": "tool_call",
            "step_index": len(self.steps),
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
        start = time.monotonic()
        try:
            yield step
            step["tool_success"] = True
        except Exception as e:
            step["tool_success"] = False
            step["error"] = str(e)[:500]
            raise
        finally:
            step["latency_ms"] = int((time.monotonic() - start) * 1000)
            self.tool_total_ms += step["latency_ms"]
            self.tool_call_count += 1
            self.steps.append(step)

    def save(self, status: str, response: str = "", error: Exception = None):
        total_ms = int((time.monotonic() - self.start_time) * 1000)

        model = self.model_name or self._resolve_model()
        cost_cny = self._compute_cost(model)

        # Cost + Prometheus metrics (F2). Best-effort and isolated from DB
        # persistence so a metrics/costing failure never loses the trace.
        self._emit_metrics(status, total_ms, model, cost_cny)

        try:
            from core.observability.trace_store import TraceStore
            from core.observability.trace_schema import (
                TraceRunRecord,
                TraceSpanRecord,
                TraceLinkRecord,
            )

            # P0: redact credentials before persisting (see _redact_secrets)
            input_message = _redact_secrets(self.input_message)
            response = _redact_secrets(response)
            safe_context = _redact_secrets(_make_json_safe(self.input_context))

            ended_at = _now_china()
            started_at = ended_at - timedelta(milliseconds=total_ms)

            metadata_json = dict(self.metadata)
            if safe_context is not None:
                metadata_json["input_context"] = safe_context

            run = TraceRunRecord(
                id=self.run_id,
                trace_id=self.run_id,
                source=self.source,
                status=status,
                started_at=started_at,
                created_at=ended_at,
                agent_type=self.agent_type,
                user_id=self.user_id,
                conversation_id=self.conversation_id
                or self.links.get("conversation_id"),
                message_id=self.message_id or self.links.get("message_id"),
                chat_task_id=self.links.get("chat_task_id"),
                workflow_run_id=self.links.get("workflow_run_id"),
                eval_run_id=self.links.get("eval_run_id"),
                eval_case_id=self.links.get("eval_case_id"),
                input_preview=(input_message[:2000] if input_message else None),
                output_preview=(response[:2000] if response else None),
                error_type=type(error).__name__ if error else None,
                error_message=str(error)[:500] if error else None,
                model_name=model,
                tokens_input=self.total_input_tokens,
                tokens_output=self.total_output_tokens,
                cost_cny=cost_cny,
                total_latency_ms=total_ms,
                llm_latency_ms=self.llm_total_ms,
                tool_latency_ms=self.tool_total_ms,
                budget_json=dict(self.budget) or None,
                metadata_json=metadata_json or None,
                ended_at=ended_at,
            )

            spans = self._build_spans(started_at)
            links = self._build_links(ended_at)

            TraceStore().save_run(run, spans=spans, links=links)
            logger.info(
                "TRACE_SAVE_OK: run_id=%s agent=%s user=%s status=%s conv=%s source=%s",
                self.run_id, self.agent_type, self.user_id, status,
                self.conversation_id, self.source,
            )
        except Exception as e:
            logger.error(
                "TRACE_SAVE_FAIL: run_id=%s agent=%s user=%s error=%s",
                self.run_id, self.agent_type, self.user_id, e, exc_info=True,
            )

    def _build_spans(self, default_ts):
        from uuid import uuid4 as _uuid4
        from core.observability.trace_schema import TraceSpanRecord

        spans = []
        for step in self.steps:
            step_type = step.get("step_type")
            if step_type == "llm_call":
                span_type = "llm"
            elif step_type == "tool_call":
                span_type = "tool"
            else:
                span_type = step_type or "step"

            tool_input = _redact_secrets(_make_json_safe(step.get("tool_input")))
            tool_output = step.get("tool_output")
            input_preview = (
                str(tool_input)[:2000] if tool_input is not None else None
            )
            output_preview = (
                _redact_secrets(str(tool_output))[:2000]
                if tool_output is not None
                else None
            )

            spans.append(
                TraceSpanRecord(
                    id=str(_uuid4()),
                    trace_id=self.run_id,
                    span_type=span_type,
                    name=step.get("tool_name") or step_type or "step",
                    status="failed" if step.get("error") else "completed",
                    sequence=step.get("step_index", 0),
                    input_preview=input_preview,
                    output_preview=output_preview,
                    error_message=step.get("error"),
                    tokens_input=step.get("prompt_tokens"),
                    tokens_output=step.get("completion_tokens"),
                    latency_ms=step.get("latency_ms", 0),
                    started_at=default_ts,
                    ended_at=default_ts,
                )
            )
        return spans

    def _build_links(self, ts):
        from uuid import uuid4 as _uuid4
        from core.observability.trace_schema import TraceLinkRecord

        links = []
        for key, value in self.links.items():
            if value is None:
                continue
            target_table = _LINK_TARGET_TABLES.get(key)
            if not target_table:
                continue
            link_type = key[:-3] if key.endswith("_id") else key
            links.append(
                TraceLinkRecord(
                    id=str(_uuid4()),
                    trace_id=self.run_id,
                    link_type=link_type,
                    target_table=target_table,
                    target_id=str(value),
                    created_at=ts,
                )
            )
        return links

    def _resolve_model(self):
        try:
            from agents.config import AIConfig
            return AIConfig.MODEL
        except Exception:
            return None

    def _compute_cost(self, model):
        try:
            from core.observability.cost import compute_cost_cny
            cost = compute_cost_cny(
                model, self.total_input_tokens, self.total_output_tokens
            )
            return Decimal(str(cost)) if cost is not None else None
        except Exception:
            return None

    def _emit_metrics(self, status: str, total_ms: int, model, cost_cny):
        """Push Prometheus counters. Fully best-effort: any import/compute error
        is swallowed so observability never degrades the agent path."""
        try:
            from core.observability.metrics import record_agent_run

            if cost_cny is not None:
                logger.info(
                    "TRACE_COST: run_id=%s agent=%s model=%s in=%d out=%d cost_cny=%s",
                    self.run_id, self.agent_type, model,
                    self.total_input_tokens, self.total_output_tokens, cost_cny,
                )

            record_agent_run(
                self.agent_type,
                status,
                latency_ms=total_ms,
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens,
                tool_calls=self.tool_call_count,
                cost_cny=float(cost_cny) if cost_cny is not None else None,
                model=model,
            )
        except Exception:
            logger.debug("metrics/cost emission failed", exc_info=True)


def _make_json_safe(obj):
    """Ensure an object is JSON-serializable for DB storage."""
    if obj is None:
        return None
    try:
        import json
        json.dumps(obj)
        return obj
    except (TypeError, ValueError, OverflowError):
        import json
        return json.loads(json.dumps(obj, default=str))


import re as _re

# Credential-like patterns scrubbed from any trace data before it is persisted.
_SECRET_PATTERNS = [
    _re.compile(r"sk-[A-Za-z0-9]{20,}"),                                  # OpenAI/DeepSeek API keys
    _re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", _re.I),                  # bearer tokens
    _re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[=:]\s*\S+"),
    _re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
]


def _redact_secrets(obj):
    """Recursively replace credential-like substrings with [REDACTED].

    Applied to trace input/output before DB persistence so that secrets pasted
    by users (in code or conversation) never land in the trace tables.
    """
    if isinstance(obj, str):
        s = obj
        for pat in _SECRET_PATTERNS:
            s = pat.sub("[REDACTED]", s)
        return s
    if isinstance(obj, dict):
        return {k: _redact_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj
