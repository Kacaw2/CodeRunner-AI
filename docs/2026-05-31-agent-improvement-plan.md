# Agent Improvement Plan

## 中文摘要

这份计划的核心目标，是把 CodeRunner-AI 当前的 agent 层从“能跑的多 agent 实现”提升为“边界清晰、失败可见、权限可控、可持续演进的 agent runtime”。它把已有 `agents/` 审查中发现的四个问题合并进同一条改造路线：工具循环耗尽时不能再静默返回空响应，重试时不能把 `SystemMessage` 重复写进历史，`auto` 路由后必须按真实 agent 类型执行限流，agent 输入契约必须和实际 `context` 字段保持一致。

计划借鉴 Claude Code 的成熟模式，但不照搬产品形态。真正要学习的是它的工程边界：每个 agent 应该有隔离上下文、声明式定义、受控工具权限、生命周期 hook、硬执行上限和可观测终态。落到本项目里，就是让 `core/definitions.py` 成为 agent 的单一事实源，让 `BaseAgent` 只在本轮调用中临时拼接 system prompt，让所有工具调用继续穿过 MCP client 和 `mcp_gateway`，并在 agent 运行前后加上可测试的 runtime hooks。

实施顺序建议分六步推进。第一步修复 `BaseAgent` 的工具循环上限，保证超过 `MAX_TOOL_ITERATIONS` 时返回明确错误并记录为失败或 limit-exceeded。第二步隔离 system context，避免 generator 校验重试时重复注入 system prompt。第三步修正聊天入口和 worker 路径的限流顺序，在 intent routing 得到 `generator`、`reviewer` 等真实类型后再应用对应额度。第四步统一 `agents/contracts.py`、`core/definitions.py` 和各 agent 实际使用的 context 字段，并让未知字段产生告警。第五步增加最小生命周期 hook，覆盖 agent run、tool call、tool result、output validation 和 trace/audit。第六步把文本 handoff 收敛为结构化 delegation payload，保留兼容文本标记，但内部按 `handoff_to`、`handoff_reason`、`handoff_summary` 处理。

完成后，agent 层的验收标准很明确：不会再因为工具循环耗尽而给用户空响应；system prompt 不会污染对话历史；`auto` 路由不会绕过 per-agent rate limit；输入契约能捕获字段漂移；工具权限和输出校验通过 runtime hook 可追踪；handoff 传递的是压缩后的结构化上下文，而不是上一轮 agent 的完整消息和工具残留。

> Date: 2026-05-31
> Scope: `agents/`, `graph/`, `app/api/v1/ai.py`, `workers/`, `mcp_gateway/`, `tools/protocol/`, and related tests.

This plan folds the current `agents/` review findings into a Claude Code-inspired improvement path. The goal is not to copy Claude Code as a product, but to adopt the parts of its agent architecture that solve concrete weaknesses in CodeRunner-AI: isolated agent context, declarative definitions, explicit tool permissions, lifecycle hooks, hard execution limits, and observable failure states.

## Current Problems To Fix

| Priority | Problem | Evidence | Impact |
|---|---|---|---|
| P1 | Tool-loop exhaustion can silently return an empty response | `agents/base.py` loops up to `MAX_TOOL_ITERATIONS`; if the last LLM response still contains `tool_calls`, `final_response` can become empty while the trace is saved as completed. The streaming path has the same risk. | Users may receive blank answers, traces look successful, and operators cannot distinguish success from a stuck tool loop. |
| P2 | Retry can persist duplicate `SystemMessage` entries | `_invoke_with_mcp_tools()` prepends a system prompt, then writes the whole message list back into state. `GeneratorAgent` retries by reusing the same state. | Multi-round generator validation can accumulate system prompts, increasing token usage and causing instruction drift or provider rejection. |
| P2 | Per-agent rate limits do not apply on user chat routes | Chat routes normalize every request to `auto`, then rate-limit before route resolution. `generator` and `reviewer` limits are bypassed in practice. | Expensive or risky agents can be called at the generic `auto` rate instead of their stricter configured limits. |
| P3 | Agent input contracts drift from real context fields | `ReviewerContext` uses `problem_id` while the agent uses `question_id`; `GeneratorContext` uses `programming_language` while the agent uses `language`; `AnalyticsContext` uses `student_id` while the agent uses `target_student_id`. `extra="ignore"` hides these mismatches. | Contract validation becomes low-signal and cannot reliably catch malformed agent invocations. |

