"""
Agent handoff mechanism (Phase 4, Task 20).

Provides handoff detection and the system prompt addendum that teaches agents
when and how to request a handoff to another agent.
"""

import re
import logging

from core.state import AgentState

logger = logging.getLogger(__name__)

VALID_HANDOFF_TARGETS = {"tutor", "reviewer", "generator", "analytics"}

HANDOFF_PROMPT_ADDENDUM = """
## Agent Handoff
If you determine that the user's request is better handled by a different agent,
you may request a handoff by including the following marker at the END of your response:

[HANDOFF: agent_type | reason]

Where agent_type is one of: tutor, reviewer, generator, analytics
And reason is a brief explanation of why the handoff is needed.

Examples:
- Student asks for code review during tutoring: [HANDOFF: reviewer | Student is requesting a structured code review]
- Teacher asks for analytics during generation: [HANDOFF: analytics | Teacher wants performance data to guide question creation]

Rules:
- Only request a handoff when the other agent would clearly do a better job.
- Provide your best partial answer before the handoff marker.
- Never hand off to yourself or to the generator if the user is a student.
"""

HANDOFF_PATTERN = re.compile(
    r"\[HANDOFF:\s*(tutor|reviewer|generator|analytics)\s*\|\s*(.+?)\s*\]",
    re.IGNORECASE,
)


def detect_handoff(state: AgentState) -> AgentState:
    """Parse the agent's final_response for a handoff marker and update state."""
    response = state.get("final_response", "")
    if not response:
        return state

    match = HANDOFF_PATTERN.search(response)
    if not match:
        return state

    target = match.group(1).lower()
    reason = match.group(2).strip()

    if target not in VALID_HANDOFF_TARGETS:
        return state

    current = state.get("agent_type", "")
    if target == current:
        return state

    from core.definitions import can_route_to
    user_role = state.get("user_role", "student")
    if not can_route_to(target, user_role):
        logger.info("Blocked handoff to '%s' for role '%s'", target, user_role)
        return state

    state["handoff_to"] = target
    state["handoff_reason"] = reason
    state["handoff_source"] = current

    cleaned = HANDOFF_PATTERN.sub("", response).rstrip()
    state["final_response"] = cleaned
    # Conclusion summary handed to the next agent (truncated to avoid bloat).
    state["handoff_summary"] = cleaned[:1500]

    logger.info("Handoff detected: %s -> %s (reason: %s)", current, target, reason)
    return state


def rebuild_handoff_messages(messages, source_agent, summary):
    """Build the next agent's compact message list for a handoff.

    Returns ``(removals, rebuilt)`` where ``rebuilt`` is the original user
    request plus a concise summary HumanMessage, and ``removals`` are
    ``RemoveMessage`` markers for every prior message that carried an id.

    * LangGraph flows (with the ``add_messages`` reducer) apply
      ``removals + rebuilt`` so the reducer drops the old history.
    * Worker flows that manage ``state['messages']`` as a plain list replace it
      with ``rebuilt`` directly (RemoveMessage markers are reducer-only).
    """
    from langchain_core.messages import HumanMessage, RemoveMessage

    original = next((m for m in messages if isinstance(m, HumanMessage)), None)

    rebuilt = []
    if original is not None:
        rebuilt.append(HumanMessage(content=original.content))
    if summary:
        rebuilt.append(HumanMessage(
            content=f"[上一助手({source_agent})的结论摘要]\n{summary}\n\n"
                    f"请基于此继续处理用户的原始请求。"))

    removals = [RemoveMessage(id=m.id) for m in messages if getattr(m, "id", None)]
    return removals, rebuilt


def apply_handoff(state: AgentState, *, use_reducer: bool = True) -> AgentState:
    """Switch *state* to its pending handoff target with a compact context.

    Rebuilds the message history to the original request plus the previous
    agent's summary, records ``handoff_source``, sets ``agent_type`` to the
    target, and clears the transient handoff fields. Shared by the LangGraph
    runner and the streaming workers.

    ``use_reducer`` controls how the rebuilt messages are written:
    ``True`` for LangGraph state (emit RemoveMessage markers for the reducer),
    ``False`` for worker state managed as a plain list (replace directly).
    """
    source = state.get("agent_type", "")
    target = state.get("handoff_to")
    summary = state.get("handoff_summary", "")

    removals, rebuilt = rebuild_handoff_messages(
        state.get("messages", []), source, summary,
    )
    state["messages"] = (removals + rebuilt) if use_reducer else rebuilt

    state["handoff_source"] = source
    state["agent_type"] = target
    state["handoff_to"] = None
    state["handoff_reason"] = None
    state["handoff_summary"] = None
    return state
