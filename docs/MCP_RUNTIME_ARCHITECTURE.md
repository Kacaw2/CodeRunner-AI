# MCP Runtime Architecture

> 最后更新: 2026-05-30

CodeRunner-AI has **one** production tool-call boundary. Both internal agents
and external API-key clients reach tools the same way: across MCP transport,
into the FastMCP gateway, and only then into `ToolRuntime`.

```text
1. MCP clients   — internal agents AND external API-key clients.
2. MCP server    — FastMCP transport server (mcp_gateway).
3. ToolRuntime   — server-side execution engine BEHIND the MCP server.
```

Internal agents must **not** call `ToolRuntime` directly in production. They use
an MCP client adapter (`mcp_gateway/client.py`) and cross MCP transport before
any tool executes. `bootstrap_tool_runtime()` runs inside the MCP server
process, not on the agent production call path.

---

## 1. Call Paths

### 1.1 Internal Agent Path

```text
Agent (agents/base.py)
  -> MCPToolClient (mcp_gateway/client.py)
  -> MCP transport (streamable-http in Docker/runtime; stdio for local dev)
  -> mcp_gateway FastMCP server
  -> ToolRuntime.call_sync(actor_type="agent_host", agent_type=...)
  -> guard: RBAC + scope + risk + audit + schema validation
  -> LocalTransport implementation handler
  -> app/service implementation
```

The internal `agent_host` identity is **authenticated over MCP transport**, not
implied by an in-process Python call. The agent host mints a short-lived,
EdDSA-signed capability token per call (`mcp_gateway/internal_auth.py`) carrying
the user_id / role / agent_type / minimal scopes; the gateway verifies the
signature with its public key and builds the caller from the *signed claims*,
never from request headers. The agent cannot self-elevate its role, and there is
no scope bypass: `agent_host` callers carry the minimal scopes their tools
require (`scopes_for_agent`) and are scope-enforced like everyone else.

### 1.2 External MCP Client Path

```text
External MCP client
  -> FastMCP transport (per-request/per-session auth)
  -> verify_api_key() -> set_caller_info(scopes=...)
  -> mcp_gateway catalog-backed wrapper (mcp_gateway/generated_tools.py)
  -> call_via_runtime() -> ToolRuntime.call_sync(actor_type="external_client", granted_scopes=...)
  -> same guard/runtime/implementation handlers as agent calls
```

External callers always use `actor_type="external_client"` and must pass the
descriptor's `required_scopes`. They never use `agent_host`.

---

## 2. Tool Surface

Every `TOOL_CATALOG` entry is mapped in `mcp_gateway/tool_map.py` and registered
on the MCP server — tool *listing* is no longer a privacy boundary. Access is
controlled by `required_scopes` (`tools/protocol/schemas/catalog.py`), role
overrides (`tools/protocol/policies/rbac.py` `_ROLE_OVERRIDES`), and approval
policy.

| Canonical tool | External name | Required scope | Role override | Risk / approval |
|---|---|---|---|---|
| `coderunner.problem.get_detail` | `get_problem_detail` | `problem:read` | — (scope only) | LOW |
| `coderunner.submission.list_for_student` | `list_student_submissions` | `submission:read` | — (scope only) | LOW |
| `coderunner.submission.get_detail` | `get_submission_detail` | `submission:read` | — (scope only) | LOW |
| `coderunner.student.get_summary` | `get_student_summary` | `student:read` | teacher, admin | MEDIUM |
| `coderunner.problem.save_generated` | `save_generated_problem` | `problem:write` | teacher, admin | HIGH / teacher approval |
| `coderunner.code.execute` | `execute_code` | `code:execute` | student, teacher, admin | HIGH / teacher approval |
| `coderunner.knowledge.search` | `search_knowledge` | `knowledge:read` | — (scope only) | LOW |
| `coderunner.knowledge.search_similar_problems` | `search_similar_problems` | `knowledge:read` | — (scope only) | LOW |
| `coderunner.knowledge.search_error_patterns` | `search_error_patterns` | `knowledge:read` | — (scope only) | LOW |
| `coderunner.analytics.student_activity` | `get_student_activity` | `analytics:read` | — (scope only) | LOW |
| `coderunner.analytics.student_stats` | `get_student_stats` | `analytics:read` | teacher, admin | LOW |
| `coderunner.analytics.class_statistics` | `get_class_statistics` | `analytics:read` | teacher, admin | LOW |
| `coderunner.analytics.problem_difficulty` | `get_problem_difficulty_stats` | `analytics:read` | teacher, admin | LOW |
| `coderunner.trace.get_agent_trace` | `get_agent_trace` | `trace:read` | teacher, admin | MEDIUM |
| `coderunner.approval.check` | `check_approval` | — (caller-bound) | — | LOW |

