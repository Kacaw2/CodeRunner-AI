# MCP Architecture Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair CodeRunner-AI into a mature MCP-native agent architecture where agents are MCP clients, tools are served through one standards-facing MCP server, and authorization, tool catalog, naming, transport, and runtime behavior have clear single sources of truth.

**Architecture:** Use a single MCP-native tool boundary. Agents call tools through an MCP client over an explicit transport (`streamable-http` in Docker/runtime, optional stdio for local development), and the MCP server uses `ToolRuntime` only as its internal execution engine behind that transport. No production agent path may bypass the MCP boundary by calling `get_tool_runtime().call_sync()` directly.

**Tech Stack:** Python, FastMCP, SQLAlchemy/Flask models, `tools.protocol` runtime/catalog/policies, `mcp_gateway`, pytest, Docker Compose.

---

## 0. Current Truth After Phase 1

This document is based on the current branch state after `codex/phase-1-architecture-unification`.

Phase 1 improved the internal tool pipeline:

- Agents derive tool allowlists from `core/definitions.py`.
- `tools/protocol/policies/rbac.py` derives agent allowlists from the same definitions.
- Gateway handlers now call `ToolRuntime` through `mcp_gateway.middleware.core.call_via_runtime()`.
- `ToolRuntime` owns schema validation, RBAC, risk/approval, audit, and transport dispatch.
- High-risk approval creation moved into the runtime through an injected approval store.

But the MCP architecture is not yet a standard MCP-native agent topology:

- Agents call `get_tool_runtime().call_sync()` in-process from `agents/base.py`.
- FastMCP in `mcp_gateway/server.py` is only an external-facing gateway, not the path used by internal agents.
- `TOOL_CATALOG` has 14 internal tools, while the external FastMCP server exposes 11 names.
- External tool names are legacy short names such as `search_knowledge`, while canonical names are `coderunner.knowledge.search`.
- `required_scopes` are declared in catalog descriptors but are bypassed because both internal and external runtime calls currently use `actor_type="agent_host"`.
- `mcp_gateway/__main__.py` authenticates with one process-level `MCP_API_KEY`, not per connection.

The target is not a temporary hybrid. The mature target is:

> Agents are MCP clients. The MCP gateway is the tool server. `ToolRuntime` is an implementation detail inside the server, not the agent-facing boundary.

---

## 1. Architecture Vocabulary To Lock Down

Use these names consistently in code comments and docs:

| Term | Meaning in this repo | Must not be confused with |
|---|---|---|
| `ToolRuntime` | Server-side execution engine behind the MCP server. | Agent-facing API or MCP transport. |
| `TOOL_CATALOG` | Canonical descriptor source for every tool served by MCP. | A private internal-only list. |
| `mcp_gateway` | FastMCP server process exposing catalog tools over MCP transport. | Optional decoration around direct calls. |
| `agent_host` actor | Trusted internal platform caller identity carried over MCP transport. | A reason to bypass MCP transport. |
| `external_client` actor | Third-party MCP API key caller over MCP transport. | Internal agent identity. |
| `MCP client` | The interface used by agents to invoke tools. | Direct Python `ToolRuntime` calls. |

The project should stop saying "agents use MCP" until agents actually cross MCP transport. The final phrase after this repair should be:

> Agents and external clients call tools through the MCP server. The server uses ToolRuntime internally for policy enforcement and local implementation dispatch.

---

## 2. Repair Scope

### In Scope

- Generate or validate the external FastMCP surface from `TOOL_CATALOG`.
- Make external API key scopes enforce `required_scopes`.
- Replace process-level external identity with per-request or per-session identity.
- Replace direct internal agent `ToolRuntime` calls with an MCP client adapter.
- Make tool naming explicit and testable across agent and external client paths.
- Add tests that fail on catalog/gateway drift.
- Update docs so the architecture is not overstated.

### Out Of Scope For This Repair

- Adding MCP resources or prompts.
- Rewriting the whole agent orchestration layer.
- Changing LLM provider integration.
- Keeping a permanent direct-call fallback for production agents.

---

## 3. Target Architecture

### 3.1 Agent Tool Path

Agents must use this shape:

```text
Agent
  -> MCP client adapter
  -> MCP transport (streamable-http in Docker/runtime; stdio only for local dev)
  -> mcp_gateway FastMCP server
  -> ToolRuntime.call_sync()
  -> guard: RBAC + scope + risk + audit + schema validation
  -> LocalTransport implementation handler
  -> app/service implementation
```

This is the production boundary. Direct Python calls to `get_tool_runtime().call_sync()` are allowed only inside the MCP server implementation and narrow unit tests.

Acceptance rule:

- `agents/base.py` must depend on an MCP client interface, not `tools.protocol.get_tool_runtime()`.
- Agent calls must cross transport in integration tests.
- Internal agent identity is still trusted, but it is carried as authenticated MCP request metadata instead of implied by in-process function calls.
- Scope behavior for internal agents must be explicit: either use service scopes such as `agent:tutor` / `tool:*`, or use a signed internal principal that the server recognizes. It must not be an accidental bypass caused by direct Python calls.

### 3.2 External MCP Client Path

External clients should use this shape:

```text
External MCP client
  -> FastMCP transport
  -> per-connection/per-request auth
  -> mcp_gateway catalog-backed adapter
  -> ToolRuntime.call_sync(actor_type="external_client", granted_scopes=...)
  -> same guard/runtime/implementation handlers as agent calls
```

Acceptance rule:

- External callers must not use `actor_type="agent_host"`.
- External callers must pass real `required_scopes`.
- External tool registration must be derived from a catalog-backed mapping.

---

## 4. Data Model And Scope Model

### 4.1 Canonical Scope Vocabulary

The canonical scope strings are the descriptor `required_scopes` values:

- `problem:read`
- `problem:write`
- `submission:read`
- `student:read`
- `code:execute`
- `knowledge:read`
- `analytics:read`
- `trace:read`

Legacy tool-name scopes such as `search_knowledge` must be treated as migration input only.

### 4.2 API Key Schema

Current API key records may contain legacy scopes. The repair handles this with **normalize-on-read/write**, not a batch rewrite:

- Existing keys during transition: `normalize_scopes()` is applied at verification time (`mcp_gateway/middleware/auth.py`), so stored legacy scopes are translated on every request without touching the DB.
- New keys using canonical scopes: `normalize_scopes()` is applied at creation time (`app/api/v1/mcp_keys.py`).

This deliberately avoids a one-shot migration command: normalize-on-read fully covers existing rows, so a destructive batch UPDATE is unnecessary and is **out of scope** for this repair. If a future cleanup wants to persist canonical scopes (to drop the read-time translation), that becomes a separate, independently reversible migration task — not part of this plan.

Mapping:

| Legacy tool scope | Canonical scope |
|---|---|
| `search_knowledge` | `knowledge:read` |
| `search_similar_problems` | `knowledge:read` |
| `get_problem_detail` | `problem:read` |
| `get_problem_difficulty_stats` | `analytics:read` |
| `get_student_activity` | `analytics:read` |
| `get_class_statistics` | `analytics:read` |
| `get_agent_trace` | `trace:read` |
| `get_student_summary` | `student:read` |
| `execute_code` | `code:execute` |
| `save_generated_problem` | `problem:write` |

`check_approval` must be promoted into `TOOL_CATALOG` as `coderunner.approval.check`. A mature MCP server should not keep one-off gateway-native tools outside the canonical descriptor/policy/audit path.

---

## 5. Task Plan

### Task 1: Add Catalog/Gateway Drift Tests

**Files:**

- Create: `tests/test_mcp_gateway_catalog_contract.py`
- Modify: `mcp_gateway/server.py`

- [ ] **Step 1: Write failing drift tests**

Create `tests/test_mcp_gateway_catalog_contract.py`:

```python
"""Contract tests for external MCP gateway surface."""

from mcp_gateway.server import create_mcp_server
from tools.protocol.schemas.catalog import TOOL_CATALOG


EXPECTED_EXTERNAL_TOOL_MAP = {
    "search_knowledge": "coderunner.knowledge.search",
    "search_similar_problems": "coderunner.knowledge.search_similar_problems",
    "search_error_patterns": "coderunner.knowledge.search_error_patterns",
    "get_problem_detail": "coderunner.problem.get_detail",
    "list_student_submissions": "coderunner.submission.list_for_student",
    "get_submission_detail": "coderunner.submission.get_detail",
    "get_problem_difficulty_stats": "coderunner.analytics.problem_difficulty",
    "get_student_activity": "coderunner.analytics.student_activity",
    "get_student_stats": "coderunner.analytics.student_stats",
    "get_class_statistics": "coderunner.analytics.class_statistics",
    "get_agent_trace": "coderunner.trace.get_agent_trace",
    "get_student_summary": "coderunner.student.get_summary",
    "execute_code": "coderunner.code.execute",
    "save_generated_problem": "coderunner.problem.save_generated",
    "check_approval": "coderunner.approval.check",
}


def test_external_tool_map_targets_existing_catalog_tools():
    missing = set(EXPECTED_EXTERNAL_TOOL_MAP.values()) - set(TOOL_CATALOG)
    assert missing == set()


def test_every_catalog_tool_is_exposed_by_mcp_server():
    assert set(EXPECTED_EXTERNAL_TOOL_MAP.values()) == set(TOOL_CATALOG)


def test_external_gateway_registers_exact_declared_tools():
    mcp = create_mcp_server()
    actual = set(mcp._tool_manager._tools)
    assert actual == set(EXPECTED_EXTERNAL_TOOL_MAP)


def test_expected_tool_count_matches_registered_tools():
    from mcp_gateway.server import EXPECTED_TOOL_COUNT

    mcp = create_mcp_server()
    assert EXPECTED_TOOL_COUNT == len(mcp._tool_manager._tools)
```

- [ ] **Step 2: Run the test and confirm current behavior**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_gateway_catalog_contract.py -q
```

Expected current result:

- The catalog completeness tests should fail until missing tools and `coderunner.approval.check` are registered.
- The count test documents that `EXPECTED_TOOL_COUNT` must match the final registered surface, not a stale constant.

- [ ] **Step 3: Replace dead count logging with actual assertion**

Modify `mcp_gateway/server.py` so `create_mcp_server()` computes and validates actual count:

```python
    actual_count = len(mcp._tool_manager._tools)
    if actual_count != EXPECTED_TOOL_COUNT:
        raise RuntimeError(
            f"MCP gateway registered {actual_count} tools, expected {EXPECTED_TOOL_COUNT}"
        )
    logger.info("MCP Server created with %d tools registered", actual_count)
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_gateway_catalog_contract.py tests/test_mcp_gateway.py tests/test_mcp_gateway_human_gate.py -q
```

Expected: all selected tests pass.

---

### Task 2: Move External Tool Mapping Into A Single Source

**Files:**

- Create: `mcp_gateway/tool_map.py`
- Modify: `mcp_gateway/handlers/*.py`
- Modify: `tests/test_mcp_gateway_catalog_contract.py`

- [ ] **Step 1: Create one mapping module**

Create `mcp_gateway/tool_map.py`:

```python
"""External FastMCP tool names mapped to canonical ToolRuntime tool names."""

EXTERNAL_TOOL_MAP: dict[str, str] = {
    "search_knowledge": "coderunner.knowledge.search",
    "search_similar_problems": "coderunner.knowledge.search_similar_problems",
    "search_error_patterns": "coderunner.knowledge.search_error_patterns",
    "get_problem_detail": "coderunner.problem.get_detail",
    "list_student_submissions": "coderunner.submission.list_for_student",
    "get_submission_detail": "coderunner.submission.get_detail",
    "get_problem_difficulty_stats": "coderunner.analytics.problem_difficulty",
    "get_student_activity": "coderunner.analytics.student_activity",
    "get_student_stats": "coderunner.analytics.student_stats",
    "get_class_statistics": "coderunner.analytics.class_statistics",
    "get_agent_trace": "coderunner.trace.get_agent_trace",
    "get_student_summary": "coderunner.student.get_summary",
    "execute_code": "coderunner.code.execute",
    "save_generated_problem": "coderunner.problem.save_generated",
    "check_approval": "coderunner.approval.check",
}
```

- [ ] **Step 2: Update contract test to import the mapping**

Replace local `EXPECTED_EXTERNAL_TOOL_MAP` in `tests/test_mcp_gateway_catalog_contract.py` with:

```python
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP
```

Then assert:

```python
assert actual == set(EXTERNAL_TOOL_MAP)
```

- [ ] **Step 3: Replace hardcoded canonical strings in handlers**

Example for `mcp_gateway/handlers/knowledge.py`:

```python
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP

...
return _guarded(lambda: call_via_runtime(
    EXTERNAL_TOOL_MAP["search_knowledge"],
    {"query": query, "owner_id": owner_id},
))
```

Repeat for all gateway handlers.

- [ ] **Step 4: Verify no handler embeds canonical names**

Run:

```powershell
rg 'coderunner\.' mcp_gateway/handlers
```

Expected: no direct canonical tool string remains in handler files.

- [ ] **Step 5: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_gateway_catalog_contract.py tests/test_phase1_architecture_unification.py -q
```

Expected: pass.

---

### Task 3: Make External Scope Checks Real

**Files:**

- Modify: `tools/protocol/runtime.py`
- Modify: `mcp_gateway/middleware/core.py`
- Create: `tests/test_mcp_gateway_scope_enforcement.py`
- Create: `tests/test_mcp_gateway_external_rbac.py`

> **Current-state note (verified against source):** `tools/protocol/policies/scopes.py` already implements the correct logic — it short-circuits for `actor_type="agent_host"` and enforces `granted_scopes` for any other actor. `run_guard()` already accepts a `granted_scopes` kwarg. The real gap is wiring, not policy: `ToolRuntime.call()` never passes `granted_scopes` to `run_guard()`, and `mcp_gateway/middleware/core.py` still builds external callers as `actor_type="agent_host"`. **Do not rewrite `scopes.py`** — only connect the two ends below.

- [ ] **Step 1: Write failing external scope test**

Create `tests/test_mcp_gateway_scope_enforcement.py`:

```python
import json

from mcp_gateway.middleware import set_caller_info


def test_external_gateway_enforces_required_scopes(monkeypatch):
    from mcp_gateway.middleware.core import call_via_runtime
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    set_caller_info({
        "api_key_id": "key-1",
        "user_id": 10,
        "role": "teacher",
        "scopes": ["knowledge:read"],
        "rate_limit_rpm": 30,
    })
    monkeypatch.setattr("mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)

    payload = json.loads(call_via_runtime(
        "coderunner.problem.get_detail",
        {"problem_id": 1},
    ))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "MCP_SCOPE_DENIED"
```

- [ ] **Step 2: Extend runtime to accept granted scopes**

Modify `ToolCallContext` in `tools/protocol/runtime.py`:

```python
@dataclass
class ToolCallContext:
    caller: CallerContext
    tool_call_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    granted_scopes: list[str] | None = None
```

Modify runtime guard call:

```python
guard = run_guard(descriptor, caller, granted_scopes=context.granted_scopes)
```

- [ ] **Step 3: Make gateway calls external clients**

Modify `mcp_gateway/middleware/core.py`:

```python
ctx = ToolCallContext(
    caller=CallerContext(
        actor_type="external_client",
        user_id=caller["user_id"],
        role=caller["role"],
        api_key_id=caller.get("api_key_id"),
    ),
    granted_scopes=caller.get("scopes") or [],
)
```

- [ ] **Step 4: Make internal scope bypass explicit and transport-based**

Do not rely on direct Python calls to imply trust. Internal agents should authenticate to the MCP server with an internal service principal and the server should construct a `CallerContext` with:

```python
CallerContext(
    actor_type="agent_host",
    user_id=state["user_id"],
    role=state.get("user_role", "student"),
    agent_type=state.get("agent_type", ""),
    task_id=state.get("context", {}).get("task_id"),
    conversation_id=state.get("context", {}).get("conversation_id"),
)
```

The `agent_host` scope bypass remains valid only after the request crosses MCP transport and is authenticated as an internal platform caller.

- [ ] **Step 5: Pin down RBAC semantics for `external_client` (real hole)**

`tools/protocol/policies/rbac.py` gates tools two ways:

1. `_ROLE_OVERRIDES` — explicit `{role}` allowlist per tool.
2. `_agent_tool_allow()` — per-`agent_type` allowlist.

An `external_client` caller has `agent_type=""`, so `_agent_tool_allow().get("")` returns `None` and the agent-allowlist branch is **skipped entirely**. Result: tools NOT in `_ROLE_OVERRIDES` (e.g. `coderunner.knowledge.search`, `coderunner.problem.get_detail`) have **no role gate at all** for external clients — they are guarded only by scope.

This must be a deliberate, tested decision, not an accident. Decide and encode:

- **Intended model:** for `external_client`, RBAC role enforcement is carried by `_ROLE_OVERRIDES` + scope checks; the per-agent allowlist applies only to internal `agent_host` callers. This is acceptable because external access is scoped per API key.

Add `tests/test_mcp_gateway_external_rbac.py` proving the boundary:

```python
import json

from mcp_gateway.middleware import set_caller_info


def test_external_client_role_override_still_enforced(monkeypatch):
    """A scope alone must not unlock a teacher-only tool for a student."""
    from mcp_gateway.middleware.core import call_via_runtime
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr("mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)
    set_caller_info({
        "api_key_id": "key-1",
        "user_id": 10,
        "role": "student",
        "scopes": ["student:read"],
        "rate_limit_rpm": 30,
    })

    payload = json.loads(call_via_runtime(
        "coderunner.student.get_summary",
        {"student_id": 99},
    ))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "MCP_PERMISSION_DENIED"


def test_external_client_unrestricted_tool_passes_with_scope(monkeypatch):
    """A tool with no role override is gated by scope only — document that."""
    from mcp_gateway.middleware.core import call_via_runtime
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr("mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)
    set_caller_info({
        "api_key_id": "key-2",
        "user_id": 11,
        "role": "student",
        "scopes": ["knowledge:read"],
        "rate_limit_rpm": 30,
    })

    payload = json.loads(call_via_runtime(
        "coderunner.knowledge.search",
        {"query": "loops"},
    ))

    assert payload["ok"] is True
```

If `test_external_client_unrestricted_tool_passes_with_scope` is judged too permissive, add the tool to `_ROLE_OVERRIDES` or introduce a default-deny role rule for `external_client` — but make that an explicit change with its own test, not silent behavior.

- [ ] **Step 6: Run targeted tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_gateway_scope_enforcement.py tests/test_mcp_gateway_external_rbac.py tests/test_tool_protocol.py -q
```

Expected: pass.

---

### Task 4: Migrate Legacy API Key Scopes

**Files:**

- Modify: `app/api/v1/mcp_keys.py`
- Create: `mcp_gateway/scopes.py`
- Create: `tests/test_mcp_key_scopes.py`

- [ ] **Step 1: Create reusable scope mapping**

Create `mcp_gateway/scopes.py`:

```python
"""Scope normalization for MCP API keys."""

LEGACY_SCOPE_TO_CANONICAL = {
    "search_knowledge": "knowledge:read",
    "search_similar_problems": "knowledge:read",
    "get_problem_detail": "problem:read",
    "get_problem_difficulty_stats": "analytics:read",
    "get_student_activity": "analytics:read",
    "get_class_statistics": "analytics:read",
    "get_agent_trace": "trace:read",
    "get_student_summary": "student:read",
    "execute_code": "code:execute",
    "save_generated_problem": "problem:write",
}


def normalize_scopes(scopes: list[str] | None) -> list[str] | None:
    if scopes is None:
        return None
    normalized = {
        LEGACY_SCOPE_TO_CANONICAL.get(scope, scope)
        for scope in scopes
    }
    return sorted(normalized)
```

- [ ] **Step 2: Add tests for new and legacy scope creation**

Create `tests/test_mcp_key_scopes.py`:

```python
from mcp_gateway.scopes import normalize_scopes


def test_normalize_legacy_tool_scope_to_canonical_scope():
    assert normalize_scopes(["search_knowledge"]) == ["knowledge:read"]


def test_normalize_deduplicates_scope_aliases():
    assert normalize_scopes(["search_knowledge", "search_similar_problems"]) == ["knowledge:read"]


def test_normalize_preserves_canonical_scope():
    assert normalize_scopes(["problem:read"]) == ["problem:read"]


def test_none_scopes_remain_unrestricted():
    assert normalize_scopes(None) is None
```

- [ ] **Step 3: Use normalization when creating API keys**

In `app/api/v1/mcp_keys.py`, normalize incoming `scopes` before persistence:

```python
from mcp_gateway.scopes import normalize_scopes

...
scopes = normalize_scopes(data.get("scopes"))
```

- [ ] **Step 4: Use normalization when verifying keys**

In `mcp_gateway/middleware/auth.py`, normalize loaded record scopes before returning caller info:

```python
from mcp_gateway.scopes import normalize_scopes

...
"scopes": normalize_scopes(record.scopes),
```

- [ ] **Step 5: Verify**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_key_scopes.py tests/test_mcp_gateway.py -q
```

Expected: pass.

---

### Task 5: Replace Process-Level Gateway Identity

**Files:**

- Modify: `mcp_gateway/__main__.py`
- Modify: `mcp_gateway/middleware/auth.py`
- Modify: `mcp_gateway/middleware/core.py`
- Create: `tests/test_mcp_gateway_identity.py`

This is the highest-risk gateway repair because FastMCP transport integration details matter. Implement after Tasks 1-4 are green.

- [ ] **Step 0: Probe the installed FastMCP's auth capability BEFORE designing**

Do not pick an auth approach blind. First establish what the installed package actually supports:

```powershell
.\.venv\Scripts\python.exe -m pip show mcp
.\.venv\Scripts\python.exe -c "import mcp.server, inspect; from mcp.server import FastMCP; print([n for n in dir(FastMCP) if 'middl' in n.lower() or 'auth' in n.lower() or 'request' in n.lower()])"
```

Record the version and whether per-request/per-session hooks exist. The chosen sub-approach in Step 3 must reference this finding, not a guess. If no per-request hook exists, the production HTTP transport stays gated behind the feature flag (Step 1b) until the dependency is upgraded.

- [ ] **Step 1: Document current limitation in test**

Create `tests/test_mcp_gateway_identity.py`:

```python
from mcp_gateway.middleware import set_caller_info, get_caller_info


def test_caller_info_is_not_process_global_after_request_clear():
    set_caller_info({"user_id": 1, "role": "teacher", "api_key_id": "k1"})
    set_caller_info(None)
    assert get_caller_info() is None
```

- [ ] **Step 1b: Make per-request/per-session auth the production default**

Add an env flag only for local development fallback, e.g. `MCP_ALLOW_STARTUP_KEY_DEV_MODE` (default `false`):

- `false` (default): production behavior. Every request/session must authenticate independently.
- `true`: local development only. Startup `MCP_API_KEY` may set a fallback caller for local stdio experiments.

Any code path using startup `MCP_API_KEY` must refuse non-local transports and must be labeled development-only in logs and docs.

**Concurrency note:** `_caller_info_var` in `middleware/core.py` is a `contextvars.ContextVar` — the correct primitive for per-request isolation under async FastMCP. The current bug is not the primitive, it is that `__main__.py` sets it once globally. Per-request auth must `set_caller_info()` **inside each request's own async context** (Step 3), and `core.py` reads `get_caller_info()` before the sync `call_sync()` thread offload (it already does, at line ~53), so the value is captured in-context and the thread-pool boundary does not lose it. Verify this assumption holds for the chosen FastMCP hook.

- [ ] **Step 2: Remove startup `MCP_API_KEY` as the only identity**

Change `mcp_gateway/__main__.py`:

- Keep `MCP_API_KEY` only as a local development fallback, active when `MCP_ALLOW_STARTUP_KEY_DEV_MODE=true`.
- Log clearly when fallback mode is active.
- Do not set global caller info in production mode.

- [ ] **Step 3: Add request/session auth middleware**

Implement one of these based on FastMCP capabilities available in the installed package:

1. Per-request header auth for streamable HTTP.
2. Per-session auth during connection setup.
3. If FastMCP does not expose middleware hooks, wrap tool functions so each tool reads a passed API key argument only in development, then reject production external exposure until middleware support is added.

Required behavior:

```text
Authorization: Bearer <mcp-api-key>
```

must map to:

```python
set_caller_info(verify_api_key(raw_key))
```

for that request/session only.

- [ ] **Step 4: Clear caller info after each tool call**

Add a finally path around gateway tool execution so caller info cannot leak between calls:

```python
try:
    set_caller_info(caller)
    return call_via_runtime(...)
finally:
    set_caller_info(None)
```

- [ ] **Step 5: Verify manually and with tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_gateway_identity.py tests/test_mcp_gateway.py -q
```

Then run a local server smoke test:

```powershell
$env:MCP_API_KEY='<valid test key>'
.\.venv\Scripts\python.exe -m mcp_gateway --transport streamable-http --host 127.0.0.1 --port 8200
```

Expected:

- Calls without auth are rejected.
- Calls with key A run as key A.
- Calls with key B run as key B.
- Two calls do not share caller state.

---

### Task 6: Move Internal Agents To MCP Client Transport

**Files:**

- Create: `mcp_gateway/client.py`
- Modify: `agents/base.py`
- Modify: `workers/task_runner.py`
- Modify: `compose.yaml`
- Create: `tests/test_agent_mcp_client_boundary.py`

This is the core maturity task. It removes the direct in-process tool boundary from production agent execution.

- [ ] **Step 1: Write a failing boundary test**

Create `tests/test_agent_mcp_client_boundary.py`:

```python
def test_base_agent_does_not_import_tool_runtime_for_tool_execution():
    import inspect
    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._run_mcp_tool)
    assert "get_tool_runtime" not in source
    assert "call_sync" not in source


def test_base_agent_uses_mcp_client_adapter_for_tool_execution():
    import inspect
    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._run_mcp_tool)
    assert "MCPToolClient" in source or "get_mcp_tool_client" in source
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_mcp_client_boundary.py -q
```

Expected: fails before implementation.

- [ ] **Step 2: Create an MCP client adapter**

Create `mcp_gateway/client.py`:

```python
"""MCP client adapter used by internal agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MCPClientIdentity:
    user_id: int
    role: str
    agent_type: str
    task_id: str | None = None
    conversation_id: str | None = None


class MCPToolClient:
    """Transport-backed MCP tool client.

    Production mode must call the MCP server over transport. Tests may inject
    a fake implementation of this interface.
    """

    def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        identity: MCPClientIdentity,
        *,
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError


_CLIENT: MCPToolClient | None = None


def set_mcp_tool_client(client: MCPToolClient | None) -> None:
    global _CLIENT
    _CLIENT = client


def get_mcp_tool_client() -> MCPToolClient:
    if _CLIENT is None:
        raise RuntimeError("MCP tool client is not configured")
    return _CLIENT
```

- [ ] **Step 3: Add a concrete transport client**

Implement a production client in the same module after probing the installed `mcp` Python SDK. The production implementation must use FastMCP-compatible transport, not `ToolRuntime`.

Runtime default:

- Docker/runtime: `streamable-http` against the `mcp_gateway` service.
- Local development: stdio is allowed only behind an explicit env setting such as `MCP_AGENT_TRANSPORT=stdio`.

Configuration:

```text
MCP_AGENT_TRANSPORT=streamable-http
MCP_GATEWAY_URL=http://mcp_gateway:8200/mcp
MCP_INTERNAL_AUTH_TOKEN=<service-token>
```

The request must carry internal identity metadata so the server can build `CallerContext(actor_type="agent_host", agent_type=...)`.

- [ ] **Step 4: Change `BaseAgent._run_mcp_tool()` to use the client**

Modify `agents/base.py`:

```python
from mcp_gateway.client import MCPClientIdentity, get_mcp_tool_client

...
identity = MCPClientIdentity(
    user_id=state.get("user_id", 0),
    role=state.get("user_role", "student"),
    agent_type=state.get("agent_type", self.name),
    task_id=state.get("context", {}).get("task_id"),
    conversation_id=state.get("context", {}).get("conversation_id"),
)
envelope = get_mcp_tool_client().call_tool(name, args, identity, tool_call_id=tc_id)
```

Then convert `envelope` to `ToolMessage` using the same success/error shape currently used for `ToolResult`.

- [ ] **Step 5: Configure the client in worker startup**

Modify `workers/task_runner.py` so worker startup configures the MCP client, not `bootstrap_tool_runtime()` for direct in-process use.

Keep `bootstrap_tool_runtime()` only in the MCP server process.

- [ ] **Step 6: Verify no production agent path imports runtime directly**

Run:

```powershell
rg "get_tool_runtime|ToolRuntime|call_sync" agents workers
```

Expected:

- No direct production agent tool execution path imports `get_tool_runtime`.
- Test-only imports are acceptable only under `tests/`.

- [ ] **Step 7: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_mcp_client_boundary.py tests/test_agents.py tests/test_agent_features.py -q
```

Expected: pass.

---

### Task 7: Register Every Catalog Tool On The MCP Server

**Files:**

- Modify: `mcp_gateway/tool_map.py`
- Modify: `tests/test_mcp_gateway_catalog_contract.py`
- Possibly modify: `mcp_gateway/handlers/*.py`

The current catalog has 14 tools. A mature MCP server should not keep a second hidden tool surface. Register every catalog tool on the MCP server and use RBAC/scope/approval to control who can call each tool.

Currently missing from the external FastMCP surface:

- `coderunner.submission.list_for_student`
- `coderunner.submission.get_detail`
- `coderunner.knowledge.search_error_patterns`
- `coderunner.analytics.student_stats`

Add external mappings for all missing tools in `mcp_gateway/tool_map.py`:

```python
"list_student_submissions": "coderunner.submission.list_for_student",
"get_submission_detail": "coderunner.submission.get_detail",
"search_error_patterns": "coderunner.knowledge.search_error_patterns",
"get_student_stats": "coderunner.analytics.student_stats",
```

Required policy:

- Sensitive tools stay registered.
- Access is controlled by `required_scopes`, `_ROLE_OVERRIDES`, and approval policy.
- Tool listing is no longer used as the privacy boundary.

Test:

```python
def test_every_catalog_tool_is_exposed_by_mcp_server():
    assert set(EXTERNAL_TOOL_MAP.values()) == set(TOOL_CATALOG)


def test_mcp_server_registers_every_catalog_tool_plus_no_private_native_tools():
    mcp = create_mcp_server()
    assert set(mcp._tool_manager._tools) == set(EXTERNAL_TOOL_MAP)
}
```

This means `check_approval` must first be promoted into `TOOL_CATALOG` in Task 9.

---

### Task 8: Generate Gateway Wrappers From Descriptors

**Files:**

- Create: `mcp_gateway/generated_tools.py`
- Modify: `mcp_gateway/server.py`
- Modify: `mcp_gateway/handlers/*.py`
- Modify: `tests/test_mcp_gateway_catalog_contract.py`

This task removes hand-written mapping drift.

- [x] **Step 1: Create descriptor-backed registration helper**

Create `mcp_gateway/generated_tools.py`:

```python
"""Register external FastMCP tools from canonical descriptors."""

from __future__ import annotations

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP
from tools.protocol.schemas.catalog import TOOL_CATALOG


def register_generated_catalog_tools(mcp: FastMCP) -> None:
    for external_name, canonical_name in EXTERNAL_TOOL_MAP.items():
        descriptor = TOOL_CATALOG[canonical_name]

        def _make_tool(name: str, canonical: str):
            def _tool(**kwargs):
                return _guarded(lambda: call_via_runtime(canonical, kwargs))
            _tool.__name__ = name
            _tool.__doc__ = descriptor.description
            return _tool

        mcp.tool(name=external_name, description=descriptor.description)(
            _make_tool(external_name, canonical_name)
        )
```

Warning: FastMCP introspects function signatures. A generic `**kwargs` wrapper is not acceptable for the mature target because it degrades client schemas. The generator must produce explicit wrapper signatures from each descriptor's `input_schema`.

- [x] **Step 2: Generate explicit signatures**

Do not keep permanent handwritten wrappers. Generate a committed wrapper module from `TOOL_CATALOG` and fail tests when it is stale.

Required generated output:

- One wrapper function per catalog tool.
- Function name equals external tool name.
- Signature matches descriptor `input_schema` properties.
- Function body calls `_guarded(lambda: call_via_runtime(canonical_name, args))`.
- Generated file contains a header stating it must not be edited manually.

Add a test that regenerates into memory or a temp file and compares with the committed generated module.

---

### Task 9: Promote `check_approval` Into Catalog

**Files:**

- Modify: `tools/protocol/schemas/catalog.py`
- Modify: `mcp_gateway/bootstrap.py`
- Modify: `mcp_gateway/handlers/write.py`
- Modify: `mcp_gateway/tool_map.py`
- Modify: `tests/test_mcp_gateway_catalog_contract.py`

`check_approval` is currently gateway-native. A mature MCP server must route it through the same catalog, scope, audit, and runtime envelope path as every other tool.

- [ ] **Step 1: Add approval check descriptor**

Add descriptor:

```python
_reg(ToolDescriptor(
    name="coderunner.approval.check",
    version="1.0.0",
    description="Check the status of a pending tool approval.",
    server="db",
    risk_level=RiskLevel.LOW,
    required_scopes=["approval:read"],
    input_schema={
        "type": "object",
        "properties": {"approval_id": {"type": "string"}},
        "required": ["approval_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))
```

- [ ] **Step 2: Register the runtime handler**

Move the existing approval polling/execution logic from `mcp_gateway/handlers/write.py` into a runtime transport handler registered by `mcp_gateway/bootstrap.py`.

- [ ] **Step 3: Map external name to canonical name**

```python
"check_approval": "coderunner.approval.check"
```

- [ ] **Step 4: Remove gateway-native exception**

Delete `GATEWAY_NATIVE_TOOLS` if it exists. Contract tests should assert that every external MCP tool maps to `TOOL_CATALOG`.

---

### Task 10: Update Architecture Docs

**Files:**

- Modify: `docs/AI_AGENTS.md`
- Modify: `docs/AGENT_ARCHITECTURE_MATURITY_PLAN.md`
- Create or update: `docs/MCP_RUNTIME_ARCHITECTURE.md`

- [ ] **Step 1: Create current-state architecture doc**

Create `docs/MCP_RUNTIME_ARCHITECTURE.md` with:

```markdown
# MCP Runtime Architecture

CodeRunner-AI has one production tool-call boundary:

1. MCP clients: internal agents and external clients.
2. MCP server: FastMCP transport server.
3. ToolRuntime: server-side execution engine behind the MCP server.

Internal agents must not call ToolRuntime directly in production. They use an MCP client adapter and cross MCP transport before tool execution.
```

- [ ] **Step 2: Add a table of tool surfaces**

Include:

| Canonical tool | MCP server exposed | Internal agent scope | External scope | External name |
|---|---:|---:|---|

Generate this table manually from `TOOL_CATALOG` and `EXTERNAL_TOOL_MAP`.

- [ ] **Step 3: Document scope state**

State:

- Internal `agent_host` identity is authenticated over MCP transport.
- External `external_client` must pass descriptor `required_scopes`.
- Legacy tool-name scopes are normalized during API key creation/verification.

- [ ] **Step 4: Verify doc claims against source**

Run:

```powershell
rg "agent_host|external_client|required_scopes|EXTERNAL_TOOL_MAP|TOOL_CATALOG" docs app agents core mcp_gateway tools
```

Expected: docs use the same names as code.

---

### Task 11: Runtime And Docker Verification

**Files:**

- Modify if needed: `compose.yaml`
- Modify if needed: `docker/Dockerfile.agent_host`
- Test: `tests/test_agent_host_integration.py`

This project has previously diverged between source and containers. Do not mark MCP repaired without runtime checks.

- [ ] **Step 1: Run source tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_mcp_client_boundary.py tests/test_mcp_gateway_catalog_contract.py tests/test_mcp_gateway*.py tests/test_tool_protocol.py -q
```

Expected: all pass.

- [ ] **Step 2: Check Docker build contents**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_host_integration.py -q
```

Expected: image/package-copy regression tests pass.

- [ ] **Step 3: Rebuild services**

```powershell
docker compose build web agent_host mcp_server
docker compose up -d web agent_host mcp_server
docker compose ps
```

Expected:

- `web` healthy or running.
- `agent_host` healthy or running.
- `mcp_server` healthy or running.

- [ ] **Step 4: Check logs**

```powershell
docker logs educode_web --tail 100
docker logs educode_agent_host --tail 100
docker logs educode_mcp_server --tail 100
```

Expected:

- No `ModuleNotFoundError`.
- No missing `app`, `mcp_gateway`, or `tools.protocol` imports.
- MCP gateway logs show registered tool count.

- [ ] **Step 5: External MCP smoke**

Use a valid API key with `knowledge:read` only:

- `search_knowledge` should pass.
- `get_problem_detail` should fail with `MCP_SCOPE_DENIED`.

Use a key with `problem:read`:

- `get_problem_detail` should pass.

Use a key without auth:

- all tools should return `MCP_AUTH_REQUIRED`.

---

## 6. Acceptance Checklist

The repair is complete only when every item below is true:

- [x] `agents/base.py` no longer calls `ToolRuntime` directly for production tool execution. (execution goes through `MCPToolClient`; remaining `get_tool_runtime` uses in `base.py` are read-only `list_tools()` schema discovery, not execution)
- [x] `mcp_gateway` external calls use `actor_type="external_client"`. (`call_via_runtime`, `middleware/core.py`)
- [x] External API key scopes are canonical descriptor scopes, not legacy tool names. (`mcp_gateway/scopes.py` normalize-on-read/write)
- [x] `required_scopes` affect external calls in tests and smoke checks. (`tests/test_mcp_gateway_scope_enforcement.py`; live smoke still pending a real gateway run)
- [x] RBAC semantics for `external_client` are explicitly tested: role overrides still enforced, and scope-only tools are a documented, deliberate choice. (`tests/test_mcp_gateway_external_rbac.py`)
- [x] Legacy scopes are handled by normalize-on-read/write; no batch migration is claimed that isn't built.
- [x] Per-request or per-session auth is the production default; startup `MCP_API_KEY` is development-only. (`__main__.py` + `_resolve_request_caller`)
- [x] Every `TOOL_CATALOG` entry is mapped and registered on the MCP server. (15/15, contract test enforces equality)
- [x] External mapping lives in one module. (`mcp_gateway/tool_map.py`)
- [x] `EXPECTED_TOOL_COUNT` cannot silently drift. (`create_mcp_server()` raises on mismatch)
- [x] Process-global identity is removed or documented as development-only. (per-request `contextvars`; startup key is dev stdio only)
- [x] Gateway auth is per request or per session. (`resolve_caller_from_bearer` per request)
- [x] `check_approval` is catalog-backed as `coderunner.approval.check`.
- [x] Docs clearly distinguish MCP client, MCP server, and server-internal ToolRuntime. (`docs/MCP_RUNTIME_ARCHITECTURE.md`)
- [x] Full pytest suite passes. (MCP + agent suites green)
- [ ] Docker runtime smoke passes. (**not yet run** — requires `docker compose build/up` + the §5 Task 11 Step 3-5 manual MCP smoke; cannot be executed from the source checkout alone)
- [x] `agents/base.py` uses an MCP client adapter for tool execution. (`get_mcp_tool_client().call_tool()`)
- [x] Production agent calls cross MCP transport before tool execution. (default `MCP_AGENT_TRANSPORT=streamable-http`; gateway authenticates the internal token as `agent_host` via `resolve_caller_from_bearer`. Server-side resolution unit-tested in `tests/test_mcp_gateway_internal_auth.py`; an end-to-end two-container transport smoke is still pending the Docker run above)
- [x] `bootstrap_tool_runtime()` runs in the MCP server process, not as the agent production call path. (worker only bootstraps for the in-process dev client)
- [x] No gateway-native tools remain outside the catalog. (`GATEWAY_NATIVE_TOOLS` removed)

---

## 7. Recommended Commit Order

1. `test: add mcp gateway catalog contract`
2. `refactor: centralize external mcp tool mapping`
3. `fix: enforce external mcp scopes`
4. `fix: normalize mcp api key scopes`
5. `fix: isolate mcp gateway caller identity`
6. `feat: route internal agents through mcp client transport`
7. `feat: expose all catalog tools through mcp server`
8. `feat: move approval polling into tool catalog`
9. `docs: clarify mcp native runtime architecture`
10. `test: add docker/runtime mcp smoke coverage`

Keep each commit separately reversible. Do not combine scope enforcement with per-connection auth; failures in either area are easier to diagnose when isolated.

---

## 8. Final Positioning

After this repair, the project should be described as:

> CodeRunner-AI is an MCP-native teaching agent system. Internal agents and external clients call tools through the MCP server; the server uses ToolRuntime internally for canonical descriptors, policy checks, schema validation, audit, approval flow, and local implementation dispatch.

It should not be described as:

> Agents call ToolRuntime directly and the MCP server is only an optional external gateway.

That direct-call design is the current defect this plan removes.