## Claude Code Patterns Worth Adopting

### 1. Isolated Agent Context

Claude Code subagents run in a separate context window and return a summarized result to the parent session. CodeRunner-AI should mirror that boundary internally:

- Keep `system_context` out of persisted conversation history.
- Keep tool residue out of handoff messages unless explicitly summarized.
- Persist only user/assistant conversation messages and structured agent results.
- Treat each agent run as an isolated `AgentSession` with a clear start, result, and trace.

### 2. Declarative Agent Definitions

Claude Code subagents are configured with frontmatter-like fields such as description, prompt, tools, model, permissions, and max turns. CodeRunner-AI already has `core/definitions.py`; it should become the single source of truth:

- `name`
- `description`
- `allowed_roles`
- `allowed_tools`
- `default_model_tier`
- `input_context_schema`
- `output_schema`
- `prompt_file`
- `max_tool_iterations`
- `max_llm_calls`
- `handoff_targets`

Agent classes should implement behavior, not redefine contracts.

### 3. Platform-Enforced Tool Permissions

Claude Code permissions are enforced by the runtime, not by model instructions. CodeRunner-AI is already close to this with MCP, RBAC, scopes, risk policy, and human gates. The next step is to make agent tool permissions traceable from one declaration:

`AgentDefinition.allowed_tools -> MCP descriptors -> scopes_for_agent() -> runtime guard -> audit log`

No agent should get broader permissions because it was routed through `auto`, a worker path, or an internal helper.

### 4. Lifecycle Hooks

Claude Code exposes hooks around tool use, subagent start/stop, compaction, and permission requests. CodeRunner-AI should introduce a small internal hook layer before adding more agent features:

- `BeforeAgentRun`: validate context and attach run budget.
- `BeforeToolCall`: enforce allowed tool, risk, scope, and sanitized args.
- `AfterToolCall`: normalize result, update trace, and audit failures.
- `AfterAgentRun`: validate output, detect handoff, record terminal status.
- `BeforeCompact` / `AfterCompact`: keep memory compaction visible and testable.

These hooks should be normal Python interfaces, not prompt instructions.

## Target Architecture

```text
AI API / Worker
  -> route intent
  -> resolve AgentDefinition
  -> create AgentSession
  -> run lifecycle hooks
  -> invoke BaseAgent with isolated system context
  -> call tools through MCP client only
  -> validate output and terminal status
  -> persist user-visible message and trace
```

Key rule: the parent request owns routing, rate limiting, persistence, and trace linkage. The agent owns model/tool interaction within a bounded session.

## Implementation Plan

### Phase 1: Stop Silent Agent Failures

**Goal:** Make exhausted tool loops explicit and observable.

**Files:**
- Modify: `agents/base.py`
- Modify: `core/exceptions.py`
- Test: `tests/test_agents.py`

**Changes:**
- Add an `AgentExecutionLimitError` or equivalent structured status.
- In `_invoke_with_mcp_tools()`, if the loop exits because `MAX_TOOL_ITERATIONS` was reached while tool calls are still pending, set a non-empty `final_response` and save trace status as failed or limit-exceeded.
- In `_stream_with_mcp_tools()`, yield an `error` event when the same limit is hit.
- Add tests for sync and streaming exhaustion.

