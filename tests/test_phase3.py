"""Tests for Phase 3 features: memory, knowledge base, eval framework, profiles."""
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage


# ── Student Profile Model Tests ──────────────────────────────

class TestStudentProfile:
    def test_create_student_profile(self, db_session, student_user, app):
        with app.app_context():
            from app.models.student_profile import StudentProfile

            profile = StudentProfile(
                student_id=student_user.id,
                error_patterns={"WA": 5, "RE": 2, "AC": 10},
                knowledge_map={"arrays": 0.8, "dp": 0.3},
                recent_topics=["arrays", "sorting"],
                preferred_language="python",
            )
            db_session.add(profile)
            db_session.commit()

            found = StudentProfile.query.filter_by(student_id=student_user.id).first()
            assert found is not None
            assert found.error_patterns["WA"] == 5
            assert found.knowledge_map["dp"] == 0.3
            assert found.preferred_language == "python"

    def test_profile_to_dict(self, db_session, student_user, app):
        with app.app_context():
            from app.models.student_profile import StudentProfile

            profile = StudentProfile(
                student_id=student_user.id,
                learning_summary="Student struggles with pointers",
                error_patterns={"CE": 3},
            )
            db_session.add(profile)
            db_session.commit()

            d = profile.to_dict()
            assert d["student_id"] == student_user.id
            assert "pointers" in d["learning_summary"]
            assert d["error_patterns"]["CE"] == 3


class TestTeacherPreference:
    def test_create_teacher_preference(self, db_session, teacher_user, app):
        with app.app_context():
            from app.models.student_profile import TeacherPreference

            pref = TeacherPreference(
                teacher_id=teacher_user.id,
                preferred_difficulty="hard",
                preferred_language="c",
                class_weak_areas=["recursion", "pointers"],
                style_notes="I prefer concise descriptions with 2 examples",
            )
            db_session.add(pref)
            db_session.commit()

            found = TeacherPreference.query.filter_by(teacher_id=teacher_user.id).first()
            assert found is not None
            assert found.preferred_difficulty == "hard"
            assert "recursion" in found.class_weak_areas

    def test_preference_to_dict(self, db_session, teacher_user, app):
        with app.app_context():
            from app.models.student_profile import TeacherPreference

            pref = TeacherPreference(
                teacher_id=teacher_user.id,
                style_notes="Brief and clear",
            )
            db_session.add(pref)
            db_session.commit()

            d = pref.to_dict()
            assert d["teacher_id"] == teacher_user.id
            assert d["style_notes"] == "Brief and clear"


# ── Memory Service Tests ─────────────────────────────────────

class TestMemoryService:
    def test_get_memory_context_student_empty(self, app, student_user):
        with app.app_context():
            from agent_host.memory import MemoryService

            ctx = MemoryService.get_memory_context(student_user.id, "student")
            assert ctx == ""

    def test_get_memory_context_student_with_profile(self, db_session, student_user, app):
        with app.app_context():
            from agent_host.memory import MemoryService
            from app.models.student_profile import StudentProfile

            profile = StudentProfile(
                student_id=student_user.id,
                learning_summary="Struggles with recursion",
                error_patterns={"WA": 10},
                knowledge_map={"recursion": 0.3, "arrays": 0.9},
            )
            db_session.add(profile)
            db_session.commit()

            ctx = MemoryService.get_memory_context(student_user.id, "student")
            assert "recursion" in ctx.lower()
            assert "Weak Areas" in ctx

    def test_get_memory_context_teacher_with_prefs(self, db_session, teacher_user, app):
        with app.app_context():
            from agent_host.memory import MemoryService
            from app.models.student_profile import TeacherPreference

            pref = TeacherPreference(
                teacher_id=teacher_user.id,
                style_notes="Concise problems",
                class_weak_areas=["dynamic programming"],
            )
            db_session.add(pref)
            db_session.commit()

            ctx = MemoryService.get_memory_context(teacher_user.id, "teacher")
            assert "Concise problems" in ctx
            assert "dynamic programming" in ctx

    def test_update_student_profile(self, db_session, student_user, app):
        with app.app_context():
            from agent_host.memory import MemoryService
            from app.models.student_profile import StudentProfile
            from app.models.submission import Submission
            from app.models.problem import Problem
            from app.models.question import Question

            problem = Problem(slug="test-q-phase3", title="Test Q", description="Desc", created_by=1)
            db_session.add(problem)
            db_session.flush()
            q = Question(problem_id=problem.id, programming_language="python")
            db_session.add(q)
            db_session.flush()

            sub = Submission(student_id=student_user.id, question_id=q.id, code="print(1)", status="completed")
            db_session.add(sub)
            db_session.commit()

            MemoryService.update_student_profile(student_user.id)

            profile = StudentProfile.query.filter_by(student_id=student_user.id).first()
            assert profile is not None
            assert profile.error_patterns.get("AC", 0) >= 1

    def test_compact_messages_short(self):
        from agent_host.memory import MemoryService

        msgs = [HumanMessage(content="hi")] * 5
        result = MemoryService.compact_messages(msgs, max_messages=20)
        assert len(result) == 5

    def test_compact_messages_long(self):
        from agent_host.memory import MemoryService

        msgs = [SystemMessage(content="sys")] + [HumanMessage(content=f"msg {i}") for i in range(30)]
        result = MemoryService.compact_messages(msgs, max_messages=10)
        assert len(result) <= 12  # system + summary + 10 recent


