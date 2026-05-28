"""Tool registry — maps tool names to servers and descriptors."""

from __future__ import annotations

import logging
from typing import Sequence

from tools.protocol.schemas.descriptors import ToolDescriptor

logger = logging.getLogger(__name__)

_GLOBAL_REGISTRY: ToolRegistry | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}
        self._server_health: dict[str, bool] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._tools:
            existing = self._tools[descriptor.name]
            if existing.server != descriptor.server:
                raise ValueError(
                    f"Duplicate tool name '{descriptor.name}' "
                    f"registered by servers '{existing.server}' and '{descriptor.server}'."
                )
        self._tools[descriptor.name] = descriptor
        if descriptor.server:
            self._server_health.setdefault(descriptor.server, True)

    def get(self, tool_name: str) -> ToolDescriptor | None:
        return self._tools.get(tool_name)

    def list_tools(
        self,
        *,
        names: Sequence[str] | None = None,
        agent_type: str | None = None,
        role: str | None = None,
    ) -> list[ToolDescriptor]:
        """Return descriptors, optionally filtered by name allowlist."""
        if names is not None:
            name_set = set(names)
            return [t for t in self._tools.values() if t.name in name_set]
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def set_server_health(self, server: str, healthy: bool) -> None:
        self._server_health[server] = healthy

    def is_healthy(self, server: str) -> bool:
        return self._server_health.get(server, False)

    def __len__(self) -> int:
        return len(self._tools)


def get_registry() -> ToolRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ToolRegistry()
    return _GLOBAL_REGISTRY


def reset_registry() -> None:
    global _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = None
