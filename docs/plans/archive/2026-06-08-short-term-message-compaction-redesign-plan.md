# Short-Term Message Compaction Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把单次 agent run 的短期消息窗口压缩从「按消息条数、一次性、可能切断 tool-call 配对」升级为「按估算 token 触发、loop 内滚动、tool-call/tool-result 配对安全、并写入 compaction trace span」的可测试实现。

**Architecture:** 新增纯函数模块 `ai/memory/compaction.py` 承载 token 估算、配对安全切分与 `compact_window` 编排；`MemoryService` 注入真实 LLM summarizer 并保留 legacy `compact_messages(list)->list` 入口；`LLMRunner` 暴露返回结构化报告的 `compact_window`；`AgentRuntime` 在进入 loop 前和每轮工具调用后调用压缩并把报告写成一个 `compaction` trace span。压缩在估算 token 低于预算时是廉价 no-op，因此 loop 内反复调用不会每轮触发 LLM。

**Tech Stack:** Python 3.11、dataclasses、LangChain `langchain_core.messages`（SystemMessage / HumanMessage / AIMessage / ToolMessage）、现有 `ai.agents.config.AIConfig` FAST tier LLM、`core/observability/tracing.py` TraceCollector、pytest。

---

## 1. 计划状态与范围

> 状态: Active
> 日期: 2026-06-08
> 来源: 本会话对 `ai/memory/service.py::compact_messages` 与 `ai/agents/runtime.py` agent loop 的审查
> 上层路线: `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md`（第 1 节 Context and Memory Architecture，真实需求第 43 条 "为 compaction 建立 trace event"、建议验收 "agent run 的上下文大小有上限策略"）

本计划只重做**单次 agent run 内的短期消息窗口压缩**。它与已存在的四份 memory 子计划（Phase 1-2 MemoryContext、Phase 3 budget/filter/audit、Phase 4 lifecycle、Phase 5 eval replay）是正交的 runtime 层工作：那四份治理的是跨会话的长/中期画像与 summary 注入，本计划治理的是当前 run 的 LangChain 消息列表。

`2026-06-08-agent-memory-context-governance-phase1-2-plan.md` 第 46/49 行把「修改 `LLMRunner.compact()` / 重新设计短期消息压缩」列为非目标。本计划正是承接那条被显式延后的工作，独立执行，不改动 Phase 1-2 的范围。

## 2. 当前实现与缺陷

当前实现：`ai/memory/service.py::compact_messages(messages, max_messages=20)`，经 `ai/agents/llm_runner.py::compact` 包装，在 `ai/agents/runtime.py::_acquire`（约第 120 行）进入 agent loop **之前调用一次**。

已确认缺陷（按严重度）：

1. **配对不安全（正确性 bug）**：切片 `messages[1:-max_messages]` / `messages[-max_messages:]` 可能把带 `tool_calls` 的 `AIMessage` 留在被丢弃/被摘要侧，而其对应 `ToolMessage` 落在保留侧，产生孤儿 `tool_call_id`。Anthropic / OpenAI 对不配对的 tool 消息会直接拒绝请求。
2. **压缩时机错位（无界增长）**：压缩只在进 loop 前发生一次；loop（`runtime.py` 约第 153-193 行）每轮 `messages.append(response)` + `messages.append(tool_msg)` 持续累加，**loop 内不再压缩**，单次多轮工具调用的上下文只受 `MAX_LLM_CALLS_PER_TRACE` 兜底。
3. **按条数而非 token 触发**：`max_messages=20` 数的是消息条数，一条几万字符的工具 stdout 也只算一条；真正的上下文约束是 token。触发条件与实际约束错配。
4. **无审计**：压缩前后保留/丢弃/摘要的边界没有写进 trace，违反上层路线第 43 条。

## 3. 目标行为

