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


class TestSafeBoundary:
    def _round(self):
        return [
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "tc1"}]),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]

    def test_tail_never_starts_with_tool_message(self):
        from ai.memory.compaction import _earliest_safe_keep_index

        body = [HumanMessage(content="q")] + self._round()
        keep = _earliest_safe_keep_index(body, start_index=2)
        assert keep == 1
        assert isinstance(body[keep], AIMessage)

    def test_clean_boundary_is_unchanged(self):
        from ai.memory.compaction import _earliest_safe_keep_index

        body = [HumanMessage(content="a"), HumanMessage(content="b"), HumanMessage(content="c")]
        assert _earliest_safe_keep_index(body, start_index=2) == 2

    def test_select_recent_respects_message_cap(self):
        from ai.memory.compaction import _select_recent_index

        body = [HumanMessage(content="m") for _ in range(10)]
        idx = _select_recent_index(body, recent_token_budget=10_000, max_recent_messages=3)
        assert len(body) - idx == 3

    def test_select_recent_respects_token_budget(self):
        from ai.memory.compaction import _select_recent_index

        body = [HumanMessage(content="x" * 40) for _ in range(10)]  # ~10 tokens each
        idx = _select_recent_index(body, recent_token_budget=25, max_recent_messages=100)
        assert len(body) - idx == 2
