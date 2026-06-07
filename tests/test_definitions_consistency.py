"""Registry consistency: every definition is internally coherent and its
references resolve. These fail loudly on drift so a new agent cannot ship
half-wired."""

import importlib

from core.definitions import AGENT_DEFINITIONS


def test_every_definition_declares_budget_and_rate_limit():
    for name, defn in AGENT_DEFINITIONS.items():
        assert defn.max_tool_iterations >= 1, name
        assert defn.rate_limit >= 1, name


def test_current_agents_keep_their_legacy_defaults():
    # No live behavior shift: tutor/reviewer/generator/analytics keep iterations=5
    # and the previous AGENT_RATE_LIMITS values.
    expected_rate = {"tutor": 20, "reviewer": 10, "generator": 5, "analytics": 10}
    for name, defn in AGENT_DEFINITIONS.items():
        assert defn.max_tool_iterations == 5, name
        assert defn.rate_limit == expected_rate[name], name


def test_handoff_targets_are_known_agents_and_exclude_self():
    names = set(AGENT_DEFINITIONS)
    for name, defn in AGENT_DEFINITIONS.items():
        assert name not in defn.handoff_targets, f"{name} hands off to itself"
        assert set(defn.handoff_targets) <= names, name


def test_prompt_ref_resolves_to_an_importable_constant():
    for name, defn in AGENT_DEFINITIONS.items():
        if not defn.prompt_ref:
            continue
        module_path, attr = defn.prompt_ref.rsplit(".", 1)
        module = importlib.import_module(module_path)
        assert hasattr(module, attr), defn.prompt_ref


def test_allowed_tools_exist_in_the_tool_catalog():
    """Every tool an agent can call must be a registered ToolRuntime descriptor.

    Bootstrap the gateway so the runtime holds the live catalog (a bare app does
    not register tools), then assert against what the runtime actually exposes."""
    from ai.mcp_gateway.bootstrap import bootstrap_tool_runtime
    from ai.tools.protocol.runtime import get_tool_runtime, set_tool_runtime, reset_tool_runtime

    previous = get_tool_runtime()
    try:
        bootstrap_tool_runtime()
        catalog = {d.name for d in get_tool_runtime().list_tools()}
    finally:
        reset_tool_runtime()
        set_tool_runtime(previous)

    assert catalog, "tool catalog is empty after bootstrap"
    for name, defn in AGENT_DEFINITIONS.items():
        missing = set(defn.allowed_tools) - catalog
        assert not missing, f"{name} references unknown tools: {missing}"


def test_output_schema_names_resolve():
    from core import schemas as schema_mod

    for name, defn in AGENT_DEFINITIONS.items():
        if defn.output_format != "json_schema":
            continue
        assert defn.output_schema_name, f"{name} is json_schema but names no schema"
        assert hasattr(schema_mod, defn.output_schema_name), defn.output_schema_name
