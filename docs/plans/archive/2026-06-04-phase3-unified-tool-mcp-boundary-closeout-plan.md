# Phase 3: Unified Tool / MCP Boundary — Closeout Plan

> 状态：Archived / Done（Phase 3 已由一致性测试、边界文档和上位计划验收记录收口）
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The upgrade plan's Phase 3 ("internal agent tool calls and external MCP client calls share one platform boundary") is *substantively already built*. `ToolRuntime.call()` is the sole policy core, and both the in-process path ([client.py:91](../../mcp_gateway/client.py)) and the external streamable-http path ([middleware/core.py:182](../../mcp_gateway/middleware/core.py)) converge on `get_tool_runtime().call_sync`. This plan does **not** re-architect anything. It closes the three remaining gaps that keep Phase 3 from being *verifiably* done: (1) no test asserts the two paths produce the same guard verdict + envelope for the same tool/identity; (2) the two-layer allowlist (agent-allowlist hook vs runtime RBAC) is an intentional design that is only implicitly documented; (3) the boundary's role glossary is spread across several docs with no single authority.

**Why these and not more:** Output-schema enforcement (still warn-only, [runtime.py:229](../../tools/protocol/runtime.py)), per-tool/per-user quotas, write-tool idempotency, and multi-tenant isolation are real enterprise hardening items but are **out of scope** here — they are net-new behavior, not boundary unification, and belong in Phase 6 (quality gates) or a dedicated Phase 3.5. This plan only proves and documents the boundary that already exists.

**Tech Stack:** Python 3, pytest (`tests/` suite with `app` fixture in `tests/conftest.py`), `tools.protocol.runtime.ToolRuntime`, `mcp_gateway` (FastMCP gateway + in-process/transport clients), EdDSA internal capability tokens (`mcp_gateway/internal_auth.py`), Markdown architecture docs under `docs/architecture/`.

---

## Current state (read before starting)

Verified by reading the boundary code. Treat this as the baseline; do not "fix" what is already correct.

| Phase 3 direction | Status | Evidence |
|---|---|---|
| Gateway keeps only transport / auth / rate-limit | ✅ done | `_guarded` does auth + `check_rate_limit`, then delegates to `call_via_runtime` ([middleware/core.py:129](../../mcp_gateway/middleware/core.py)) |
| schema / RBAC / scope / risk / human-gate / sanitize / audit / trace sink into ToolRuntime | ✅ done | `ToolRuntime.call()` pipeline ([runtime.py:101](../../tools/protocol/runtime.py)): `_validate_input` → `run_guard` → `_sanitize_args` → transport → `_validate_output` → `emit_audit` |
| in-process and streamable-http have equal permission semantics | ✅ done | both reach `get_tool_runtime().call_sync`; `actor_type` set from signature/API-key, never self-declared ([guard.py:15](../../tools/protocol/policies/guard.py)) |
| agents do not import tool implementations | ✅ done | grep of `agents/` for `tools.problems/code/knowledge_search/...` returns zero |
| consistent envelope across paths | ⚠️ partial | both use `ToolResult.to_envelope()`; external re-parses via `_envelope_from_mcp_result` — but **no test pins that they agree** |
| two-layer allowlist (agent hook + runtime RBAC) | ⚠️ partial | agent path fires `BEFORE_TOOL_CALL` ([executor.py:30](../../agents/executor.py)) AND RBAC; external path is RBAC/scope only. Tested for external RBAC ([test_mcp_gateway_external_rbac.py](../../tests/test_mcp_gateway_external_rbac.py)) but the *cross-path difference* is not documented as intentional |
| single boundary glossary | ❌ missing | roles are described across `mcp-runtime.md`, `agent-runtime-core.md`, `tools-mcp-rag.md` with no canonical one-pager |

## Scope decisions

