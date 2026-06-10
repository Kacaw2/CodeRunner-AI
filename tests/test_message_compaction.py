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


class TestCompactWindow:
    def _msgs(self, n_human):
        out = [SystemMessage(content="sys")]
        for i in range(n_human):
            out.append(HumanMessage(content="x" * 400))  # ~100 tokens each
        return out

    def test_under_budget_is_noop(self):
        from ai.memory.compaction import compact_window

        msgs = self._msgs(2)
        result = compact_window(
            msgs, token_budget=10_000, recent_token_budget=8_000,
            max_recent_messages=20, summarizer=lambda _t: "SUMMARY",
        )
        assert result.compacted is False
        assert result.messages == msgs
        assert result.dropped_messages == 0

    def test_over_budget_uses_llm_summary_and_preserves_system(self):
        from ai.memory.compaction import compact_window

        msgs = self._msgs(30)
        result = compact_window(
            msgs, token_budget=500, recent_token_budget=300,
            max_recent_messages=20, summarizer=lambda _t: "LLM SUMMARY",
        )
        assert result.compacted is True
        assert result.summarized is True
        assert result.fallback_used is False
        assert isinstance(result.messages[0], SystemMessage)
        assert isinstance(result.messages[1], HumanMessage)
        assert "LLM SUMMARY" in result.messages[1].content
        assert result.tokens_after < result.tokens_before

    def test_falls_back_to_structured_when_summarizer_returns_none(self):
        from ai.memory.compaction import compact_window

        msgs = self._msgs(30)
        result = compact_window(
            msgs, token_budget=500, recent_token_budget=300,
            max_recent_messages=20, summarizer=lambda _t: None,
        )
        assert result.compacted is True
        assert result.summarized is False
        assert result.fallback_used is True
        assert isinstance(result.messages[1], HumanMessage)

    def test_does_not_orphan_tool_messages(self):
        from ai.memory.compaction import compact_window

        msgs = [SystemMessage(content="sys")]
        for i in range(20):
            msgs.append(HumanMessage(content="x" * 400))
            msgs.append(AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": f"tc{i}"}]))
            msgs.append(ToolMessage(content="y" * 400, tool_call_id=f"tc{i}"))
        result = compact_window(
            msgs, token_budget=500, recent_token_budget=300,
            max_recent_messages=20, summarizer=lambda _t: "S",
        )
        kept_tail = result.messages[2:]
        assert not (kept_tail and isinstance(kept_tail[0], ToolMessage))
        for j, m in enumerate(kept_tail):
            if isinstance(m, ToolMessage):
                assert any(
                    isinstance(p, AIMessage) and p.tool_calls for p in kept_tail[:j]
                )

    def test_summarizer_exception_falls_back(self):
        from ai.memory.compaction import compact_window

        def boom(_t):
            raise RuntimeError("llm down")

        msgs = self._msgs(30)
        result = compact_window(
            msgs, token_budget=500, recent_token_budget=300,
            max_recent_messages=20, summarizer=boom,
        )
        assert result.compacted is True
        assert result.fallback_used is True
