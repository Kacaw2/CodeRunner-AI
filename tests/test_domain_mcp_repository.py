"""MCP domain mapping and repository contracts."""

from __future__ import annotations

import inspect

from app.models.user import User, UserRole


def test_legacy_mcp_modules_reexport_domain_mappings():
    from core.db.models.mcp_api_key import McpApiKey as LegacyApiKey
    from core.db.models.mcp_approval import McpToolApproval as LegacyApproval
    from core.db.models.mcp_audit_log import McpAuditLog as LegacyAuditLog
    from domain.models.mcp import McpApiKey, McpAuditLog, McpToolApproval

    assert LegacyApiKey is McpApiKey
    assert LegacyApproval is McpToolApproval
    assert LegacyAuditLog is McpAuditLog


def test_mcp_domain_models_do_not_import_flask_extensions():
    from domain.models import mcp

    source = inspect.getsource(mcp)
    assert "app.core.extensions" not in source
    assert "db.Model" not in source


def test_sync_mcp_repository_manages_keys_approvals_and_audit(db_session):
    from domain.models.mcp import McpApiKey
    from domain.repositories.mcp import SyncMcpRepository

    user = User(
        username="mcp-repository-user",
        password="hashed",
        email="mcp-repository@test.com",
        role=UserRole.TEACHER,
    )
    db_session.add(user)
    db_session.flush()

    repo = SyncMcpRepository(db_session)
    key = repo.add_api_key(
        McpApiKey(
            id="repository-key",
            user_id=user.id,
            key_hash="hash-value",
            name="Repository key",
            role="teacher",
            scopes=["problem:read"],
            rate_limit_rpm=30,
        )
    )
    db_session.flush()

    assert repo.get_active_api_key_by_hash("hash-value") is key
    assert repo.get_api_key_for_user("repository-key", user.id) is key
    assert repo.list_api_keys_for_user(user.id) == [key]

    approval = repo.create_approval(
        id="repository-approval",
        api_key_id=key.id,
        user_id=user.id,
        tool_name="coderunner.code.execute",
        tool_args={"code": "print(1)"},
        risk_level="high",
        status="pending",
    )
    audit = repo.add_audit_log(
        api_key_id=key.id,
        user_id=user.id,
        tool_name="coderunner.problem.get_detail",
        tool_args={"problem_id": 1},
        status="success",
        latency_ms=12,
    )
    db_session.flush()

    assert repo.get_approval(approval.id) is approval
    assert repo.list_approvals(status="pending", limit=50) == [approval]
    assert audit.api_key_id == key.id


def test_sync_mcp_repository_does_not_commit(db_session):
    from domain.models.mcp import McpApiKey
    from domain.repositories.mcp import SyncMcpRepository

    user = User(
        username="mcp-no-autocommit",
        password="hashed",
        email="mcp-no-autocommit@test.com",
        role=UserRole.TEACHER,
    )
    db_session.add(user)
    db_session.flush()

    repo = SyncMcpRepository(db_session)
    repo.add_api_key(
        McpApiKey(
            id="uncommitted-key",
            user_id=user.id,
            key_hash="uncommitted-hash",
            name="Uncommitted key",
            role="teacher",
        )
    )
    db_session.flush()
    assert repo.get_active_api_key_by_hash("uncommitted-hash") is not None

    db_session.rollback()

    assert repo.get_active_api_key_by_hash("uncommitted-hash") is None
