"""MCP tool wrappers for high-risk write operations — Human Gate approval flow."""

import json

from mcp.server import FastMCP

from mcp_gateway.middleware import (
    _guarded,
    call_via_runtime,
    get_caller_info,
)
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP


def register_write_tools(mcp: FastMCP):

    @mcp.tool(
        name="execute_code",
        description=(
            "Execute code in a sandboxed environment. This is a HIGH-RISK "
            "operation that requires teacher approval before execution. "
            "Returns an approval_id — use check_approval to poll for the result."
        ),
    )
    def execute_code(
        code: str, language: str = "python", stdin_text: str = ""
    ) -> str:
        return _guarded(lambda: call_via_runtime(
            EXTERNAL_TOOL_MAP["execute_code"],
            {"code": code, "language": language, "stdin_text": stdin_text},
        ))

    @mcp.tool(
        name="save_generated_problem",
        description=(
            "Save an AI-generated problem as a draft for teacher review. "
            "This is a HIGH-RISK operation that requires teacher approval. "
            "Returns an approval_id — use check_approval to poll for the result."
        ),
    )
    def save_generated_problem(question_data: str) -> str:
        try:
            parsed = json.loads(question_data)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "ok": False,
                "error": {
                    "code": "MCP_ARGUMENT_INVALID",
                    "message": "question_data must be valid JSON string",
                    "retryable": False,
                },
            })

        def _call():
            caller = get_caller_info() or {}
            return call_via_runtime(
                EXTERNAL_TOOL_MAP["save_generated_problem"],
                {"question_data": parsed, "teacher_id": caller.get("user_id", 0)},
            )

        return _guarded(_call)

    @mcp.tool(
        name="check_approval",
        description=(
            "Check the status of a pending tool approval and retrieve the "
            "result if approved. Returns: pending, approved (with result), "
            "rejected (with reason), or expired."
        ),
    )
    def check_approval(approval_id: str) -> str:
        return _guarded(lambda: call_via_runtime(
            EXTERNAL_TOOL_MAP["check_approval"],
            {"approval_id": approval_id},
        ))