- **No production-transport integration test that boots the FastMCP server.** The streamable-http path is already unit-tested for token minting/verification ([test_agent_mcp_client_boundary.py:125](../../tests/test_agent_mcp_client_boundary.py)) and gateway-side caller resolution ([test_mcp_gateway_internal_auth.py](../../tests/test_mcp_gateway_internal_auth.py)). The consistency test in Task 1 exercises the *gateway tool wrapper* (`call_via_runtime`) and the *in-process client* against the **same bootstrapped ToolRuntime** — this proves the shared policy core without the cost/flakiness of a live HTTP server.
- **The two-layer allowlist stays as-is.** It is correct: the agent hook enforces a per-agent tool *allowlist* (which tools *this agent* may use), RBAC enforces *role* permission (which tools *this user role* may use). They are different axes. Task 2 documents and pins the invariant; it does not collapse them.
- **Glossary extends existing docs, does not replace them.** Task 3 adds one canonical boundary section and links the existing architecture docs to it, rather than rewriting them.

## File Structure

| File | Responsibility | Created/Modified |
|---|---|---|
| `tests/test_mcp_boundary_consistency.py` | Same tool + same identity → same guard verdict + same envelope shape across in-process client and gateway wrapper | Create |
| `tests/test_mcp_gateway_external_rbac.py` | Add an explicit assertion naming the two-layer allowlist invariant (agent hook absent on external path) | Modify |
| `docs/architecture/mcp-runtime.md` | Add the canonical "Boundary roles & responsibilities" glossary + the two-layer allowlist invariant | Modify |
| `docs/plans/archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md` | Mark Phase 3 acceptance criteria as met with references | Modify |

## Constraints (do not violate)

- No change to `ToolRuntime`, `mcp_gateway`, the clients, the guard, or any agent behavior. This is a test + documentation closeout. If a test in Task 1 fails, that is a **real boundary bug** to be reported and triaged — do not paper over it by weakening the assertion.
- The consistency test MUST bootstrap a real `ToolRuntime` via `bootstrap_tool_runtime()` (as the existing RBAC test does) so it exercises the live registry/guard, not a mock.
- Existing boundary suites MUST stay green: `tests/test_agent_mcp_client_boundary.py`, `tests/test_mcp_gateway_external_rbac.py`, `tests/test_mcp_gateway_scope_enforcement.py`, `tests/test_mcp_gateway_human_gate.py`, `tests/test_mcp_gateway_identity.py`, `tests/test_mcp_permission_matrix.py`.

---

## Task 1: Cross-path boundary consistency test

**Files:**
- Create: `tests/test_mcp_boundary_consistency.py`

The core防漂移 gap. Pin that the in-process agent path and the gateway external path, given the *same tool and same effective identity*, reach the same ToolRuntime verdict and emit the same envelope shape. This is what makes "equal permission semantics" a guarantee instead of a coincidence.

- [ ] **Step 1: Write the test**

```python
# tests/test_mcp_boundary_consistency.py
"""Both tool entry paths share one policy core.

For the same tool and the same effective identity, the in-process MCP client
(agent path) and the gateway tool wrapper (external/transport path) must reach
the same ToolRuntime verdict and produce the same envelope shape. This pins the
Phase 3 "equal permission semantics across paths" guarantee against drift.
"""

import json

import pytest

from mcp_gateway.bootstrap import bootstrap_tool_runtime
from mcp_gateway.middleware import set_caller_info


@pytest.fixture(autouse=True)
def _runtime_and_no_rate_limit(app, monkeypatch):
    # Real registry + guard, not a mock — the whole point is to test the shared core.
    with app.app_context():
        bootstrap_tool_runtime()
        monkeypatch.setattr(
            "mcp_gateway.middleware.core.check_rate_limit", lambda *_: True
        )
        yield


def _inproc_envelope(tool: str, args: dict, *, user_id: int, role: str, agent: str) -> dict:
    from mcp_gateway.client import InProcessMCPToolClient, MCPClientIdentity

    identity = MCPClientIdentity(user_id=user_id, role=role, agent_type=agent)
    return InProcessMCPToolClient().call_tool(tool, args, identity)


def _gateway_envelope(tool: str, args: dict, *, user_id: int, role: str, agent: str) -> dict:
    from mcp_gateway.middleware.core import call_via_runtime

    # agent_host caller mirrors what the verified internal token would yield.
    from tools.protocol.policies.scopes import scopes_for_agent

    set_caller_info({
        "actor_type": "agent_host",
        "api_key_id": f"internal:{agent}",
        "user_id": user_id,
        "role": role,
        "agent_type": agent,
        "scopes": scopes_for_agent(agent),
        "rate_limit_rpm": 600,
    })
    try:
        return json.loads(call_via_runtime(tool, args))
    finally:
        set_caller_info(None)


def test_allowed_call_agrees_across_paths():
    kw = dict(user_id=1, role="student", agent="tutor")
    a = _inproc_envelope("coderunner.knowledge.search", {"query": "loops"}, **kw)
    b = _gateway_envelope("coderunner.knowledge.search", {"query": "loops"}, **kw)
    assert a["ok"] == b["ok"] is True
    assert set(a) >= {"ok", "tool", "data"}
    assert set(a) == set(b), f"envelope keys diverged: {set(a) ^ set(b)}"


def test_rbac_denied_call_agrees_across_paths():
    # A teacher-only tool requested by a student must be denied identically.
    kw = dict(user_id=1, role="student", agent="tutor")
    a = _inproc_envelope("coderunner.student.get_summary", {"student_id": 99}, **kw)
    b = _gateway_envelope("coderunner.student.get_summary", {"student_id": 99}, **kw)
    assert a["ok"] == b["ok"] is False
    assert a["error"]["code"] == b["error"]["code"]
    assert a["status"] == b["status"]
```

