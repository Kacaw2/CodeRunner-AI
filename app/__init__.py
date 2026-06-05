# app/__init__.py
import os
import threading
from flask import Flask
from app.core.config import config
from app.core.extensions import init_extensions

def create_app(config_name=None):
    # 1. Use environment variable to determine which config to use, default to config's default
    env_name = config_name or os.getenv("FLASK_ENV", "default")

    app = Flask(__name__)
    app.config.from_object(config.get(env_name, config["default"]))

    # P0: SECRET_KEY gate — refuse to boot in production with insecure key.
    # Development (DEBUG=True) and Testing (TESTING=True) are exempt.
    if not app.config.get("DEBUG") and not app.config.get("TESTING"):
        sk = app.config.get("SECRET_KEY")
        if not sk or sk == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "SECRET_KEY is unset or using the insecure default. "
                "Set the SECRET_KEY env var before starting in production."
            )

    # 2. Prevent sqlite path not existing: if it's sqlite:////xxx, create the directory
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:////"):
        db_path = uri.replace("sqlite:////", "", 1)   # /opt/data/app.db
        db_dir = os.path.dirname(db_path)             # /opt/data
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    # 3. Initialize extensions (db, api, migrate...)
    init_extensions(app)

    # 4. Register blueprints
    register_blueprints(app)

    # 5. Adopt one engine for the whole Flask process, then verify schema
    with app.app_context():
        from app.core.extensions import db
        from core.db import session as core_session
        core_session.set_engine(db.engine)
        _ensure_tables(app)

    # 6. Startup tasks
    with app.app_context():
        _recover_orphaned_tasks(app)
        if app.config.get("ENABLE_KB_STARTUP_INDEX", False):
            _async_index_knowledge_base(app)

    # 7. Register CLI commands
    _register_cli_commands(app)

    return app


def _ensure_tables(app):
    """Verify the schema was migrated. Does NOT create tables — the schema is
    owned by Alembic now (run `flask db upgrade head` on deploy)."""
    try:
        from app.core.extensions import db
        from sqlalchemy import inspect
        existing = set(inspect(db.engine).get_table_names())
        required = {
            "users", "agent_trace_runs", "chat_tasks", "workflow_runs",
            "mcp_api_keys", "mcp_audit_logs", "mcp_tool_approvals",
        }
        missing = required - existing
        if missing:
            app.logger.error(
                "Startup: schema missing %s — run `flask db upgrade head`", missing
            )
        else:
            app.logger.info("Startup: schema present (Alembic-managed)")
    except Exception as e:
        app.logger.error("Startup: schema check FAILED: %s", e, exc_info=True)


def _recover_orphaned_tasks(app):
    """C1: Resume tasks that were running when the server last crashed."""
    try:
        from graph.recovery import recover_orphaned_tasks, recover_orphaned_workflows
        recovered = recover_orphaned_tasks()
        if recovered:
            app.logger.info("Startup: recovered %d orphaned tasks", recovered)
        else:
            app.logger.info("Startup: no orphaned tasks found")

        recovered_workflows = recover_orphaned_workflows()
        if recovered_workflows:
            app.logger.info("Startup: recovered %d orphaned workflows", recovered_workflows)
        else:
            app.logger.info("Startup: no orphaned workflows found")
    except Exception as e:
        app.logger.warning("Startup: orphan recovery skipped: %s", e)


def _async_index_knowledge_base(app):
    """C2 + D1/D2: Index questions and seed knowledge base (background thread)."""
    def _do_index():
        with app.app_context():
            try:
                from knowledge.store import index_all_problems
                count = index_all_problems()
                app.logger.info("Knowledge base indexing complete: %d questions", count)
            except Exception as e:
                app.logger.warning("Knowledge base indexing skipped: %s", e)

            try:
                from scripts.seed_knowledge import seed_all
                err_count, kp_count = seed_all()
                if err_count or kp_count:
                    app.logger.info("Knowledge base seeded: %d error patterns, %d knowledge points",
                                    err_count, kp_count)
            except Exception as e:
                app.logger.warning("Knowledge base seeding skipped: %s", e)

    threading.Thread(target=_do_index, daemon=True).start()


def _register_cli_commands(app):
    """Register Flask CLI commands."""
    try:
        from scripts.seed_knowledge import register_cli
        register_cli(app)
    except Exception as e:
        app.logger.debug("CLI command registration skipped: %s", e)
    try:
        from scripts.migrate_kb import register_cli as register_migrate_cli
        register_migrate_cli(app)
    except Exception as e:
        app.logger.debug("KB migrate CLI registration skipped: %s", e)


def register_blueprints(app):
    from app.core.extensions import api
    
    from app.api.public.health import health_bp
    app.register_blueprint(health_bp)

    from app.api.v1.auth import bp as auth_api_bp
    api.register_blueprint(auth_api_bp)

    from app.api.v1.questions import blp as questions_blp
    from app.api.v1.questions import public_blp as questions_public_blp
    api.register_blueprint(questions_blp)
    api.register_blueprint(questions_public_blp)

    from app.api.v1.submissions import blp as submissions_blp
    api.register_blueprint(submissions_blp)

    from app.api.v1.judge import bp as judge_bp
    app.register_blueprint(judge_bp)

    from app.api.v1.grades import blp as grades_blp
    api.register_blueprint(grades_blp)

    from app.api.v1.classrooms import blp as classrooms_blp
    api.register_blueprint(classrooms_blp)

    from app.api.v1.quizzes import blp as quizzes_blp
    api.register_blueprint(quizzes_blp)

    from app.api.v1.problems import blp as problems_blp
    api.register_blueprint(problems_blp)

    from app.api.v1.teacher_stats import blp as teacher_stats_blp
    api.register_blueprint(teacher_stats_blp)

    from app.api.v1.teacher_students import blp as teacher_students_blp
    api.register_blueprint(teacher_students_blp)
    
    from app.api.v1.user_profile import blp as user_profile_blp
    api.register_blueprint(user_profile_blp)


    # === Public API Endpoints ===

    from app.api.public import public_bp
    app.register_blueprint(public_bp)
 
    from app.api.public.quizzes import public_quiz_blp
    api.register_blueprint(public_quiz_blp)

    from app.web import main_bp, auth_bp, student_bp, teacher_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(teacher_bp)

    from app.web.question import question_bp
    app.register_blueprint(question_bp)

    from app.web.submissions import submissions_web_bp
    app.register_blueprint(submissions_web_bp)

    from app.api.v1.ai import bp as ai_bp
    app.register_blueprint(ai_bp)

    from app.api.v1.mcp_keys import bp as mcp_keys_bp
    app.register_blueprint(mcp_keys_bp)

    from app.api.v1.mcp_approvals import bp as mcp_approvals_bp
    app.register_blueprint(mcp_approvals_bp)

    from app.web.ai_chat import ai_chat_bp
    app.register_blueprint(ai_chat_bp)
