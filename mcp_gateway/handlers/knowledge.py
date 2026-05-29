"""MCP tool wrappers for knowledge-base operations."""

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime


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
        return _guarded(lambda: call_via_runtime(
            "coderunner.knowledge.search",
            {"query": query, "owner_id": owner_id},
        ))

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
        return _guarded(lambda: call_via_runtime(
            "coderunner.knowledge.search_similar_problems",
            {"query": query, "language": language, "limit": limit},
        ))
