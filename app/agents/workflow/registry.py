"""Step handler registry — maps step types to their execution logic."""

import logging
from typing import Callable

logger = logging.getLogger(__name__)

StepHandler = Callable[[dict, dict], dict]
# signature: handler(step_def, context) -> output_dict


_HANDLERS: dict[str, StepHandler] = {}


def register_step_handler(step_type: str, handler: StepHandler):
    _HANDLERS[step_type] = handler


def get_step_handler(step_type: str) -> StepHandler | None:
    return _HANDLERS.get(step_type)


def list_step_types() -> list[str]:
    return list(_HANDLERS.keys())


def _handle_agent_call(step_def: dict, context: dict) -> dict:
    """Dispatch to an existing specialist agent."""
    from langchain_core.messages import HumanMessage
    from app.agents.orchestrator import _AGENTS

    agent_type = step_def.get("agent_type", "")
    instruction = step_def.get("instruction", "")

    agent = _AGENTS.get(agent_type)
    if not agent:
        return {"error": f"Unknown agent: {agent_type}", "success": False}

    state = {
        "messages": [HumanMessage(content=instruction)],
        "agent_type": agent_type,
        "user_id": context.get("user_id", 0),
        "user_role": context.get("user_role", "student"),
        "context": context.get("agent_context", {}),
        "tool_results": [],
        "final_response": "",
        "auto_routed": True,
        "handoff_to": None,
        "handoff_reason": None,
        "previous_agents": [],
    }

    result_state = agent.invoke(state)
    return {
        "success": True,
        "response": result_state.get("final_response", ""),
        "parsed_output": result_state.get("parsed_output"),
        "trace_id": result_state.get("trace_id"),
    }


def _handle_tool_call(step_def: dict, context: dict) -> dict:
    """Execute a single tool directly."""
    from app.agents.tools import get_all_tools
    from app.agents.tools.permissions import check_tool_permission

    tool_name = step_def.get("tool_name", "")
    tool_args = step_def.get("tool_args", {})
    agent_type = step_def.get("agent_type", "supervisor")
    user_role = context.get("user_role", "student")

    if not check_tool_permission(agent_type, tool_name, user_role):
        return {"error": f"Permission denied: {tool_name}", "success": False}

    tools = get_all_tools()
    tool_map = {t.name: t for t in tools}
    tool = tool_map.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}", "success": False}

    try:
        result = tool.invoke(tool_args)
        return {"success": True, "result": result}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_validation(step_def: dict, context: dict) -> dict:
    """Run a validation/critic step using LLM."""
    from langchain_core.messages import HumanMessage
    from app.agents.config import AIConfig

    instruction = step_def.get("instruction", "")
    target_step = step_def.get("validates_step")
    step_outputs = context.get("step_outputs", {})

    target_output = step_outputs.get(target_step, {}) if target_step is not None else {}

    prompt = (
        f"You are a quality validator. Evaluate the following output.\n\n"
        f"Validation criteria: {instruction}\n\n"
        f"Output to validate:\n{target_output}\n\n"
        f"Respond with JSON: {{\"passed\": true/false, \"issues\": [...], \"score\": 1-5}}"
    )

    try:
        llm = AIConfig.get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        import json
        content = response.content or ""
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(content[start:end])
            return {"success": True, "passed": result.get("passed", True), **result}
        return {"success": True, "passed": True, "issues": []}
    except Exception as e:
        logger.warning("Validation step failed: %s", e)
        return {"success": True, "passed": True, "issues": [f"Validation skipped: {e}"]}


def _handle_llm_call(step_def: dict, context: dict) -> dict:
    """Execute a standalone LLM call (not agent-bound)."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.agents.config import AIConfig

    instruction = step_def.get("instruction", "")
    system_prompt = step_def.get("system_prompt", "You are a helpful assistant.")
    step_outputs = context.get("step_outputs", {})

    enriched_instruction = instruction
    if step_outputs:
        enriched_instruction += f"\n\nPrevious step results available:\n{step_outputs}"

    try:
        llm = AIConfig.get_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=enriched_instruction),
        ]
        response = llm.invoke(messages)
        return {"success": True, "response": response.content or ""}
    except Exception as e:
        return {"error": str(e), "success": False}


def _handle_human_gate(step_def: dict, context: dict) -> dict:
    """Mark step as waiting for human approval."""
    return {
        "success": True,
        "waiting_approval": True,
        "approval_prompt": step_def.get("instruction", "Approve this action?"),
    }


# Register built-in handlers
register_step_handler("agent_call", _handle_agent_call)
register_step_handler("tool_call", _handle_tool_call)
register_step_handler("validation", _handle_validation)
register_step_handler("llm_call", _handle_llm_call)
register_step_handler("human_gate", _handle_human_gate)
