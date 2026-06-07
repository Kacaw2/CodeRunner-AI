"""Tool protocol error codes and exception hierarchy.

Merged from former mcp/errors/{codes,exceptions}.py.
"""

from __future__ import annotations

from enum import Enum


class MCPErrorCode(str, Enum):
    AUTH_REQUIRED = "MCP_AUTH_REQUIRED"
    PERMISSION_DENIED = "MCP_PERMISSION_DENIED"
    SCOPE_DENIED = "MCP_SCOPE_DENIED"
    RATE_LIMITED = "MCP_RATE_LIMITED"
    APPROVAL_REQUIRED = "MCP_APPROVAL_REQUIRED"
    APPROVAL_PENDING = "MCP_APPROVAL_PENDING"
    APPROVAL_REJECTED = "MCP_APPROVAL_REJECTED"
    TOOL_NOT_FOUND = "MCP_TOOL_NOT_FOUND"
    SCHEMA_INVALID = "MCP_SCHEMA_INVALID"
    ARGUMENT_INVALID = "MCP_ARGUMENT_INVALID"
    TRANSPORT_UNAVAILABLE = "MCP_TRANSPORT_UNAVAILABLE"
    TOOL_TIMEOUT = "MCP_TOOL_TIMEOUT"
    INTERNAL_ERROR = "MCP_INTERNAL_ERROR"

    @property
    def retryable(self) -> bool:
        return self in _RETRYABLE

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self, 500)


_RETRYABLE = {
    MCPErrorCode.RATE_LIMITED,
    MCPErrorCode.TRANSPORT_UNAVAILABLE,
    MCPErrorCode.TOOL_TIMEOUT,
}

_HTTP_STATUS = {
    MCPErrorCode.AUTH_REQUIRED: 401,
    MCPErrorCode.PERMISSION_DENIED: 403,
    MCPErrorCode.SCOPE_DENIED: 403,
    MCPErrorCode.RATE_LIMITED: 429,
    MCPErrorCode.APPROVAL_REQUIRED: 202,
    MCPErrorCode.APPROVAL_PENDING: 202,
    MCPErrorCode.APPROVAL_REJECTED: 403,
    MCPErrorCode.TOOL_NOT_FOUND: 404,
    MCPErrorCode.SCHEMA_INVALID: 422,
    MCPErrorCode.ARGUMENT_INVALID: 422,
    MCPErrorCode.TRANSPORT_UNAVAILABLE: 503,
    MCPErrorCode.TOOL_TIMEOUT: 504,
    MCPErrorCode.INTERNAL_ERROR: 500,
}


class MCPError(Exception):
    code: MCPErrorCode = MCPErrorCode.INTERNAL_ERROR

    def __init__(self, message: str = "", *, trace_id: str = ""):
        super().__init__(message)
        self.trace_id = trace_id

    def to_envelope(self) -> dict:
        return {
            "ok": False,
            "error": {
                "code": self.code.value,
                "message": str(self),
                "retryable": self.code.retryable,
            },
            "trace_id": self.trace_id,
        }


class MCPAuthRequired(MCPError):
    code = MCPErrorCode.AUTH_REQUIRED


class MCPPermissionDenied(MCPError):
    code = MCPErrorCode.PERMISSION_DENIED


class MCPScopeDenied(MCPError):
    code = MCPErrorCode.SCOPE_DENIED


class MCPRateLimited(MCPError):
    code = MCPErrorCode.RATE_LIMITED


class MCPApprovalRequired(MCPError):
    code = MCPErrorCode.APPROVAL_REQUIRED

    def __init__(
        self,
        message: str = "",
        *,
        approval_id: str = "",
        resume_token: str = "",
        trace_id: str = "",
    ):
        super().__init__(message, trace_id=trace_id)
        self.approval_id = approval_id
        self.resume_token = resume_token

    def to_envelope(self) -> dict:
        env = super().to_envelope()
        env["approval_id"] = self.approval_id
        env["resume_token"] = self.resume_token
        return env


class MCPApprovalPending(MCPError):
    code = MCPErrorCode.APPROVAL_PENDING


class MCPApprovalRejected(MCPError):
    code = MCPErrorCode.APPROVAL_REJECTED


class MCPToolNotFound(MCPError):
    code = MCPErrorCode.TOOL_NOT_FOUND


class MCPSchemaInvalid(MCPError):
    code = MCPErrorCode.SCHEMA_INVALID


class MCPArgumentInvalid(MCPError):
    code = MCPErrorCode.ARGUMENT_INVALID


class MCPTransportUnavailable(MCPError):
    code = MCPErrorCode.TRANSPORT_UNAVAILABLE


class MCPToolTimeout(MCPError):
    code = MCPErrorCode.TOOL_TIMEOUT


class MCPInternalError(MCPError):
    code = MCPErrorCode.INTERNAL_ERROR
