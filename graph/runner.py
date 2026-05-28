import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from agents.config import AIConfig
from core.definitions import AGENT_DEFINITIONS, can_route_to
from core.exceptions import AIError
from core.state import AgentState
from agents import TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent

logger = logging.getLogger(__name__)

_AGENTS = {
    "tutor": TutorAgent(),
    "reviewer": ReviewerAgent(),
    "generator": GeneratorAgent(),
    "analytics": AnalyticsAgent(),
}

VALID_AGENT_TYPES = set(_AGENTS.keys())

MAX_HANDOFFS = 2


def _build_intent_prompt() -> str:
    """Build the intent classification prompt from agent definitions."""
    lines = [
        "Classify this user message into one of these agent types.",
        "User role: {user_role}",
        "",
        "Agent types:",
    ]
    for defn in AGENT_DEFINITIONS.values():
        lines.append(f"- {defn.name}: {defn.description}")
    lines.extend([
        "",
        'User message: "{message}"',
        "",
        "Output ONLY the agent type name (" + "/".join(AGENT_DEFINITIONS.keys()) + ").",
        'If unsure, output "tutor" for students and "analytics" for teachers.',
    ])
    return "\n".join(lines)


INTENT_CLASSIFY_PROMPT = _build_intent_prompt()


def _default_agent_for_role(user_role: str) -> str:
    if user_role == "student":
        return "tutor"
    return "analytics"


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
        state["agent_type"] = _default_agent_for_role(user_role)
        state["auto_routed"] = True
        return state

    try:
        from models.tiers import ModelTier
        llm = AIConfig.get_llm(tier=ModelTier.FAST)
        prompt = INTENT_CLASSIFY_PROMPT.format(user_role=user_role, message=user_message[:500])
        response = llm.invoke([HumanMessage(content=prompt)])
        classified = response.content.strip().lower()

        if classified not in VALID_AGENT_TYPES:
            classified = _default_agent_for_role(user_role)

        if not can_route_to(classified, user_role):
            logger.info("Role '%s' not allowed for agent '%s', falling back", user_role, classified)
            classified = _default_agent_for_role(user_role)

        state["agent_type"] = classified
        state["auto_routed"] = True
        logger.info("Intent classified as '%s' for message: %.80s", classified, user_message)
    except Exception as e:
        logger.warning("Intent classification failed, falling back: %s", e)
        state["agent_type"] = _default_agent_for_role(user_role)
        state["auto_routed"] = True

    return state


def _route(state: AgentState) -> AgentState:
    agent_type = state.get("agent_type")
    if agent_type == "auto" or not agent_type:
        return _classify_intent(state)

    if agent_type in VALID_AGENT_TYPES:
        user_role = state.get("user_role", "student")
        if not can_route_to(agent_type, user_role):
            logger.warning("Role '%s' denied access to agent '%s', redirecting",
                           user_role, agent_type)
            state["agent_type"] = _default_agent_for_role(user_role)
        return state

    state["agent_type"] = "tutor"
    return state


def _run_agent(agent_type: str, state: AgentState) -> AgentState:
    agent = _AGENTS[agent_type]
    try:
        result = agent.invoke(state)
        previous = result.get("previous_agents") or []
        if agent_type not in previous:
            previous.append(agent_type)
        result["previous_agents"] = previous
        return result
    except AIError as e:
        logger.error("Agent '%s' failed: %s", agent_type, e)
        state["final_response"] = e.user_message
        return state
    except Exception as e:
        logger.exception("Unexpected error in agent '%s'", agent_type)
        state["final_response"] = "An unexpected error occurred. Please try again later."
        return state


def _check_handoff(state: AgentState) -> str:
    """After an agent runs, check if it requested a handoff to another agent."""
    handoff_to = state.get("handoff_to")
    if not handoff_to or handoff_to not in VALID_AGENT_TYPES:
        return "respond"

    current_agent = state.get("agent_type", "")
    if handoff_to == current_agent:
        return "respond"

    previous = state.get("previous_agents") or []
    if handoff_to in previous:
        logger.info("Handoff to '%s' blocked: already processed by that agent", handoff_to)
        return "respond"

    if len(previous) >= MAX_HANDOFFS:
        logger.info("Handoff to '%s' blocked: max handoffs (%d) reached", handoff_to, MAX_HANDOFFS)
        return "respond"

    user_role = state.get("user_role", "student")
    if not can_route_to(handoff_to, user_role):
        logger.info("Handoff to '%s' blocked: role '%s' not allowed", handoff_to, user_role)
        return "respond"

    logger.info("Agent '%s' handing off to '%s' (reason: %s)",
                current_agent, handoff_to, state.get("handoff_reason", ""))

    state["agent_type"] = handoff_to
    state["handoff_to"] = None
    state["handoff_reason"] = None
    return handoff_to


def _respond(state: AgentState) -> AgentState:
    """Validate structured agent output and trigger retry if schema check fails."""
    agent_type = state.get("agent_type", "")

    defn = AGENT_DEFINITIONS.get(agent_type)
    if defn and defn.output_format == "free_text":
        return state

    final_response = state.get("final_response", "")
    if not final_response:
        return state

    from core.schemas import validate_agent_output, extract_json
    parsed = extract_json(final_response)
    if not parsed:
        return state

    valid, error_msg = validate_agent_output(agent_type, parsed)
    if valid:
        return state

    attempt = state.get("validation_attempt", 0)
    if attempt >= 2:
        logger.warning("Schema validation failed after retries for %s: %s", agent_type, error_msg)
        state["final_response"] = f"[Warning: output may be incomplete] {final_response}"
        return state

    from langchain_core.messages import HumanMessage
    state["validation_attempt"] = attempt + 1
    state["messages"].append(
        HumanMessage(content=f"Your output failed schema validation: {error_msg}\nPlease fix and output valid JSON.")
    )
    state["needs_retry"] = True
    return state


def _next_node(state: AgentState) -> str:
    return state.get("agent_type", "tutor")


def _respond_or_retry(state: AgentState) -> str:
    """After validation, either retry the agent or finish."""
    if state.get("needs_retry"):
        state["needs_retry"] = False
        return state.get("agent_type", "tutor")
    return "__end__"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("route", _route)
    for agent_name in _AGENTS:
        graph.add_node(agent_name, lambda s, an=agent_name: _run_agent(an, s))
    graph.add_node("respond", _respond)

    graph.set_entry_point("route")
    graph.add_conditional_edges("route", _next_node,
                                {name: name for name in _AGENTS})

    handoff_targets = {name: name for name in _AGENTS}
    handoff_targets["respond"] = "respond"
    for agent_name in _AGENTS:
        graph.add_conditional_edges(agent_name, _check_handoff, handoff_targets)

    retry_targets = {name: name for name in _AGENTS}
    retry_targets["__end__"] = END
    graph.add_conditional_edges("respond", _respond_or_retry, retry_targets)

    return graph


class AgentOrchestrator:
    def __init__(self):
        self._graph = build_graph().compile()

    def run(self, state: AgentState) -> AgentState:
        return self._graph.invoke(state)
