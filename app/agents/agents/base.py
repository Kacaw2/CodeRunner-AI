import json
import logging
from abc import ABC, abstractmethod

from langchain_core.messages import AIMessage, ToolMessage

from app.agents.config import AIConfig, MAX_TOOL_ITERATIONS
from app.agents.exceptions import LLMError, ToolError, retry_on_llm_error
from app.agents.state import AgentState

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def invoke(self, state: AgentState) -> AgentState:
        ...

    def stream(self, state: AgentState):
        """Default streaming: run invoke() and yield the final response."""
        result = self.invoke(state)
        response = result.get("final_response", "")
        if response:
            yield {"type": "token", "content": response}

    @staticmethod
    def _inject_security(tool_name: str, args: dict, state: dict) -> dict:
        """Override security-critical tool arguments from verified agent state."""
        args = dict(args)
        if tool_name == "get_submission_detail":
            args["user_id"] = state["user_id"]
            args["user_role"] = state.get("user_role", "student")
        if tool_name == "get_student_submissions":
            if state.get("user_role") == "student":
                args["student_id"] = state["user_id"]
        return args

    @staticmethod
    @retry_on_llm_error(max_retries=2, base_delay=1.0)
    def _llm_invoke(llm, messages):
        return llm.invoke(messages)

    @staticmethod
    @retry_on_llm_error(max_retries=2, base_delay=1.0)
    def _llm_stream(llm, messages):
        return llm.stream(messages)

    def _run_tools(self, tool_calls: list, tools: list, state: dict) -> list[ToolMessage]:
        """Execute tool calls with error handling. Returns ToolMessage list."""
        tool_map = {t.name: t for t in tools}
        results = []
        for tc in tool_calls:
            name = tc["name"]
            tool = tool_map.get(name)
            if not tool:
                results.append(ToolMessage(
                    content=f"Unknown tool: {name}",
                    tool_call_id=tc["id"],
                ))
                continue
            args = self._inject_security(name, tc["args"], state)
            try:
                result = tool.invoke(args)
                results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            except Exception as e:
                logger.warning("Tool %s failed: %s", name, e)
                error_msg = f"Tool '{name}' encountered an error: {type(e).__name__}: {e}"
                results.append(ToolMessage(content=error_msg, tool_call_id=tc["id"]))
        return results

    def _invoke_with_tools(self, state: AgentState, tools: list, system_ctx: str) -> AgentState:
        """Shared invoke loop: LLM + tool calls with retries."""
        from langchain_core.messages import SystemMessage
        llm = AIConfig.get_llm()
        llm_with_tools = llm.bind_tools(tools)

        messages = [SystemMessage(content=system_ctx)] + list(state["messages"])
        response = None

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self._llm_invoke(llm_with_tools, messages)
            except LLMError:
                if iteration == 0:
                    raise
                break

            messages.append(response)

            if not response.tool_calls:
                break

            tool_msgs = self._run_tools(response.tool_calls, tools, state)
            messages.extend(tool_msgs)

        state["messages"] = messages
        state["final_response"] = (response.content if response and response.content else "")
        return state

    def _stream_with_tools(self, state: AgentState, tools: list, system_ctx: str):
        """Shared streaming loop: LLM + tool calls with retries."""
        from langchain_core.messages import SystemMessage
        llm = AIConfig.get_llm()
        llm_with_tools = llm.bind_tools(tools)

        messages = [SystemMessage(content=system_ctx)] + list(state["messages"])

        for iteration in range(MAX_TOOL_ITERATIONS):
            collected_content = ""
            tool_calls = []

            try:
                stream = self._llm_stream(llm_with_tools, messages)
                for chunk in stream:
                    if chunk.content:
                        collected_content += chunk.content
                        yield {"type": "token", "content": chunk.content}
                    if chunk.tool_call_chunks:
                        for tc_chunk in chunk.tool_call_chunks:
                            if tc_chunk.get("index") is not None:
                                idx = tc_chunk["index"]
                                while len(tool_calls) <= idx:
                                    tool_calls.append({"name": "", "args": "", "id": ""})
                                if tc_chunk.get("name"):
                                    tool_calls[idx]["name"] = tc_chunk["name"]
                                if tc_chunk.get("args"):
                                    tool_calls[idx]["args"] += tc_chunk["args"]
                                if tc_chunk.get("id"):
                                    tool_calls[idx]["id"] = tc_chunk["id"]
            except LLMError as e:
                if iteration == 0:
                    yield {"type": "error", "message": e.user_message}
                    return
                break

            if not tool_calls:
                state["final_response"] = collected_content
                messages.append(AIMessage(content=collected_content))
                break

            parsed_calls = []
            for tc in tool_calls:
                if not tc["name"]:
                    continue
                args = tc["args"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parsed_calls.append({"name": tc["name"], "args": args, "id": tc["id"]})

            ai_msg = AIMessage(content=collected_content, tool_calls=parsed_calls)
            messages.append(ai_msg)

            for tc in parsed_calls:
                yield {"type": "tool_call", "tool": tc["name"], "input": str(tc["args"])}
                tool_msgs = self._run_tools([tc], tools, state)
                messages.extend(tool_msgs)
                yield {"type": "tool_result", "tool": tc["name"],
                       "summary": f"Fetched {tc['name']} result"}

        state["messages"] = messages
