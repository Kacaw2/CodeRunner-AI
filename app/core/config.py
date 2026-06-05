# app/core/config.py
import os
class Config:
    """Base configuration"""
    # Application configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False
    TESTING = False

    # Single source of truth for the DB URL — core builds it once
    # (DATABASE_URL → MYSQL_* → DB_* precedence lives in core/config.py).
    from core.config import get_settings as _get_core_settings
    SQLALCHEMY_DATABASE_URI = _get_core_settings().DB_URL

    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False  # Set to True to see SQL statements in logs
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }
    
    # API documentation configuration
    API_TITLE = 'Code Runner API'
    API_VERSION = 'v1'
    OPENAPI_VERSION = '3.0.3'
    OPENAPI_URL_PREFIX = '/'
    OPENAPI_SWAGGER_UI_PATH = '/swagger-ui'
    OPENAPI_SWAGGER_UI_URL = 'https://cdn.jsdelivr.net/npm/swagger-ui-dist/'
    
    # Code execution configuration
    MAX_EXECUTION_TIME = 5  # Maximum execution time in seconds
    MAX_MEMORY_USAGE = 128 * 1024  # Maximum memory usage in KB

    # AI Agent configuration
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
    AI_MODEL = os.environ.get('AI_MODEL', 'deepseek-chat')
    AI_MAX_TOKENS = int(os.environ.get('AI_MAX_TOKENS', '2048'))
    AI_TEMPERATURE = float(os.environ.get('AI_TEMPERATURE', '0.7'))
    AI_RATE_LIMIT = int(os.environ.get('AI_RATE_LIMIT', '20'))
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # Cookie security
    SESSION_COOKIE_SECURE = False
    AUTH_COOKIE_SECURE = False


class DevelopmentConfig(Config):
    """Development environment configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True  # Show SQL statements in development
    ENABLE_KB_STARTUP_INDEX = True


class ProductionConfig(Config):
    """Production environment configuration"""
    DEBUG = False
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = True
    AUTH_COOKIE_SECURE = True
    ENABLE_KB_STARTUP_INDEX = False


class TestingConfig(Config):
    """Testing environment configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {}  # SQLite doesn't support pool_size


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
