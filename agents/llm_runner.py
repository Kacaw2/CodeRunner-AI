"""LLMRunner — pure model concerns extracted from BaseAgent.

Holds the retrying LLM invoke/stream, token-usage extraction (single source for
both sync and stream paths), and message compaction. No tracing or tool logic.
"""

import logging

from core.exceptions import retry_on_llm_error

logger = logging.getLogger(__name__)


def _usage_number(metadata, key: str) -> int:
    if not isinstance(metadata, dict):
        return 0
    value = metadata.get(key, 0)
    return value if isinstance(value, int) else 0


class LLMRunner:
    """Stateless helpers for the model-call portion of an agent loop."""

    @staticmethod
    @retry_on_llm_error(max_retries=2, base_delay=1.0)
    def invoke(llm, messages):
        return llm.invoke(messages)

    @staticmethod
    @retry_on_llm_error(max_retries=2, base_delay=1.0)
    def stream(llm, messages):
        return llm.stream(messages)

    @staticmethod
    def extract_usage(response) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) from a response or chunk."""
        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, dict) and usage_metadata:
            return (
                _usage_number(usage_metadata, "input_tokens"),
                _usage_number(usage_metadata, "output_tokens"),
            )
        response_metadata = getattr(response, "response_metadata", None)
        usage = (
            response_metadata.get("token_usage", {})
            if isinstance(response_metadata, dict) else {}
        )
        return (
            _usage_number(usage, "prompt_tokens"),
            _usage_number(usage, "completion_tokens"),
        )

    @staticmethod
    def compact(messages, max_messages: int = 20):
        """Compact message history; never raise (mirrors BaseAgent behavior)."""
        try:
            from memory.service import MemoryService
            return MemoryService.compact_messages(messages, max_messages=max_messages)
        except Exception as e:
            logger.warning("Message compaction failed: %s", e)
            return messages