```text
messages = [SystemMessage, ...history...]
  -> estimate total tokens
  -> if total <= token_budget: 原样返回 (compacted=False, 廉价 no-op)
  -> else:
       body = messages[1:]                      # 永远保留 system
       recent_start = select_recent(body, recent_token_budget, max_recent_messages)
       keep = earliest_safe_keep_index(body, recent_start)   # 配对安全：tail 不以 ToolMessage 开头
       early, recent = body[:keep], body[keep:]
       summary = summarizer(transcript(early)) or structured_fallback(early)
       return [SystemMessage, HumanMessage(summary)] + recent
  -> 返回 CompactionResult(messages, compacted, dropped, kept, summarized, fallback_used, tokens_before, tokens_after)
```

不变式：
- `messages[0]`（SystemMessage）始终原样保留在结果第 0 位。
- 结果中的保留尾部不以 `ToolMessage` 开头；保留尾部内任意 `ToolMessage` 的父 `AIMessage(tool_calls)` 也在保留尾部内（因为同一 tool round 连续且以 AIMessage 起头，配对安全等价于「尾部不以 ToolMessage 开头」）。
- token 低于预算时不调用 LLM、不改变列表（loop 内可廉价反复调用）。
- summarizer 失败（返回 None / 抛异常）时回退到结构化截断，绝不抛出。

## 4. 非目标

- 不引入真实 tokenizer 依赖；用 `len(text)//4` 的字符启发式估算，作为已消费的内部度量，不对外承诺精确 token 数。
- 不改动跨会话长/中期 memory（StudentProfile / TeacherPreference / AIConversation.summary 与 `get_memory_context`）。
- 不改动 handoff context 裁剪（`test_handoff_context.py` 覆盖的 `RemoveMessage` 路径）。
- 不新增数据库表或 Alembic migration；compaction 审计复用现有 trace span（`trace.steps` -> `_build_spans`）。
- 不改 `WorkflowEngine`、ToolRuntime、MCP、handoff kernel。
- 不删除 `compact_messages` / `compact` 旧入口；保留向后兼容签名。

## 5. 文件地图

### 新增

| 文件 | 职责 |
|---|---|
| `ai/memory/compaction.py` | 纯函数：`estimate_tokens`、`message_tokens`、`_select_recent_index`、`_earliest_safe_keep_index`、`compact_window`；`CompactionResult` dataclass；预算常量 |
| `tests/test_message_compaction.py` | 覆盖 token 估算、配对安全切分、no-op、LLM 摘要、结构化回退 |

### 修改

| 文件 | 职责 |
|---|---|
| `ai/memory/service.py` | `compact_messages` 委托新模块（保持 `list->list`）；新增 `compact_window`（返回 `CompactionResult`）与 `_llm_summarize_transcript` summarizer |
| `ai/agents/llm_runner.py` | 新增 `compact_window`（返回 `CompactionResult`）；`compact` 改为返回 `compact_window(...).messages`，签名不变 |
| `core/observability/tracing.py` | `TraceCollector` 新增 `trace_compaction(result)`，把压缩报告 append 成一个 `compaction` step |
| `ai/agents/runtime.py` | `_acquire` 进 loop 前用 `compact_window` 并记录 span；loop 内每轮工具调用后再压缩并记录 |
| `docs/architecture/data-state-memory.md` | 补「短期消息窗口压缩」当前实现态与配对/token/审计语义 |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_message_compaction.py` | 纯函数与编排（新增） |
| `tests/test_llm_runner.py` | `compact` 向后兼容 + 新 `compact_window` 返回报告 |
| `tests/test_agent_runtime_kernel.py` | loop 内压缩触发、配对安全、compaction span 写入 |

## 6. 数据契约

`ai/memory/compaction.py` 目标接口：

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# 字符启发式：约 4 字符 ≈ 1 token。仅作内部预算度量，不对外承诺精确值。
DEFAULT_CONTEXT_TOKEN_BUDGET = 12000   # 超过此估算总量才触发压缩
DEFAULT_RECENT_TOKEN_BUDGET = 8000     # 保留尾部的估算 token 上限
DEFAULT_MAX_RECENT_MESSAGES = 20       # 保留尾部的硬性条数上限（防御纵深）


@dataclass(frozen=True)
class CompactionResult:
    messages: list
    compacted: bool
    dropped_messages: int
    kept_messages: int
    summarized: bool        # 是否使用了 LLM 摘要
    fallback_used: bool     # 是否回退到结构化截断
    tokens_before: int
    tokens_after: int
```

