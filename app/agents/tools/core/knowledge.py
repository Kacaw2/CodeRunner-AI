"""Core knowledge-base logic — no framework dependency."""


def search_similar_problems_impl(
    query: str,
    language: str = "python",
    limit: int = 5,
) -> dict:
    from agent_host.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_similar_problems(query, n=limit, language=language)
        return {"similar_problems": results}
    except Exception as e:
        return {"similar_problems": [], "error": str(e)}


def search_knowledge_impl(
    query: str,
    owner_id: int = None,
) -> dict:
    from agent_host.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        scope_filter = {"owner_id": owner_id} if owner_id else None
        results = kb.search_knowledge(query, n=3, scope_filter=scope_filter)
        return {"relevant_knowledge": results}
    except Exception as e:
        return {"relevant_knowledge": [], "error": str(e)}


def search_error_patterns_impl(query: str) -> dict:
    from agent_host.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_error_patterns(query, n=3)
        return {"error_patterns": results}
    except Exception as e:
        return {"error_patterns": [], "error": str(e)}
