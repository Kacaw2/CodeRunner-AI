from langchain_core.tools import tool

from app.agents.tools.core.problems import get_problem_detail_impl
from app.agents.tools.db_context import get_current_session


@tool
def get_problem_detail(problem_id: int) -> dict:
    """Get problem description and public (non-hidden) test cases by problem ID."""
    return get_problem_detail_impl(problem_id, session=get_current_session())
