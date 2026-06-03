import logging
import os

from core.exceptions import ConfigError

logger = logging.getLogger(__name__)

# Per-agent rate limits (requests per minute)
AGENT_RATE_LIMITS: dict[str, int] = {
    "tutor": 20,
    "reviewer": 10,
    "generator": 5,
    "analytics": 10,
}

MAX_TOOL_ITERATIONS = 5

# Production-side guardrail on the total number of LLM calls charged to a single
# logical trace. A trace is shared across an entire handoff chain / workflow /
# chat task (see core.observability.tracing), so this caps aggregate LLM usage
# ACROSS agents, complementing the per-loop MAX_TOOL_ITERATIONS ceiling. Must be
# larger than MAX_TOOL_ITERATIONS so a single agent loop is never cut short.
MAX_LLM_CALLS_PER_TRACE = 12


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
    def get_llm(cls, tier=None):
        """Return an LLM instance.

        When *tier* is provided, delegates to the ModelRouter so that each
        tier resolves to the appropriate model/temperature/token config.
        Without a tier this returns a BALANCED-tier instance, which preserves
        the original single-model behaviour for callers that haven't been
        migrated yet.
        """
        from models import ModelTier, get_model_router
        if tier is None:
            tier = ModelTier.BALANCED
        return get_model_router().get_llm(tier)
