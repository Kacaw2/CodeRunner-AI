from langchain_core.tools import tool

from app.agents.tools.core.knowledge import (
    search_similar_problems_impl,
    search_knowledge_impl,
    search_error_patterns_impl,
)


@tool
def search_similar_problems(query: str, language: str = "python", limit: int = 5) -> dict:
    """Search existing problem bank for similar problems. Use this for deduplication
    before generating new problems. Returns a list of similar problems with similarity scores."""
    return search_similar_problems_impl(query, language, limit)


@tool
def search_knowledge(query: str, owner_id: int = None) -> dict:
    """Search course knowledge base for relevant concepts, patterns, or explanations.
    Use this to provide accurate, curriculum-aligned explanations to students.
    Returns structured results with topic, category, content, and relevance score.
    If owner_id is provided, results are scoped to global + that owner's content."""
    return search_knowledge_impl(query, owner_id)


@tool
def search_error_patterns(query: str) -> dict:
    """Search for common error patterns similar to the student's issue.
    Returns structured results with error_type, content, and relevance score."""
    return search_error_patterns_impl(query)