**Strengthening (added after code review):**
- The exhaustion condition is *"loop ran all iterations AND the last response still had `tool_calls`"*. Do **not** treat a normal final iteration (last response had no tool calls) as a failure — that path is already correct via the `break` at `base.py:160` / `base.py:258`.
- Track loop completion explicitly. The current `for` loop has no post-loop flag; add a `for ... else:` clause (the `else` runs only when no `break` fired) or a boolean to detect natural exhaustion, otherwise you cannot distinguish "exited by break" from "exited by exhaustion".
- `GeneratorAgent` has its **own** `invoke()` and `stream()`. `invoke()` reuses `_invoke_with_mcp_tools` so it inherits the fix, but it has a second silent path: when JSON cannot be parsed after `MAX_VALIDATION_ROUNDS`, `generator/agent.py:217` does `return state` with a possibly empty/raw `final_response`. Decide explicitly — either fold this into Phase 1 (return a structured "generation failed validation" status) or mark it out-of-scope in writing. Do not leave it implicit.
- `generator.stream()` is a *validation* loop, not a *tool* loop, so the tool-exhaustion bug does not apply there — note this so reviewers don't expect a change.

**Acceptance criteria:**
- No successful trace is recorded for a tool loop that exceeded the limit.
- User-facing response is explicit, not blank.
- A natural completion on the final iteration (no pending tool calls) is still recorded as `completed`.
- Existing agent tests continue to pass.

### Phase 2: Isolate System Context From Conversation History

**Goal:** Prevent duplicate system prompts during retry and handoff.

**Files:**
- Modify: `agents/base.py`
- Modify: `agents/generator/agent.py` (**required, not optional** — see below)
- Test: `tests/test_agents.py`

**Changes:**
- Build the LLM message list as `[SystemMessage(content=system_ctx)] + conversation_messages`.
- Persist only non-system messages back to `state["messages"]`.
- Ensure generator validation retries append only repair `HumanMessage` entries to conversation history.
- Add a regression test where generator fails validation once and retries without accumulating multiple `SystemMessage` objects.

**Strengthening (added after code review):**
- `agents/generator/agent.py` is a **required** change, not "if needed". `generator.stream()` builds its own `[SystemMessage] + messages` at `generator/agent.py:274` and writes the full list (including the `SystemMessage`) back via `state["messages"] = messages` at `generator/agent.py:388`. Fixing only `base.py` leaves this second injection source intact, and `generator.invoke()` re-enters `_invoke_with_mcp_tools` in a loop (`generator/agent.py:198`), so accumulation persists across validation rounds.
- The write-back filter must strip `SystemMessage` instances specifically (`isinstance(m, SystemMessage)`), not "the first message", because security-alert prepending (`_maybe_inject_security_alert`) and compaction may reshape the list.
- `MemoryService.compact_messages(messages, max_messages=20)` runs *after* the `SystemMessage` is prepended (`base.py:127`, `base.py:214`). Verify compaction preserves the system message and that the new "persist non-system only" step happens **after** compaction, so a compacted tail is what gets stored — not the pre-compaction list.

**Acceptance criteria:**
- `state["messages"]` never contains the generated system prompt after an agent run (sync, stream, and generator paths).
- Generator retry still receives the intended system context exactly once per LLM call.
- Token usage does not grow due to duplicated system prompts across validation rounds.

### Phase 3: Restore Real Per-Agent Rate Limits

**Goal:** Apply configured rate limits to the resolved agent, not only `auto`.

**Files:**
- Modify: `app/api/v1/ai.py`
- Modify: `workers/chat.py`
- Modify: `workers/task_runner.py`
- Test: `tests/test_api_ai.py`

**Changes:**
- Keep a lightweight pre-route global throttle for abuse protection.
- After `_classify_intent()` resolves the real agent, apply `_rate_limit_or_abort(user_id, resolved_agent_type)`.
- Ensure `chat`, `chat_stream`, and `chat_async` use the same rate-limit ordering.
- Add tests proving generator requests are limited by `AGENT_RATE_LIMITS["generator"]` after auto-routing.

**Strengthening (added after code review):**
- **The sync `/chat` path is the hard case and the plan must spell out the mechanism.** Today routing for sync chat is buried inside `orch.run()` (`ai.py:311`); the API never calls `_classify_intent` itself, so there is no resolved agent type to rate-limit against before execution. The stream path *does* call `_classify_intent` explicitly (`ai.py:428`), so it is straightforward. Choose **one** mechanism for sync and document it:
  - **Option A (preferred): classify-then-run.** Call `_classify_intent(state)` in the API layer first, rate-limit on the resolved type, then pass the already-resolved `agent_type` into the orchestrator so it does not re-classify. Requires `AgentOrchestrator.run` to skip classification when `agent_type != "auto"`. **Confirmed:** `graph/runner.py:99` already guards classification with `if agent_type == "auto" or not agent_type:`, so passing a concrete resolved type makes `run()` skip `_classify_intent` automatically. No orchestrator change needed beyond passing the type through.
  - **Option B: post-hoc limit.** Run first, then charge the resolved bucket. Rejected: the expensive call already executed, so it only throttles the *next* request — weak protection for `generator`.
