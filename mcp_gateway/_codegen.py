"""Generator for the descriptor-driven external FastMCP tool wrappers.

The committed module ``mcp_gateway/generated_tools.py`` is produced by
``render_generated_tools_module()``. A contract test re-renders in memory and
fails if the committed file is stale, so the gateway surface can never drift
from ``TOOL_CATALOG`` / ``EXTERNAL_TOOL_MAP``.

Run ``python -m mcp_gateway._codegen`` to regenerate the committed file.

Caller-identity fields are NOT exposed as client parameters. Some canonical
descriptors include identity fields in their ``input_schema`` (so the runtime
can validate/inject them), but external API clients must never set them — that
would let an API-key holder spoof another user. Such fields are listed in
``CALLER_INJECTED_FIELDS`` and stripped from the generated signature. When the
descriptor marks one ``required`` (e.g. ``teacher_id``), the wrapper injects it
from the authenticated caller inside the ``_guarded`` context.
"""

from __future__ import annotations

import os

from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP
from tools.protocol.schemas.catalog import TOOL_CATALOG

# Canonical tool name -> descriptor fields that must come from the authenticated
# caller, never from client input. Stripped from the external signature.
CALLER_INJECTED_FIELDS: dict[str, set[str]] = {
    "coderunner.submission.get_detail": {"user_id", "user_role"},
    "coderunner.problem.save_generated": {"teacher_id"},
}

# How to derive a required injected field from get_caller_info() inside _guarded.
_CALLER_INJECT_EXPR: dict[str, str] = {
    "teacher_id": '_caller.get("user_id", 0)',
    "user_id": '_caller.get("user_id", 0)',
    "student_id": '_caller.get("user_id", 0)',
    "user_role": '_caller.get("role", "student")',
}

_PY_TYPE = {
    "integer": "int",
    "string": "str",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "array": "list",
}

_HEADER = '''"""AUTO-GENERATED — DO NOT EDIT BY HAND.

Generated from tools.protocol.schemas.catalog.TOOL_CATALOG and
mcp_gateway.tool_map.EXTERNAL_TOOL_MAP by mcp_gateway/_codegen.py.

Run ``python -m mcp_gateway._codegen`` to regenerate. The contract test in
tests/test_mcp_gateway_catalog_contract.py fails if this file is stale.
"""

from __future__ import annotations

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime, get_caller_info


def register_generated_catalog_tools(mcp: FastMCP) -> None:
'''


def _type_hint(schema: dict) -> str:
    t = schema.get("type", "string")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        base = _PY_TYPE.get(non_null[0], "object") if non_null else "object"
        return f"{base} | None" if "null" in t else base
    return _PY_TYPE.get(t, "object")


def _render_param(name: str, schema: dict, required: bool) -> str:
    hint = _type_hint(schema)
    if required:
        return f"{name}: {hint}"
    default = schema["default"] if "default" in schema else None
    return f"{name}: {hint} = {default!r}"


def _render_tool(external_name: str, canonical_name: str) -> str:
    descriptor = TOOL_CATALOG[canonical_name]
    schema = descriptor.input_schema or {}
    props: dict = schema.get("properties", {})
    required = set(schema.get("required", []))
    injected = CALLER_INJECTED_FIELDS.get(canonical_name, set())

    client_fields = [n for n in props if n not in injected]
    # Required (no default) params must precede optional ones in Python.
    ordered = [n for n in client_fields if n in required] + [
        n for n in client_fields if n not in required
    ]
    params = ", ".join(
        _render_param(n, props[n], n in required) for n in ordered
    )

    # args dict: client fields pass through; required injected fields come from
    # the caller. Non-required injected fields are simply omitted (the runtime
    # injects them during _sanitize_args).
    arg_items = [f'"{n}": {n}' for n in ordered]
    inject_required = [n for n in injected if n in required]
    for n in inject_required:
        arg_items.append(f'"{n}": {_CALLER_INJECT_EXPR[n]}')
    args_dict = "{" + ", ".join(arg_items) + "}"

    lines = [
        f"    @mcp.tool(name={external_name!r}, description={descriptor.description!r})",
        f"    def {external_name}({params}) -> str:",
    ]
    if inject_required:
        lines += [
            "        def _call():",
            "            _caller = get_caller_info() or {}",
            "            return call_via_runtime(",
            f"                {canonical_name!r},",
            f"                {args_dict},",
            "            )",
            f"        return _guarded(_call, canonical_tool={canonical_name!r})",
        ]
    else:
        lines += [
            "        return _guarded(lambda: call_via_runtime(",
            f"            {canonical_name!r},",
            f"            {args_dict},",
            f"        ), canonical_tool={canonical_name!r})",
        ]
    return "\n".join(lines)


def render_generated_tools_module() -> str:
    blocks = [
        _render_tool(external, canonical)
        for external, canonical in EXTERNAL_TOOL_MAP.items()
    ]
    return _HEADER + "\n\n".join(blocks) + "\n"


_TARGET = os.path.join(os.path.dirname(__file__), "generated_tools.py")


def write_generated_tools_module() -> None:
    with open(_TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_generated_tools_module())


if __name__ == "__main__":
    write_generated_tools_module()
    print(f"Wrote {_TARGET}")
