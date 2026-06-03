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
