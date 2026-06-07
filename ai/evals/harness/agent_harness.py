"""AgentHarness — single logical trace per chat task / handoff chain.

Progressive B: the harness owns one ``TraceCollector`` and installs it as the
ambient trace (see ``core.observability.tracing.use_current_trace``). Agents run
as execution units inside that ambient trace, writing spans without owning the
trace lifecycle. ``stream()`` is the main implementation; ``run()`` drains the
stream and aggregates a final ``AgentResult``.
"""

from dataclasses import dataclass, field

from ai.agents.base import _trace_links_from_state
from ai.agents.registry import get_agent_instance
from ai.graph.handoff import stream_with_handoffs
from ai.graph.runner import _classify_intent


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

        def _stream_agent(agent_type, run_state):
            agent = get_agent_instance(agent_type, default="tutor")
            yield from agent.stream(run_state)

        final_response = ""
        with use_current_trace(trace):
            for event in stream_with_handoffs(state, stream_fn=_stream_agent):
                if event.get("type") == "handoff_start":
                    final_response = ""
                elif event.get("type") == "token":
                    final_response += event.get("content", "")
                yield event

            resolved = state.get("agent_type", resolved)
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
