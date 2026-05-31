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

    cleaned = HANDOFF_PATTERN.sub("", response).rstrip()
    state["final_response"] = cleaned
    # Conclusion summary handed to the next agent (truncated to avoid bloat).
    state["handoff_summary"] = cleaned[:1500]

    logger.info("Handoff detected: %s -> %s (reason: %s)", current, target, reason)
    return state
