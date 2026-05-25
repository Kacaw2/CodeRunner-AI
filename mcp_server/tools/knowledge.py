"""MCP tool wrappers for knowledge-base operations."""

import json

from mcp.server import FastMCP

from app.agents.tools.core.knowledge import (
    search_similar_problems_impl,
    search_knowledge_impl,
)
from mcp_server.middleware import mcp_tool_middleware


def register_knowledge_tools(mcp: FastMCP):
    @mcp.tool(
        name="search_knowledge",
        description=(
            "Search course knowledge base for relevant concepts, patterns, "
            "or explanations. Returns structured results with topic, category, "
            "content, and relevance score."
        ),
    )
    @mcp_tool_middleware("search_knowledge")
    def search_knowledge(query: str, owner_id: int | None = None) -> str:
        result = search_knowledge_impl(query, owner_id)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(
        name="search_similar_problems",
        description=(
            "Search existing problem bank for similar problems. "
            "Returns a list of similar problems with similarity scores."
        ),
    )
    @mcp_tool_middleware("search_similar_problems")
    def search_similar_problems(
        query: str, language: str = "python", limit: int = 5
    ) -> str:
        result = search_similar_problems_impl(query, language, limit)
        return json.dumps(result, ensure_ascii=False)
