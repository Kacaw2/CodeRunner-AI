"""MCP Server entry point — tool registration and lifecycle.

Note: The local mcp/ package (Phase 5 kernel) shadows the third-party
``mcp`` SDK.  We temporarily adjust sys.path to import FastMCP.
"""

import logging
import os
import sys

def _import_fastmcp():
    """Import FastMCP from the installed mcp SDK, bypassing the local mcp/ shadow."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    saved_path = sys.path[:]
    saved_modules = {k: v for k, v in sys.modules.items() if k == "mcp" or k.startswith("mcp.")}
    try:
        for k in saved_modules:
            del sys.modules[k]
        sys.path = [p for p in sys.path if os.path.abspath(p) != project_root]
        from mcp.server import FastMCP as _FastMCP
        return _FastMCP
    finally:
        sys.path = saved_path
        sys.modules.update(saved_modules)

FastMCP = _import_fastmcp()

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