# ── Eval Framework Tests ─────────────────────────────────────

class TestEvalJudges:
    def test_answer_leak_judge_detects_long_code(self):
        from evals.judges.judges import judge_answer_leak

        response = "Here's the solution:\n```python\ndef solve(a, b):\n    c = a + b\n    d = c * 2\n    e = d - 1\n    return e + 1\n    # extra line\n```"
        result = judge_answer_leak(response, {"solution_keywords": []})
        assert result["passed"] is False

    def test_answer_leak_judge_passes_short_code(self):
        from evals.judges.judges import judge_answer_leak

        response = "Try something like:\n```python\nfor i in range(n):\n    print(i)\n```"
        result = judge_answer_leak(response, {"solution_keywords": []})
        assert result["passed"] is True

    def test_answer_leak_judge_detects_keywords(self):
        from evals.judges.judges import judge_answer_leak

        response = "You could use def twoSum to solve this"
        result = judge_answer_leak(response, {"solution_keywords": ["def twoSum"]})
        assert result["passed"] is False

    def test_regex_absent_judge_passes(self):
        from evals.judges.judges import judge_regex_absent

        response = "I can help you with that problem."
        result = judge_regex_absent(response, {"pattern": "system\\s*prompt", "flags": "IGNORECASE"})
        assert result["passed"] is True

    def test_regex_absent_judge_fails(self):
        from evals.judges.judges import judge_regex_absent

        response = "The system prompt says I should help."
        result = judge_regex_absent(response, {"pattern": "system\\s*prompt", "flags": "IGNORECASE"})
        assert result["passed"] is False

    def test_contains_any_judge(self):
        from evals.judges.judges import judge_contains_any

        response = "I recommend you practice more sorting problems."
        result = judge_contains_any(response, {"keywords": ["recommend", "suggest"]})
        assert result["passed"] is True

    def test_contains_any_judge_fails(self):
        from evals.judges.judges import judge_contains_any

        response = "Your code is correct."
        result = judge_contains_any(response, {"keywords": ["error", "bug", "issue"]})
        assert result["passed"] is False

    def test_max_code_lines_judge(self):
        from evals.judges.judges import judge_max_code_lines

        response = "Check this:\n```python\nprint(1)\nprint(2)\n```"
        result = judge_max_code_lines(response, {"max_lines": 5})
        assert result["passed"] is True

    def test_max_code_lines_judge_fails(self):
        from evals.judges.judges import judge_max_code_lines

        lines = "\n".join(f"line_{i}" for i in range(10))
        response = f"Here:\n```python\n{lines}\n```"
        result = judge_max_code_lines(response, {"max_lines": 5})
        assert result["passed"] is False

    def test_json_schema_judge_question(self):
        from evals.judges.judges import judge_json_schema
        import json

        data = {
            "title": "Test",
            "description": "A test problem",
            "solution": "print(1)",
            "test_cases": [{"input": "", "expected_output": "1"}],
        }
        response = f"```json\n{json.dumps(data)}\n```"
        result = judge_json_schema(response, {"schema_name": "question_schema"})
        assert result["passed"] is True

    def test_json_schema_judge_missing_field(self):
        from evals.judges.judges import judge_json_schema
        import json

        data = {"title": "Test", "description": "A test"}
        response = f"```json\n{json.dumps(data)}\n```"
        result = judge_json_schema(response, {"schema_name": "question_schema"})
        assert result["passed"] is False

    def test_min_length_judge(self):
        from evals.judges.judges import judge_min_length

        assert judge_min_length("short", {"min_length": 50})["passed"] is False
        assert judge_min_length("x" * 60, {"min_length": 50})["passed"] is True

    def test_run_judge_dispatcher(self):
        from evals.judges.judges import run_judge

        result = run_judge({"type": "min_length", "min_length": 5}, "hello world")
        assert result["passed"] is True

    def test_run_judge_unknown_type(self):
        from evals.judges.judges import run_judge

        result = run_judge({"type": "nonexistent"}, "hello")
        assert result["passed"] is False


# ── EvalRun Model Tests ──────────────────────────────────────

