"""In-process transport — calls server tool functions directly.

Used when Agent Host and MCP servers run in the same process.
Can be replaced with HTTP/SSE transport for multi-process deployment.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., dict[str, Any]]


class LocalTransport:
    """Dispatch tool calls to in-process handler functions."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register_handler(self, tool_name: str, handler: ToolHandler) -> None:
        self._handlers[tool_name] = handler

    async def call(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise KeyError(f"No handler registered for tool '{tool_name}'")

        start = time.monotonic()
        result = handler(**args)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        logger.debug("tool=%s latency_ms=%d", tool_name, elapsed_ms)
        return result

    def invoke(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Synchronously dispatch to a registered handler.

        Mirrors `call()` minus the async/timeout wrapper, for callers
        (e.g. the post-approval execution path) that run outside the
        async pipeline.
        """
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise KeyError(f"No handler registered for tool '{tool_name}'")
        return handler(**args)

    def has_handler(self, tool_name: str) -> bool:
        return tool_name in self._handlers

    def registered_tools(self) -> list[str]:
        return sorted(self._handlers.keys())
