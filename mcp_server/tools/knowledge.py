"""MCP tool wrappers for knowledge-base operations."""

import json

from mcp.server import FastMCP

from app.agents.tools.core.knowledge import (
    search_similar_problems_impl,
    search_knowledge_impl,
)
from mcp_server.middleware import run_mcp_guard


def register_knowledge_tools(mcp: FastMCP):
    @mcp.tool(
        name="search_knowledge",
        description=(
            "Search course knowledge base for relevant concepts, patterns, "
            "or explanations. Returns structured results with topic, category, "
            "content, and relevance score."
        ),
    )
    def search_knowledge(query: str, owner_id: int | None = None) -> str:
        args = {"query": query, "owner_id": owner_id}
        guard = run_mcp_guard("search_knowledge", args)
        if guard.rejected:
            return guard.error_json
        try:
            result = search_knowledge_impl(query, owner_id)
            guard.record_success("search_knowledge", args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            guard.record_error("search_knowledge", args, e)
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="search_similar_problems",
        description=(
            "Search existing problem bank for similar problems. "
            "Returns a list of similar problems with similarity scores."
        ),
    )
    def search_similar_problems(
        query: str, language: str = "python", limit: int = 5
    ) -> str:
        args = {"query": query, "language": language, "limit": limit}
        guard = run_mcp_guard("search_similar_problems", args)
        if guard.rejected:
            return guard.error_json
        try:
            result = search_similar_problems_impl(query, language, limit)
            guard.record_success("search_similar_problems", args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            guard.record_error("search_similar_problems", args, e)
            return json.dumps({"error": str(e)})
