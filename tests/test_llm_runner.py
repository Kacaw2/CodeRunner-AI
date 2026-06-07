"""Unit tests for LLMRunner pure helpers."""


def test_extract_usage_prefers_usage_metadata():
    from ai.agents.llm_runner import LLMRunner

    class _Resp:
        usage_metadata = {"input_tokens": 11, "output_tokens": 5}
        response_metadata = {}

    assert LLMRunner.extract_usage(_Resp()) == (11, 5)


def test_extract_usage_falls_back_to_response_metadata():
    from ai.agents.llm_runner import LLMRunner

    class _Resp:
        usage_metadata = None
        response_metadata = {"token_usage": {"prompt_tokens": 9, "completion_tokens": 3}}

    assert LLMRunner.extract_usage(_Resp()) == (9, 3)


def test_extract_usage_handles_missing_metadata():
    from ai.agents.llm_runner import LLMRunner

    class _Resp:
        usage_metadata = None
        response_metadata = None

    assert LLMRunner.extract_usage(_Resp()) == (0, 0)


def test_compact_never_raises_and_returns_list():
    from ai.agents.llm_runner import LLMRunner
    from langchain_core.messages import HumanMessage

    msgs = [HumanMessage(content=f"m{i}") for i in range(30)]
    out = LLMRunner.compact(msgs, max_messages=20)
    assert isinstance(out, list)
    assert len(out) <= 30
