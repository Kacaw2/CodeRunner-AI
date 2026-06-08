"""Tests for advanced agent features: generation pipeline, preference learning,
analytics tool coverage, and agent handoff."""

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
    from domain.models.user import User, UserRole
    user = User(username="teacher4", password="hashed", email="t4@test.com", role=UserRole.TEACHER)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def student_user(db_session):
    from domain.models.user import User, UserRole
    user = User(username="student4", password="hashed", email="s4@test.com", role=UserRole.STUDENT)
    db_session.add(user)
    db_session.commit()
    return user


# ── Task 16: Multi-agent generation pipeline ─────────────────

class TestGenerationPipeline:

    def test_pipeline_state_type_has_all_fields(self):
        from ai.workers.generation_pipeline import PipelineState
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
        from ai.workers.generation_pipeline import build_generation_pipeline
        graph = build_generation_pipeline()
        compiled = graph.compile()
        assert compiled is not None

    @patch("ai.agents.generator.agent._validate_solution")
    def test_validate_problem_passes_on_all_ac(self, mock_validate):
        from ai.workers.generation_pipeline import _validate_problem

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
        from ai.workers.generation_pipeline import _validate_problem

        state = {
            "generated_problem": None,
            "validation_results": [],
            "validation_passed": False,
        }
        result = _validate_problem(state)
        assert result["validation_passed"] is False

    def test_finalize_draft_assembles_result(self):
        from ai.workers.generation_pipeline import _finalize_draft

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
        from ai.workers.generation_pipeline import _finalize_draft

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

    def test_generation_pipeline_keeps_rendered_teacher_context(self):
        from ai.workers.generation_pipeline import _generate_problem

        state = {
            "teacher_id": 1,
            "language": "python",
            "difficulty": "medium",
            "topic": "loops",
            "test_case_count": 3,
            "prompt": "Create a loop problem",
            "teacher_context": "Teacher Preferences: concise",
            "generated_problem": None,
            "validation_results": [],
            "validation_passed": False,
            "similar_problems": [],
            "is_duplicate": False,
            "dedup_attempts": 0,
            "quality_review": None,
            "generate_attempts": 0,
            "final_draft": None,
            "error": None,
            "status": "generating",
        }

        with patch("ai.workers.generation_pipeline.AIConfig.get_llm") as get_llm:
            llm = MagicMock()
            llm.invoke.return_value.content = (
                '{"title":"Loop","solution":"pass","test_cases":[{"input":"","expected_output":""}]}'
            )
            get_llm.return_value = llm

            _generate_problem(state)

            messages = llm.invoke.call_args.args[0]
            assert "Teacher Preferences: concise" in messages[0].content


# ── Task 17: Teacher preference learning ─────────────────────

class TestPreferenceLearner:

    def test_learn_from_generation_creates_preference(self, app, teacher_user, db_session):
        from ai.memory.preference import learn_from_generation
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
        from ai.memory.preference import learn_from_generation
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
        from ai.memory.preference import learn_from_generation
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


# ── Task 19: Analytics tools ─────────────────────────────────

