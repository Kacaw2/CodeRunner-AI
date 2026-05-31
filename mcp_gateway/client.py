"""MCP client adapter used by internal agents.

Agents are MCP clients. They must not import ``ToolRuntime`` directly; they call
tools through an ``MCPToolClient``. Two concrete implementations exist:

- ``InProcessMCPToolClient`` — local/dev/test path. Delegates to the in-process
  ``ToolRuntime`` (a server-internal detail) without crossing transport. Used
  when ``MCP_AGENT_TRANSPORT`` is unset or ``inproc``.
- ``StreamableHTTPMCPToolClient`` — production path. Crosses the MCP transport
  to the ``mcp_gateway`` FastMCP server. Used when
  ``MCP_AGENT_TRANSPORT=streamable-http``.

The default (when none is configured) is the in-process client, so unit tests
and local runs work without a running gateway. Production worker startup calls
``configure_mcp_client_from_env()`` to select the transport client explicitly.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPClientIdentity:
    user_id: int
    role: str
    agent_type: str
    task_id: str | None = None
    conversation_id: str | None = None


class MCPToolClient:
    """Transport-agnostic MCP tool client interface.

    ``call_tool`` returns a ToolRuntime envelope dict (the same shape as
    ``ToolResult.to_envelope()``): on success ``{"ok": True, "data": {...}}``;
    on failure ``{"ok": False, "error": {...}, "status": ...}``.
    """

    def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        identity: MCPClientIdentity,
        *,
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError


class InProcessMCPToolClient(MCPToolClient):
    """Local/dev/test client — delegates to the in-process ToolRuntime.

    This keeps the direct ``ToolRuntime`` dependency inside the (server-side)
    client module instead of in ``agents/base.py``. It does not cross MCP
    transport and is not the production boundary.
    """

    def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        identity: MCPClientIdentity,
        *,
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        from tools.protocol import get_tool_runtime, ToolCallContext
        from core.auth.context import build_caller_context
        from tools.protocol.policies.scopes import scopes_for_agent

        caller = build_caller_context(
            user_id=identity.user_id,
            role=identity.role,
            agent_type=identity.agent_type,
            task_id=identity.task_id,
            conversation_id=identity.conversation_id,
        )
        ctx = ToolCallContext(
            caller=caller,
            tool_call_id=tool_call_id,
            granted_scopes=scopes_for_agent(identity.agent_type),
        )
        result = get_tool_runtime().call_sync(tool_name, args, ctx)
        return result.to_envelope()


class StreamableHTTPMCPToolClient(MCPToolClient):
    """Production client — crosses MCP transport to the mcp_gateway server.

    For each call the client mints a short-lived, EdDSA-signed capability token
    carrying the caller's identity and minimal scopes. The gateway verifies the
    signature and builds an ``agent_host`` CallerContext from the signed claims,
    so the agent cannot self-declare its user_id/role/scopes.
    """

    def __init__(self, gateway_url: str, signing_key: str) -> None:
        self._gateway_url = gateway_url
        self._signing_key = signing_key

    def _build_auth_header(self, identity: MCPClientIdentity) -> str:
        from mcp_gateway.internal_auth import mint_internal_token
        from tools.protocol.policies.scopes import scopes_for_agent

        token = mint_internal_token(
            user_id=identity.user_id,
            role=identity.role,
            agent_type=identity.agent_type,
            scopes=scopes_for_agent(identity.agent_type),
            task_id=identity.task_id,
            conversation_id=identity.conversation_id,
            signing_key=self._signing_key,
        )
        return f"Bearer {token}"

    def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        identity: MCPClientIdentity,
        *,
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        import asyncio

        coro = self._call_async(tool_name, args, identity, tool_call_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

    async def _call_async(
        self,
        tool_name: str,
        args: dict[str, Any],
        identity: MCPClientIdentity,
        tool_call_id: str,
    ) -> dict[str, Any]:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp.client.session import ClientSession

        headers = {"Authorization": self._build_auth_header(identity)}

        async with streamablehttp_client(self._gateway_url, headers=headers) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return _envelope_from_mcp_result(result)


def _envelope_from_mcp_result(result: Any) -> dict[str, Any]:
    """Parse a FastMCP tool result into a ToolRuntime envelope dict."""
    text = ""
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", "") or ""
    if not text:
        return {"ok": False, "error": {"code": "MCP_INTERNAL_ERROR",
                                       "message": "Empty tool result"},
                "status": "error"}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "error": {"code": "MCP_INTERNAL_ERROR",
                                       "message": "Malformed tool result"},
                "status": "error"}


_CLIENT: MCPToolClient | None = None


def set_mcp_tool_client(client: MCPToolClient | None) -> None:
    global _CLIENT
    _CLIENT = client


def get_mcp_tool_client() -> MCPToolClient:
    """Return the configured client, defaulting to the in-process client."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = InProcessMCPToolClient()
    return _CLIENT


def configure_mcp_client_from_env() -> MCPToolClient:
    """Select the agent tool client based on environment.

    - ``MCP_AGENT_TRANSPORT=streamable-http`` → production transport client.
    - anything else (default) → in-process client.
    """
    transport = os.environ.get("MCP_AGENT_TRANSPORT", "inproc").strip().lower()
    if transport == "streamable-http":
        gateway_url = os.environ.get(
            "MCP_GATEWAY_URL", "http://mcp_gateway:8200/mcp"
        )
        from mcp_gateway.internal_auth import load_signing_key_from_env

        signing_key = load_signing_key_from_env()
        if not signing_key:
            raise RuntimeError(
                "MCP_AGENT_TRANSPORT=streamable-http requires "
                "MCP_INTERNAL_SIGNING_KEY to be set"
            )
        client: MCPToolClient = StreamableHTTPMCPToolClient(gateway_url, signing_key)
        logger.info("Agent MCP client: streamable-http -> %s", gateway_url)
    else:
        client = InProcessMCPToolClient()
        logger.info("Agent MCP client: in-process ToolRuntime (dev/local)")
    set_mcp_tool_client(client)
    return client
