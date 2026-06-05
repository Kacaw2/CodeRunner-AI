"""ToolRuntime — the sole entry point for agents and workflows to call tools.

All tool invocations go through `ToolRuntime.call()`.
No agent or workflow may import or execute tools directly.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from core.auth.context import CallerContext
from tools.protocol.errors import (
    MCPError,
    MCPToolNotFound,
    MCPApprovalRequired,
    MCPInternalError,
    MCPArgumentInvalid,
    MCPSchemaInvalid,
)
from core.observability.audit import AuditEntry, emit_audit, log_tool_call
from tools.protocol.policies.guard import run_guard
from tools.protocol.registry import ToolRegistry, get_registry
from tools.protocol.schemas.descriptors import ToolDescriptor
from tools.protocol.transports.inproc import LocalTransport

logger = logging.getLogger(__name__)

_GLOBAL_RUNTIME: ToolRuntime | None = None

_TRUTHY = {"1", "true", "yes", "on"}


def _output_schema_enforced() -> bool:
    """Read MCP_OUTPUT_SCHEMA_ENFORCE at call time so the toggle is live."""
    import os
    return os.environ.get("MCP_OUTPUT_SCHEMA_ENFORCE", "").strip().lower() in _TRUTHY


@dataclass
class ToolCallContext:
    caller: CallerContext
    tool_call_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    granted_scopes: list[str] | None = None


@dataclass
class ToolResult:
    ok: bool
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    trace_id: str = ""
    tool_call_id: str = ""
    latency_ms: int = 0
    status: str = "success"
    approval_id: str = ""
    resume_token: str = ""

    def to_envelope(self) -> dict[str, Any]:
        env: dict[str, Any] = {
            "ok": self.ok,
            "tool": self.tool,
            "trace_id": self.trace_id,
            "tool_call_id": self.tool_call_id,
            "latency_ms": self.latency_ms,
        }
        if self.ok:
            env["data"] = self.data
        else:
            env["error"] = self.error or {}
            env["status"] = self.status
            if self.approval_id:
                env["approval_id"] = self.approval_id
                env["resume_token"] = self.resume_token
        return env


class ToolRuntime:
    """Agent/Workflow sole tool invocation interface."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        transport: LocalTransport | None = None,
        approval_store: Any | None = None,
    ) -> None:
        self._registry = registry or get_registry()
        self._transport = transport or LocalTransport()
        self._approval_store = approval_store

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def transport(self) -> LocalTransport:
        return self._transport

    def list_tools(
        self,
        *,
        names: Sequence[str] | None = None,
    ) -> list[ToolDescriptor]:
        return self._registry.list_tools(names=names)

    async def call(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """Execute a tool call through the full MCP pipeline."""
        caller = context.caller
        trace_id = caller.trace_id
        tool_call_id = context.tool_call_id
        start = time.monotonic()

        descriptor = self._registry.get(tool_name)
        if descriptor is None:
            return self._error_result(
                tool_name, MCPToolNotFound(f"Tool '{tool_name}' not found", trace_id=trace_id),
                tool_call_id=tool_call_id,
            )

        try:
            self._validate_input(descriptor, args, trace_id)
        except MCPError as exc:
            self._emit(descriptor, caller, tool_call_id, start,
                       status="error", error_code=exc.code.value, args=args)
            return self._error_result(tool_name, exc, tool_call_id=tool_call_id)

        guard = run_guard(descriptor, caller, granted_scopes=context.granted_scopes)
        if guard.rejected:
            self._emit(descriptor, caller, tool_call_id, start,
                       status="rejected", error_code=guard.error.code.value if guard.error else "",
                       args=args)
            if isinstance(guard.error, MCPApprovalRequired):
                approval_id = guard.error.approval_id
                if self._approval_store is not None:
                    approval_id = self._approval_store.create(descriptor, caller, args)
                return ToolResult(
                    ok=False, tool=tool_name, trace_id=trace_id,
                    tool_call_id=tool_call_id,
                    status="approval_required",
                    approval_id=approval_id,
                    resume_token=guard.error.resume_token,
                    error={"code": guard.error.code.value, "message": str(guard.error), "retryable": False},
                    latency_ms=self._elapsed(start),
                )
            return self._error_result(tool_name, guard.error, tool_call_id=tool_call_id)

        try:
            sanitized = self._sanitize_args(args, caller)
            raw = await self._call_with_retry(descriptor, tool_name, sanitized)
            elapsed = self._elapsed(start)

            self._validate_output(descriptor, raw, trace_id)
            self._emit(descriptor, caller, tool_call_id, start, status="success", args=args)

            return ToolResult(
                ok=True,
                tool=tool_name,
                data=raw,
                trace_id=trace_id,
                tool_call_id=tool_call_id,
                latency_ms=elapsed,
            )

        except MCPError as exc:
            self._emit(descriptor, caller, tool_call_id, start,
                       status="error", error_code=exc.code.value, args=args)
            return self._error_result(tool_name, exc, tool_call_id=tool_call_id)
        except Exception as exc:
            logger.exception("tool=%s unexpected error", tool_name)
            mcp_err = MCPInternalError(str(exc), trace_id=trace_id)
            self._emit(descriptor, caller, tool_call_id, start,
                       status="error", error_code=mcp_err.code.value, args=args)
            return self._error_result(tool_name, mcp_err, tool_call_id=tool_call_id)

    def call_sync(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """Synchronous wrapper for environments without an event loop."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.call(tool_name, args, context))
                return future.result()
        return asyncio.run(self.call(tool_name, args, context))

    async def _call_with_retry(
        self,
        descriptor: ToolDescriptor,
        tool_name: str,
        sanitized: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the transport call with bounded retry on *retryable* errors only.

        ``max_attempts`` is the number of retries after the initial attempt, so
        ``max_attempts=0`` (today's default for every descriptor) makes exactly
        one attempt — the wiring is behavior-preserving until a tool opts in.
        Only ``retryable`` MCP errors (rate-limit / transport / timeout) are
        retried; a schema or permission fault is not transient and propagates
        immediately. Wraps the transport execution alone — guard, input and
        output validation stay outside the retry loop.
        """
        import asyncio

        policy = descriptor.retry_policy
        attempt = 0
        while True:
            try:
                return await self._transport.call(
                    tool_name, sanitized, timeout_ms=descriptor.timeout_ms
                )
            except MCPError as exc:
                if exc.code.retryable and attempt < policy.max_attempts:
                    attempt += 1
                    if policy.backoff_ms > 0:
                        await asyncio.sleep(policy.backoff_ms / 1000)
                    continue
                raise

    @staticmethod
    def _sanitize_args(args: dict[str, Any], caller: CallerContext) -> dict[str, Any]:
        """Strip identity fields that the LLM should not control."""
        sanitized = dict(args)
        for key in ("user_id", "user_role", "role", "teacher_id", "student_id"):
            sanitized.pop(key, None)

        if caller.role == "student":
            sanitized["student_id"] = caller.user_id
        elif caller.role == "teacher":
            sanitized["teacher_id"] = caller.user_id
        sanitized["_caller_user_id"] = caller.user_id
        sanitized["_caller_role"] = caller.role
        sanitized["_caller_agent_type"] = caller.agent_type
        return sanitized

    @staticmethod
    def _validate_input(
        descriptor: ToolDescriptor,
        args: dict[str, Any],
        trace_id: str,
    ) -> None:
        if not descriptor.input_schema:
            return
        try:
            import jsonschema
            jsonschema.validate(args, descriptor.input_schema)
        except jsonschema.ValidationError as exc:
            raise MCPArgumentInvalid(exc.message, trace_id=trace_id) from exc

    @staticmethod
    def _validate_output(
        descriptor: ToolDescriptor,
        result: Any,
        trace_id: str,
    ) -> None:
        """output_schema check, warn-only by default (schema 先松后紧).

        Default behavior logs a warning on mismatch but never fails the call.
        Setting ``MCP_OUTPUT_SCHEMA_ENFORCE`` truthy flips a mismatch into an
        ``MCPSchemaInvalid`` error — a single ops decision once the catalog's
        schemas are trusted, not a code change. The default stays off so that
        completing schemas cannot turn a previously-working tool into an error.
        """
        if not descriptor.output_schema:
            return
        try:
            import jsonschema
            jsonschema.validate(result, descriptor.output_schema)
        except jsonschema.ValidationError as exc:
            if _output_schema_enforced():
                raise MCPSchemaInvalid(
                    f"output_schema mismatch for tool '{descriptor.name}': {exc.message}",
                    trace_id=trace_id,
                ) from exc
            logger.warning(
                "output_schema mismatch tool=%s trace_id=%s: %s",
                descriptor.name, trace_id, exc.message,
            )
        except MCPSchemaInvalid:
            raise
        except Exception:  # noqa: BLE001 — observability must never block a tool result
            logger.exception("output_schema validation crashed tool=%s", descriptor.name)

    def _emit(
        self,
        tool: ToolDescriptor,
        caller: CallerContext,
        tool_call_id: str,
        start: float,
        *,
        status: str = "success",
        error_code: str = "",
        args: dict[str, Any] | None = None,
    ) -> None:
        latency_ms = self._elapsed(start)
        emit_audit(AuditEntry(
            trace_id=caller.trace_id,
            task_id=caller.task_id or "",
            conversation_id=caller.conversation_id or "",
            agent_type=caller.agent_type,
            tool_call_id=tool_call_id,
            tool_name=tool.name,
            server_name=tool.server,
            user_id=caller.user_id,
            role=caller.role,
            status=status,
            latency_ms=latency_ms,
            error_code=error_code,
        ))
        # Persist to the McpAuditLog table so audit survives beyond the log
        # stream. Best-effort: log_tool_call swallows and rolls back on failure,
        # so a tool result is never blocked by an audit write.
        log_tool_call(
            api_key_id=getattr(caller, "api_key_id", None),
            user_id=caller.user_id,
            tool_name=tool.name,
            tool_args=self._audit_args(args),
            status=status,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _audit_args(args: dict[str, Any] | None) -> dict[str, Any] | None:
        """Drop injected caller-identity fields before persisting tool args."""
        if not args:
            return None
        return {k: v for k, v in args.items() if not k.startswith("_caller_")}

    @staticmethod
    def _elapsed(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def _error_result(
        tool_name: str,
        error: MCPError | None,
        *,
        tool_call_id: str = "",
    ) -> ToolResult:
        if error is None:
            error = MCPInternalError("Unknown error")
        return ToolResult(
            ok=False,
            tool=tool_name,
            trace_id=error.trace_id,
            tool_call_id=tool_call_id,
            error={"code": error.code.value, "message": str(error), "retryable": error.code.retryable},
            status=error.code.value,
        )


def get_tool_runtime() -> ToolRuntime:
    global _GLOBAL_RUNTIME
    if _GLOBAL_RUNTIME is None:
        _GLOBAL_RUNTIME = ToolRuntime()
    return _GLOBAL_RUNTIME


def set_tool_runtime(runtime: ToolRuntime) -> None:
    global _GLOBAL_RUNTIME
    _GLOBAL_RUNTIME = runtime


def reset_tool_runtime() -> None:
    global _GLOBAL_RUNTIME
    _GLOBAL_RUNTIME = None