> Verify first: confirm the chosen tools' role rules match the assertions. Run
> `grep -rn "student.get_summary\|knowledge.search" tools/protocol/policies/` and
> check `evals/mcp/permission_matrix.yaml`. If `get_summary` is not student-denied
> for a student caller (e.g. a student reading their own summary), swap in a tool
> that is unambiguously teacher-only (check `_ROLE_OVERRIDES` in the rbac policy)
> so the deny assertion is real. Do NOT weaken the assertion to match a surprise —
> if an allowed-everywhere tool denies on one path only, that is the bug this task
> exists to catch.

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_mcp_boundary_consistency.py -v`
Expected: PASS. If `test_rbac_denied_call_agrees_across_paths` fails because the two paths *disagree*, STOP and report — that is a genuine boundary divergence, not a test bug.

- [ ] **Step 3: Run the surrounding boundary suite for no regression**

Run: `pytest tests/test_mcp_gateway_external_rbac.py tests/test_agent_mcp_client_boundary.py tests/test_mcp_gateway_scope_enforcement.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_boundary_consistency.py
git commit -m "test(mcp): pin equal guard verdict and envelope across both tool paths"
```

---

## Task 2: Pin the two-layer allowlist invariant

**Files:**
- Modify: `tests/test_mcp_gateway_external_rbac.py`

The agent path enforces *two* gates (per-agent allowlist hook + role RBAC); the external API-key path enforces *one* (RBAC/scope, no agent allowlist). This is intentional. Add an assertion + docstring that names it, so a future reader does not "fix" the missing agent hook on the external path.

- [ ] **Step 1: Add the invariant test**

```python
# add to tests/test_mcp_gateway_external_rbac.py

def test_external_path_has_no_agent_allowlist_layer():
    """Invariant: the agent-allowlist hook (BEFORE_TOOL_CALL) is an agent-path
    concept only. External API-key callers are gated by RBAC + scope, never by a
    per-agent tool allowlist — there is no agent in that flow. The gateway tool
    wrapper must therefore NOT invoke the hook manager.

    If this breaks, do not add the hook to the external path; revisit the design.
    """
    import inspect

    from mcp_gateway.middleware import core

    src = inspect.getsource(core.call_via_runtime)
    assert "HookEvent" not in src
    assert "get_hook_manager" not in src
    assert "BEFORE_TOOL_CALL" not in src
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_mcp_gateway_external_rbac.py -v`
Expected: PASS (the gateway wrapper does not reference the hook manager today)

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_gateway_external_rbac.py
git commit -m "test(mcp): pin two-layer allowlist invariant (agent hook is agent-path only)"
```

---

## Task 3: Canonical boundary glossary + Phase 3 acceptance

