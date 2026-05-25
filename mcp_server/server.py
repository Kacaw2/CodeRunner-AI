"""MCP Server entry point — tool registration and lifecycle."""

import logging

from mcp.server import FastMCP

from mcp_server.tools.knowledge import register_knowledge_tools
from mcp_server.tools.problems import register_problem_tools

logger = logging.getLogger(__name__)


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "coderunner-mcp",
        instructions=(
            "CodeRunner MCP Server — read-only access to the coding "
            "education platform's knowledge base and problem bank."
        ),
    )
    register_knowledge_tools(mcp)
    register_problem_tools(mcp)
    logger.info("MCP Server created with 4 tools registered")
    return mcp
