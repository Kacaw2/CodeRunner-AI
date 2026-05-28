"""Convert MCP tool descriptors to LLM tool-calling schemas.

The LLM sees OpenAI-compatible function schemas.
This adapter builds them from ToolDescriptor without importing LangChain.
"""

from __future__ import annotations

from typing import Sequence
from tools.protocol.schemas.descriptors import ToolDescriptor


def descriptors_to_llm_tools(
    descriptors: Sequence[ToolDescriptor],
) -> list[dict]:
    """Return a list of OpenAI-style function schemas."""
    return [_to_function_schema(d) for d in descriptors]


def _to_function_schema(desc: ToolDescriptor) -> dict:
    return {
        "type": "function",
        "function": {
            "name": desc.name,
            "description": desc.description,
            "parameters": desc.input_schema,
        },
    }


def descriptors_to_langchain_tool_defs(
    descriptors: Sequence[ToolDescriptor],
) -> list[dict]:
    """Format for ChatOpenAI.bind_tools() which expects the same shape."""
    return descriptors_to_llm_tools(descriptors)
