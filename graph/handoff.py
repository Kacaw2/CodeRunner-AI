"""
Agent handoff mechanism.

Delegation is a structured tool call (``coderunner.agent.delegate``), not a
free-text marker: the tool boundary validates the target edge and role RBAC,
then fills ``handoff_to/reason/source/summary`` on the run state. This module
owns the shared target validator (used by the delegate handler) plus the
context-rebuild helpers that the runner and workers apply to switch agents.
"""

import logging

from core.definitions import AGENT_DEFINITIONS, can_route_to
from core.state import AgentState

logger = logging.getLogger(__name__)

VALID_HANDOFF_TARGETS = frozenset().union(
    *(d.handoff_targets for d in AGENT_DEFINITIONS.values())
)

# Conclusion summary handed to the next agent is truncated to avoid context bloat.
HANDOFF_SUMMARY_LIMIT = 1500

HANDOFF_PROMPT_ADDENDUM = """
## Agent Handoff
If the user's request would clearly be handled better by a different agent, call
the `coderunner.agent.delegate` tool to hand the conversation off. Do NOT write a
handoff as plain text — the only way to delegate is the tool call.

Arguments:
- target: one of tutor, reviewer, generator, analytics
- reason: a brief explanation of why the handoff is needed
- summary: your conclusion so far, so the next agent can continue without
  re-deriving context

Rules:
- Only delegate when the other agent would clearly do a better job.
- You may only delegate to agents declared as your handoff targets; an illegal
  target or a target the user's role cannot access is rejected at the tool
  boundary.
- Never delegate to yourself.
"""


def validate_handoff_target(source: str, target: str, user_role: str) -> str | None:
    """Validate a delegation edge. Return an error message, or ``None`` if allowed.

    Shared by the delegate tool handler so the same rules that the legacy
    text-marker path enforced (valid target, no self-handoff, declared per-source
    target, role RBAC) now live at the tool boundary.
    """
    if target not in VALID_HANDOFF_TARGETS:
        return f"Unknown handoff target '{target}'."
    if target == source:
        return "An agent cannot hand off to itself."
    source_defn = AGENT_DEFINITIONS.get(source)
    if source_defn is not None and target not in source_defn.handoff_targets:
        return f"Agent '{source}' may not delegate to '{target}'."
    if not can_route_to(target, user_role):
        return f"Role '{user_role}' is not allowed to use agent '{target}'."
    return None


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
