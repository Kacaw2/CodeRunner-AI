from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.user import User, UserRole


def test_public_problem_list_returns_language_variants(client, app):
    with app.app_context():
        teacher = User(
            username="teacher_api_problem",
            password="test-password",
            email="teacher_api_problem@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add(teacher)
        db.session.flush()
        problem = Problem(
            slug="api-two-sum",
            title="API Two Sum",
            description="Desc",
            created_by=teacher.id,
        )
        db.session.add(problem)
        db.session.flush()
        db.session.add_all(
            [
                Question(
                    problem_id=problem.id,
                    programming_language="python",
                    starter_code="py",
                    solution="py",
                ),
                Question(
                    problem_id=problem.id,
                    programming_language="c",
                    starter_code="c",
                    solution="c",
                ),
            ]
        )
        db.session.commit()

    resp = client.get("/api/v1/problems")
    assert resp.status_code == 200
    data = resp.get_json()
    item = next(p for p in data["items"] if p["title"] == "API Two Sum")
    assert item["default_language"] == "python"
    assert [v["language"] for v in item["variants"]] == ["python", "c"]


def test_problem_detail_selects_language(client, app):
    with app.app_context():
        teacher = User(
            username="teacher_api_detail",
            password="test-password",
            email="teacher_api_detail@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add(teacher)
        db.session.flush()
        problem = Problem(
            slug="api-detail",
            title="API Detail",
            description="Desc",
            created_by=teacher.id,
        )
        db.session.add(problem)
        db.session.flush()
        db.session.add_all(
            [
                Question(
                    problem_id=problem.id,
                    programming_language="python",
                    starter_code="py-code",
                    solution="py-sol",
                ),
                Question(
                    problem_id=problem.id,
                    programming_language="c",
                    starter_code="c-code",
                    solution="c-sol",
                ),
                TestCase(
                    problem_id=problem.id,
                    input="1",
                    expected_output="1",
                    is_hidden=False,
                    weight=1.0,
                ),
            ]
        )
        db.session.commit()
        problem_id = problem.id

    resp = client.get(f"/api/v1/problems/{problem_id}?language=c")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["selected_language"] == "c"
    assert data["starter_code"] == "c-code"
    assert data["test_cases"][0]["input"] == "1"
