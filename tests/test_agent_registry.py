"""The factory is the single name->class resolution point. Every declared
definition must resolve to a concrete BaseAgent subclass, and vice versa."""

import pytest

from core.definitions import AGENT_DEFINITIONS


def test_every_definition_has_a_registered_class():
    from agents.registry import AGENT_CLASSES
    from agents.base import BaseAgent

    assert set(AGENT_CLASSES) == set(AGENT_DEFINITIONS)
    for name, cls in AGENT_CLASSES.items():
        assert issubclass(cls, BaseAgent), name
        assert cls.name == name, f"{cls.__name__}.name != registry key {name}"


def test_get_agent_instance_returns_correct_type():
    from agents.registry import get_agent_instance
    from agents.tutor.agent import TutorAgent

    inst = get_agent_instance("tutor")
    assert isinstance(inst, TutorAgent)


def test_unknown_agent_raises():
    from agents.registry import get_agent_class

    with pytest.raises(KeyError):
        get_agent_class("nonexistent")


def test_get_agent_instance_default_for_router_fallback():
    # The routing call sites fall back to tutor on an unknown type; the factory
    # exposes that as an explicit default rather than each site hardcoding it.
    from agents.registry import get_agent_instance
    from agents.tutor.agent import TutorAgent

    inst = get_agent_instance("garbage", default="tutor")
    assert isinstance(inst, TutorAgent)
