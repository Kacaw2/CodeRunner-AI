from langchain_core.tools import tool


@tool
def search_similar_problems(query: str, language: str = "python", limit: int = 5) -> dict:
    """Search existing problem bank for similar problems. Use this for deduplication
    before generating new problems. Returns a list of similar problems with similarity scores."""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_similar_problems(query, n=limit, language=language)
        return {"similar_problems": results}
    except Exception as e:
        return {"similar_problems": [], "error": str(e)}


@tool
def search_knowledge(query: str, owner_id: int = None) -> dict:
    """Search course knowledge base for relevant concepts, patterns, or explanations.
    Use this to provide accurate, curriculum-aligned explanations to students.
    Returns structured results with topic, category, content, and relevance score.
    If owner_id is provided, results are scoped to global + that owner's content."""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        scope_filter = {"owner_id": owner_id} if owner_id else None
        results = kb.search_knowledge(query, n=3, scope_filter=scope_filter)
        return {"relevant_knowledge": results}
    except Exception as e:
        return {"relevant_knowledge": [], "error": str(e)}


@tool
def search_error_patterns(query: str) -> dict:
    """Search for common error patterns similar to the student's issue.
    Returns structured results with error_type, content, and relevance score."""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_error_patterns(query, n=3)
        return {"error_patterns": results}
    except Exception as e:
        return {"error_patterns": [], "error": str(e)}