`coderunner.approval.check` carries no `required_scopes` by design: it is the
post-approval polling loop, callable by whoever initiated the gated call.
Gating it on a scope outside the canonical vocabulary (§3) would break external
clients. It is now a full catalog tool — no gateway-native exception remains.

---

## 3. Scope Model

Canonical scope vocabulary (descriptor `required_scopes` values):

`problem:read`, `problem:write`, `submission:read`, `student:read`,
`code:execute`, `knowledge:read`, `analytics:read`, `trace:read`.

- **Internal `agent_host`** identity is authenticated over MCP transport and
  carries the minimal scopes its tools require (`scopes_for_agent`); it is
  scope-enforced like every other actor (RBAC and the per-agent allowlist also
  apply). There is no scope bypass.
- **External `external_client`** must pass the descriptor `required_scopes`.
  Missing scope → `MCP_SCOPE_DENIED`.
- **Legacy tool-name scopes** (e.g. `search_knowledge`) are normalized to
  canonical scopes by `mcp_gateway/scopes.py` `normalize_scopes()`, applied both
  at API-key creation (`app/api/v1/mcp_keys.py`) and at verification time
  (`mcp_gateway/middleware/auth.py`). This is normalize-on-read/write — there is
  **no** batch migration.

### RBAC semantics for `external_client`

`_ROLE_OVERRIDES` gates role-restricted tools for every actor (so a student API
key cannot reach `get_student_summary` on scope alone — that returns
`MCP_PERMISSION_DENIED`). The per-`agent_type` allowlist applies only to
internal `agent_host` callers (`external_client` has `agent_type=""`, so that
branch is skipped). Tools with no role override are therefore gated by scope
alone — this is a **deliberate, tested** choice (see
`tests/test_mcp_gateway_external_rbac.py`), acceptable because external access is
scoped per API key.

---

## 4. Identity Isolation

`mcp_gateway/middleware/core.py` stores caller info in a `contextvars.ContextVar`
for per-request isolation. Production auth is per-request/per-session: every
request must authenticate independently via `Authorization: Bearer <mcp-api-key>`.
The startup `MCP_API_KEY` is **development-only**, active only when
`MCP_ALLOW_STARTUP_KEY_DEV_MODE=true`, and refuses non-local transports. Caller
info is cleared in a `finally` after each tool call so it cannot leak between
requests.

---

## 5. Vocabulary

| Term | Meaning | Not |
|---|---|---|
| `ToolRuntime` | Server-side execution engine behind the MCP server. | Agent-facing API or transport. |
| `TOOL_CATALOG` | Canonical descriptor source for every served tool. | A private internal-only list. |
| `mcp_gateway` | FastMCP server exposing catalog tools over transport. | Optional decoration around direct calls. |
| `agent_host` actor | Trusted internal caller identity carried over transport. | A reason to bypass transport. |
| `external_client` actor | Third-party MCP API-key caller over transport. | Internal agent identity. |
| `MCP client` | The interface agents use to invoke tools. | Direct Python `ToolRuntime` calls. |

> CodeRunner-AI is an MCP-native teaching agent system. Internal agents and
> external clients call tools through the MCP server; the server uses
> ToolRuntime internally for canonical descriptors, policy checks, schema
> validation, audit, approval flow, and local implementation dispatch.
