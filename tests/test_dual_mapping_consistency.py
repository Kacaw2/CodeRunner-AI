# tests/test_dual_mapping_consistency.py
"""While the 7 tables remain dual-mapped, the core (runtime) registry must
never carry a column the authoritative Flask model lacks, and shared columns
must keep compatible types. Core MAY be a read-only subset (e.g. users)."""

import pytest

SHARED_TABLES = [
    "ai_conversations", "ai_messages", "chat_tasks",
    "workflow_runs", "workflow_steps", "eval_runs", "users",
]

# Known, accepted projection mismatches (core read-only views). Each entry is
# a deliberate divergence, not drift: revisit when the table is de-duplicated.
ACCEPTED_TYPE_MISMATCH = {("users", "role")}  # Flask Enum(UserRole) vs core String


@pytest.fixture(scope="module")
def both_registries():
    # Importing the combined metadata builder forces BOTH app.models and
    # core.db.models submodules to import and register their tables.
    from core.db.metadata import build_target_metadata
    build_target_metadata()
    from app.core.extensions import db
    from core.db.session import Base
    return db.metadata, Base.metadata


@pytest.mark.parametrize("table", SHARED_TABLES)
def test_core_columns_are_subset_of_flask(both_registries, table):
    flask_md, core_md = both_registries
    flask_cols = set(flask_md.tables[table].columns.keys())
    core_cols = set(core_md.tables[table].columns.keys())
    extra = core_cols - flask_cols
    assert not extra, (
        f"{table}: core/db/models defines columns absent from the "
        f"authoritative Flask model: {sorted(extra)}. Update app/models or "
        f"remove them from core."
    )


@pytest.mark.parametrize("table", SHARED_TABLES)
def test_shared_column_types_are_compatible(both_registries, table):
    flask_md, core_md = both_registries
    flask_t = flask_md.tables[table]
    core_t = core_md.tables[table]
    for name in set(core_t.columns.keys()) & set(flask_t.columns.keys()):
        if (table, name) in ACCEPTED_TYPE_MISMATCH:
            continue
        flask_type = flask_t.columns[name].type.__class__.__name__
        core_type = core_t.columns[name].type.__class__.__name__
        assert flask_type == core_type, (
            f"{table}.{name}: type drift — Flask={flask_type} core={core_type}"
        )
