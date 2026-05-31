"""Structured error types for the AI agent system."""

import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)


class AIError(Exception):
    """Base exception for all AI agent errors."""

    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or "An error occurred while processing your request."


class LLMError(AIError):
    """LLM API call failure (timeout, rate limit, server error)."""

    def __init__(self, message: str, status_code: int | None = None):
        user_msg = "The AI service is temporarily unavailable. Please try again in a moment."
        super().__init__(message, user_msg)
        self.status_code = status_code


class ToolError(AIError):
    """A tool invocation failed."""

    def __init__(self, tool_name: str, message: str):
        user_msg = f"Failed to execute {tool_name}. The operation will continue without this result."
        super().__init__(f"Tool '{tool_name}' failed: {message}", user_msg)
        self.tool_name = tool_name


class ValidationError(AIError):
    """Agent output failed validation (e.g. bad JSON from generator)."""

    def __init__(self, message: str):
        super().__init__(message, "The AI response could not be validated. Please try again.")


class RateLimitError(AIError):
    """User has exceeded their rate limit."""

    def __init__(self, retry_after: int = 60):
        super().__init__(
            f"Rate limit exceeded, retry after {retry_after}s",
            f"You've sent too many requests. Please wait {retry_after} seconds.",
        )
        self.retry_after = retry_after


class ConfigError(AIError):
    """Missing or invalid AI configuration."""

    def __init__(self, message: str):
        super().__init__(message, "AI service is not properly configured. Please contact an administrator.")


class AgentExecutionLimitError(AIError):
    """Agent exhausted its tool-iteration budget without producing a final answer."""

    def __init__(self, agent_name: str, max_iterations: int):
        super().__init__(
            f"Agent '{agent_name}' reached the tool-iteration limit ({max_iterations}) "
            "with tool calls still pending",
            "I couldn't finish this request within the allowed number of steps. "
            "Please simplify your request or try again.",
        )
        self.agent_name = agent_name
        self.max_iterations = max_iterations


def retry_on_llm_error(max_retries: int = 2, base_delay: float = 1.0):
    """Decorator: retry LLM calls with exponential backoff.

    Retries on connection errors, timeouts, and 5xx status codes.
    Does NOT retry on 4xx (bad request, auth errors) — those are permanent.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    error_str = str(e).lower()

                    is_retryable = any(kw in error_str for kw in (
                        "timeout", "connection", "502", "503", "504",
                        "rate_limit", "rate limit", "overloaded",
                        "server_error", "internal server error",
                    ))

                    if not is_retryable or attempt == max_retries:
                        raise LLMError(str(e)) from e

                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, max_retries + 1, delay, e,
                    )
                    time.sleep(delay)

            raise LLMError(str(last_exc)) from last_exc
        return wrapper
    return decorator