class TestAnalyticsTools:

    def test_get_student_activity_returns_structure(self, app, student_user, db_session):
        from ai.tools.analytics.queries import get_student_activity_impl
        result = get_student_activity_impl(student_id=student_user.id, days=30)
        assert "student_id" in result
        assert "total_submissions" in result
        assert "daily_activity" in result
        assert result["total_submissions"] == 0

    def test_get_student_activity_with_submissions(self, app, student_user, db_session):
        from app.models.submission import Submission
        from app.models.problem import Problem
        from app.models.question import Question
        from ai.tools.analytics.queries import get_student_activity_impl

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

        result = get_student_activity_impl(student_id=student_user.id, days=30)
        assert result["total_submissions"] == 3
        assert result["total_accepted"] == 2

    def test_get_class_statistics_no_classrooms(self, app, teacher_user):
        from ai.tools.analytics.queries import get_class_statistics_impl
        result = get_class_statistics_impl(teacher_id=teacher_user.id)
        assert result["classrooms"] == []

    def test_get_problem_difficulty_stats_no_submissions(self, app, db_session):
        from ai.tools.analytics.queries import get_problem_difficulty_stats_impl
        result = get_problem_difficulty_stats_impl(problem_id=99999)
        assert result["total_submissions"] == 0

    def test_get_problem_difficulty_stats_with_data(self, app, student_user, db_session):
        from app.models.submission import Submission
        from app.models.problem import Problem
        from app.models.question import Question
        from ai.tools.analytics.queries import get_problem_difficulty_stats_impl

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

        result = get_problem_difficulty_stats_impl(problem_id=problem.id)
        assert result["total_submissions"] == 5
        assert result["unique_students"] == 1
        assert result["status_distribution"]["AC"] == 2

    def test_analytics_tools_in_rbac(self):
        from ai.tools.protocol.policies.rbac import _agent_tool_allow, _ROLE_OVERRIDES
        allow = _agent_tool_allow()["analytics"]
        assert "coderunner.analytics.student_activity" in allow
        assert "coderunner.analytics.class_statistics" in allow
        assert "coderunner.analytics.problem_difficulty" in allow
        assert "student" not in _ROLE_OVERRIDES["coderunner.analytics.class_statistics"]

    def test_analytics_agent_has_mcp_tools(self):
        from ai.agents.analytics.agent import AnalyticsAgent
        tools = AnalyticsAgent().mcp_tool_names
        assert "coderunner.analytics.student_activity" in tools
        assert "coderunner.analytics.class_statistics" in tools
        assert "coderunner.analytics.problem_difficulty" in tools


# ── Task 20: Agent handoff ───────────────────────────────────

class TestHandoff:

    def test_declared_edge_allowed_at_boundary(self):
        from ai.graph.handoff import validate_handoff_target
        assert validate_handoff_target("tutor", "reviewer", "student") is None

    def test_undeclared_edge_rejected_at_boundary(self):
        from ai.graph.handoff import validate_handoff_target
        # tutor does not declare generator as a handoff target.
        assert validate_handoff_target("tutor", "generator", "student") is not None

    def test_same_agent_handoff_rejected_at_boundary(self):
        from ai.graph.handoff import validate_handoff_target
        assert validate_handoff_target("tutor", "tutor", "student") is not None

    def test_check_handoff_routes_correctly(self):
        from ai.graph.runner import _check_handoff
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
        from ai.graph.runner import _check_handoff
        state = {
            "agent_type": "reviewer",
            "handoff_to": "analytics",
            "handoff_reason": "Need data",
            "previous_agents": ["tutor", "reviewer"],
        }
        result = _check_handoff(state)
        assert result == "respond"

    def test_check_handoff_blocked_by_loop(self):
        from ai.graph.runner import _check_handoff
        state = {
            "agent_type": "reviewer",
            "handoff_to": "tutor",
            "handoff_reason": "Go back",
            "previous_agents": ["tutor"],
        }
        result = _check_handoff(state)
        assert result == "respond"

    def test_check_handoff_returns_respond_when_no_handoff(self):
        from ai.graph.runner import _check_handoff
        state = {
            "agent_type": "tutor",
            "handoff_to": None,
            "handoff_reason": None,
            "previous_agents": [],
        }
        result = _check_handoff(state)
        assert result == "respond"

    def test_orchestrator_graph_compiles_with_handoff(self):
        from ai.graph.runner import build_graph
        graph = build_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_handoff_addendum_in_agent_prompts(self, app):
        from ai.agents.tutor.agent import TutorAgent
        from ai.agents.reviewer.agent import ReviewerAgent
        from ai.agents.analytics.agent import AnalyticsAgent

        for AgentCls in [TutorAgent, ReviewerAgent, AnalyticsAgent]:
            agent = AgentCls()
            ctx = agent._build_system_context({
                "user_id": 1,
                "user_role": "student",
                "context": {},
            })
            assert "delegate" in ctx, f"{AgentCls.__name__} missing delegate guidance in system context"

    def test_state_has_handoff_fields(self):
        from core.state import AgentState
        import typing
        hints = typing.get_type_hints(AgentState)
        assert "handoff_to" in hints
        assert "handoff_reason" in hints
        assert "previous_agents" in hints
