"""Agent lifecycle hooks (Phase 5).

Reliability checks live in in-process synchronous runtime code instead of
prompt instructions. Each hook subscribes to one or more lifecycle events and
fires in registration order. A ``deny`` result from a ``BEFORE_*`` hook blocks
the action (e.g. an undeclared tool call); ``AFTER_*`` hooks are observability
only and surface warnings without blocking.

Built-in hooks:
* :class:`ContractValidationHook` (BEFORE_AGENT_RUN) — warn-only input check.
* :class:`ToolAllowlistHook`       (BEFORE_TOOL_CALL) — blocks undeclared tools.
* :class:`OutputValidationHook`    (AFTER_AGENT_RUN)  — warn-only schema check;
  the single runtime path shared by graph and worker flows.
* :class:`TraceAuditHook`          (AFTER_TOOL_CALL/AFTER_AGENT_RUN) — audit log.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    BEFORE_AGENT_RUN = "before_agent_run"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    AFTER_AGENT_RUN = "after_agent_run"


@dataclass
class HookResult:
    """Outcome of one hook invocation (or an aggregated manager result)."""

    allowed: bool = True
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, *, warnings: list[str] | None = None, metadata: dict | None = None) -> "HookResult":
        return cls(allowed=True, warnings=list(warnings or []), metadata=dict(metadata or {}))

    @classmethod
    def deny(cls, error: str, *, warnings: list[str] | None = None,
             metadata: dict | None = None) -> "HookResult":
        return cls(allowed=False, error=error, warnings=list(warnings or []),
                   metadata=dict(metadata or {}))


@dataclass
class HookContext:
    """Data passed to a hook for a given lifecycle event.

    Fields not relevant to an event are left at their defaults (e.g.
    ``tool_call`` is only set for the tool-call events).
    """

    event: HookEvent
    agent_name: str
    state: dict
    tool_call: dict | None = None
    tool_result: Any = None
    final_response: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Hook(ABC):
    """Base class for a lifecycle hook.

    Subclasses declare a ``name`` and the set of ``events`` they handle, and
    implement :meth:`run`.
    """

    name: str = ""
    events: frozenset[HookEvent] = frozenset()

    @abstractmethod
    def run(self, ctx: HookContext) -> HookResult:
        ...


class HookManager:
    """Registry that fires hooks for a lifecycle event in registration order.

    Warnings from every fired hook are aggregated. The first ``deny`` from a
    ``BEFORE_*`` hook short-circuits the remaining hooks and is returned so the
    caller can block the action.
    """

    def __init__(self) -> None:
        self._hooks: list[Hook] = []

    def register(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def hooks_for(self, event: HookEvent) -> list[Hook]:
        return [h for h in self._hooks if event in h.events]

    def fire(self, ctx: HookContext) -> HookResult:
        aggregated = HookResult.ok()
        for hook in self._hooks:
            if ctx.event not in hook.events:
                continue
            try:
                result = hook.run(ctx)
            except Exception as exc:  # a hook must never break the agent loop
                logger.warning("Hook '%s' raised on %s: %s", hook.name, ctx.event, exc)
                continue
            aggregated.warnings.extend(result.warnings)
            aggregated.metadata.update(result.metadata)
            if not result.allowed:
                aggregated.allowed = False
                aggregated.error = result.error
                return aggregated
        return aggregated


# ── Built-in hooks ──────────────────────────────────────────────────


class ContractValidationHook(Hook):
    """Warn-only validation of the agent's input state (mirrors Phase 4.2)."""

    name = "contract_validation"
    events = frozenset({HookEvent.BEFORE_AGENT_RUN})

    def run(self, ctx: HookContext) -> HookResult:
        from ai.agents.contracts import validate_agent_input

        errors = validate_agent_input(ctx.agent_name, ctx.state)
        return HookResult.ok(warnings=list(errors))


class ToolAllowlistHook(Hook):
    """Block tool calls outside the agent's declared allowlist.

    Defense-in-depth: the LLM only receives schemas for allowed tools and MCP
    scopes enforce permissions server-side, but this hook denies an undeclared
    tool before it crosses the MCP client boundary.
    """

    name = "tool_allowlist"
    events = frozenset({HookEvent.BEFORE_TOOL_CALL})

    def run(self, ctx: HookContext) -> HookResult:
        from core.definitions import allowed_tools_for

        tool_name = (ctx.tool_call or {}).get("name", "")
        allowed = allowed_tools_for(ctx.agent_name)
        if tool_name in allowed:
            return HookResult.ok()
        return HookResult.deny(
            f"Tool '{tool_name}' is not in the allowlist for agent '{ctx.agent_name}'",
            metadata={"blocked_tool": tool_name},
        )


class OutputValidationHook(Hook):
    """Warn-only schema validation of an agent's final response.

    Single runtime path for sync and worker flows. Free-text agents and
    non-JSON responses are skipped. The validation outcome is exposed in
    ``metadata['output_valid']`` so the graph can decide whether to retry.
    """

    name = "output_validation"
    events = frozenset({HookEvent.AFTER_AGENT_RUN})

    def run(self, ctx: HookContext) -> HookResult:
        from core.definitions import AGENT_DEFINITIONS

        defn = AGENT_DEFINITIONS.get(ctx.agent_name)
        if defn is None or defn.output_format == "free_text":
            return HookResult.ok()

        final_response = ctx.final_response or ""
        if not final_response:
            return HookResult.ok()

        from core.schemas import extract_json, validate_agent_output

        parsed = extract_json(final_response)
        if not parsed:
            # No JSON to validate (e.g. a plain error message); not a schema
            # violation we can assert on.
            return HookResult.ok()

        valid, error_msg = validate_agent_output(ctx.agent_name, parsed)
        if valid:
            return HookResult.ok(metadata={"output_valid": True})
        return HookResult.ok(
            warnings=[f"output schema validation failed: {error_msg}"],
            metadata={"output_valid": False, "validation_error": error_msg},
        )


class TraceAuditHook(Hook):
    """Audit-log tool failures and limit-exceeded terminal states."""

    name = "trace_audit"
    events = frozenset({HookEvent.AFTER_TOOL_CALL, HookEvent.AFTER_AGENT_RUN})

    def run(self, ctx: HookContext) -> HookResult:
        if ctx.event is HookEvent.AFTER_TOOL_CALL:
            envelope = ctx.tool_result or {}
            if isinstance(envelope, dict) and not envelope.get("ok"):
                err = (envelope.get("error") or {}) if isinstance(envelope, dict) else {}
                logger.info(
                    "tool call failed (agent=%s, tool=%s): %s",
                    ctx.agent_name,
                    (ctx.tool_call or {}).get("name", ""),
                    err.get("code", envelope.get("status", "unknown")),
                )
        return HookResult.ok()


# ── Default manager ─────────────────────────────────────────────────


def build_default_hook_manager() -> HookManager:
    mgr = HookManager()
    mgr.register(ContractValidationHook())
    mgr.register(ToolAllowlistHook())
    mgr.register(OutputValidationHook())
    mgr.register(TraceAuditHook())
    return mgr


_default_manager: HookManager | None = None


def get_hook_manager() -> HookManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = build_default_hook_manager()
    return _default_manager


def set_hook_manager(manager: HookManager | None) -> None:
    """Override the process-wide hook manager (test seam)."""
    global _default_manager
    _default_manager = manager


def reset_hook_manager() -> None:
    set_hook_manager(None)
