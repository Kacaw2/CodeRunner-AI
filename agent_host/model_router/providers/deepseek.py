import os

from langchain_core.language_models import BaseChatModel

from agent_host.model_router.providers.base import BaseProvider
from agent_host.model_router.tiers import ModelTier


# Tier -> (model_name, temperature, max_tokens) defaults.
# DeepSeek currently offers one chat model, so the tier differentiation is
# expressed through temperature and token budget.  When DeepSeek ships
# distinct model sizes this map can point to different model names.
_TIER_DEFAULTS: dict[ModelTier, dict] = {
    ModelTier.FAST: {
        "model": os.environ.get("AI_MODEL_FAST", os.environ.get("AI_MODEL", "deepseek-chat")),
        "temperature": 0.3,
        "max_tokens": 1024,
    },
    ModelTier.BALANCED: {
        "model": os.environ.get("AI_MODEL_BALANCED", os.environ.get("AI_MODEL", "deepseek-chat")),
        "temperature": 0.7,
        "max_tokens": 2048,
    },
    ModelTier.STRONG: {
        "model": os.environ.get("AI_MODEL_STRONG", os.environ.get("AI_MODEL", "deepseek-chat")),
        "temperature": 0.5,
        "max_tokens": 4096,
    },
}


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def __init__(self):
        self._api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self._base_url = "https://api.deepseek.com"

    def supports_tier(self, tier: ModelTier) -> bool:
        return tier in _TIER_DEFAULTS

    def get_llm(self, tier: ModelTier) -> BaseChatModel:
        if not self._api_key:
            from agent_host.exceptions import ConfigError
            raise ConfigError("DEEPSEEK_API_KEY environment variable is not set")

        from langchain_openai import ChatOpenAI

        cfg = _TIER_DEFAULTS[tier]
        return ChatOpenAI(
            model=cfg["model"],
            api_key=self._api_key,
            base_url=self._base_url,
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            request_timeout=30,
        )
