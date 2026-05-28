"""Data sanitization for MCP tool responses — prevents PII and internal data leaks."""

from core.observability.tracing import _redact_secrets


def sanitize_agent_trace(run: dict, steps: list[dict]) -> dict:
    ctx = run.get("input_context") or {}
    ctx.pop("system_prompt", None)
    ctx.pop("system_message", None)
    # Egress defense-in-depth: scrub credential-like strings even from
    # historical rows persisted before write-side redaction existed.
    run["input_context"] = _redact_secrets(ctx)
    if run.get("input_message"):
        run["input_message"] = _redact_secrets(run["input_message"])
    if run.get("output_response"):
        run["output_response"] = _redact_secrets(run["output_response"])

    for step in steps:
        tool_input = _redact_secrets(step.get("tool_input") or {})
        if "code" in tool_input:
            code = tool_input["code"]
            tool_input["code"] = code[:200] + "..." if len(code) > 200 else code
        step["tool_input"] = tool_input
        preview = step.get("tool_output_preview")
        if preview:
            preview = _redact_secrets(preview)
            step["tool_output_preview"] = preview[:300] if len(preview) > 300 else preview

    return {"run": run, "steps": steps}


def sanitize_student_summary(
    student_id: int, profile: dict, stats: dict
) -> dict:
    return {
        "student_id": student_id,
        "preferred_language": profile.get("preferred_language"),
        "weak_topics": list((profile.get("error_patterns") or {}).keys()),
        "strong_topics": list((profile.get("knowledge_map") or {}).keys())[:10],
        "total_submissions": stats.get("total_submissions", 0),
        "acceptance_rate": stats.get("acceptance_rate", 0),
        "active_days": stats.get("active_days", 0),
        "current_streak": stats.get("current_streak", 0),
    }
