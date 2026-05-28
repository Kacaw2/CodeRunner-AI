from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel

from models.tiers import ModelTier


class BaseProvider(ABC):
    """Interface for LLM providers.

    Each provider maps ModelTier values to concrete model configurations.
    Currently only DeepSeek is implemented; the interface exists so that
    adding a second provider later doesn't require refactoring agents.
    """

    name: str = ""

    @abstractmethod
    def get_llm(self, tier: ModelTier) -> BaseChatModel:
        ...

    @abstractmethod
    def supports_tier(self, tier: ModelTier) -> bool:
        ...
