from mcp_gateway.scopes import normalize_scopes


def test_normalize_legacy_tool_scope_to_canonical_scope():
    assert normalize_scopes(["search_knowledge"]) == ["knowledge:read"]


def test_normalize_deduplicates_scope_aliases():
    assert normalize_scopes(["search_knowledge", "search_similar_problems"]) == ["knowledge:read"]


def test_normalize_preserves_canonical_scope():
    assert normalize_scopes(["problem:read"]) == ["problem:read"]


def test_none_scopes_remain_unrestricted():
    assert normalize_scopes(None) is None
