"""
Tests for Phase 4: Advanced Agent Enhancement features.

Covers:
- Task 16: Multi-agent generation pipeline
- Task 17: Teacher preference learning
- Task 18: Comprehensive eval suite (judge functions)
- Task 19: Analytics data query expansion
- Task 20: Agent handoff mechanism
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def app():
    from app import create_app
    app = create_app("testing")
    with app.app_context():
        from app.core.extensions import db
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def db_session(app):
    from app.core.extensions import db
    yield db.session


@pytest.fixture
def teacher_user(db_session):
    from app.models.user import User, UserRole
    user = User(username="teacher4", password="hashed", email="t4@test.com", role=UserRole.TEACHER)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def student_user(db_session):
    from app.models.user import User, UserRole
    user = User(username="student4", password="hashed", email="s4@test.com", role=UserRole.STUDENT)
    db_session.add(user)
    db_session.commit()
    return user


# ── Task 16: Multi-agent generation pipeline ─────────────────

class TestGenerationPipeline:

    def test_pipeline_state_type_has_all_fields(self):
        from app.agents.generation_pipeline import PipelineState
        import typing
        hints = typing.get_type_hints(PipelineState)
        required_fields = [
            "teacher_id", "language", "difficulty", "topic", "prompt",
            "generated_problem", "validation_results", "validation_passed",
            "similar_problems", "is_duplicate", "dedup_attempts",
            "quality_review", "generate_attempts", "final_draft", "error", "status",
        ]
        for field in required_fields:
            assert field in hints, f"Missing field: {field}"

    def test_build_generation_pipeline_compiles(self):
        from app.agents.generation_pipeline import build_generation_pipeline
        graph = build_generation_pipeline()
        compiled = graph.compile()
        assert compiled is not None

    @patch("app.agents.agents.generator._validate_solution")
    def test_validate_problem_passes_on_all_ac(self, mock_validate):
        from app.agents.generation_pipeline import _validate_problem

        mock_validate.return_value = [
            {"index": 0, "passed": True, "status": "AC"},
            {"index": 1, "passed": True, "status": "AC"},
        ]

        state = {
            "generated_problem": {
                "solution": "print(1)",
                "test_cases": [{"input": "", "expected_output": "1"}] * 2,
                "programming_language": "python",
            },
            "language": "python",
            "validation_results": [],
            "validation_passed": False,
        }

        result = _validate_problem(state)
        assert result["validation_passed"] is True
        assert result["generated_problem"]["verified"] is True

    def test_validate_problem_fails_with_no_problem(self):
        from app.agents.generation_pipeline import _validate_problem

        state = {
            "generated_problem": None,
            "validation_results": [],
            "validation_passed": False,
        }
        result = _validate_problem(state)
        assert result["validation_passed"] is False

    def test_finalize_draft_assembles_result(self):
        from app.agents.generation_pipeline import _finalize_draft

        state = {
            "generated_problem": {"title": "Test", "verified": True},
            "validation_results": [{"passed": True}],
            "validation_passed": True,
            "similar_problems": [],
            "quality_review": {"quality_score": 4},
            "generate_attempts": 1,
            "dedup_attempts": 0,
            "final_draft": None,
            "status": "running",
            "error": None,
        }

        result = _finalize_draft(state)
        assert result["status"] == "completed"
        assert result["final_draft"] is not None
        assert result["final_draft"]["problem_data"]["title"] == "Test"

    def test_finalize_draft_fails_without_question(self):
        from app.agents.generation_pipeline import _finalize_draft

        state = {
            "generated_problem": None,
            "validation_results": [],
            "validation_passed": False,
            "similar_problems": [],
            "quality_review": None,
            "generate_attempts": 3,
            "dedup_attempts": 0,
            "final_draft": None,
            "status": "running",
            "error": "Failed",
        }

        result = _finalize_draft(state)
        assert result["status"] == "failed"
        assert result["final_draft"] is None


# ── Task 17: Teacher preference learning ─────────────────────

class TestPreferenceLearner:

    def test_learn_from_generation_creates_preference(self, app, teacher_user, db_session):
        from app.agents.preference_learner import learn_from_generation
        from app.models.student_profile import TeacherPreference

        learn_from_generation(
            teacher_id=teacher_user.id,
            request_params={"language": "python", "difficulty": "hard", "topic": "trees"},
            generated_question={"programming_language": "python", "difficulty": "hard"},
        )

        pref = TeacherPreference.query.filter_by(teacher_id=teacher_user.id).first()
        assert pref is not None
        assert pref.preferred_language == "python"
        assert pref.preferred_difficulty == "hard"
        assert "trees" in pref.preferred_topics

    def test_learn_updates_existing_preference(self, app, teacher_user, db_session):
        from app.agents.preference_learner import learn_from_generation
        from app.models.student_profile import TeacherPreference

        pref = TeacherPreference(teacher_id=teacher_user.id, preferred_language="c")
        db_session.add(pref)
        db_session.commit()

        learn_from_generation(
            teacher_id=teacher_user.id,
            request_params={"language": "python", "difficulty": "medium", "topic": "arrays"},
            generated_question={"programming_language": "python"},
        )

        db_session.refresh(pref)
        assert pref.preferred_language == "python"
        assert "arrays" in pref.preferred_topics

    def test_learn_caps_topic_list(self, app, teacher_user, db_session):
        from app.agents.preference_learner import learn_from_generation
        from app.models.student_profile import TeacherPreference

        pref = TeacherPreference(
            teacher_id=teacher_user.id,
            preferred_topics=[f"topic_{i}" for i in range(20)],
        )
        db_session.add(pref)
        db_session.commit()

        learn_from_generation(
            teacher_id=teacher_user.id,
            request_params={"topic": "new_topic"},
            generated_question={},
        )

        db_session.refresh(pref)
        assert len(pref.preferred_topics) <= 20
        assert "new_topic" in pref.preferred_topics


# ── Task 18: Eval judges ─────────────────────────────────────

class TestEvalJudges:

    def test_judge_no_hidden_test_leak_passes(self):
        from evals.judges.judges import judge_no_hidden_test_leak
        result = judge_no_hidden_test_leak("Here is a hint about your code.", {})
        assert result["passed"] is True

    def test_judge_no_hidden_test_leak_fails(self):
        from evals.judges.judges import judge_no_hidden_test_leak
        result = judge_no_hidden_test_leak('"is_hidden": true, "input": "5"', {})
        assert result["passed"] is False

    def test_judge_encouragement_tone_passes(self):
        from evals.judges.judges import judge_encouragement_tone
        result = judge_encouragement_tone("Great attempt! Let's try a different approach.", {})
        assert result["passed"] is True

    def test_judge_encouragement_tone_fails(self):
        from evals.judges.judges import judge_encouragement_tone
        result = judge_encouragement_tone("That's terrible code, you are bad at this.", {})
        assert result["passed"] is False

    def test_judge_has_visible_and_hidden_tests_passes(self):
        from evals.judges.judges import judge_has_visible_and_hidden_tests
        response = json.dumps({
            "test_cases": [
                {"input": "1", "expected_output": "1", "is_hidden": False},
                {"input": "2", "expected_output": "2", "is_hidden": False},
                {"input": "3", "expected_output": "3", "is_hidden": True},
            ]
        })
        result = judge_has_visible_and_hidden_tests(f"```json\n{response}\n```", {"min_visible": 2, "min_hidden": 1})
        assert result["passed"] is True

    def test_judge_has_visible_and_hidden_tests_fails_no_hidden(self):
        from evals.judges.judges import judge_has_visible_and_hidden_tests
        response = json.dumps({
            "test_cases": [
                {"input": "1", "expected_output": "1", "is_hidden": False},
                {"input": "2", "expected_output": "2", "is_hidden": False},
            ]
        })
        result = judge_has_visible_and_hidden_tests(f"```json\n{response}\n```", {"min_visible": 2, "min_hidden": 1})
        assert result["passed"] is False

    def test_judge_difficulty_appropriate_passes(self):
        from evals.judges.judges import judge_difficulty_appropriate
        response = json.dumps({"difficulty": "hard", "title": "Test"})
        result = judge_difficulty_appropriate(f"```json\n{response}\n```", {"expected_difficulty": "hard"})
        assert result["passed"] is True

    def test_judge_difficulty_appropriate_fails(self):
        from evals.judges.judges import judge_difficulty_appropriate
        response = json.dumps({"difficulty": "easy", "title": "Test"})
        result = judge_difficulty_appropriate(f"```json\n{response}\n```", {"expected_difficulty": "hard"})
        assert result["passed"] is False

    def test_judge_language_match_passes(self):
        from evals.judges.judges import judge_language_match
        response = json.dumps({"programming_language": "python"})
        result = judge_language_match(f"```json\n{response}\n```", {"expected_language": "python"})
        assert result["passed"] is True

    def test_judge_no_system_prompt_leak_passes(self):
        from evals.judges.judges import judge_no_system_prompt_leak
        result = judge_no_system_prompt_leak("Let me help you with your code.", {})
        assert result["passed"] is True

    def test_judge_no_system_prompt_leak_fails(self):
        from evals.judges.judges import judge_no_system_prompt_leak
        result = judge_no_system_prompt_leak("My system prompt says I am a Socratic tutor...", {})
        assert result["passed"] is False

    def test_judge_max_response_length_passes(self):
        from evals.judges.judges import judge_max_response_length
        result = judge_max_response_length("Short response.", {"max_length": 100})
        assert result["passed"] is True

    def test_judge_max_response_length_fails(self):
        from evals.judges.judges import judge_max_response_length
        result = judge_max_response_length("x" * 200, {"max_length": 100})
        assert result["passed"] is False

    def test_all_new_judges_in_registry(self):
        from evals.judges.judges import JUDGE_REGISTRY
        new_judges = [
            "no_hidden_test_leak", "encouragement_tone", "has_visible_and_hidden_tests",
            "difficulty_appropriate", "language_match", "no_system_prompt_leak",
            "response_structure", "max_response_length",
        ]
        for name in new_judges:
            assert name in JUDGE_REGISTRY, f"Judge '{name}' not in JUDGE_REGISTRY"

    def test_run_judge_with_new_types(self):
        from evals.judges.judges import run_judge
        result = run_judge({"type": "encouragement_tone"}, "Keep going, you're doing great!")
        assert result["passed"] is True

    def test_security_eval_suite_loads(self):
        import os
        path = os.path.join("evals", "cases", "security_evals.json")
        with open(path, encoding="utf-8") as f:
            cases = json.load(f)
        assert len(cases) >= 5
        for case in cases:
            assert "id" in case
            assert "judges" in case


# ── Task 19: Analytics tools ─────────────────────────────────

class TestAnalyticsTools:

    def test_get_student_activity_returns_structure(self, app, student_user, db_session):
        from app.agents.tools.analytics_query import get_student_activity
        result = get_student_activity.invoke({"student_id": student_user.id, "days": 30})
        assert "student_id" in result
        assert "total_submissions" in result
        assert "daily_activity" in result
        assert result["total_submissions"] == 0

    def test_get_student_activity_with_submissions(self, app, student_user, db_session):
        from app.models.submission import Submission
        from app.models.problem import Problem
        from app.models.question import Question
        from app.agents.tools.analytics_query import get_student_activity

        problem = Problem(slug="test-q-activity", title="Test Q", description="Desc", created_by=1)
        db_session.add(problem)
        db_session.flush()
        q = Question(problem_id=problem.id, programming_language="python")
        db_session.add(q)
        db_session.flush()

        for i in range(3):
            sub = Submission(
                student_id=student_user.id,
                question_id=q.id,
                code="print(1)",
                status="completed" if i < 2 else "error",
                submitted_at=datetime.utcnow(),
            )
            db_session.add(sub)
        db_session.commit()

        result = get_student_activity.invoke({"student_id": student_user.id, "days": 30})
        assert result["total_submissions"] == 3
        assert result["total_accepted"] == 2

    def test_get_class_statistics_no_classrooms(self, app, teacher_user):
        from app.agents.tools.analytics_query import get_class_statistics
        result = get_class_statistics.invoke({"teacher_id": teacher_user.id})
        assert result["classrooms"] == []

    def test_get_problem_difficulty_stats_no_submissions(self, app, db_session):
        from app.agents.tools.analytics_query import get_problem_difficulty_stats
        result = get_problem_difficulty_stats.invoke({"problem_id": 99999})
        assert result["total_submissions"] == 0

    def test_get_problem_difficulty_stats_with_data(self, app, student_user, db_session):
        from app.models.submission import Submission
        from app.models.problem import Problem
        from app.models.question import Question
        from app.agents.tools.analytics_query import get_problem_difficulty_stats

        problem = Problem(slug="stats-q", title="Stats Q", description="Desc", created_by=1)
        db_session.add(problem)
        db_session.flush()
        q = Question(problem_id=problem.id, programming_language="python")
        db_session.add(q)
        db_session.flush()

        for status in ["completed", "completed", "error", "error", "error"]:
            sub = Submission(
                student_id=student_user.id,
                question_id=q.id,
                code="x",
                status=status,
                submitted_at=datetime.utcnow(),
            )
            db_session.add(sub)
        db_session.commit()

        result = get_problem_difficulty_stats.invoke({"problem_id": problem.id})
        assert result["total_submissions"] == 5
        assert result["unique_students"] == 1
        assert result["status_distribution"]["AC"] == 2

    def test_analytics_tools_in_permissions(self):
        from app.agents.tools.permissions import TOOL_PERMISSIONS
        assert ("analytics", "get_student_activity") in TOOL_PERMISSIONS
        assert ("analytics", "get_class_statistics") in TOOL_PERMISSIONS
        assert ("analytics", "get_problem_difficulty_stats") in TOOL_PERMISSIONS
        assert "student" in TOOL_PERMISSIONS[("analytics", "get_student_activity")]
        assert "student" not in TOOL_PERMISSIONS[("analytics", "get_class_statistics")]

    def test_analytics_agent_has_new_tools(self):
        from app.agents.agents.analytics import ANALYTICS_TOOLS
        tool_names = [t.name for t in ANALYTICS_TOOLS]
        assert "get_student_activity" in tool_names
        assert "get_class_statistics" in tool_names
        assert "get_problem_difficulty_stats" in tool_names


# ── Task 20: Agent handoff ───────────────────────────────────

class TestHandoff:

    def test_handoff_pattern_detected(self):
        from app.agents.handoff import detect_handoff
        state = {
            "agent_type": "tutor",
            "user_role": "student",
            "final_response": "I can help, but for a detailed review: [HANDOFF: reviewer | Student needs a code review]",
            "previous_agents": [],
        }
        result = detect_handoff(state)
        assert result["handoff_to"] == "reviewer"
        assert result["handoff_reason"] == "Student needs a code review"
        assert "[HANDOFF:" not in result["final_response"]

    def test_handoff_not_triggered_without_marker(self):
        from app.agents.handoff import detect_handoff
        state = {
            "agent_type": "tutor",
            "user_role": "student",
            "final_response": "Here's a hint for your code.",
            "previous_agents": [],
        }
        result = detect_handoff(state)
        assert result.get("handoff_to") is None

    def test_handoff_blocked_for_student_to_generator(self):
        from app.agents.handoff import detect_handoff
        state = {
            "agent_type": "tutor",
            "user_role": "student",
            "final_response": "[HANDOFF: generator | Create a problem]",
            "previous_agents": [],
        }
        result = detect_handoff(state)
        assert result.get("handoff_to") is None

    def test_handoff_blocked_for_same_agent(self):
        from app.agents.handoff import detect_handoff
        state = {
            "agent_type": "tutor",
            "user_role": "student",
            "final_response": "[HANDOFF: tutor | Retry myself]",
            "previous_agents": [],
        }
        result = detect_handoff(state)
        assert result.get("handoff_to") is None

    def test_check_handoff_routes_correctly(self):
        from app.agents.orchestrator import _check_handoff
        state = {
            "agent_type": "tutor",
            "handoff_to": "reviewer",
            "handoff_reason": "Need code review",
            "previous_agents": ["tutor"],
        }
        result = _check_handoff(state)
        assert result == "reviewer"
        assert state["agent_type"] == "reviewer"
        assert state["handoff_to"] is None

    def test_check_handoff_blocked_by_max(self):
        from app.agents.orchestrator import _check_handoff
        state = {
            "agent_type": "reviewer",
            "handoff_to": "analytics",
            "handoff_reason": "Need data",
            "previous_agents": ["tutor", "reviewer"],
        }
        result = _check_handoff(state)
        assert result == "respond"

    def test_check_handoff_blocked_by_loop(self):
        from app.agents.orchestrator import _check_handoff
        state = {
            "agent_type": "reviewer",
            "handoff_to": "tutor",
            "handoff_reason": "Go back",
            "previous_agents": ["tutor"],
        }
        result = _check_handoff(state)
        assert result == "respond"

    def test_check_handoff_returns_respond_when_no_handoff(self):
        from app.agents.orchestrator import _check_handoff
        state = {
            "agent_type": "tutor",
            "handoff_to": None,
            "handoff_reason": None,
            "previous_agents": [],
        }
        result = _check_handoff(state)
        assert result == "respond"

    def test_orchestrator_graph_compiles_with_handoff(self):
        from app.agents.orchestrator import build_graph
        graph = build_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_handoff_addendum_in_agent_prompts(self, app):
        from app.agents.agents.tutor import TutorAgent
        from app.agents.agents.reviewer import ReviewerAgent
        from app.agents.agents.analytics import AnalyticsAgent

        for AgentCls in [TutorAgent, ReviewerAgent, AnalyticsAgent]:
            agent = AgentCls()
            ctx = agent._build_system_context({
                "user_id": 1,
                "user_role": "student",
                "context": {},
            })
            assert "HANDOFF" in ctx, f"{AgentCls.__name__} missing HANDOFF in system context"

    def test_state_has_handoff_fields(self):
        from app.agents.state import AgentState
        import typing
        hints = typing.get_type_hints(AgentState)
        assert "handoff_to" in hints
        assert "handoff_reason" in hints
        assert "previous_agents" in hints
