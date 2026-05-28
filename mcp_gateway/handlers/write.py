"""MCP tool wrappers for high-risk write operations — Human Gate approval flow."""

import json
import uuid

from mcp.server import FastMCP

from core.db.session import get_session
from mcp_gateway.middleware import (
    run_mcp_guard,
    get_caller_info,
    CODE_MAX_LENGTH,
    ALLOWED_LANGUAGES,
)


def _create_approval(tool_name: str, tool_args: dict, session) -> dict:
    from core.db.models.mcp_approval import McpToolApproval
    from app.core.timezone import now_china

    caller = get_caller_info() or {}
    approval_id = str(uuid.uuid4())
    approval = McpToolApproval(
        id=approval_id,
        api_key_id=caller.get("api_key_id"),
        user_id=caller.get("user_id"),
        tool_name=tool_name,
        tool_args=tool_args,
        risk_level="high",
        status="pending",
        expires_at=McpToolApproval.default_expiry(),
        created_at=now_china(),
    )
    session.add(approval)
    session.commit()
    return {"id": approval_id}


def _execute_approved_tool(approval, session) -> dict:
    tool_name = approval.tool_name
    tool_args = approval.tool_args or {}

    if tool_name == "execute_code":
        from tools.code.executor import execute_code_impl
        return execute_code_impl(
            code=tool_args.get("code", ""),
            language=tool_args.get("language", "python"),
            stdin_text=tool_args.get("stdin_text", ""),
        )
    elif tool_name == "save_generated_problem":
        from tools.problems.write import save_generated_problem_impl
        return save_generated_problem_impl(
            question_data=tool_args.get("question_data", {}),
            teacher_id=approval.user_id,
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
        args = {"code": code, "language": language, "stdin_text": stdin_text}
        guard = run_mcp_guard("execute_code", args)
        if guard.rejected:
            return guard.error_json

        if len(code) > CODE_MAX_LENGTH:
            return json.dumps({
                "error": f"Code exceeds maximum length ({CODE_MAX_LENGTH} chars)"
            })
        if language not in ALLOWED_LANGUAGES:
            return json.dumps({
                "error": f"Language '{language}' not allowed. Use: {sorted(ALLOWED_LANGUAGES)}"
            })

        session = get_session()
        try:
            info = _create_approval("execute_code", args, session)
            guard.record_success("execute_code", args)
            return json.dumps({
                "status": "approval_required",
                "approval_id": info["id"],
                "message": "代码执行需要审批，请教师在后台确认。",
            })
        except Exception as e:
            guard.record_error("execute_code", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()

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
            return json.dumps({"error": "question_data must be valid JSON string"})

        args = {"question_data": parsed}
        guard = run_mcp_guard("save_generated_problem", args)
        if guard.rejected:
            return guard.error_json

        session = get_session()
        try:
            info = _create_approval("save_generated_problem", args, session)
            guard.record_success("save_generated_problem", args)
            return json.dumps({
                "status": "approval_required",
                "approval_id": info["id"],
                "message": "题目保存需要审批，请教师在后台确认。",
            })
        except Exception as e:
            guard.record_error("save_generated_problem", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()

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
        guard = run_mcp_guard("check_approval", args)
        if guard.rejected:
            return guard.error_json

        from core.db.models.mcp_approval import McpToolApproval

        session = get_session()
        try:
            approval = session.get(McpToolApproval, approval_id)
            if not approval:
                guard.record_success("check_approval", args)
                return json.dumps({"error": "Approval not found"})

            approval.check_expiration()

            if approval.status == "approved":
                if approval.result is None:
                    result = _execute_approved_tool(approval, session)
                    approval.result = result
                    approval.status = "executed"
                    session.commit()
                guard.record_success("check_approval", args)
                return json.dumps({
                    "status": "executed",
                    "result": approval.result,
                }, ensure_ascii=False, default=str)

            elif approval.status == "executed":
                guard.record_success("check_approval", args)
                return json.dumps({
                    "status": "executed",
                    "result": approval.result,
                }, ensure_ascii=False, default=str)

            elif approval.status == "rejected":
                session.commit()
                guard.record_success("check_approval", args)
                return json.dumps({
                    "status": "rejected",
                    "reason": approval.review_notes or "",
                })

            elif approval.status == "expired":
                session.commit()
                guard.record_success("check_approval", args)
                return json.dumps({
                    "status": "expired",
                    "message": "审批已超时。请重新发起工具调用。",
                })

            else:
                session.commit()
                guard.record_success("check_approval", args)
                return json.dumps({
                    "status": "pending",
                    "message": "等待教师审批",
                })

        except Exception as e:
            guard.record_error("check_approval", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()
