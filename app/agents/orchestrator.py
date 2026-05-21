import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.agents.config import AIConfig
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

VALID_AGENT_TYPES = set(_AGENTS.keys())

INTENT_CLASSIFY_PROMPT = """Classify this user message into one of these agent types.
User role: {user_role}

Agent types:
- tutor: Student asking for help, hints, explanations about a coding problem
- reviewer: Request to review, analyze, or critique code
- generator: Teacher asking to create/generate a new coding problem or question
- analytics: Request for performance data, statistics, learning analysis

User message: "{message}"

Output ONLY the agent type name (tutor/reviewer/generator/analytics).
If unsure, output "tutor" for students and "analytics" for teachers."""


def _classify_intent(state: AgentState) -> AgentState:
    """LLM-based intent classification to route to the right agent."""
    agent_type = state.get("agent_type")
    if agent_type and agent_type in VALID_AGENT_TYPES:
        return state

    user_role = state.get("user_role", "student")
    user_message = ""
    if state.get("messages"):
        last = state["messages"][-1]
        user_message = getattr(last, "content", str(last))

    if not user_message:
        state["agent_type"] = "tutor" if user_role == "student" else "analytics"
        state["auto_routed"] = True
        return state

    try:
        llm = AIConfig.get_llm()
        prompt = INTENT_CLASSIFY_PROMPT.format(user_role=user_role, message=user_message[:500])
        response = llm.invoke([HumanMessage(content=prompt)])
        classified = response.content.strip().lower()

        if classified not in VALID_AGENT_TYPES:
            classified = "tutor" if user_role == "student" else "analytics"

        if user_role == "student" and classified == "generator":
            classified = "tutor"

        state["agent_type"] = classified
        state["auto_routed"] = True
        logger.info("Intent classified as '%s' for message: %.80s", classified, user_message)
    except Exception as e:
        logger.warning("Intent classification failed, falling back: %s", e)
        state["agent_type"] = "tutor" if user_role == "student" else "analytics"
        state["auto_routed"] = True

    return state


def _route(state: AgentState) -> AgentState:
    agent_type = state.get("agent_type")
    if agent_type == "auto" or not agent_type:
        return _classify_intent(state)
    if agent_type in VALID_AGENT_TYPES:
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
