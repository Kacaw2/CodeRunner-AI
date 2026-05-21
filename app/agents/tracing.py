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
            from app.models.agent_trace import AgentRun

            total_ms = int((time.monotonic() - self.start_time) * 1000)
            run = AgentRun(
                id=self.run_id,
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                agent_type=self.agent_type,
                status=status,
                input_message=self.input_message[:2000] if self.input_message else None,
                input_context=self.input_context,
                output_response=response[:2000] if response else None,
                total_latency_ms=total_ms,
                llm_latency_ms=self.llm_total_ms,
                tool_latency_ms=self.tool_total_ms,
                tokens_input=self.total_input_tokens,
                tokens_output=self.total_output_tokens,
                tool_call_count=self.tool_call_count,
                tool_calls_json=self.steps,
                error_type=type(error).__name__ if error else None,
                error_message=str(error)[:500] if error else None,
            )
            db.session.add(run)
            db.session.commit()
        except Exception as e:
            logger.warning("Failed to save trace: %s", e)
