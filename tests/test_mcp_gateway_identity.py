"""Per-request gateway identity isolation (Task 5).

These tests prove caller identity is not a process-global value: it is resolved
per request and cleared after each call so it cannot leak between callers.
"""

import json

from ai.mcp_gateway.middleware import set_caller_info, get_caller_info


def test_caller_info_is_not_process_global_after_request_clear():
    set_caller_info({"user_id": 1, "role": "teacher", "api_key_id": "k1"})
    set_caller_info(None)
    assert get_caller_info() is None


def test_guarded_rejects_when_no_caller(monkeypatch):
    from ai.mcp_gateway.middleware import core

    core.set_caller_info(None)
    monkeypatch.setattr(core, "_resolve_request_caller", lambda: None)

    out = json.loads(core._guarded(lambda: "SHOULD_NOT_RUN"))
    assert out["ok"] is False
    assert out["error"]["code"] == "MCP_AUTH_REQUIRED"


def test_guarded_resolves_per_request_identity_and_clears(monkeypatch):
    from ai.mcp_gateway.middleware import core

    core.set_caller_info(None)
    monkeypatch.setattr(core, "check_rate_limit", lambda *_, **__: True)
    monkeypatch.setattr(
        core,
        "_resolve_request_caller",
        lambda: {
            "api_key_id": "k1",
            "user_id": 1,
            "role": "teacher",
            "rate_limit_rpm": 30,
        },
    )

    seen = {}

    def _run():
        seen["caller"] = core.get_caller_info()
        return "OK"

    result = core._guarded(_run)

    assert result == "OK"
    # Identity was available during the call...
    assert seen["caller"]["api_key_id"] == "k1"
    # ...but cleared afterward so it cannot leak to the next request.
    assert core.get_caller_info() is None


def test_per_request_identity_overrides_stale_fallback(monkeypatch):
    """A request's own bearer identity wins over any pre-set fallback."""
    from ai.mcp_gateway.middleware import core

    core.set_caller_info({"api_key_id": "stale", "user_id": 99, "role": "student"})
    monkeypatch.setattr(core, "check_rate_limit", lambda *_, **__: True)
    monkeypatch.setattr(
        core,
        "_resolve_request_caller",
        lambda: {
            "api_key_id": "fresh",
            "user_id": 1,
            "role": "teacher",
            "rate_limit_rpm": 30,
        },
    )

    seen = {}
    core._guarded(lambda: seen.setdefault("caller", core.get_caller_info()))

    assert seen["caller"]["api_key_id"] == "fresh"
