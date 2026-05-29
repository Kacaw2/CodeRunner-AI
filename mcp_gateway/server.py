"""MCP Gateway entry point — tool registration and lifecycle.

The local protocol package now lives at tools/protocol/, so the PyPI
``mcp`` SDK no longer needs the sys.path hack that the legacy
mcp_server/server.py required.
"""

import logging

from mcp.server import FastMCP

from mcp_gateway.handlers.knowledge import register_knowledge_tools
from mcp_gateway.handlers.problems import register_problem_tools
from mcp_gateway.handlers.analytics import register_analytics_tools
from mcp_gateway.handlers.traces import register_trace_tools
from mcp_gateway.handlers.students import register_student_tools
from mcp_gateway.handlers.submissions import register_submission_tools
from mcp_gateway.handlers.write import register_write_tools
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP

logger = logging.getLogger(__name__)

EXPECTED_TOOL_COUNT = len(EXTERNAL_TOOL_MAP)


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "coderunner-mcp",
        instructions=(
            "CodeRunner MCP Server — access to the coding education "
            "platform's knowledge base, problem bank, analytics, and "
            "sandboxed code execution. High-risk write tools require "
            "teacher approval via the Human Gate workflow."
        ),
    )
    register_knowledge_tools(mcp)
    register_problem_tools(mcp)
    register_analytics_tools(mcp)
    register_trace_tools(mcp)
    register_student_tools(mcp)
    register_submission_tools(mcp)
    register_write_tools(mcp)

    registered = set(mcp._tool_manager._tools)
    expected = set(EXTERNAL_TOOL_MAP)
    if registered != expected:
        raise RuntimeError(
            "MCP tool surface drifted from EXTERNAL_TOOL_MAP. "
            f"missing={sorted(expected - registered)} "
            f"unexpected={sorted(registered - expected)}"
        )

    logger.info("MCP Server created with %d tools registered", len(registered))
    return mcp
