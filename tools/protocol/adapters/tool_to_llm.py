"""Convert MCP tool descriptors to LLM tool-calling schemas.

The LLM sees OpenAI-compatible function schemas.
This adapter builds them from ToolDescriptor without importing LangChain.
"""

from __future__ import annotations

from typing import Sequence
from tools.protocol.schemas.descriptors import ToolDescriptor


def to_llm_tool_name(tool_name: str) -> str:
    """Encode a canonical MCP tool name as an OpenAI-compatible function name."""
    return tool_name.replace("_", "_u_").replace(".", "_d_")


def from_llm_tool_name(llm_name: str) -> str:
    """Decode a function name produced by :func:`to_llm_tool_name`."""
    out: list[str] = []
    i = 0
    while i < len(llm_name):
        if llm_name.startswith("_d_", i):
            out.append(".")
            i += 3
        elif llm_name.startswith("_u_", i):
            out.append("_")
            i += 3
        else:
            out.append(llm_name[i])
            i += 1
    return "".join(out)


def descriptors_to_llm_tools(
    descriptors: Sequence[ToolDescriptor],
) -> list[dict]:
    """Return a list of OpenAI-style function schemas."""
    return [_to_function_schema(d) for d in descriptors]


def _to_function_schema(desc: ToolDescriptor) -> dict:
    return {
        "type": "function",
        "function": {
            "name": to_llm_tool_name(desc.name),
            "description": desc.description,
            "parameters": desc.input_schema,
        },
    }


def descriptors_to_langchain_tool_defs(
    descriptors: Sequence[ToolDescriptor],
) -> list[dict]:
    """Format for ChatOpenAI.bind_tools() which expects the same shape."""
    return descriptors_to_llm_tools(descriptors)
