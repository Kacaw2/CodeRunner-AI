"""Unified platform settings — replaces agent_host/core/config.py and mcp_gateway/config.py."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_DEFAULT_SECRET = "dev-secret-key-change-in-production"


def _build_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    user = os.environ.get("MYSQL_USER", os.environ.get("DB_USER", "root"))
    password = os.environ.get("MYSQL_PASSWORD", os.environ.get("DB_PASSWORD", ""))
    host = os.environ.get("MYSQL_HOST", os.environ.get("DB_HOST", "localhost"))
    port = os.environ.get("MYSQL_PORT", os.environ.get("DB_PORT", "3306"))
    database = os.environ.get("MYSQL_DATABASE", os.environ.get("DB_NAME", "coderunner"))
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


class Settings:
    # ── Database ────────────────────────────────────────────────
    DB_URL: str = _build_database_url()
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
    TASK_BUFFER_TTL: int = 3600

    # ── Agent rate limits (requests per minute) ─────────────────
    AGENT_RATE_LIMITS: dict = {
        "tutor": 20,
        "reviewer": 10,
        "generator": 5,
        "analytics": 10,
    }

    # ── Server (worker daemon) ──────────────────────────────────
    HOST: str = os.environ.get("AGENT_HOST_BIND", "0.0.0.0")
    PORT: int = int(os.environ.get("AGENT_HOST_PORT", "8100"))
    DEBUG: bool = os.environ.get("DEBUG", "False").lower() in ("true", "1")

    # ── MCP Gateway ─────────────────────────────────────────────
    MCP_HOST: str = os.environ.get("MCP_HOST", "127.0.0.1")
    MCP_PORT: int = int(os.environ.get("MCP_PORT", "8200"))
    MCP_API_KEY: str = os.environ.get("MCP_API_KEY", "")

    @property
    def database_url(self) -> str:
        return self.DB_URL

    def validate(self) -> None:
        """P0: fail-fast if a production (non-DEBUG) process boots with an
        unset or insecure default SECRET_KEY (used for JWT signing)."""
        if not self.DEBUG:
            if not self.SECRET_KEY or self.SECRET_KEY == _DEFAULT_SECRET:
                raise RuntimeError(
                    "SECRET_KEY is unset or using the insecure default in "
                    "non-DEBUG mode. Set the SECRET_KEY env var before starting "
                    "in production."
                )


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
