"""Flask and core must derive the production DB URL from ONE source, so a
one-sided edit can never point the two layers at different databases."""


def test_flask_base_config_uses_core_db_url():
    from app.core.config import Config
    from core.config import get_settings

    assert Config.SQLALCHEMY_DATABASE_URI == get_settings().DB_URL
