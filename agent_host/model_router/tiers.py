from enum import Enum


class ModelTier(str, Enum):
    """Abstraction over model capability levels.

    Agents declare which tier they need; the ModelRouter resolves it to
    a concrete provider + model configuration.
    """
    FAST = "fast"
    BALANCED = "balanced"
    STRONG = "strong"
