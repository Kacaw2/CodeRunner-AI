"""MCP tool wrapper for student summary operations (medium risk — sanitized output)."""

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP


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
        return _guarded(lambda: call_via_runtime(
            EXTERNAL_TOOL_MAP["get_student_summary"],
            {"student_id": student_id},
        ))
