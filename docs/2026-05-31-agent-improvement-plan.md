# Agent Improvement Plan

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

**Acceptance criteria:**
- No successful trace is recorded for a tool loop that exceeded the limit.
- User-facing response is explicit, not blank.
- Existing agent tests continue to pass.

### Phase 2: Isolate System Context From Conversation History

**Goal:** Prevent duplicate system prompts during retry and handoff.

**Files:**
- Modify: `agents/base.py`
- Modify: `agents/generator/agent.py` if needed
- Test: `tests/test_agents.py`

**Changes:**
- Build the LLM message list as `[SystemMessage(content=system_ctx)] + conversation_messages`.
- Persist only non-system messages back to `state["messages"]`.
- Ensure generator validation retries append only repair `HumanMessage` entries to conversation history.
- Add a regression test where generator fails validation once and retries without accumulating multiple `SystemMessage` objects.

**Acceptance criteria:**
- `state["messages"]` never contains the generated system prompt after an agent run.
- Generator retry still receives the intended system context once per LLM call.
- Token usage does not grow due to duplicated system prompts.

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

**Acceptance criteria:**
- `auto` no longer bypasses `generator`, `reviewer`, or `analytics` limits.
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

**Acceptance criteria:**
- Contract validation warns on unexpected context keys.
- `core/definitions.py` and `agents/contracts.py` cannot drift silently.
- Existing API context construction remains compatible.

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
