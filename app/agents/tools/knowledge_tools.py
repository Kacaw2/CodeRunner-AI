from langchain_core.tools import tool


@tool
def search_similar_questions(query: str, language: str = "python", limit: int = 5) -> dict:
    """Search existing question bank for similar questions. Use this for deduplication
    before generating new questions. Returns a list of similar questions with similarity scores."""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_similar_questions(query, n=limit, language=language)
        return {"similar_questions": results}
    except Exception as e:
        return {"similar_questions": [], "error": str(e)}


@tool
def search_knowledge(query: str) -> dict:
    """Search course knowledge base for relevant concepts, patterns, or explanations.
    Use this to provide accurate, curriculum-aligned explanations to students."""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_knowledge(query, n=3)
        return {"relevant_knowledge": results}
    except Exception as e:
        return {"relevant_knowledge": [], "error": str(e)}


@tool
def search_error_patterns(query: str) -> dict:
    """Search for common error patterns similar to the student's issue.
    Returns explanations and typical fixes for similar errors."""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_error_patterns(query, n=3)
        return {"error_patterns": results}
    except Exception as e:
        return {"error_patterns": [], "error": str(e)}
