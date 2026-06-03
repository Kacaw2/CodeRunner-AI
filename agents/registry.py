"""Single name->class resolution point for the four specialist agents.

`core.definitions` is pure data and cannot reference the agent classes; this
module is the `agents/`-layer companion that maps the same definition names to
their concrete `BaseAgent` subclasses. Every runtime path (API, worker,
orchestrator, eval harness) resolves agents here instead of keeping its own
local dict, so adding an agent means editing this map plus its definition — not
five call sites.
"""

from __future__ import annotations

from agents.base import BaseAgent
from agents.tutor.agent import TutorAgent
from agents.reviewer.agent import ReviewerAgent
from agents.generator.agent import GeneratorAgent
from agents.analytics.agent import AnalyticsAgent

AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "tutor": TutorAgent,
    "reviewer": ReviewerAgent,
    "generator": GeneratorAgent,
    "analytics": AnalyticsAgent,
}


def get_agent_class(name: str, default: str | None = None) -> type[BaseAgent]:
    """Return the agent class for *name*.

    With *default* set, an unknown name resolves to the default class instead of
    raising — mirrors the routing call sites' historical fallback to tutor.
    """
    if name in AGENT_CLASSES:
        return AGENT_CLASSES[name]
    if default is not None:
        return AGENT_CLASSES[default]
    raise KeyError(f"No agent registered for '{name}'")


def get_agent_instance(name: str, default: str | None = None) -> BaseAgent:
    return get_agent_class(name, default=default)()