- **Add an explicit `auto` / global bucket.** `AGENT_RATE_LIMITS` has no `auto` key, so `_check_rate_limit` (`ai.py:27`) silently falls back to `20`. The pre-route throttle should use a named global limit (e.g. add `"_global": N`) instead of relying on the `.get(..., 20)` default, so the abuse ceiling is intentional and visible.
- **Avoid double classification cost.** Option A risks classifying twice (once for rate limit, once in the orchestrator) — an extra LLM call per request. Pass the resolved type through to prevent it.
- `chat_async` / worker paths (`workers/chat.py`, `workers/task_runner.py`) must keep injection + sanitization checks before any rate-limit short-circuit, matching the existing `detect_injection` → `sanitize_user_input` → rate-limit order in `ai.py:282-290`.

**Acceptance criteria:**
- `auto` no longer bypasses `generator`, `reviewer`, or `analytics` limits — on **both** sync and stream paths.
- The pre-route global throttle uses an explicit named limit, not the `20` fallback default.
- Resolved-agent classification runs at most once per request (no double LLM cost).
- The client response still includes useful rate-limit headers.
- Proxy/worker paths keep validation and injection checks before execution.

### Phase 4: Make Agent Contracts The Source Of Truth

**Goal:** Align contracts, definitions, and real context fields.

**Files:**
- Modify: `agents/contracts.py`
- Modify: `core/definitions.py`
- Modify: agent context builders only if needed
- Test: `tests/test_agent_features.py` or a new `tests/test_agent_contracts.py`

**Changes:**
- Replace mismatched fields:
  - Reviewer: use `question_id`, `code`, `language`.
  - Generator: use `language`, `difficulty`, `topic`, `test_case_count`, `prompt`.
  - Analytics: use `target_student_id`, `question_id`, `period`.
- Change contract validation from `extra="ignore"` to a stricter mode where unknown fields are surfaced as warnings.
- Add a consistency test comparing `AgentDefinition.input_fields` against the Pydantic context model fields.

**Strengthening (added after code review):**
- **Pydantic has no native "warn" mode.** `extra="forbid"` *raises*; `extra="ignore"` is the current silent behavior. To stay warn-only (the stated S7 policy in `contracts.py`), implement it manually: keep `extra="allow"`, then in `validate_agent_input` diff `set(context.keys())` against `model.model_fields` and log a warning for each unexpected key. Do not switch to `forbid` — it would create a new rejection path the plan explicitly forbids.
- **The real `context` dict carries legitimate non-contract keys** that will otherwise generate warning noise: `conversation_id` (set at `ai.py:301`), `generated_problem` (set at `generator/agent.py:259`), and whatever `_build_context()` injects. Either (a) add these as optional fields on each context model, or (b) maintain an allowlist of "framework keys" excluded from the unexpected-key check. Decide and document, or the warning channel becomes noise and gets ignored.
- **Definitions are the asymmetry to watch.** `core/definitions.py` already uses the *correct* field names (`question_id`, `language`, `target_student_id`); only `agents/contracts.py` is wrong. So the consistency test should assert `set(AgentDefinition.input_fields) ⊇ {required context model fields}` and fail loudly if a future edit reintroduces drift in either direction.
- Verify no caller actually populates the old names (`problem_id`, `programming_language`, `student_id`) in `context`. Grep before renaming; if a frontend/API builder sends `problem_id`, renaming the contract field silently drops it under today's `extra="ignore"` and the consistency test won't catch a *runtime* sender mismatch.

