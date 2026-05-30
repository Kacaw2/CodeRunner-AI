from typing import TypedDict, Literal, Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    agent_type: Literal["tutor", "reviewer", "generator", "analytics"]
    user_id: int
    user_role: str
    context: dict
    tool_results: list
    final_response: str
    # Phase 1 additions
    validation_passed: bool
    attempt: int
    task_id: str
    trace_id: str
    parsed_output: dict
    # Phase 2 additions
    auto_routed: bool
    handoff_to: str
    handoff_reason: str
    handoff_summary: str
    previous_agents: list
