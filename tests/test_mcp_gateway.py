"""Tests for Phase 3 — MCP Server, API Key management, auth/permission/rate-limit."""

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest

from app import create_app
from app.core.extensions import db as _db
from domain.models.user import User, UserRole
from mcp_gateway.middleware.auth import hash_api_key, verify_api_key
from domain.models.mcp import McpApiKey
from domain.models.mcp import McpAuditLog
from mcp_gateway.middleware import set_caller_info, get_caller_info, _guarded
from mcp_gateway.middleware.rate_limit import check_rate_limit


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
        username="mcp_teacher", password="hashed",
        email="mcp_teacher@test.com", role=UserRole.TEACHER,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def student_user(db_session):
    user = User(
        username="mcp_student", password="hashed",
        email="mcp_student@test.com", role=UserRole.STUDENT,
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


# ── MCP Server creation ──

class TestMcpServerCreation:
    def test_server_registers_all_tools(self):
        from mcp_gateway.server import create_mcp_server, EXPECTED_TOOL_COUNT
        mcp = create_mcp_server()
        tools = list(mcp._tool_manager._tools.keys())
        assert len(tools) == EXPECTED_TOOL_COUNT
        for name in [
            "search_knowledge", "search_similar_problems",
            "get_problem_detail", "get_problem_difficulty_stats",
            "get_student_activity", "get_class_statistics",
            "get_agent_trace", "get_student_summary",
            "execute_code", "save_generated_problem", "check_approval",
        ]:
            assert name in tools


# ── Core logic extraction ──

class TestCoreFunctions:
    def test_search_similar_problems_impl(self):
        from tools.knowledge_search.search import search_similar_problems_impl
        with patch("knowledge.store.get_knowledge_base") as mock_kb:
            mock_kb.return_value.search_similar_problems.return_value = [
                {"id": 1, "title": "Two Sum", "score": 0.95}
            ]
            result = search_similar_problems_impl("two sum", "python", 5)
        assert "similar_problems" in result
        assert len(result["similar_problems"]) == 1

    def test_search_knowledge_impl(self):
        from tools.knowledge_search.search import search_knowledge_impl
        with patch("knowledge.store.get_knowledge_base") as mock_kb:
            mock_kb.return_value.search_knowledge.return_value = [
                {"topic": "Arrays", "content": "..."}
            ]
            result = search_knowledge_impl("arrays")
        assert "relevant_knowledge" in result
        assert len(result["relevant_knowledge"]) == 1

    def test_get_problem_detail_impl_not_found(self, app):
        from tools.problems.queries import get_problem_detail_impl
        with app.app_context():
            result = get_problem_detail_impl(99999)
        assert result == {"error": "Problem not found"}

    def test_get_problem_difficulty_stats_impl_no_variants(self, app):
        from tools.analytics.queries import get_problem_difficulty_stats_impl
        with app.app_context():
            result = get_problem_difficulty_stats_impl(99999)
        assert result["total_submissions"] == 0
        assert "No variants found" in result.get("message", "")


# ── API Key management endpoints ──

class TestApiKeyManagement:
    def test_create_key(self, client, mock_auth_teacher):
        resp = client.post(
            "/api/v1/mcp/keys",
            json={"name": "My Claude Desktop"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "My Claude Desktop"
        assert data["key"].startswith("mcp-")
        assert data["role"] == "teacher"
        assert "Save this key" in data["message"]

    def test_create_key_with_scopes(self, client, mock_auth_teacher):
        resp = client.post(
            "/api/v1/mcp/keys",
            json={"name": "Limited Key", "scopes": ["search_knowledge"]},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["scopes"] == ["knowledge:read"]

    def test_list_keys(self, client, mock_auth_teacher, teacher_user):
        client.post("/api/v1/mcp/keys", json={"name": "Key1"})
        client.post("/api/v1/mcp/keys", json={"name": "Key2"})
        resp = client.get("/api/v1/mcp/keys")
        assert resp.status_code == 200
        keys = resp.get_json()
        assert len(keys) == 2

    def test_revoke_key(self, client, mock_auth_teacher):
        resp = client.post("/api/v1/mcp/keys", json={"name": "Temp Key"})
        key_id = resp.get_json()["id"]
        resp = client.delete(f"/api/v1/mcp/keys/{key_id}")
        assert resp.status_code == 200
        assert resp.get_json()["message"] == "Key revoked"

    def test_revoke_already_revoked(self, client, mock_auth_teacher):
        resp = client.post("/api/v1/mcp/keys", json={"name": "Temp Key"})
        key_id = resp.get_json()["id"]
        client.delete(f"/api/v1/mcp/keys/{key_id}")
        resp = client.delete(f"/api/v1/mcp/keys/{key_id}")
        assert resp.status_code == 400

    def test_revoke_nonexistent(self, client, mock_auth_teacher):
        resp = client.delete("/api/v1/mcp/keys/nonexistent-id")
        assert resp.status_code == 404

    def test_student_cannot_create_key(self, client, mock_auth_student):
        resp = client.post("/api/v1/mcp/keys", json={"name": "Forbidden"})
        assert resp.status_code == 403


# ── API Key verification ──

class TestApiKeyVerification:
    def test_hash_api_key_deterministic(self):
        key = "mcp-test-key-123"
        assert hash_api_key(key) == hash_api_key(key)

    def test_verify_valid_key(self, app, teacher_user, db_session):
        teacher_id = teacher_user.id
        raw_key = "mcp-test-valid-key"
        record = McpApiKey(
            id=str(uuid.uuid4()),
            user_id=teacher_id,
            key_hash=hash_api_key(raw_key),
            name="Test Key",
            role="teacher",
            rate_limit_rpm=30,
        )
        db_session.add(record)
        db_session.commit()

        with patch("mcp_gateway.middleware.auth.get_session", return_value=db_session):
            caller = verify_api_key(raw_key)
        assert caller is not None
        assert caller["user_id"] == teacher_id
        assert caller["role"] == "teacher"

    def test_verify_invalid_key(self, app, db_session):
        with patch("mcp_gateway.middleware.auth.get_session", return_value=db_session):
            caller = verify_api_key("mcp-nonexistent-key")
        assert caller is None

    def test_verify_revoked_key(self, app, teacher_user, db_session):
        from app.core.timezone import now_china
        raw_key = "mcp-revoked-key"
        record = McpApiKey(
            id=str(uuid.uuid4()),
            user_id=teacher_user.id,
            key_hash=hash_api_key(raw_key),
            name="Revoked Key",
            role="teacher",
            revoked_at=now_china(),
        )
        db_session.add(record)
        db_session.commit()

        with patch("mcp_gateway.middleware.auth.get_session", return_value=db_session):
            caller = verify_api_key(raw_key)
        assert caller is None


# ── Middleware: permission + scope + rate limit ──

class TestMiddleware:
    def test_no_caller_returns_auth_error(self):
        set_caller_info(None)

        result = _guarded(lambda: json.dumps({"ok": True}))
        data = json.loads(result)
        assert data["error"]["code"] == "MCP_AUTH_REQUIRED"

    def test_wrong_role_returns_permission_error(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        result = run_guard(
            TOOL_CATALOG["coderunner.trace.get_agent_trace"],
            CallerContext(user_id=1, role="student"),
        )
        assert result.rejected is True
        assert result.error.code.value == "MCP_PERMISSION_DENIED"

    def test_scope_restriction(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        result = run_guard(
            TOOL_CATALOG["coderunner.problem.get_detail"],
            CallerContext(actor_type="external_client", user_id=1, role="teacher"),
            granted_scopes=["search_knowledge"],
        )
        assert result.rejected is True
        assert result.error.code.value == "MCP_SCOPE_DENIED"

    def test_valid_call_passes(self):
        set_caller_info({
            "api_key_id": "k1", "user_id": 1,
            "role": "teacher", "scopes": None, "rate_limit_rpm": 30,
        })

        with patch("mcp_gateway.middleware.core.check_rate_limit", return_value=True):
            result = _guarded(lambda: json.dumps({"ok": True}))
        data = json.loads(result)
        assert data["ok"] is True

    def test_rate_limit_exceeded(self):
        set_caller_info({
            "api_key_id": "k1", "user_id": 1,
            "role": "teacher", "scopes": None, "rate_limit_rpm": 30,
        })

        with patch("mcp_gateway.middleware.core.check_rate_limit", return_value=False):
            result = _guarded(lambda: json.dumps({"ok": True}))
        data = json.loads(result)
        assert data["error"]["code"] == "MCP_RATE_LIMITED"


# ── Rate limiter ──

class TestRateLimiter:
    def test_allows_under_limit(self):
        mock_redis = MagicMock()
        # incr returns the post-increment count for this window
        mock_redis.incr.return_value = 5
        with patch("mcp_gateway.middleware.rate_limit._redis_client", mock_redis):
            assert check_rate_limit("k1", 30) is True

    def test_blocks_over_limit(self):
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 31
        with patch("mcp_gateway.middleware.rate_limit._redis_client", mock_redis):
            assert check_rate_limit("k1", 30) is False

    def test_sets_expiry_only_on_first_hit(self):
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 1
        with patch("mcp_gateway.middleware.rate_limit._redis_client", mock_redis):
            assert check_rate_limit("k1", 30) is True
        mock_redis.expire.assert_called_once_with("mcp_rate:k1", 60)

    def test_no_redis_allows_all(self):
        with patch("mcp_gateway.middleware.rate_limit._redis_client", None):
            assert check_rate_limit("k1", 30) is True

    def test_no_redis_fails_closed_for_high_risk(self):
        # Redis down → cannot throttle. High-risk tools must be denied rather
        # than allowed to flood unbounded.
        with patch("mcp_gateway.middleware.rate_limit._redis_client", None):
            assert check_rate_limit("k1", 30, high_risk=True) is False
            assert check_rate_limit("k1", 30, high_risk=False) is True

    def test_redis_error_fails_closed_for_high_risk(self):
        mock_redis = MagicMock()
        mock_redis.incr.side_effect = RuntimeError("connection reset")
        with patch("mcp_gateway.middleware.rate_limit._redis_client", mock_redis):
            assert check_rate_limit("k1", 30, high_risk=True) is False
            assert check_rate_limit("k1", 30, high_risk=False) is True


class TestGuardedFailClosed:
    """_guarded must fail closed for high-risk tools when Redis is unavailable."""

    def _set_caller(self):
        set_caller_info({
            "api_key_id": "k1", "user_id": 1,
            "role": "teacher", "scopes": None, "rate_limit_rpm": 30,
        })

    def _ensure_registered(self, *canonical_names):
        from tools.protocol.registry import get_registry
        from tools.protocol.schemas.catalog import TOOL_CATALOG
        reg = get_registry()
        for name in canonical_names:
            reg.register(TOOL_CATALOG[name])

    def test_high_risk_denied_when_redis_down(self):
        self._set_caller()
        self._ensure_registered("coderunner.code.execute")
        with patch("mcp_gateway.middleware.rate_limit._redis_client", None):
            result = _guarded(
                lambda: json.dumps({"ok": True}),
                canonical_tool="coderunner.code.execute",
            )
        data = json.loads(result)
        assert data["error"]["code"] == "MCP_RATE_LIMITED"

    def test_low_risk_allowed_when_redis_down(self):
        self._set_caller()
        self._ensure_registered("coderunner.knowledge.search")
        with patch("mcp_gateway.middleware.rate_limit._redis_client", None):
            result = _guarded(
                lambda: json.dumps({"ok": True}),
                canonical_tool="coderunner.knowledge.search",
            )
        data = json.loads(result)
        assert data["ok"] is True


# ── Permission matrix ──

class TestMcpPermissions:
    def test_teacher_allowed(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="teacher")
        for tool in [
            "coderunner.knowledge.search",
            "coderunner.knowledge.search_similar_problems",
            "coderunner.problem.get_detail",
            "coderunner.analytics.problem_difficulty",
        ]:
            desc = TOOL_CATALOG[tool]
            assert run_guard(desc, ctx, granted_scopes=desc.required_scopes).passed

    def test_admin_allowed(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        desc = TOOL_CATALOG["coderunner.knowledge.search"]
        assert run_guard(
            desc,
            CallerContext(user_id=1, role="admin"),
            granted_scopes=desc.required_scopes,
        ).passed

    def test_student_denied_restricted_tools(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="student")
        assert run_guard(TOOL_CATALOG["coderunner.trace.get_agent_trace"], ctx).rejected
        assert run_guard(TOOL_CATALOG["coderunner.student.get_summary"], ctx).rejected

    def test_student_allowed_read_tools(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.guard import run_guard
        from tools.protocol.schemas.catalog import TOOL_CATALOG

        ctx = CallerContext(user_id=1, role="student")
        for tool in ["coderunner.knowledge.search", "coderunner.problem.get_detail"]:
            desc = TOOL_CATALOG[tool]
            assert run_guard(desc, ctx, granted_scopes=desc.required_scopes).passed

    def test_unknown_tool_allowed_by_default(self):
        from core.auth.context import CallerContext
        from tools.protocol.policies.rbac import check_rbac
        from tools.protocol.schemas.descriptors import ToolDescriptor

        check_rbac(
            ToolDescriptor(
                name="nonexistent.tool",
                version="1.0.0",
                description="",
                input_schema={},
                output_schema={},
            ),
            CallerContext(user_id=1, role="teacher"),
        )


# ── Audit logging ──

class TestAuditLog:
    def test_log_tool_call(self, app, db_session):
        from core.observability.audit import log_tool_call
        with patch("core.observability.audit.get_session", return_value=db_session):
            log_tool_call(
                api_key_id=None,
                user_id=None,
                tool_name="search_knowledge",
                tool_args={"query": "test"},
                status="success",
                latency_ms=42,
            )

        logs = db_session.query(McpAuditLog).all()
        assert len(logs) == 1
        assert logs[0].tool_name == "search_knowledge"
        assert logs[0].status == "success"
        assert logs[0].latency_ms == 42


# ── Capability-token replay protection ──

class TestTokenReplay:
    def test_claim_jti_first_use_then_replay(self):
        from mcp_gateway.middleware import rate_limit

        mock_redis = MagicMock()
        # Redis SET NX returns True on first claim, None when the key exists.
        mock_redis.set.side_effect = [True, None]
        with patch.object(rate_limit, "_redis_client", mock_redis):
            assert rate_limit.claim_jti("jti-1", 120) is True
            assert rate_limit.claim_jti("jti-1", 120) is False

    def test_claim_jti_fail_open_without_redis(self):
        from mcp_gateway.middleware import rate_limit

        with patch.object(rate_limit, "_redis_client", None):
            assert rate_limit.claim_jti("jti-x", 120) is True

    def test_resolve_caller_rejects_replayed_token(self):
        from mcp_gateway.middleware import core

        claims = {"sub": "1", "role": "student", "agent_type": "tutor",
                  "scopes": [], "jti": "abc", "exp": 9999999999}
        # verify_*/load_* are imported inside the function, so patch them at
        # their source module; claim_jti is bound on core at import time.
        with patch("mcp_gateway.internal_auth.load_verify_key_from_env", return_value="k"), \
             patch("mcp_gateway.internal_auth.verify_internal_token", return_value=claims), \
             patch.object(core, "claim_jti", return_value=False):
            assert core.resolve_caller_from_bearer("token") is None