**Acceptance criteria:**
- Contract validation warns on unexpected context keys **without raising**.
- Known framework keys (`conversation_id`, `generated_problem`, …) do not produce warnings.
- `core/definitions.py` and `agents/contracts.py` cannot drift silently (consistency test enforces it).
- Existing API context construction remains compatible (no field a live caller sends gets silently dropped).

### Phase 5: Add Agent Lifecycle Hooks

**Goal:** Move reliability checks out of prompts and into runtime code.

**Files:**
- Create: `agents/hooks.py`
- Modify: `agents/base.py`
- Modify: `agents/executor.py`
- Test: `tests/test_agent_hooks.py`

**Changes:**
- Define hook events for `BeforeAgentRun`, `BeforeToolCall`, `AfterToolCall`, and `AfterAgentRun`.
- Start with built-in hooks only:
  - contract validation hook
  - tool allowlist hook
  - output validation hook
  - trace/audit hook
- Keep hook implementation synchronous and in-process for now.

**Acceptance criteria:**
- Tool permission failures are reported through a consistent hook result.
- Agent output validation has one runtime path for sync and worker flows.
- Hook tests prove the hooks fire in order.

### Phase 6: Convert Text Handoff Into Structured Delegation

**Goal:** Make handoff safer and closer to subagent delegation.

**Files:**
- Modify: `graph/handoff.py`
- Modify: `graph/runner.py`
- Test: `tests/test_agent_features.py`

**Changes:**
- Keep `[HANDOFF: ...]` as backward-compatible input.
- Internally normalize handoff to:
  - `handoff_to`
  - `handoff_reason`
  - `handoff_summary`
  - `handoff_source`
- Rebuild the next agent context from the original user request plus a concise summary, not the full previous message/tool history.

**Acceptance criteria:**
- Students still cannot hand off to generator.
- Handoff loops remain blocked.
- The target agent receives a compact summary instead of polluted history.

## Detailed Execution Plan

This section turns the phases above into concrete, ordered, verifiable steps. Phases 1–4 fix the four reported defects and are the committed scope; Phases 5–6 are additive architecture and are **explicitly optional** for closing the four defects — schedule them separately. Each step lists the edit site, the approach, and how to prove it.

### Sequencing rationale

1. **P1 + P2 first (same file, `BaseAgent`).** They touch the same loop and message-state code; doing them together avoids two passes over `_invoke_with_mcp_tools` / `_stream_with_mcp_tools` and one merge conflict surface.
2. **P3 (rate limit) next.** User-facing and independent of the `BaseAgent` work; correct before any traffic expansion.
3. **P4 (contracts) last of the committed scope.** Pure observability; lowest blast radius; becomes the substrate for Phase 5 hooks if those proceed.

---

### Step 1 — P1: stop silent tool-loop exhaustion

**Edit sites:** `agents/base.py` (`_invoke_with_mcp_tools` loop at `:134-180`, `_stream_with_mcp_tools` loop at `:220-294`), `core/exceptions.py`.

1. Add a structured status to `core/exceptions.py`:
   - `class AgentExecutionLimitError(AIError)` with a fixed `user_message` like *"The assistant reached its tool-call limit before finishing. Please retry or narrow the request."*
2. Sync loop (`_invoke_with_mcp_tools`):
   - Convert the bare `for iteration in range(MAX_TOOL_ITERATIONS):` to detect natural exhaustion. Simplest: after the loop, check `if response is not None and response.tool_calls:` → the loop ended with pending tool calls.
   - In that branch, set `state["final_response"] = AgentExecutionLimitError().user_message`, then `trace.save(status="limit_exceeded", response=state["final_response"])` and **return early** (or raise `AgentExecutionLimitError` if callers should treat it as failure — pick one and apply consistently; returning a non-empty body is friendlier for chat).
   - Leave the existing `break`-driven completion (`:160`) untouched so normal runs still record `completed`.
3. Stream loop (`_stream_with_mcp_tools`):
   - Track whether the loop broke normally. Use a flag set in the `if not tool_calls:` branch (`:258`). After the loop, if the flag is unset, `yield {"type": "error", "message": AgentExecutionLimitError().user_message}` and `trace.save(status="limit_exceeded")`, set `trace_saved = True`, and `return`.
