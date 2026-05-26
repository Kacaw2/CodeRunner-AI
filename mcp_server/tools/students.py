"""MCP tool wrapper for student summary operations (medium risk — sanitized output)."""

import json

from mcp.server import FastMCP

from app.agents.tools.core.student_summary import get_student_summary_impl
from mcp_server.db import get_session
from mcp_server.middleware import run_mcp_guard
from mcp_server.sanitizer import sanitize_student_summary


def register_student_tools(mcp: FastMCP):
    @mcp.tool(
        name="get_student_summary",
        description=(
            "Get an aggregated learning summary for a student. "
            "Returns preferred language, weak/strong topics, submission "
            "counts, acceptance rate, and active days. "
            "No PII (username, email, raw code) is included."
        ),
    )
    def get_student_summary(student_id: int) -> str:
        args = {"student_id": student_id}
        guard = run_mcp_guard("get_student_summary", args)
        if guard.rejected:
            return guard.error_json
        session = get_session()
        try:
            raw = get_student_summary_impl(student_id, session=session)
            if "error" in raw:
                guard.record_success("get_student_summary", args)
                return json.dumps(raw, ensure_ascii=False)
            sanitized = sanitize_student_summary(
                student_id, raw["profile"], raw["stats"]
            )
            guard.record_success("get_student_summary", args)
            return json.dumps(sanitized, ensure_ascii=False)
        except Exception as e:
            guard.record_error("get_student_summary", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()
