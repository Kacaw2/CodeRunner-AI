"""MCP tool wrappers for problem and analytics operations."""

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime


def register_problem_tools(mcp: FastMCP):
    @mcp.tool(
        name="get_problem_detail",
        description=(
            "Get problem description and public (non-hidden) test cases "
            "by problem ID."
        ),
    )
    def get_problem_detail(problem_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            "coderunner.problem.get_detail",
            {"problem_id": problem_id},
        ))

    @mcp.tool(
        name="get_problem_difficulty_stats",
        description=(
            "Get success rate and error distribution for a specific problem. "
            "Returns student attempt counts, pass/fail rates, and common "
            "error types."
        ),
    )
    def get_problem_difficulty_stats(problem_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            "coderunner.analytics.problem_difficulty",
            {"problem_id": problem_id},
        ))
