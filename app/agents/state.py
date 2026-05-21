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