4. Generator decision (write it down): `generator/agent.py:217` returns `state` with unparsed/empty `final_response` after `MAX_VALIDATION_ROUNDS`. Either (a) set `state["final_response"]` to a structured "could not produce valid problem JSON" message before returning, or (b) record this as out-of-scope in the PR description. Do not leave silent.

**Proof:**
- New tests in `tests/test_agents.py`: a fake LLM that *always* returns `tool_calls` → assert sync result has non-empty `final_response`, trace status is `limit_exceeded`, and **not** `completed`. Stream variant → assert an `error` event is yielded and no `completed` trace.
- Regression: a fake LLM that returns no tool calls on the first turn still yields `completed`.

---

### Step 2 — P2: isolate system context from persisted history

**Edit sites:** `agents/base.py` (`:123`, `:168`, `:210`, `:286`), `agents/generator/agent.py` (`:274`, `:388`).

1. In both `BaseAgent` loops, before writing back, strip system messages:
   ```python
   from langchain_core.messages import SystemMessage
   state["messages"] = [m for m in messages if not isinstance(m, SystemMessage)]
   ```
   Apply this at `base.py:168` (sync) and `base.py:286` (stream).
2. Ordering: keep compaction (`base.py:127`, `:214`) where it is — it runs on the in-flight `messages` (with system prepended) for the LLM call. The filter above runs only at write-back, so the stored tail is post-compaction and system-free.
3. `generator.invoke()` (`:198`): since it re-calls `_invoke_with_mcp_tools` in a loop and that helper now writes back system-free messages, each round re-prepends exactly one fresh `SystemMessage` at `base.py:123`. No extra change needed here once Step 2.1 lands — but assert it in a test.
4. `generator.stream()` (own loop): it builds `[SystemMessage] + messages` at `:274` and writes `state["messages"] = messages` at `:388`. Apply the same `isinstance` filter at `:388`.

**Proof:**
- `tests/test_agents.py`: drive `generator.invoke()` through one validation-failure retry with a fake LLM; assert the message list handed to the LLM on round 2 contains **exactly one** `SystemMessage`, and that `state["messages"]` after the run contains **zero** `SystemMessage`.
- Repeat the zero-`SystemMessage` post-run assertion for `tutor`/`reviewer` sync and stream paths.

---

### Step 3 — P3: real per-agent rate limits after routing

**Edit sites:** `app/api/v1/ai.py` (`chat` `:280-290`, `chat_stream` `:369-379`, plus the `generate()` body `:426-428`), `agents/config.py`, `workers/chat.py`, `workers/task_runner.py`.

1. `agents/config.py`: add an explicit global bucket, e.g. `AGENT_RATE_LIMITS["_global"] = 30` (pick the abuse ceiling deliberately). Document why it differs from per-agent limits.
2. Sync `/chat` (Option A, classify-then-run):
   - After `sanitize_user_input` (`:287`), build the minimal state and call `_classify_intent(state)` to resolve the agent **before** rate-limiting.
   - Pre-route throttle: `_rate_limit_or_abort(user.id, "_global")` for abuse protection.
   - Resolved-agent throttle: `_rate_limit_or_abort(user.id, resolved_agent_type)`.
   - Pass the resolved `agent_type` into `orch.run({... "agent_type": resolved_agent_type ...})`. Per `graph/runner.py:99`, `run()` then skips re-classification → no double LLM cost.
3. Stream `/chat/stream`: classification already happens in `generate()` at `:428`. Move/duplicate the resolved-agent `_rate_limit_or_abort` to fire right after `_classify_intent` resolves `resolved_agent_type` (`:429`), before invoking `agent.stream`. Keep the pre-route `_global` throttle near `:379`. Note: emitting a 429 mid-SSE is awkward — prefer doing the per-agent check before the first `yield`, or send a terminal `{"type":"error"}` SSE event + stop.
4. `workers/chat.py`, `workers/task_runner.py`: apply the same `_global` → resolve → per-agent ordering; keep `detect_injection` + `sanitize_user_input` ahead of the rate-limit short-circuit (mirror `ai.py:282-287`).

