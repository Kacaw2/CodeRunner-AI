"""MCP tool wrappers for problem and analytics operations."""

import json

from mcp.server import FastMCP

from tools.problems.queries import get_problem_detail_impl
from tools.analytics.queries import get_problem_difficulty_stats_impl
from core.db.session import get_session
from mcp_gateway.middleware import run_mcp_guard


def register_problem_tools(mcp: FastMCP):
    @mcp.tool(
        name="get_problem_detail",
        description=(
            "Get problem description and public (non-hidden) test cases "
            "by problem ID."
        ),
    )
    def get_problem_detail(problem_id: int) -> str:
        args = {"problem_id": problem_id}
        guard = run_mcp_guard("get_problem_detail", args)
        if guard.rejected:
            return guard.error_json
        session = get_session()
        try:
            result = get_problem_detail_impl(problem_id, session=session)
            guard.record_success("get_problem_detail", args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            guard.record_error("get_problem_detail", args, e)
            return json.dumps({"error": str(e)})
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
    def get_problem_difficulty_stats(problem_id: int) -> str:
        args = {"problem_id": problem_id}
        guard = run_mcp_guard("get_problem_difficulty_stats", args)
        if guard.rejected:
            return guard.error_json
        session = get_session()
        try:
            result = get_problem_difficulty_stats_impl(
                problem_id, session=session
            )
            guard.record_success("get_problem_difficulty_stats", args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            guard.record_error("get_problem_difficulty_stats", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()
