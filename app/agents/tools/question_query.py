from langchain_core.tools import tool


@tool
def get_problem_detail(problem_id: int) -> dict:
    """Get problem description and public (non-hidden) test cases by problem ID."""
    from app.models.problem import Problem
    from app.models.question import TestCase
    problem = Problem.query.get(problem_id)
    if not problem:
        return {"error": "Problem not found"}
    cases = TestCase.query.filter_by(problem_id=problem.id, is_hidden=False).all()
    languages = [v.programming_language for v in problem.variants] if problem.variants else []
    return {
        "problem_id": problem.id,
        "title": problem.title,
        "description": problem.description,
        "difficulty": problem.difficulty,
        "languages": languages,
        "test_cases": [
            {"input": tc.input, "expected_output": tc.expected_output}
            for tc in cases
        ],
    }
