"""MCP tool wrappers for high-risk write operations — Human Gate approval flow."""

import json

from mcp.server import FastMCP

from core.db.session import get_session
from mcp_gateway.middleware import (
    _guarded,
    call_via_runtime,
    get_caller_info,
)


def _execute_approved_tool(approval, session) -> dict:
    tool_name = approval.tool_name
    tool_args = approval.tool_args or {}

    if tool_name in {"execute_code", "coderunner.code.execute"}:
        from tools.code.executor import execute_code_impl
        return execute_code_impl(
            code=tool_args.get("code", ""),
            language=tool_args.get("language", "python"),
            stdin_text=tool_args.get("stdin_text", ""),
        )
    elif tool_name in {"save_generated_problem", "coderunner.problem.save_generated"}:
        from tools.problems.write import save_generated_problem_impl
        return save_generated_problem_impl(
            question_data=tool_args.get("question_data", {}),
            teacher_id=tool_args.get("teacher_id") or approval.user_id,
            session=session,
        )
    else:
        return {"error": f"Unknown high-risk tool: {tool_name}"}


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
            "coderunner.code.execute",
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

        caller = get_caller_info() or {}
        return _guarded(lambda: call_via_runtime(
            "coderunner.problem.save_generated",
            {"question_data": parsed, "teacher_id": caller.get("user_id", 0)},
        ))

    @mcp.tool(
        name="check_approval",
        description=(
            "Check the status of a pending tool approval and retrieve the "
            "result if approved. Returns: pending, approved (with result), "
            "rejected (with reason), or expired."
        ),
    )
    def check_approval(approval_id: str) -> str:
        args = {"approval_id": approval_id}

        from core.db.models.mcp_approval import McpToolApproval

        def _check():
            session = get_session()
            try:
                approval = session.get(McpToolApproval, approval_id)
                if not approval:
                    return json.dumps({
                        "ok": False,
                        "error": {
                            "code": "MCP_TOOL_NOT_FOUND",
                            "message": "Approval not found",
                            "retryable": False,
                        },
                    })

                approval.check_expiration()

                if approval.status == "approved":
                    if approval.result is None:
                        result = _execute_approved_tool(approval, session)
                        approval.result = result
                        approval.status = "executed"
                        session.commit()
                    return json.dumps({
                        "status": "executed",
                        "result": approval.result,
                    }, ensure_ascii=False, default=str)

                elif approval.status == "executed":
                    return json.dumps({
                        "status": "executed",
                        "result": approval.result,
                    }, ensure_ascii=False, default=str)

                elif approval.status == "rejected":
                    session.commit()
                    return json.dumps({
                        "status": "rejected",
                        "reason": approval.review_notes or "",
                    })

                elif approval.status == "expired":
                    session.commit()
                    return json.dumps({
                        "status": "expired",
                        "message": "审批已超时。请重新发起工具调用。",
                    })

                session.commit()
                return json.dumps({
                    "status": "pending",
                    "message": "等待教师审批",
                })
            finally:
                session.close()

        return _guarded(_check)