`Summarizer` 约定：`Callable[[str], str | None]`，输入 early 段 transcript，返回摘要文本；返回 `None` 表示不可用，由 `compact_window` 回退到结构化截断。

所有字段都必须被消费：`CompactionResult` 的每个字段都由 `TraceCollector.trace_compaction` 写入 span，或由 `MemoryService.compact_messages` / `LLMRunner.compact` 读取 `.messages`。若实现时发现某字段无消费点，删除它。

---

### Task 1: token 估算纯函数

**Files:**
- Create: `ai/memory/compaction.py`
- Test: `tests/test_message_compaction.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_message_compaction.py`:

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_message_compaction.py::TestEstimateTokens -v`
Expected: FAIL（`ModuleNotFoundError: ai.memory.compaction`）

- [ ] **Step 3: 实现估算函数**

创建 `ai/memory/compaction.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# 字符启发式：约 4 字符 ≈ 1 token。仅作内部预算度量，不对外承诺精确值。
DEFAULT_CONTEXT_TOKEN_BUDGET = 12000
DEFAULT_RECENT_TOKEN_BUDGET = 8000
DEFAULT_MAX_RECENT_MESSAGES = 20


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def message_tokens(message) -> int:
    total = estimate_tokens(getattr(message, "content", ""))
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        try:
            total += estimate_tokens(json.dumps(tool_calls, default=str))
        except (TypeError, ValueError):
            total += estimate_tokens(str(tool_calls))
    return total
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_message_compaction.py::TestEstimateTokens -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add ai/memory/compaction.py tests/test_message_compaction.py
git commit -m "feat(memory): add token estimation helpers for message compaction"
```

---

### Task 2: 配对安全切分

**Files:**
- Modify: `ai/memory/compaction.py`
- Test: `tests/test_message_compaction.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_message_compaction.py` 追加:

```python
class TestSafeBoundary:
    def _round(self):
        # 一个完整 tool round：AIMessage(tool_calls) 紧跟其 ToolMessage。
        return [
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "tc1"}]),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]

    def test_tail_never_starts_with_tool_message(self):
        from ai.memory.compaction import _earliest_safe_keep_index

        body = [HumanMessage(content="q")] + self._round()
        # 候选边界落在 ToolMessage 上 -> 必须回退到其父 AIMessage。
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
        # 极大 token 预算下仍受条数上限约束。
        idx = _select_recent_index(body, recent_token_budget=10_000, max_recent_messages=3)
        assert len(body) - idx == 3

    def test_select_recent_respects_token_budget(self):
        from ai.memory.compaction import _select_recent_index

        body = [HumanMessage(content="x" * 40) for _ in range(10)]  # 每条 ~10 token
        idx = _select_recent_index(body, recent_token_budget=25, max_recent_messages=100)
        # 25 token 预算下最多容纳 2 条整消息。
        assert len(body) - idx == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_message_compaction.py::TestSafeBoundary -v`
Expected: FAIL（`AttributeError` / 函数未定义）

- [ ] **Step 3: 实现切分函数**

在 `ai/memory/compaction.py` 追加:

```python
def _select_recent_index(
    body: list, recent_token_budget: int, max_recent_messages: int
) -> int:
    """返回 body 中保留尾部的起始下标（token 预算 + 条数上限，取更靠后者）。"""
    total = 0
    token_start = len(body)
    while token_start > 0:
        t = message_tokens(body[token_start - 1])
        if total + t > recent_token_budget and token_start < len(body):
            break
        total += t
        token_start -= 1
    count_start = max(0, len(body) - max_recent_messages)
    return max(token_start, count_start)


