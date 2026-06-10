from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


class TestEstimateTokens:
    def test_empty_text_is_zero(self):
        from ai.memory.compaction import estimate_tokens

        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_nonempty_text_uses_four_char_heuristic(self):
        from ai.memory.compaction import estimate_tokens

        assert estimate_tokens("a" * 4) == 1
        assert estimate_tokens("a" * 7) == 1
        assert estimate_tokens("a" * 8) == 2

    def test_message_tokens_counts_content(self):
        from ai.memory.compaction import message_tokens

        assert message_tokens(HumanMessage(content="a" * 40)) == 10

    def test_message_tokens_includes_tool_call_args(self):
        from ai.memory.compaction import message_tokens

        bare = AIMessage(content="")
        with_calls = AIMessage(
            content="",
            tool_calls=[{"name": "run_code", "args": {"src": "x" * 40}, "id": "tc1"}],
        )
        assert message_tokens(with_calls) > message_tokens(bare)
