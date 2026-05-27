import logging

from langchain_core.language_models import BaseChatModel

from agent_host.model_router.tiers import ModelTier
from agent_host.model_router.providers.base import BaseProvider
from agent_host.model_router.providers.deepseek import DeepSeekProvider

logger = logging.getLogger(__name__)

_router_instance: "ModelRouter | None" = None


class ModelRouter:
    """Resolves a ModelTier to a concrete LLM instance via the configured provider."""

    def __init__(self, provider: BaseProvider | None = None):
        self._provider = provider or DeepSeekProvider()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def get_llm(self, tier: ModelTier = ModelTier.BALANCED) -> BaseChatModel:
        if not self._provider.supports_tier(tier):
            logger.warning("Provider '%s' does not support tier '%s', falling back to BALANCED",
                           self._provider.name, tier.value)
            tier = ModelTier.BALANCED
        return self._provider.get_llm(tier)


def get_model_router() -> ModelRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance
