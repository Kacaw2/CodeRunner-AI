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
from mcp_gateway.handlers.write import register_write_tools

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