def _earliest_safe_keep_index(body: list, start_index: int) -> int:
    """把候选边界向前回退，使保留尾部不以 ToolMessage 开头。

    tool round 在消息序列中连续且以 AIMessage(tool_calls) 起头，因此只要保证
    body[keep] 不是 ToolMessage，就保证保留尾部内每个 ToolMessage 的父
    AIMessage 也在尾部内（配对安全）。"""
    i = max(0, min(start_index, len(body)))
    while i > 0 and isinstance(body[i], ToolMessage):
        i -= 1
    return i
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_message_compaction.py::TestSafeBoundary -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add ai/memory/compaction.py tests/test_message_compaction.py
git commit -m "feat(memory): add tool-pairing-safe window boundary selection"
```

---

### Task 3: compact_window 编排

**Files:**
- Modify: `ai/memory/compaction.py`
- Test: `tests/test_message_compaction.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_message_compaction.py` 追加:

```python
class TestCompactWindow:
    def _msgs(self, n_human):
        out = [SystemMessage(content="sys")]
        for i in range(n_human):
            out.append(HumanMessage(content="x" * 400))  # 每条 ~100 token
        return out

    def test_under_budget_is_noop(self):
        from ai.memory.compaction import compact_window

        msgs = self._msgs(2)  # ~200 token，远低于预算
        result = compact_window(
            msgs, token_budget=10_000, recent_token_budget=8_000,
            max_recent_messages=20, summarizer=lambda _t: "SUMMARY",
        )
        assert result.compacted is False
        assert result.messages == msgs
        assert result.dropped_messages == 0

    def test_over_budget_uses_llm_summary_and_preserves_system(self):
        from ai.memory.compaction import compact_window

        msgs = self._msgs(30)  # ~3000 token
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
        kept_tail = result.messages[2:]  # 跳过 system + summary
        assert not (kept_tail and isinstance(kept_tail[0], ToolMessage))
        # 保留尾部里每个 ToolMessage 的父 AIMessage 都在
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_message_compaction.py::TestCompactWindow -v`
Expected: FAIL（`compact_window` 未定义）

- [ ] **Step 3: 实现编排函数**

在 `ai/memory/compaction.py` 追加:

```python
@dataclass(frozen=True)
class CompactionResult:
    messages: list
    compacted: bool
    dropped_messages: int
    kept_messages: int
    summarized: bool
    fallback_used: bool
    tokens_before: int
    tokens_after: int


def _total_tokens(messages: list) -> int:
    return sum(message_tokens(m) for m in messages)


def _transcript(early: list) -> str:
    parts = []
    for m in early:
        content = getattr(m, "content", "")
        if content:
            role = getattr(m, "type", "unknown")
            parts.append(f"[{role}] {content[:300]}")
    return "\n".join(parts)


def _structured_fallback(early: list) -> str:
    topics = []
    for m in early:
        content = getattr(m, "content", "")
        if content:
            topics.append(content[:100])
    tail = "..." if len(topics) > 5 else ""
    return "Previous conversation summary: discussed " + "; ".join(topics[:5]) + tail