**Files:**
- Modify: `docs/architecture/mcp-runtime.md`
- Modify: `docs/plans/archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md`

Give the boundary one authoritative description and record Phase 3 as met.

- [ ] **Step 1: Read the current doc to place the section**

Run: `sed -n '1,40p' docs/architecture/mcp-runtime.md` (or open it). Decide whether to add a top-level "Boundary roles & responsibilities" section or extend an existing one. Do not duplicate content already there — link to it.

- [ ] **Step 2: Add the canonical glossary**

Add a section to `docs/architecture/mcp-runtime.md` defining each boundary role and what it may/may not do, sourced from the verified code:

| Role | Is | May do | May NOT do |
|---|---|---|---|
| Flask app | Main business app | Serve UI/API, originate user requests | Execute tools directly |
| FastAPI Agent Host (`workers/__main__.py`) | Agent runtime / scheduling service | Run agents, mint internal capability tokens | Bypass ToolRuntime policy |
| Agents (`agents/`) | Internal business logic, MCP *clients* | Call tools via `MCPToolClient` | Import tool implementations or `ToolRuntime` |
| DeepSeek | External LLM provider | Produce tool-call requests | Control identity/scopes (sanitized) |
| `mcp_gateway` | External transport boundary | Auth, rate-limit, transport | Tool policy (delegated to ToolRuntime) |
| `ToolRuntime` (`tools/protocol/`) | The single policy core | schema, RBAC/scope/risk, human-gate, sanitize, audit, trace | — |

Then add the **two-layer allowlist invariant** (from Task 2) and the **equal-semantics guarantee** (from Task 1), each linking to the pinning test. Cross-link `agent-runtime-core.md` and `tools-mcp-rag.md` to this section instead of restating it.

- [ ] **Step 3: Record Phase 3 acceptance in the upgrade plan**

In `docs/plans/archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md`, under the Phase 3 验收标准, annotate each criterion as met with a reference (the consistency test, the boundary code, the glossary). Note the deferred hardening items (output-schema enforce, quotas, idempotency, multi-tenant) as explicitly out of Phase 3 and tracked for Phase 3.5 / Phase 6.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/mcp-runtime.md docs/plans/archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md
git commit -m "docs(mcp): canonical boundary glossary and Phase 3 acceptance record"
```

---

## Acceptance Criteria (from the upgrade plan)

- [ ] agent does not directly import tool implementations — already true; guarded by `tests/test_agent_mcp_client_boundary.py`.
- [ ] external MCP and internal agent tool calls return a consistent envelope — **Task 1** pins it.
- [ ] tool calls are associated with user / role / agent / conversation / task / trace — already true via `CallerContext` + `emit_audit`; referenced in the Task 3 glossary.
- [ ] high-risk / write tools still pass through the human gate — already true; covered by `tests/test_mcp_gateway_human_gate.py`.

## Out of scope (tracked for Phase 3.5 / Phase 6)

- Flipping `output_schema` validation from warn-only to enforce ([runtime.py:229](../../tools/protocol/runtime.py)) — needs the catalog's output schemas completed first.
- Per-tool / per-user quotas at the ToolRuntime layer (today: connection-level per-api-key only).
- Write-tool idempotency keys / dedup (relevant to approval replay).
- Multi-tenant isolation enforcement in the guard (`CallerContext.tenant_id` exists but is unused).
- Per-tool circuit breaker / retry policy beyond `timeout_ms`.
- A live-HTTP streamable-http integration test booting the FastMCP server.

## Risks & Mitigations

- **Task 1 surfaces a real divergence:** if the two paths disagree on a deny, that is the bug the task exists to catch — report and triage, do not weaken the test. Most likely cause would be the external path missing a guard step the in-process path has (it does not today, per the code read, but the test guarantees it stays so).
- **Chosen test tools have surprising role rules:** Task 1 Step 1's "verify first" note reconciles tool choice against `permission_matrix.yaml` and `_ROLE_OVERRIDES` before asserting.
- **Glossary drifts from code:** Task 3 links each invariant to its pinning test, so a behavior change that breaks the doc also breaks a test.
