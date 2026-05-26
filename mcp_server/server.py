"""MCP Server entry point — tool registration and lifecycle."""

import logging

from mcp.server import FastMCP

from mcp_server.tools.knowledge import register_knowledge_tools
from mcp_server.tools.problems import register_problem_tools
from mcp_server.tools.analytics import register_analytics_tools
from mcp_server.tools.traces import register_trace_tools
from mcp_server.tools.students import register_student_tools
from mcp_server.tools.write import register_write_tools

logger = logging.getLogger(__name__)

EXPECTED_TOOL_COUNT = 11


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
    register_write_tools(mcp)
    logger.info("MCP Server created with %d tools registered", EXPECTED_TOOL_COUNT)
    return mcp
