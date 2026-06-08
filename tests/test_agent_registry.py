"""The factory is the single name->class resolution point. Every declared
definition must resolve to a concrete BaseAgent subclass, and vice versa."""

import re
from pathlib import Path

import pytest

from core.definitions import AGENT_DEFINITIONS


def test_every_definition_has_a_registered_class():
    from ai.agents.registry import AGENT_CLASSES
    from ai.agents.base import BaseAgent

    assert set(AGENT_CLASSES) == set(AGENT_DEFINITIONS)
    for name, cls in AGENT_CLASSES.items():
        assert issubclass(cls, BaseAgent), name
        assert cls.name == name, f"{cls.__name__}.name != registry key {name}"


def test_get_agent_instance_returns_correct_type():
    from ai.agents.registry import get_agent_instance
    from ai.agents.tutor.agent import TutorAgent

    inst = get_agent_instance("tutor")
    assert isinstance(inst, TutorAgent)


def test_unknown_agent_raises():
    from ai.agents.registry import get_agent_class

    with pytest.raises(KeyError):
        get_agent_class("nonexistent")


def test_get_agent_instance_default_for_router_fallback():
    # The routing call sites fall back to tutor on an unknown type; the factory
    # exposes that as an explicit default rather than each site hardcoding it.
    from ai.agents.registry import get_agent_instance
    from ai.agents.tutor.agent import TutorAgent

    inst = get_agent_instance("garbage", default="tutor")
    assert isinstance(inst, TutorAgent)


def test_no_runtime_module_redeclares_an_agent_class_map():
    """Guard against a sixth hand-rolled name->class dict creeping back in.

    Allowed to import the classes (e.g. for isinstance), but not to build a
    `{"tutor": TutorAgent, ...}` dispatch dict outside agents/registry.py.
    """
    root = Path(__file__).resolve().parents[1]
    suspects = [
        root / "ai" / "agent_runtime" / "services" / "chat_runner.py",
        root / "app" / "api" / "v1" / "ai.py",
        root / "ai" / "graph" / "runner.py",
        root / "ai" / "evals" / "runner.py",
        root / "ai" / "evals" / "harness" / "agent_harness.py",
    ]
    pattern = re.compile(r'["\']tutor["\']\s*:\s*TutorAgent')
    for path in suspects:
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path} still hand-rolls an agent map"


def test_class_attrs_match_definition_and_are_not_redeclared():
    """description/tier come from the definition; classes only fix `name`."""
    from ai.agents.registry import AGENT_CLASSES
    from core.definitions import get_definition

    for name, cls in AGENT_CLASSES.items():
        defn = get_definition(name)
        inst = cls()
        assert inst.description == defn.description, name
        assert inst.default_model_tier == defn.default_model_tier, name
        # description/default_model_tier must not be in the class __dict__
        assert "description" not in cls.__dict__, f"{name} redeclares description"
        assert "default_model_tier" not in cls.__dict__, f"{name} redeclares tier"
