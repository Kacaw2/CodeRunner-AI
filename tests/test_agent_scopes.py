"""Minimal scope derivation for internal agents (F1 defense in depth).

An internal agent_host caller must carry the minimal set of scopes its tools
require — the union of ``required_scopes`` across the agent's allowed tools —
rather than a god-mode scope bypass.
"""


def test_tutor_scopes_are_union_of_its_tools():
    from tools.protocol.policies.scopes import scopes_for_agent

    scopes = set(scopes_for_agent("tutor"))

    assert scopes == {"code:execute", "problem:read", "submission:read", "knowledge:read"}


def test_generator_scopes_include_problem_write():
    from tools.protocol.policies.scopes import scopes_for_agent

    scopes = set(scopes_for_agent("generator"))

    assert scopes == {"code:execute", "knowledge:read", "problem:write"}


def test_unknown_agent_gets_no_scopes():
    from tools.protocol.policies.scopes import scopes_for_agent

    assert scopes_for_agent("nope") == []
