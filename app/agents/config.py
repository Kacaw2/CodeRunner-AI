import logging
import os

from app.agents.exceptions import ConfigError

logger = logging.getLogger(__name__)

# Per-agent rate limits (requests per minute)
AGENT_RATE_LIMITS: dict[str, int] = {
    "tutor": 20,
    "reviewer": 10,
    "generator": 5,
    "analytics": 10,
}

MAX_TOOL_ITERATIONS = 5


class AIConfig:
    API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
    BASE_URL: str = "https://api.deepseek.com"
    MODEL: str = os.environ.get("AI_MODEL", "deepseek-chat")
    MAX_TOKENS: int = int(os.environ.get("AI_MAX_TOKENS", "2048"))
    TEMPERATURE: float = float(os.environ.get("AI_TEMPERATURE", "0.7"))
    RATE_LIMIT: int = int(os.environ.get("AI_RATE_LIMIT", "20"))
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    @classmethod
    def validate(cls):
        if not cls.API_KEY:
            raise ConfigError("DEEPSEEK_API_KEY environment variable is not set")

    @classmethod
    def get_llm(cls):
        cls.validate()
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=cls.MODEL,
            api_key=cls.API_KEY,
            base_url=cls.BASE_URL,
            max_tokens=cls.MAX_TOKENS,
            temperature=cls.TEMPERATURE,
            request_timeout=30,
        )
