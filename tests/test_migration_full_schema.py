"""Gate test: ``alembic upgrade head`` must build the COMPLETE core schema.

This is the executable acceptance criterion for making the Alembic migration
chain the single source of truth for the database schema, so that the test and
startup paths can eventually drop ``db.create_all()``.

Current state (why this is ``xfail``):
    The migration chain has NO baseline migration that creates the core ORM
    tables (``users``, ``questions``, ``problems``, ``submissions`` ...). The
    base revision ``f9bf29de9f8f`` is an empty ``pass`` stamp, and later
    revisions only apply *incremental* deltas (``op.batch_alter_table`` /
    ``op.add_column``) on top of a schema that production builds with
    ``db.create_all()``. Running ``upgrade head`` against a truly empty DB
    therefore fails at the first ALTER (``questions`` does not exist yet).

When the chain is completed (a baseline migration creates the full schema),
this gate turns green; ``create_all()`` can then be removed from
``tests/conftest.py`` and ``app/__init__.py``'s startup path.

Running locally:
    * With Docker:        ``pytest tests/test_migration_full_schema.py`` —
      a throwaway MySQL container is started via testcontainers.
    * With your own DB:   ``TEST_MYSQL_URL=mysql+pymysql://user:pass@host:port``
      (a user that can CREATE/DROP DATABASE) then run the same command. A
      uniquely-named empty schema is created, migrated, and dropped.
"""
import os
import uuid

import pytest


def _expected_core_tables() -> set[str]:
    """Every table the application's models declare = the schema migrations
    must be able to build on their own."""
    import importlib
    import pkgutil

    import app.models as models_pkg

    # Import every model module so all tables register on db.metadata
    # (app.models.__init__ intentionally omits some, e.g. ai_conversation).
    for module in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{module.name}")

    from app.core.extensions import db
    import core.db.session as core_session
    import core.db.models.agent_trace  # noqa: F401  register trace/eval tables

    # .tables.keys() lists names without forcing FK resolution (avoids
    # NoReferencedTableError when a target lives in another metadata).
    flask_tables = set(db.metadata.tables.keys())
    core_tables = set(core_session.Base.metadata.tables.keys())
    return flask_tables | core_tables


def _docker_available() -> bool:
    try:
        import docker  # testcontainers pulls this in

        docker.from_env().ping()
        return True
    except Exception:
        return False


def _upgrade_and_list_tables(database_url: str) -> set[str]:
    """Build a bare Flask app bound to ``database_url``, run ``upgrade head``
    (NO ``create_all``), and return the resulting table names."""
    from flask import Flask
    from flask_migrate import upgrade
    from sqlalchemy import inspect

    from app.core.extensions import db, migrate
    import app.models  # noqa: F401

    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)

    with flask_app.app_context():
        upgrade()  # schema is built PURELY from the migration chain
        return set(inspect(db.engine).get_table_names())


def _provision_empty_database():
    """Yield an empty MySQL database URL. Prefers an explicit ``TEST_MYSQL_URL``
    (server endpoint, no database) and falls back to a testcontainers MySQL."""
    server_url = os.environ.get("TEST_MYSQL_URL")
    if server_url:
        from sqlalchemy import create_engine, text

        schema = f"migtest_{uuid.uuid4().hex[:12]}"
        engine = create_engine(server_url)
        with engine.begin() as conn:
            conn.execute(text(f"CREATE DATABASE `{schema}`"))
        try:
            base = server_url.rstrip("/")
            yield f"{base}/{schema}?charset=utf8mb4"
        finally:
            with engine.begin() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS `{schema}`"))
            engine.dispose()
        return

    if not _docker_available():
        pytest.skip(
            "Need a MySQL test DB: start Docker (testcontainers) or set TEST_MYSQL_URL"
        )
    mysql = pytest.importorskip("testcontainers.mysql")
    with mysql.MySqlContainer("mysql:8.0") as container:
        url = container.get_connection_url()
        if url.startswith("mysql://"):
            url = url.replace("mysql://", "mysql+pymysql://", 1)
        yield url


@pytest.fixture()
def empty_mysql_url():
    yield from _provision_empty_database()


def test_alembic_upgrade_head_builds_complete_core_schema(empty_mysql_url):
    expected = _expected_core_tables()

    actual = _upgrade_and_list_tables(empty_mysql_url)

    missing = expected - actual
    assert not missing, f"Migrations did not create core tables: {sorted(missing)}"
