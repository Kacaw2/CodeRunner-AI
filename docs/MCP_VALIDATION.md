# MCP Validation Suite

> 最后更新: 2026-05-30

The MCP boundary verifies four things: **what tools are exposed**, **who can
call them**, **whether every call goes through the unified security pipeline**,
and **whether failure / audit / human-approval are stable and traceable**.

## Fast suite (CI entry)

Run on every PR that touches `mcp_gateway/`, `tools/protocol/`, `core/auth/`,
`core/definitions.py`, or `evals/mcp/`:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_mcp_gateway.py `
  tests/test_mcp_gateway_catalog_contract.py `
  tests/test_mcp_permission_matrix.py `
  tests/test_mcp_gateway_scope_enforcement.py `
  tests/test_mcp_gateway_external_rbac.py `
  tests/test_mcp_gateway_internal_auth.py `
  tests/test_mcp_internal_token.py `
  tests/test_mcp_gateway_human_gate.py `
  tests/test_agent_host_scope_enforcement.py `
  tests/test_agent_scopes.py `
  -q
```

Shorthand (catches anything named to match):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_* tests/test_agent_*scope* -q
```

## What each area maps to

| # | Area | Covered by |
|---|------|-----------|
| 1 | **Tool contract** — exposed tools == catalog, no drift, codegen fresh, no identity leakage | `test_mcp_gateway_catalog_contract.py` |
| 1 | **Schema completeness** — input/output schema, risk level, canonical scopes, HIGH⇒approval | `test_mcp_gateway_catalog_contract.py::test_descriptor_is_complete` / `test_high_risk_tools_require_approval` |
| 2 | **Identity auth** — signed internal token; expired / tampered / wrong-audience / forged-header rejected | `test_mcp_internal_token.py`, `test_mcp_gateway_internal_auth.py` |
| 3 | **Permission matrix** — external/internal allow & deny grid | `test_mcp_permission_matrix.py` + `evals/mcp/permission_matrix.yaml` |
| 4 | **Scope / RBAC** — scope gate + role override + per-agent allowlist | `test_mcp_gateway_scope_enforcement.py`, `test_mcp_gateway_external_rbac.py`, `test_agent_host_scope_enforcement.py`, `test_agent_scopes.py` |
| 5 | **Risk / human gate** — HIGH risk never executes directly | `test_mcp_gateway_human_gate.py`, matrix `*_requires_approval` rows |

## The permission matrix

`evals/mcp/permission_matrix.yaml` is the authorization oracle. Each row is one
decision run through the real guard pipeline (RBAC → scope → risk) in
`tools/protocol/policies/guard.py`.

Row fields: `id`, `caller_type` (`external_client` | `agent_host`), `role`,
`agent_type`, `scopes` (a list, `AGENT_MINIMAL`, or null), `tool` (canonical
name), `expected` (`ok` or an `MCP_*` code).

**Workflow: add a tool → add rows.** `test_matrix_covers_every_catalog_tool`
fails if any catalog tool has no row, so coverage can't silently rot.

### Decision-order caveat

RBAC runs **before** scope. A role-restricted tool returns
`MCP_PERMISSION_DENIED` even when the scope is also missing — the matrix encodes
the real observed code, not the idealized one. For a tool with a role override,
the per-agent allowlist is skipped (role decides); for a tool without one, the
allowlist gates internal agents and scope gates everyone.

## Error envelope

All guard rejections share one shape:

```json
{ "ok": false, "error": { "code": "MCP_SCOPE_DENIED", "message": "...", "retryable": false }, "trace_id": "..." }
```

Codes: `MCP_AUTH_REQUIRED`, `MCP_PERMISSION_DENIED`, `MCP_SCOPE_DENIED`,
`MCP_RATE_LIMITED`, `MCP_APPROVAL_REQUIRED` / `_PENDING` / `_REJECTED`,
`MCP_TOOL_NOT_FOUND`, `MCP_SCHEMA_INVALID`, `MCP_ARGUMENT_INVALID`,
`MCP_TRANSPORT_UNAVAILABLE`, `MCP_TOOL_TIMEOUT`, `MCP_INTERNAL_ERROR`.

## Not yet in the MVP

Deferred until needed: schema-arg rejection grid (`MCP_ARGUMENT_INVALID`),
audit/trace redaction tests, explicit failure-mode tests (transport timeout,
runtime not bootstrapped, audit-write failure → fail-closed), and a YAML-driven
eval runner. The pytest fast suite is the single CI entry for now.
