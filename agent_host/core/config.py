import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── Database ────────────────────────────────────────────────
    DB_URL: str = os.environ.get("DATABASE_URL", "")
    if not DB_URL:
        _user = os.environ.get("MYSQL_USER", "root")
        _password = os.environ.get("MYSQL_PASSWORD", "")
        _host = os.environ.get("MYSQL_HOST", "localhost")
        _port = os.environ.get("MYSQL_PORT", "3306")
        _database = os.environ.get("MYSQL_DATABASE", "coderunner")
        DB_URL = (
            f"mysql+pymysql://{_user}:{_password}@{_host}:{_port}/{_database}"
            f"?charset=utf8mb4"
        )

    DB_POOL_SIZE: int = 5
    DB_POOL_RECYCLE: int = 3600

    # ── Redis ───────────────────────────────────────────────────
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ── Auth ────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get(
        "SECRET_KEY", "dev-secret-key-change-in-production"
    )
    JWT_ALGORITHM: str = "HS256"

    # ── DeepSeek / LLM ──────────────────────────────────────────
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    AI_MODEL: str = os.environ.get("AI_MODEL", "deepseek-chat")
    AI_MAX_TOKENS: int = int(os.environ.get("AI_MAX_TOKENS", "2048"))
    AI_TEMPERATURE: float = float(os.environ.get("AI_TEMPERATURE", "0.7"))

    # ── Flask backend (adapter target) ──────────────────────────
    FLASK_BASE_URL: str = os.environ.get("FLASK_BASE_URL", "http://localhost:9900")

    # ── Worker ──────────────────────────────────────────────────
    WORKER_MAX_THREADS: int = 4
    TASK_BUFFER_TTL: int = 3600  # Redis buffer TTL in seconds

    # ── Agent rate limits (requests per minute) ─────────────────
    AGENT_RATE_LIMITS: dict = {
        "tutor": 20,
        "reviewer": 10,
        "generator": 5,
        "analytics": 10,
    }

    # ── Server ──────────────────────────────────────────────────
    HOST: str = os.environ.get("AGENT_HOST_BIND", "0.0.0.0")
    PORT: int = int(os.environ.get("AGENT_HOST_PORT", "8100"))
    DEBUG: bool = os.environ.get("DEBUG", "False").lower() in ("true", "1")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
