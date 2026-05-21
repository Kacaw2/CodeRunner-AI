import logging

from langgraph.graph import StateGraph, END

from app.agents.exceptions import AIError
from app.agents.state import AgentState
from app.agents.agents import TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent

logger = logging.getLogger(__name__)

_AGENTS = {
    "tutor": TutorAgent(),
    "reviewer": ReviewerAgent(),
    "generator": GeneratorAgent(),
    "analytics": AnalyticsAgent(),
}


def _route(state: AgentState) -> AgentState:
    agent_type = state.get("agent_type")
    if agent_type and agent_type in _AGENTS:
        return state
    state["agent_type"] = "tutor"
    return state


def _run_agent(agent_type: str, state: AgentState) -> AgentState:
    agent = _AGENTS[agent_type]
    try:
        return agent.invoke(state)
    except AIError as e:
        logger.error("Agent '%s' failed: %s", agent_type, e)
        state["final_response"] = e.user_message
        return state
    except Exception as e:
        logger.exception("Unexpected error in agent '%s'", agent_type)
        state["final_response"] = "An unexpected error occurred. Please try again later."
        return state


def _respond(state: AgentState) -> AgentState:
    return state


def _next_node(state: AgentState) -> str:
    return state.get("agent_type", "tutor")


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("route", _route)
    graph.add_node("tutor", lambda s: _run_agent("tutor", s))
    graph.add_node("reviewer", lambda s: _run_agent("reviewer", s))
    graph.add_node("generator", lambda s: _run_agent("generator", s))
    graph.add_node("analytics", lambda s: _run_agent("analytics", s))
    graph.add_node("respond", _respond)

    graph.set_entry_point("route")
    graph.add_conditional_edges("route", _next_node, {
        "tutor": "tutor",
        "reviewer": "reviewer",
        "generator": "generator",
        "analytics": "analytics",
    })
    for agent_name in _AGENTS:
        graph.add_edge(agent_name, "respond")
    graph.add_edge("respond", END)

    return graph


class AgentOrchestrator:
    def __init__(self):
        self._graph = build_graph().compile()

    def run(self, state: AgentState) -> AgentState:
        return self._graph.invoke(state)
