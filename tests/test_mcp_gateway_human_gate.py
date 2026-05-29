"""Tests for Phase 4 — Human Gate, sanitization, approval flow, write tools."""

import json
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest

from app import create_app
from app.core.extensions import db as _db
from app.core.timezone import now_china
from app.models.user import User, UserRole


@pytest.fixture(scope="module")
def app():
    application = create_app("testing")
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    application.config["SERVER_NAME"] = "localhost"
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture(autouse=True)
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


@pytest.fixture()
def client(app, db_session):
    return app.test_client()


@pytest.fixture()
def teacher_user(db_session):
    user = User(
        username="p4_teacher", password="hashed",
        email="p4_teacher@test.com", role=UserRole.TEACHER,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def student_user(db_session):
    user = User(
        username="p4_student", password="hashed",
        email="p4_student@test.com", role=UserRole.STUDENT,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def mock_auth_teacher(teacher_user):
    with patch("app.auth.decorators.get_current_user_or_401", return_value=teacher_user), \
         patch("app.auth.decorators._try_get_user_from_sources", return_value=teacher_user):
        yield teacher_user


@pytest.fixture()
def mock_auth_student(student_user):
    with patch("app.auth.decorators.get_current_user_or_401", return_value=student_user), \
         patch("app.auth.decorators._try_get_user_from_sources", return_value=student_user):
        yield student_user


# ── Sanitization ──

class TestSanitization:
    def test_sanitize_agent_trace_removes_system_prompt(self):
        from mcp_gateway.middleware.sanitizer import sanitize_agent_trace

        run = {
            "id": "run-1",
            "input_context": {
                "system_prompt": "SECRET PROMPT",
                "system_message": "SECRET MSG",
                "user_query": "How to sort?",
            },
        }
        steps = [
            {
                "tool_name": "execute_code",
                "tool_input": {"code": "x" * 300, "language": "python"},
                "tool_output_preview": "y" * 500,
            }
        ]

        result = sanitize_agent_trace(run, steps)

        assert "system_prompt" not in result["run"]["input_context"]
        assert "system_message" not in result["run"]["input_context"]
        assert result["run"]["input_context"]["user_query"] == "How to sort?"

        assert len(result["steps"][0]["tool_input"]["code"]) == 203  # 200 + "..."
        assert len(result["steps"][0]["tool_output_preview"]) == 300

    def test_sanitize_agent_trace_short_code_unchanged(self):
        from mcp_gateway.middleware.sanitizer import sanitize_agent_trace

        run = {"input_context": {}}
        steps = [{"tool_input": {"code": "print(1)"}, "tool_output_preview": "1"}]

        result = sanitize_agent_trace(run, steps)
        assert result["steps"][0]["tool_input"]["code"] == "print(1)"

    def test_sanitize_student_summary_no_pii(self):
        from mcp_gateway.middleware.sanitizer import sanitize_student_summary

        profile = {
            "preferred_language": "python",
            "error_patterns": {"off-by-one": 3, "null-ref": 1},
            "knowledge_map": {"arrays": 0.8, "loops": 0.7, "trees": 0.5},
            "username": "should_not_appear",
            "email": "should_not_appear@test.com",
        }
        stats = {
            "total_submissions": 42,
            "acceptance_rate": 0.76,
            "active_days": 15,
            "current_streak": 3,
        }

        result = sanitize_student_summary(99, profile, stats)

        assert result["student_id"] == 99
        assert result["preferred_language"] == "python"
        assert "off-by-one" in result["weak_topics"]
        assert "arrays" in result["strong_topics"]
        assert result["total_submissions"] == 42
        assert "username" not in result
        assert "email" not in result


# ── MCP Server tool count ──

class TestMcpServerPhase4:
    def test_server_registers_full_tool_surface(self):
        from mcp_gateway.server import create_mcp_server
        from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP
        mcp = create_mcp_server()
        tools = set(mcp._tool_manager._tools.keys())
        assert tools == set(EXTERNAL_TOOL_MAP)


# ── Permission matrix (Phase 4 additions) ──

class TestPhase4Permissions:
    def test_teacher_allowed_medium_risk(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="teacher")
        assert run_guard(TOOL_CATALOG["coderunner.trace.get_agent_trace"], ctx).passed
        assert run_guard(TOOL_CATALOG["coderunner.student.get_summary"], ctx).passed

    def test_teacher_allowed_high_risk(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="teacher")
        assert run_guard(TOOL_CATALOG["coderunner.code.execute"], ctx).error.code.value == "MCP_APPROVAL_REQUIRED"
        assert run_guard(TOOL_CATALOG["coderunner.problem.save_generated"], ctx).error.code.value == "MCP_APPROVAL_REQUIRED"

    def test_admin_allowed_all(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="admin")
        for tool in ["coderunner.trace.get_agent_trace", "coderunner.student.get_summary"]:
            assert run_guard(TOOL_CATALOG[tool], ctx).passed
        for tool in ["coderunner.code.execute", "coderunner.problem.save_generated"]:
            assert run_guard(TOOL_CATALOG[tool], ctx).error.code.value == "MCP_APPROVAL_REQUIRED"

    def test_student_denied_medium_risk(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="student")
        assert run_guard(TOOL_CATALOG["coderunner.trace.get_agent_trace"], ctx).rejected
        assert run_guard(TOOL_CATALOG["coderunner.student.get_summary"], ctx).rejected

    def test_student_denied_high_risk_write(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="student")
        assert run_guard(TOOL_CATALOG["coderunner.code.execute"], ctx).error.code.value == "MCP_APPROVAL_REQUIRED"
        assert run_guard(TOOL_CATALOG["coderunner.problem.save_generated"], ctx).error.code.value == "MCP_PERMISSION_DENIED"


# ── Risk levels ──

class TestRiskLevels:
    def test_all_tools_have_risk_level(self):
        from tools.protocol.schemas.catalog import TOOL_CATALOG
        expected_tools = {
            "coderunner.knowledge.search", "coderunner.knowledge.search_similar_problems",
            "coderunner.problem.get_detail", "coderunner.analytics.problem_difficulty",
            "coderunner.analytics.student_activity", "coderunner.analytics.class_statistics",
            "coderunner.trace.get_agent_trace", "coderunner.student.get_summary",
            "coderunner.code.execute", "coderunner.problem.save_generated",
        }
        assert expected_tools <= set(TOOL_CATALOG)

    def test_high_risk_tools(self):
        from tools.protocol.schemas.catalog import TOOL_CATALOG
        assert TOOL_CATALOG["coderunner.code.execute"].risk_level.value == "high"
        assert TOOL_CATALOG["coderunner.problem.save_generated"].risk_level.value == "high"

    def test_medium_risk_tools(self):
        from tools.protocol.schemas.catalog import TOOL_CATALOG
        assert TOOL_CATALOG["coderunner.trace.get_agent_trace"].risk_level.value == "medium"
        assert TOOL_CATALOG["coderunner.student.get_summary"].risk_level.value == "medium"


# ── McpToolApproval model ──

class TestApprovalModel:
    def test_create_approval(self, app, db_session, teacher_user):
        from core.db.models.mcp_approval import McpToolApproval

        approval = McpToolApproval(
            id=str(uuid.uuid4()),
            user_id=teacher_user.id,
            tool_name="execute_code",
            tool_args={"code": "print(1)", "language": "python"},
            status="pending",
            expires_at=McpToolApproval.default_expiry(),
            created_at=now_china(),
        )
        db_session.add(approval)
        db_session.commit()

        fetched = db_session.get(McpToolApproval, approval.id)
        assert fetched is not None
        assert fetched.tool_name == "execute_code"
        assert fetched.status == "pending"

    def test_expiration_check(self, app, db_session, teacher_user):
        from core.db.models.mcp_approval import McpToolApproval

        approval = McpToolApproval(
            id=str(uuid.uuid4()),
            user_id=teacher_user.id,
            tool_name="execute_code",
            tool_args={"code": "print(1)"},
            status="pending",
            expires_at=now_china() - timedelta(minutes=1),
            created_at=now_china() - timedelta(minutes=31),
        )
        db_session.add(approval)
        db_session.commit()

        approval.check_expiration()
        assert approval.status == "expired"

    def test_to_dict(self, app, db_session, teacher_user):
        from core.db.models.mcp_approval import McpToolApproval

        approval = McpToolApproval(
            id=str(uuid.uuid4()),
            user_id=teacher_user.id,
            tool_name="save_generated_problem",
            tool_args={"question_data": {}},
            status="pending",
            expires_at=McpToolApproval.default_expiry(),
            created_at=now_china(),
        )
        db_session.add(approval)
        db_session.commit()

        d = approval.to_dict()
        assert d["tool_name"] == "save_generated_problem"
        assert d["status"] == "pending"
        assert "expires_at" in d


# ── Flask approval endpoints ──

class TestApprovalEndpoints:
    def _create_approval(self, db_session, teacher_user):
        from core.db.models.mcp_approval import McpToolApproval

        approval = McpToolApproval(
            id=str(uuid.uuid4()),
            user_id=teacher_user.id,
            tool_name="execute_code",
            tool_args={"code": "print(42)", "language": "python"},
            status="pending",
            expires_at=McpToolApproval.default_expiry(),
            created_at=now_china(),
        )
        db_session.add(approval)
        db_session.commit()
        return approval

    def test_list_approvals(self, client, mock_auth_teacher, teacher_user, db_session):
        self._create_approval(db_session, teacher_user)
        resp = client.get("/api/v1/mcp/approvals")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["tool_name"] == "execute_code"

    def test_list_approvals_filter_status(self, client, mock_auth_teacher, teacher_user, db_session):
        self._create_approval(db_session, teacher_user)
        resp = client.get("/api/v1/mcp/approvals?status=approved")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 0

    def test_get_approval_detail(self, client, mock_auth_teacher, teacher_user, db_session):
        approval = self._create_approval(db_session, teacher_user)
        resp = client.get(f"/api/v1/mcp/approvals/{approval.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == approval.id
        assert data["tool_args"]["code"] == "print(42)"

    def test_get_approval_not_found(self, client, mock_auth_teacher):
        resp = client.get("/api/v1/mcp/approvals/nonexistent")
        assert resp.status_code == 404

    def test_approve_flow(self, client, mock_auth_teacher, teacher_user, db_session):
        approval = self._create_approval(db_session, teacher_user)
        resp = client.post(
            f"/api/v1/mcp/approvals/{approval.id}/approve",
            json={"notes": "Looks safe"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "approved"

        resp = client.get(f"/api/v1/mcp/approvals/{approval.id}")
        assert resp.get_json()["status"] == "approved"

    def test_reject_flow(self, client, mock_auth_teacher, teacher_user, db_session):
        approval = self._create_approval(db_session, teacher_user)
        resp = client.post(
            f"/api/v1/mcp/approvals/{approval.id}/reject",
            json={"reason": "Dangerous code"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "rejected"

    def test_cannot_approve_rejected(self, client, mock_auth_teacher, teacher_user, db_session):
        approval = self._create_approval(db_session, teacher_user)
        client.post(f"/api/v1/mcp/approvals/{approval.id}/reject",
                     json={"reason": "No"})
        resp = client.post(f"/api/v1/mcp/approvals/{approval.id}/approve")
        assert resp.status_code == 400

    def test_student_cannot_list_approvals(self, client, mock_auth_student):
        resp = client.get("/api/v1/mcp/approvals")
        assert resp.status_code == 403


# ── Core logic extraction ──

class TestPhase4CoreFunctions:
    def test_get_agent_trace_impl_not_found(self, app):
        from tools.traces.queries import get_agent_trace_impl
        with app.app_context():
            result = get_agent_trace_impl("nonexistent-run-id")
        assert result == {"error": "Agent run not found"}

    def test_get_student_summary_impl_not_found(self, app):
        from tools.students.summary import get_student_summary_impl
        with app.app_context():
            result = get_student_summary_impl(99999)
        assert result == {"error": "Student not found"}

    def test_execute_code_impl(self):
        from tools.code.executor import execute_code_impl
        with patch("app.services.executor_service.ExecutorService.run_code") as mock:
            mock.return_value = {
                "status": "AC",
                "stdout": "hello\n",
                "stderr": "",
                "time_ms": 50,
            }
            result = execute_code_impl("print('hello')", "python")
        assert result["status"] == "AC"
        assert result["stdout"] == "hello\n"

    def test_save_generated_problem_impl(self, app, db_session):
        from tools.problems.write import save_generated_problem_impl
        teacher = User(
            username="gen_teacher", password="h",
            email="gen@test.com", role=UserRole.TEACHER,
        )
        db_session.add(teacher)
        db_session.flush()

        result = save_generated_problem_impl(
            question_data={"title": "Test Q", "difficulty": "easy"},
            teacher_id=teacher.id,
        )
        assert "draft_id" in result
        assert result["status"] == "pending_review"


# ── Code validation in write tools ──

class TestCodeValidation:
    def test_code_max_length(self):
        from mcp_gateway.middleware import CODE_MAX_LENGTH
        assert CODE_MAX_LENGTH == 10_000

    def test_allowed_languages(self):
        from mcp_gateway.middleware import ALLOWED_LANGUAGES
        assert ALLOWED_LANGUAGES == {"python", "c"}
