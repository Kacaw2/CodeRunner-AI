"""The Alembic target metadata is the single ``DomainBase.metadata`` and must
expose the full schema (Flask-owned tables AND the trace/eval tables)."""


def test_target_metadata_is_the_single_domain_metadata(app):
    from core.db.metadata import build_target_metadata
    from domain.base import DomainBase

    # One registry, one metadata: build_target_metadata returns it directly.
    assert build_target_metadata() is DomainBase.metadata


def test_target_metadata_includes_trace_tables(app):
    from core.db.metadata import build_target_metadata

    md = build_target_metadata()
    # Trace/eval tables register on the same metadata as the Flask models.
    assert "agent_trace_runs" in md.tables
    assert "agent_trace_spans" in md.tables
    assert "eval_case_runs" in md.tables


def test_target_metadata_includes_flask_tables(app):
    from core.db.metadata import build_target_metadata

    md = build_target_metadata()
    # Each shared/Flask table appears exactly once (no duplicate-name collision).
    for name in ("users", "ai_conversations", "ai_messages",
                 "chat_tasks", "workflow_runs", "workflow_steps", "eval_runs"):
        assert name in md.tables


def test_target_metadata_matches_flask_metadata(app):
    from core.db.metadata import build_target_metadata
    from app.core.extensions import db

    md = build_target_metadata()
    # db.metadata IS DomainBase.metadata, so a shared table's columns match.
    flask_cols = set(db.metadata.tables["users"].columns.keys())
    target_cols = set(md.tables["users"].columns.keys())
    assert target_cols == flask_cols
