"""MCP exception hierarchy."""

from __future__ import annotations

from .codes import MCPErrorCode


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
