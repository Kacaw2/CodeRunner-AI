"""
Knowledge Base Migration Script

Deletes old collections (which used L2 distance and per-Question indexing)
and rebuilds them with cosine distance at Problem-level granularity.

Usage:
    # Inside Docker or with the venv activated:
    python -m scripts.migrate_kb

    # Or via Flask CLI:
    flask kb-migrate
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

COLLECTION_NAMES = ["questions", "knowledge_points", "error_patterns"]


def migrate(app=None):
    if app is None:
        from app import create_app
        app = create_app()

    with app.app_context():
        from app.agents.knowledge_base import get_knowledge_base, index_all_problems
        import app.agents.knowledge_base as kb_module

        kb = get_knowledge_base()
        client = kb.client

        logger.info("=== Knowledge Base Migration ===")

        for name in COLLECTION_NAMES:
            try:
                old = client.get_collection(name)
                old_count = old.count()
                logger.info("Deleting collection '%s' (%d entries)...", name, old_count)
                client.delete_collection(name)
            except Exception:
                logger.info("Collection '%s' does not exist, skipping delete.", name)

        kb_module._kb_instance = None
        kb = get_knowledge_base()

        for name in COLLECTION_NAMES:
            col = client.get_collection(name)
            space = col.metadata.get("hnsw:space", "unknown")
            logger.info("Recreated collection '%s' with distance=%s", name, space)

        logger.info("Re-indexing all problems...")
        count = index_all_problems()
        logger.info("Indexed %d problems.", count)

        logger.info("Re-seeding knowledge points and error patterns...")
        try:
            from scripts.seed_knowledge import seed_all
            err_count, kp_count = seed_all()
            logger.info("Seeded %d error patterns, %d knowledge points.", err_count, kp_count)
        except Exception as e:
            logger.warning("Seeding skipped: %s", e)

        logger.info("=== Migration complete ===")


def register_cli(app):
    @app.cli.command("kb-migrate")
    def kb_migrate_cmd():
        """Delete old KB collections and rebuild with cosine distance."""
        migrate(app)


if __name__ == "__main__":
    migrate()
