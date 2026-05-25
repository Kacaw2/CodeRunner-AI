"""Core problem-query logic — no framework dependency."""


def get_problem_detail_impl(problem_id: int, session=None) -> dict:
    from app.models.problem import Problem
    from app.models.question import TestCase

    if session:
        problem = session.get(Problem, problem_id)
    else:
        problem = Problem.query.get(problem_id)

    if not problem:
        return {"error": "Problem not found"}

    if session:
        cases = (
            session.query(TestCase)
            .filter_by(problem_id=problem.id, is_hidden=False)
            .all()
        )
    else:
        cases = TestCase.query.filter_by(
            problem_id=problem.id, is_hidden=False
        ).all()

    languages = (
        [v.programming_language for v in problem.variants]
        if problem.variants
        else []
    )
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