**Proof:**
- `tests/test_api_ai.py`: with Redis (or a fake), send N>5 chat requests that route to `generator`; assert the 6th returns 429 with `Retry-After`, proving `AGENT_RATE_LIMITS["generator"]=5` now binds.
- Assert `auto`/tutor traffic still allows up to its own limit (20) and is not throttled at 5.
- Assert `_classify_intent` is invoked once per sync request (mock + call count) — guards against double classification.

---

### Step 4 — P4: align contracts, warn on drift

**Edit sites:** `agents/contracts.py` (`:43-71`, `:82-116`), test `tests/test_agent_contracts.py` (new).

1. Pre-flight grep: confirm no live caller sends the old names. Search `app/`, `workers/`, frontend payload builders, and `_build_context` for `problem_id`, `programming_language`, `student_id`. If any sender uses them, rename the **sender** too in the same PR (or the field silently drops under `extra="ignore"`).
2. Fix field names in `contracts.py`:
   - `ReviewerContext`: `problem_id` → `question_id`; add `language`.
   - `GeneratorContext`: `programming_language` → `language`; add `difficulty` (exists), `test_case_count`, `prompt`.
   - `AnalyticsContext`: `student_id` → `target_student_id`; add `period`.
3. Warn-only unexpected-key detection (no `forbid`):
   - Set `model_config = ConfigDict(extra="allow")` on each context model.
   - In `validate_agent_input`, after `model_validate`, compute `unexpected = set(ctx.keys()) - set(model_fields) - FRAMEWORK_KEYS` where `FRAMEWORK_KEYS = {"conversation_id", "generated_problem", ...}`; append a warning string per unexpected key. Never raise.
4. Drift guard test (`tests/test_agent_contracts.py`):
   - For each agent, assert the Pydantic context model's declared fields are a subset of `AgentDefinition.input_fields` (and vice-versa for required ones), so a future rename in either file fails CI.

**Proof:**
- New `tests/test_agent_contracts.py` passes; deliberately introducing a mismatched field name in a local edit makes it fail (sanity-check the guard).
- Existing suites green: run the focused agent + API suites (below).

---

### Phases 5–6 (optional, separate PRs)

Do **not** bundle these with the defect fixes. Gate them behind Phases 1–4 being merged and stable. Phase 5 (lifecycle hooks) should reuse the now-correct `validate_agent_input` and the `limit_exceeded` status from Step 1 rather than reintroducing checks. Phase 6 (structured handoff) depends on Step 2's clean message state — the compact summary it forwards must be built from system-free history.

## Test Plan

Run the focused agent suite after each phase:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agents.py tests\test_agent_features.py tests\test_agent_scopes.py tests\test_agent_mcp_client_boundary.py -q
```

Run the API and MCP boundary suite before merging:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api_ai.py tests\test_mcp_gateway.py tests\test_mcp_gateway_human_gate.py tests\test_tool_protocol.py tests\test_phase1_architecture_unification.py -q
```

Run static diff checks before commit:

```powershell
git diff --check
git diff --cached --check
```

## Suggested Delivery Order

1. Phase 1 and Phase 2 together: both are in `BaseAgent` and should be fixed before larger architecture work.
2. Phase 3: rate limiting is user-facing and should be corrected before expanding agent usage.
3. Phase 4: contract consistency becomes the foundation for hook validation.
4. Phase 5: hooks make future reliability work easier.
5. Phase 6: structured handoff can be done after the message-state cleanup is stable.

## Non-Goals

- Do not replace LangGraph in this plan.
- Do not replace DeepSeek or the model router.
- Do not bypass MCP by calling tool implementations directly from agents.
- Do not introduce a compatibility layer that preserves known-bad behavior.
- Do not broaden agent permissions to make tests pass.

## Success Definition

The agent layer is considered improved when:

- no agent can complete with an empty response after exhausting tool iterations;
- system prompts are not persisted into conversation history;
- `auto` routing still works but resolved agents get their own rate limits;
- agent contracts match real request context fields and warn on drift;
- tool calls and output validation pass through observable runtime hooks;
- handoff uses a compact structured delegation payload.