class TestEvalRunModel:
    def test_create_eval_run(self, db_session, app):
        with app.app_context():
            from app.models.eval_run import EvalRun

            run = EvalRun(
                suite_name="tutor_evals",
                model_name="deepseek-v3",
                total_cases=5,
                passed_cases=4,
                pass_rate=0.8,
                results_json=[{"case_id": "test_001", "passed": True}],
                duration_seconds=12.5,
            )
            db_session.add(run)
            db_session.commit()

            found = EvalRun.query.first()
            assert found.suite_name == "tutor_evals"
            assert found.pass_rate == 0.8
            assert found.total_cases == 5

    def test_eval_run_to_dict(self, db_session, app):
        with app.app_context():
            from app.models.eval_run import EvalRun

            run = EvalRun(
                suite_name="generator_evals",
                total_cases=3,
                passed_cases=3,
                pass_rate=1.0,
            )
            db_session.add(run)
            db_session.commit()

            d = run.to_dict()
            assert d["suite_name"] == "generator_evals"
            assert d["pass_rate"] == 1.0


# ── Memory Injection into Agents Tests ───────────────────────

class TestMemoryInjectionInAgents:
    @patch("agent_host.agents.base.AIConfig")
    def test_tutor_injects_memory_context(self, mock_config, db_session, student_user, app):
        with app.app_context():
            from agent_host.agents.tutor import TutorAgent
            from app.models.student_profile import StudentProfile

            profile = StudentProfile(
                student_id=student_user.id,
                learning_summary="Student struggles with pointer arithmetic",
            )
            db_session.add(profile)
            db_session.commit()

            agent = TutorAgent()
            state = {
                "user_id": student_user.id,
                "user_role": "student",
                "context": {},
            }
            ctx = agent._build_system_context(state)
            assert "pointer arithmetic" in ctx

    @patch("agent_host.agents.base.AIConfig")
    def test_generator_injects_teacher_preferences(self, mock_config, db_session, teacher_user, app):
        with app.app_context():
            from agent_host.agents.generator import GeneratorAgent
            from app.models.student_profile import TeacherPreference

            pref = TeacherPreference(
                teacher_id=teacher_user.id,
                style_notes="Use concise problem descriptions with exactly 2 examples",
            )
            db_session.add(pref)
            db_session.commit()

            agent = GeneratorAgent()
            state = {
                "user_id": teacher_user.id,
                "user_role": "teacher",
                "context": {},
            }
            ctx = agent._build_system_context(state)
            assert "concise problem descriptions" in ctx

    @patch("agent_host.agents.base.AIConfig")
    def test_analytics_injects_memory_context(self, mock_config, db_session, student_user, app):
        with app.app_context():
            from agent_host.agents.analytics import AnalyticsAgent
            from app.models.student_profile import StudentProfile

            profile = StudentProfile(
                student_id=student_user.id,
                learning_summary="Strong in arrays, weak in graphs",
                knowledge_map={"arrays": 0.9, "graphs": 0.2},
            )
            db_session.add(profile)
            db_session.commit()

            agent = AnalyticsAgent()
            state = {
                "user_id": student_user.id,
                "user_role": "student",
                "context": {},
            }
            ctx = agent._build_system_context(state)
            assert "graphs" in ctx


# ── Knowledge Tools Permissions Tests ────────────────────────

class TestKnowledgeToolPermissions:
    def test_tutor_can_use_search_knowledge(self):
        from mcp.policies.rbac import check_rbac, _AGENT_TOOL_ALLOW
        assert "coderunner.knowledge.search" in _AGENT_TOOL_ALLOW["tutor"]
        assert "coderunner.knowledge.search_error_patterns" in _AGENT_TOOL_ALLOW["tutor"]

    def test_generator_can_use_search_similar(self):
        from mcp.policies.rbac import _AGENT_TOOL_ALLOW
        assert "coderunner.knowledge.search_similar_problems" in _AGENT_TOOL_ALLOW["generator"]

    def test_reviewer_cannot_use_knowledge_tools(self):
        from mcp.policies.rbac import _AGENT_TOOL_ALLOW
        assert "coderunner.knowledge.search" not in _AGENT_TOOL_ALLOW["reviewer"]
        assert "coderunner.knowledge.search_similar_problems" not in _AGENT_TOOL_ALLOW["reviewer"]


# ── API Endpoint Tests ───────────────────────────────────────

class TestProfileAPI:
    def test_get_profile_student_empty(self, client, mock_auth_student, mock_redis):
        resp = client.get("/api/v1/ai/profile")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profile"] is None

    def test_get_profile_teacher_empty(self, client, mock_auth_teacher, mock_redis):
        resp = client.get("/api/v1/ai/profile")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["preference"] is None

    def test_update_teacher_preference(self, client, mock_auth_teacher, mock_redis):
        resp = client.put("/api/v1/ai/profile", json={
            "preferred_difficulty": "hard",
            "preferred_language": "c",
            "style_notes": "Be verbose",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["preference"]["preferred_difficulty"] == "hard"
        assert data["preference"]["style_notes"] == "Be verbose"

    def test_update_student_language(self, client, mock_auth_student, mock_redis):
        resp = client.put("/api/v1/ai/profile", json={
            "preferred_language": "java",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profile"]["preferred_language"] == "java"

    def test_eval_history_empty(self, client, mock_auth_teacher, mock_redis):
        resp = client.get("/api/v1/ai/evals/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 0
        assert data["runs"] == []
