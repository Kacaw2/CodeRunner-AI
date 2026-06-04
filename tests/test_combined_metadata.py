"""The Alembic target metadata must see BOTH ORM registries without colliding
on the 7 dual-mapped table names."""


def test_combined_metadata_includes_core_only_tables(app):
    from core.db.metadata import build_target_metadata

    md = build_target_metadata()
    # Previously invisible to Flask-only autogenerate:
    assert "agent_trace_runs" in md.tables
    assert "agent_trace_spans" in md.tables
    assert "eval_case_runs" in md.tables


def test_combined_metadata_dedupes_shared_tables(app):
    from core.db.metadata import build_target_metadata

    md = build_target_metadata()
    # Shared names present exactly once (build did not raise on duplicates):
    for name in ("users", "ai_conversations", "ai_messages",
                 "chat_tasks", "workflow_runs", "workflow_steps", "eval_runs"):
        assert name in md.tables


def test_combined_metadata_shared_table_is_flask_definition(app):
    from core.db.metadata import build_target_metadata
    from app.core.extensions import db

    md = build_target_metadata()
    # Flask's column set wins for a shared table.
    flask_cols = set(db.metadata.tables["users"].columns.keys())
    combined_cols = set(md.tables["users"].columns.keys())
    assert combined_cols == flask_cols
