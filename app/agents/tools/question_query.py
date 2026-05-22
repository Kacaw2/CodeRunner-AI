from langchain_core.tools import tool


@tool
def get_question_detail(question_id: int) -> dict:
    """Get question description and public (non-hidden) test cases by question ID."""
    from app.models.question import Question, TestCase
    q = Question.query.get(question_id)
    if not q:
        return {"error": "Question not found"}
    problem = q.problem
    if not problem:
        return {"error": "Problem not found"}
    # Only expose public test cases; hidden ones must stay confidential
    cases = TestCase.query.filter_by(problem_id=problem.id, is_hidden=False).all()
    return {
        "id": q.id,
        "problem_id": problem.id,
        "title": problem.title,
        "description": problem.description,
        "language": q.programming_language,
        "test_cases": [
            {"input": tc.input, "expected_output": tc.expected_output}
            for tc in cases
        ],
    }
