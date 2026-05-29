"""Contract tests for external MCP gateway surface.

EXPECTED_EXTERNAL_TOOL_MAP is an independent oracle: it is intentionally NOT
imported from mcp_gateway.tool_map so that a wrong edit to the source map is
caught by test_source_map_matches_declared_contract rather than silently
accepted.
"""

from mcp_gateway.server import create_mcp_server
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP
from tools.protocol.schemas.catalog import TOOL_CATALOG


EXPECTED_EXTERNAL_TOOL_MAP = {
    "search_knowledge": "coderunner.knowledge.search",
    "search_similar_problems": "coderunner.knowledge.search_similar_problems",
    "search_error_patterns": "coderunner.knowledge.search_error_patterns",
    "get_problem_detail": "coderunner.problem.get_detail",
    "list_student_submissions": "coderunner.submission.list_for_student",
    "get_submission_detail": "coderunner.submission.get_detail",
    "get_problem_difficulty_stats": "coderunner.analytics.problem_difficulty",
    "get_student_activity": "coderunner.analytics.student_activity",
    "get_student_stats": "coderunner.analytics.student_stats",
    "get_class_statistics": "coderunner.analytics.class_statistics",
    "get_agent_trace": "coderunner.trace.get_agent_trace",
    "get_student_summary": "coderunner.student.get_summary",
    "execute_code": "coderunner.code.execute",
    "save_generated_problem": "coderunner.problem.save_generated",
    "check_approval": "coderunner.approval.check",
}


def test_source_map_matches_declared_contract():
    assert EXTERNAL_TOOL_MAP == EXPECTED_EXTERNAL_TOOL_MAP


def test_external_tool_map_targets_existing_catalog_tools():
    missing = set(EXPECTED_EXTERNAL_TOOL_MAP.values()) - set(TOOL_CATALOG)
    assert missing == set()


def test_every_catalog_tool_is_exposed_by_mcp_server():
    assert set(EXPECTED_EXTERNAL_TOOL_MAP.values()) == set(TOOL_CATALOG)


def test_external_gateway_registers_exact_declared_tools():
    mcp = create_mcp_server()
    actual = set(mcp._tool_manager._tools)
    assert actual == set(EXPECTED_EXTERNAL_TOOL_MAP)


def test_expected_tool_count_matches_registered_tools():
    from mcp_gateway.server import EXPECTED_TOOL_COUNT

    mcp = create_mcp_server()
    assert EXPECTED_TOOL_COUNT == len(mcp._tool_manager._tools)
