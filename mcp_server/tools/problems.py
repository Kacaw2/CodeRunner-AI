"""MCP tool wrappers for problem and analytics operations."""

import json

from mcp.server import FastMCP

from app.agents.tools.core.problems import get_problem_detail_impl
from app.agents.tools.core.analytics import get_problem_difficulty_stats_impl
from mcp_server.db import get_session
from mcp_server.middleware import mcp_tool_middleware


def register_problem_tools(mcp: FastMCP):
    @mcp.tool(
        name="get_problem_detail",
        description=(
            "Get problem description and public (non-hidden) test cases "
            "by problem ID."
        ),
    )
    @mcp_tool_middleware("get_problem_detail")
    def get_problem_detail(problem_id: int) -> str:
        session = get_session()
        try:
            result = get_problem_detail_impl(problem_id, session=session)
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool(
        name="get_problem_difficulty_stats",
        description=(
            "Get success rate and error distribution for a specific problem. "
            "Returns student attempt counts, pass/fail rates, and common "
            "error types."
        ),
    )
    @mcp_tool_middleware("get_problem_difficulty_stats")
    def get_problem_difficulty_stats(problem_id: int) -> str:
        session = get_session()
        try:
            result = get_problem_difficulty_stats_impl(
                problem_id, session=session
            )
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
