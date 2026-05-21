"""Tests for the AI exceptions module."""
import time
from unittest.mock import patch, MagicMock

import pytest

from app.agents.exceptions import (
    AIError,
    LLMError,
    ToolError,
    ValidationError,
    RateLimitError,
    ConfigError,
    retry_on_llm_error,
)


class TestExceptionTypes:
    def test_ai_error_base(self):
        err = AIError("internal detail")
        assert str(err) == "internal detail"
        assert err.user_message == "An error occurred while processing your request."

    def test_ai_error_custom_user_message(self):
        err = AIError("detail", user_message="Custom message")
        assert err.user_message == "Custom message"

    def test_llm_error(self):
        err = LLMError("timeout after 30s", status_code=504)
        assert "timeout" in str(err)
        assert err.status_code == 504
        assert "temporarily unavailable" in err.user_message

    def test_tool_error(self):
        err = ToolError("execute_code", "sandbox unavailable")
        assert err.tool_name == "execute_code"
        assert "execute_code" in err.user_message

    def test_validation_error(self):
        err = ValidationError("bad JSON from LLM")
        assert "validated" in err.user_message

    def test_rate_limit_error(self):
        err = RateLimitError(retry_after=30)
        assert err.retry_after == 30
        assert "30" in err.user_message

    def test_config_error(self):
        err = ConfigError("DEEPSEEK_API_KEY not set")
        assert "not properly configured" in err.user_message

    def test_exception_hierarchy(self):
        assert issubclass(LLMError, AIError)
        assert issubclass(ToolError, AIError)
        assert issubclass(ValidationError, AIError)
        assert issubclass(RateLimitError, AIError)
        assert issubclass(ConfigError, AIError)
        assert issubclass(AIError, Exception)


class TestRetryDecorator:
    def test_no_retry_on_success(self):
        call_count = 0

        @retry_on_llm_error(max_retries=2, base_delay=0.01)
        def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeeds() == "ok"
        assert call_count == 1

    def test_retry_on_timeout(self):
        call_count = 0

        @retry_on_llm_error(max_retries=2, base_delay=0.01)
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Connection timeout")
            return "ok"

        assert fails_then_succeeds() == "ok"
        assert call_count == 3

    def test_no_retry_on_non_retryable(self):
        @retry_on_llm_error(max_retries=2, base_delay=0.01)
        def bad_request():
            raise Exception("400 Bad Request: invalid model")

        with pytest.raises(LLMError):
            bad_request()

    def test_max_retries_exhausted(self):
        call_count = 0

        @retry_on_llm_error(max_retries=1, base_delay=0.01)
        def always_timeout():
            nonlocal call_count
            call_count += 1
            raise Exception("Connection timeout")

        with pytest.raises(LLMError):
            always_timeout()
        assert call_count == 2  # initial + 1 retry

    def test_retry_on_503(self):
        call_count = 0

        @retry_on_llm_error(max_retries=1, base_delay=0.01)
        def server_error_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("503 Service Unavailable")
            return "recovered"

        assert server_error_then_ok() == "recovered"
        assert call_count == 2
