import logging
import time
from contextlib import contextmanager
from uuid import uuid4

logger = logging.getLogger(__name__)


class TraceCollector:

    def __init__(self, agent_type: str, user_id: int, conversation_id: int = None):
        self.run_id = str(uuid4())
        self.agent_type = agent_type
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.steps = []
        self.start_time = time.monotonic()
        self.llm_total_ms = 0
        self.tool_total_ms = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.tool_call_count = 0
        self.input_message = ""
        self.input_context = None

    @contextmanager
    def trace_llm_call(self):
        step = {"step_type": "llm_call", "step_index": len(self.steps)}
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
        try:
            from app.core.extensions import db
            from app.models.agent_trace import AgentRun, AgentRunStep

            total_ms = int((time.monotonic() - self.start_time) * 1000)

            # P0: redact credentials before persisting (see _redact_secrets)
            self.input_message = _redact_secrets(self.input_message)
            response = _redact_secrets(response)
            safe_steps = _redact_secrets(_make_json_safe(self.steps))
            safe_context = _redact_secrets(_make_json_safe(self.input_context))

            run = AgentRun(
                id=self.run_id,
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                agent_type=self.agent_type,
                status=status,
                input_message=self.input_message[:2000] if self.input_message else None,
                input_context=safe_context,
                output_response=response[:2000] if response else None,
                total_latency_ms=total_ms,
                llm_latency_ms=self.llm_total_ms,
                tool_latency_ms=self.tool_total_ms,
                tokens_input=self.total_input_tokens,
                tokens_output=self.total_output_tokens,
                tool_call_count=self.tool_call_count,
                tool_calls_json=safe_steps,
                error_type=type(error).__name__ if error else None,
                error_message=str(error)[:500] if error else None,
            )
            db.session.add(run)

            for step in safe_steps if isinstance(safe_steps, list) else []:
                db_step = AgentRunStep(
                    run_id=self.run_id,
                    step_index=step.get("step_index", 0),
                    step_type=step.get("step_type"),
                    tool_name=step.get("tool_name"),
                    tool_input=step.get("tool_input"),
                    tool_output_preview=str(step.get("tool_output", ""))[:500],
                    tool_success=step.get("tool_success"),
                    llm_prompt_tokens=step.get("prompt_tokens"),
                    llm_completion_tokens=step.get("completion_tokens"),
                    latency_ms=step.get("latency_ms", 0),
                    error=step.get("error"),
                )
                db.session.add(db_step)

            db.session.commit()
            logger.info("TRACE_SAVE_OK: run_id=%s agent=%s user=%d status=%s conv=%s",
                        self.run_id, self.agent_type, self.user_id, status, self.conversation_id)
        except Exception as e:
            logger.error("TRACE_SAVE_FAIL: run_id=%s agent=%s user=%d error=%s",
                         self.run_id, self.agent_type, self.user_id, e, exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass


def _make_json_safe(obj):
    """Ensure an object is JSON-serializable for DB storage."""
    if obj is None:
        return None
    try:
        import json
        json.dumps(obj)
        return obj
    except (TypeError, ValueError, OverflowError):
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
    by users (in code or conversation) never land in agent_runs / agent_run_steps.
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