def compact_window(
    messages: list,
    *,
    token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
    recent_token_budget: int = DEFAULT_RECENT_TOKEN_BUDGET,
    max_recent_messages: int = DEFAULT_MAX_RECENT_MESSAGES,
    summarizer: Callable[[str], str | None] | None = None,
) -> CompactionResult:
    tokens_before = _total_tokens(messages)
    if not messages or tokens_before <= token_budget:
        return CompactionResult(
            messages=messages, compacted=False, dropped_messages=0,
            kept_messages=len(messages), summarized=False, fallback_used=False,
            tokens_before=tokens_before, tokens_after=tokens_before,
        )

    system_msg = messages[0]
    body = messages[1:]
    recent_start = _select_recent_index(body, recent_token_budget, max_recent_messages)
    keep = _earliest_safe_keep_index(body, recent_start)
    early, recent = body[:keep], body[keep:]
    if not early:
        return CompactionResult(
            messages=messages, compacted=False, dropped_messages=0,
            kept_messages=len(messages), summarized=False, fallback_used=False,
            tokens_before=tokens_before, tokens_after=tokens_before,
        )

    summary_text = None
    summarized = False
    if summarizer is not None:
        try:
            summary_text = summarizer(_transcript(early))
        except Exception:
            summary_text = None
    if summary_text:
        summarized = True
        body_text = f"Previous conversation summary:\n{summary_text}"
    else:
        body_text = _structured_fallback(early)

    compacted_messages = [system_msg, HumanMessage(content=body_text)] + recent
    return CompactionResult(
        messages=compacted_messages, compacted=True,
        dropped_messages=len(early), kept_messages=len(recent),
        summarized=summarized, fallback_used=not summarized,
        tokens_before=tokens_before, tokens_after=_total_tokens(compacted_messages),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_message_compaction.py -v`
Expected: PASS（Task 1-3 全部）

- [ ] **Step 5: 提交**

```bash
git add ai/memory/compaction.py tests/test_message_compaction.py
git commit -m "feat(memory): add token-budget compact_window with pairing-safe summary"
```

---

### Task 4: MemoryService 接线（保留 legacy 入口）

**Files:**
- Modify: `ai/memory/service.py:150-196`
- Test: `tests/test_agents.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents.py` 追加（放在文件末尾的独立 class）:

```python
class TestCompactWindowService:
    def test_compact_messages_returns_list_and_preserves_system(self, app):
        from langchain_core.messages import SystemMessage, HumanMessage
        from ai.memory.service import MemoryService

        with app.app_context():
            msgs = [SystemMessage(content="sys")] + [
                HumanMessage(content="x" * 400) for _ in range(40)
            ]
            out = MemoryService.compact_messages(msgs, max_messages=20)
            assert isinstance(out, list)
            assert isinstance(out[0], SystemMessage)

    def test_compact_window_reports_compaction(self, app):
        from langchain_core.messages import SystemMessage, HumanMessage
        from ai.memory.service import MemoryService

        with app.app_context():
            msgs = [SystemMessage(content="sys")] + [
                HumanMessage(content="x" * 4000) for _ in range(40)
            ]
            result = MemoryService.compact_window(msgs, max_recent_messages=20)
            assert result.compacted is True
            assert result.tokens_after < result.tokens_before
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents.py::TestCompactWindowService -v`
Expected: FAIL（`MemoryService.compact_window` 未定义）

- [ ] **Step 3: 重写 compact_messages 并新增 compact_window / summarizer**

把 `ai/memory/service.py` 第 150-196 行的整段 `compact_messages` 替换为:

```python
    @staticmethod
    def _llm_summarize_transcript(transcript: str) -> str | None:
        """FAST-tier LLM 摘要；失败返回 None 由 compact_window 回退到结构化截断。"""
        if not transcript:
            return None
        try:
            from ai.agents.config import AIConfig
            from ai.llm.tiers import ModelTier

            llm = AIConfig.get_llm(tier=ModelTier.FAST)
            prompt = (
                "Compress the following conversation history into a brief summary "
                "(max 200 words). Preserve key facts, decisions, and context.\n\n"
                + transcript
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content or None
        except Exception as e:
            logger.warning("LLM compression failed, falling back to truncation: %s", e)
            return None

    @staticmethod
    def compact_window(messages: list, *, max_recent_messages: int = 20):
        """结构化压缩单次 run 的消息窗口，返回 CompactionResult。"""
        from ai.memory.compaction import (
            DEFAULT_CONTEXT_TOKEN_BUDGET,
            DEFAULT_RECENT_TOKEN_BUDGET,
            compact_window,
        )

        return compact_window(
            messages,
            token_budget=DEFAULT_CONTEXT_TOKEN_BUDGET,
            recent_token_budget=DEFAULT_RECENT_TOKEN_BUDGET,
            max_recent_messages=max_recent_messages,
            summarizer=MemoryService._llm_summarize_transcript,
        )

    @staticmethod
    def compact_messages(messages: list, max_messages: int = 20) -> list:
        """Backward-compatible list->list entry; delegates to compact_window."""
        return MemoryService.compact_window(
            messages, max_recent_messages=max_messages
        ).messages
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents.py::TestCompactWindowService tests/test_llm_runner.py -v`
Expected: PASS（含旧 `test_compact_never_raises_and_returns_list`）

- [ ] **Step 5: 提交**

```bash
git add ai/memory/service.py tests/test_agents.py
git commit -m "refactor(memory): delegate compact_messages to compact_window"
```

---

### Task 5: LLMRunner.compact_window

**Files:**
- Modify: `ai/agents/llm_runner.py:53-61`
- Test: `tests/test_llm_runner.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_llm_runner.py` 追加:

```python
def test_compact_window_returns_result(app):
    from ai.agents.llm_runner import LLMRunner
    from langchain_core.messages import SystemMessage, HumanMessage

    with app.app_context():
        msgs = [SystemMessage(content="sys")] + [
            HumanMessage(content="x" * 4000) for _ in range(40)
        ]
        result = LLMRunner.compact_window(msgs, max_messages=20)
        assert hasattr(result, "messages")
        assert hasattr(result, "compacted")
        assert isinstance(result.messages, list)


def test_compact_window_never_raises(app):
    from ai.agents.llm_runner import LLMRunner

    with app.app_context():
        result = LLMRunner.compact_window(["not-a-message"], max_messages=20)
        assert isinstance(result.messages, list)
```

注：`test_llm_runner.py` 现有用例不带 `app` fixture。新增用例使用 `app` fixture（`tests/conftest.py` 已提供）以便 summarizer 走 app context；旧用例保持不变。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_llm_runner.py::test_compact_window_returns_result -v`
Expected: FAIL（`LLMRunner.compact_window` 未定义）

- [ ] **Step 3: 实现 compact_window 并保留 compact**

把 `ai/agents/llm_runner.py` 第 53-61 行的 `compact` 替换为:

```python
    @staticmethod
    def compact_window(messages, max_messages: int = 20):
        """Compact message history; never raise. Returns CompactionResult."""
        from ai.memory.compaction import CompactionResult

        try:
            from ai.memory.service import MemoryService

            return MemoryService.compact_window(
                messages, max_recent_messages=max_messages
            )
        except Exception as e:
            logger.warning("Message compaction failed: %s", e)
            return CompactionResult(
                messages=messages, compacted=False, dropped_messages=0,
                kept_messages=len(messages), summarized=False, fallback_used=False,
                tokens_before=0, tokens_after=0,
            )

    @staticmethod
    def compact(messages, max_messages: int = 20):
        """Backward-compatible list->list wrapper around compact_window."""
        return LLMRunner.compact_window(messages, max_messages=max_messages).messages
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_llm_runner.py -v`
Expected: PASS（新旧用例全部）

- [ ] **Step 5: 提交**

```bash
git add ai/agents/llm_runner.py tests/test_llm_runner.py
git commit -m "feat(agents): add LLMRunner.compact_window returning compaction report"
```

---

### Task 6: TraceCollector.trace_compaction + runtime loop 内压缩

**Files:**
- Modify: `core/observability/tracing.py:187`（在 `add_artifact` 前插入新方法）
- Modify: `ai/agents/runtime.py:119-121`（进 loop 前）与 `ai/agents/runtime.py:193`（loop 内每轮工具后）
- Test: `tests/test_agent_runtime_kernel.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent_runtime_kernel.py` 追加。先确认该文件已有可复用的 fake-LLM / runtime 装配 helper（顶部 import 与现有用例）；下面的用例假定与现有用例相同的装配方式（fake LLM 先返回若干 tool call，再返回最终文本）。若 helper 名称不同，按文件现有 helper 调整：

```python
def test_compaction_span_recorded_when_over_budget(monkeypatch):
    """超预算时 runtime 应写入一个 compaction span。"""
    from core.observability.tracing import TraceCollector
    from ai.memory.compaction import CompactionResult

    trace = TraceCollector(agent_type="tutor", user_id=1)
    result = CompactionResult(
        messages=[], compacted=True, dropped_messages=5, kept_messages=3,
        summarized=True, fallback_used=False, tokens_before=900, tokens_after=300,
    )
    trace.trace_compaction(result)

    spans = [s for s in trace.steps if s.get("step_type") == "compaction"]
    assert len(spans) == 1
    assert spans[0]["tool_input"]["dropped_messages"] == 5
    assert spans[0]["tool_input"]["tokens_after"] == 300


def test_trace_compaction_noop_not_recorded():
    from core.observability.tracing import TraceCollector
    from ai.memory.compaction import CompactionResult

    trace = TraceCollector(agent_type="tutor", user_id=1)
    result = CompactionResult(
        messages=[], compacted=False, dropped_messages=0, kept_messages=3,
        summarized=False, fallback_used=False, tokens_before=10, tokens_after=10,
    )
    trace.trace_compaction(result)
    assert not [s for s in trace.steps if s.get("step_type") == "compaction"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agent_runtime_kernel.py::test_compaction_span_recorded_when_over_budget -v`
Expected: FAIL（`TraceCollector.trace_compaction` 未定义）

- [ ] **Step 3: 实现 trace_compaction**

在 `core/observability/tracing.py` 的 `add_artifact` 方法（第 188 行）之前插入:

```python
    def trace_compaction(self, result) -> None:
        """Record a short-term message-window compaction as a span. No-op when
        nothing was compacted, so cheap in-loop calls under budget add no span."""
        if not getattr(result, "compacted", False):
            return
        self.steps.append({
            "step_type": "compaction",
            "step_index": len(self.steps),
            "tool_name": "compaction",
            "tool_input": {
                "dropped_messages": result.dropped_messages,
                "kept_messages": result.kept_messages,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
                "summarized": result.summarized,
                "fallback_used": result.fallback_used,
            },
            "latency_ms": 0,
        })
```

- [ ] **Step 4: 运行 trace 测试确认通过**

Run: `pytest tests/test_agent_runtime_kernel.py::test_compaction_span_recorded_when_over_budget tests/test_agent_runtime_kernel.py::test_trace_compaction_noop_not_recorded -v`
Expected: PASS

- [ ] **Step 5: 进 loop 前用 compact_window 并记录 span**

在 `ai/agents/runtime.py` 把第 119-121 行:

```python
        messages = [SystemMessage(content=system_ctx)] + list(session.messages)
        messages = LLMRunner.compact(messages, max_messages=20)
        return trace, owns_trace, llm_with_tools, messages
```

替换为:

```python
        messages = [SystemMessage(content=system_ctx)] + list(session.messages)
        compaction = LLMRunner.compact_window(messages, max_messages=20)
        messages = compaction.messages
        trace.trace_compaction(compaction)
        return trace, owns_trace, llm_with_tools, messages
```

- [ ] **Step 6: loop 内每轮工具调用后再压缩**

在 `ai/agents/runtime.py` 的 loop 内，紧接处理完 `response.tool_calls`、所有 `messages.append(tool_msg)` 之后（即第 193 行 `_record_tool_artifact(...)` 所在 for 循环结束后、回到 `for iteration` 顶部之前）插入:

```python
                compaction = LLMRunner.compact_window(messages, max_messages=20)
                messages = compaction.messages
                trace.trace_compaction(compaction)
```

注意缩进：该行与 `for tc in response.tool_calls:`（第 185 行）同级，位于 `for iteration in range(...)` 体内、内层 `for tc` 之后。预算未超时 `compact_window` 是廉价 no-op 且不写 span。

- [ ] **Step 7: 写 loop 内压缩集成断言**

在 `tests/test_agent_runtime_kernel.py` 追加一个用例，用现有 fake-LLM 装配方式构造「多轮工具调用 + 大 ToolMessage」的 run，断言：
1. run 正常完成（不因孤儿 tool_call 报错）；
2. `trace.steps` 中存在至少一个 `compaction` span。

```python
def test_inloop_compaction_keeps_run_valid_and_records_span(monkeypatch):
    # 复用本文件现有的 runtime + fake LLM 装配 helper。
    # fake LLM：前两轮各返回一个 tool_call（工具回大体量 stdout），第三轮返回最终文本。
    # 断言 run 完成且至少写入一个 compaction span。
    ...
```

实现者按本文件既有 runtime 装配 helper 补全 `...`；若现有用例已能驱动多轮工具循环，复制其装配并把工具输出放大到超出 `DEFAULT_CONTEXT_TOKEN_BUDGET`（例如单条 `"x" * 60000`）。

- [ ] **Step 8: 运行 runtime 全量测试确认通过**

Run: `pytest tests/test_agent_runtime_kernel.py -v`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add core/observability/tracing.py ai/agents/runtime.py tests/test_agent_runtime_kernel.py
git commit -m "feat(agents): compact message window in-loop and record compaction span"
```

---

### Task 7: 文档与回归

**Files:**
- Modify: `docs/architecture/data-state-memory.md`
- Test: 全量 pytest

- [ ] **Step 1: 更新架构文档**

在 `docs/architecture/data-state-memory.md` 找到描述短期 memory / `compact_messages` 的段落（grep `compact`），把它更新为当前实现态，至少写明三点：
1. 触发条件是估算 token 超过 `DEFAULT_CONTEXT_TOKEN_BUDGET`，不再是固定消息条数；
2. 压缩在 agent loop 内每轮工具调用后滚动执行，且 token 低于预算时为 no-op；
3. 切分保证 tool-call/tool-result 配对安全，且每次实际压缩写入一个 `compaction` trace span。

若该文件没有对应段落，在「短期/工作记忆」小节新增一段同样内容。

- [ ] **Step 2: 运行全量测试**

Run: `pytest -q`
Expected: PASS（无回归；特别关注 `tests/test_handoff_context.py`、`tests/test_agents.py`、`tests/test_llm_runner.py`、`tests/test_agent_runtime_kernel.py`、`tests/test_message_compaction.py`）

- [ ] **Step 3: 提交**

```bash
git add docs/architecture/data-state-memory.md
git commit -m "docs: document token-budget pairing-safe message compaction"
```

---

## 7. 验收标准

- 单次 run 的消息窗口压缩由估算 token 触发，不再因固定 20 条阈值误压缩或漏压缩。
- 压缩后保留尾部不以 `ToolMessage` 开头；多轮工具调用的 run 不再因孤儿 `tool_call_id` 触发 provider 拒绝。
- agent loop 在 token 超预算时于轮内滚动压缩；低于预算时为零成本 no-op。
- 每次实际压缩在 trace 中可见一个 `compaction` span，含 before/after token 与 dropped/kept 计数。
- `MemoryService.compact_messages(list)->list` 与 `LLMRunner.compact(list)->list` 旧签名保持可用。
- `compaction.py` 与 `CompactionResult` 无未消费字段。

## 8. 风险与回滚

- **预算常量取值**：12000 / 8000 为字符启发式估算下的初值，可能对某些模型偏保守或偏激进。回滚或调参只需改 `ai/memory/compaction.py` 顶部三个常量，不涉及结构变更。
- **loop 内压缩开销**：no-op 路径只做一次 `_total_tokens` 线性扫描；若大 run 下扫描成本显著，可在 runtime 侧加「仅当新增消息数超过阈值才扫描」的门槛，但不在本计划范围内提前优化（YAGNI）。
- **summarizer 行为变化**：摘要 prompt 与 FAST tier 与旧实现一致，仅迁移位置；若线上摘要质量回退，可单独调 `_llm_summarize_transcript` 的 prompt，不影响切分正确性。
