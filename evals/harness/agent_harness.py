"""AgentHarness — single logical trace per chat task / handoff chain.

Progressive B: the harness owns one ``TraceCollector`` and installs it as the
ambient trace (see ``core.observability.tracing.use_current_trace``). Agents run
as execution units inside that ambient trace, writing spans without owning the
trace lifecycle. ``stream()`` is the main implementation; ``run()`` drains the
stream and aggregates a final ``AgentResult``.
"""

from dataclasses import dataclass, field

from agents import TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent
from agents.base import _trace_links_from_state
from graph.handoff import apply_handoff
from graph.runner import MAX_HANDOFFS, _classify_intent

_AGENT_MAP = {
    "tutor": TutorAgent,
    "reviewer": ReviewerAgent,
    "generator": GeneratorAgent,
    "analytics": AnalyticsAgent,
}


@dataclass
class AgentResult:
    """Aggregated outcome of one harness run."""

    trace_id: str
    status: str
    agent_type: str
    response: str = ""
    events: list = field(default_factory=list)


class AgentHarness:
    """Drive one chat task / handoff chain under a single owned trace."""

    def stream(
        self,
        *,
        agent_type: str,
        message: str,
        user_id,
        user_role: str,
        source: str = "agent",
        context: dict | None = None,
        budget: dict | None = None,
        history: list | None = None,
    ):
        """Yield agent events, ending with a single ``done`` carrying trace_id.

        The harness creates and owns one ``TraceCollector``, installs it as the
        ambient trace, runs the resolved agent plus any handoffs inside it, then
        saves the trace once with the aggregated final status.
        """
        from langchain_core.messages import HumanMessage
        from core.observability.tracing import TraceCollector, use_current_trace

        context = dict(context or {})

        # budget/source reach the agent runtime via the ambient TraceCollector
        # below (use_current_trace), not through this state dict.
        state = {
            "messages": list(history or []) + [HumanMessage(content=message)],
            "agent_type": agent_type,
            "user_id": user_id,
            "user_role": user_role,
            "context": context,
            "tool_results": [],
            "final_response": "",
        }

        resolved = agent_type
        if not resolved or resolved == "auto":
            state = _classify_intent(state)
            resolved = state.get("agent_type", "tutor")
            state["agent_type"] = resolved

        trace = TraceCollector(
            agent_type=resolved,
            user_id=user_id,
            conversation_id=context.get("conversation_id"),
            source=source,
            links=_trace_links_from_state(state),
            budget=budget,
        )
        trace.input_message = message
        trace.input_context = context

        final_response = ""
        with use_current_trace(trace):
            agent = _AGENT_MAP.get(resolved, TutorAgent)()
            for event in agent.stream(state):
                if event.get("type") == "token":
                    final_response += event.get("content", "")
                yield event

            handoff_count = 0
            previous_agents = [resolved]
            while (
                state.get("handoff_to")
                and handoff_count < MAX_HANDOFFS
                and state["handoff_to"] in _AGENT_MAP
                and state["handoff_to"] not in previous_agents
            ):
                target_type = state["handoff_to"]
                yield {
                    "type": "handoff_start",
                    "target": target_type,
                    "reason": state.get("handoff_reason", ""),
                }

                apply_handoff(state, use_reducer=False)

                target_agent = _AGENT_MAP.get(target_type, TutorAgent)()
                final_response = ""
                for event in target_agent.stream(state):
                    if event.get("type") == "token":
                        final_response += event.get("content", "")
                    yield event

                previous_agents.append(target_type)
                resolved = target_type
                handoff_count += 1

            if not final_response:
                final_response = state.get("final_response", "")

        status = trace.pending_status or "completed"
        trace.save(status=status, response=final_response, error=trace.pending_error)

        yield {
            "type": "done",
            "trace_id": trace.run_id,
            "agent_type": resolved,
            "status": status,
            "response": final_response,
        }

    def run(
        self,
        *,
        agent_type: str,
        message: str,
        user_id,
        user_role: str,
        source: str = "agent",
        context: dict | None = None,
        budget: dict | None = None,
        history: list | None = None,
    ) -> AgentResult:
        """Drain ``stream`` and aggregate the final ``AgentResult``."""
        events = []
        for event in self.stream(
            agent_type=agent_type,
            message=message,
            user_id=user_id,
            user_role=user_role,
            source=source,
            context=context,
            budget=budget,
            history=history,
        ):
            events.append(event)

        done = next((e for e in events if e.get("type") == "done"), None)
        if done is None:
            raise RuntimeError("AgentHarness.stream did not emit a done event")

        return AgentResult(
            trace_id=done["trace_id"],
            status=done["status"],
            agent_type=done["agent_type"],
            response=done.get("response", ""),
            events=events,
        )
