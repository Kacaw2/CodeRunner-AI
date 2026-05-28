"""Data sanitization for MCP tool responses — prevents PII and internal data leaks."""


def sanitize_agent_trace(run: dict, steps: list[dict]) -> dict:
    ctx = run.get("input_context") or {}
    ctx.pop("system_prompt", None)
    ctx.pop("system_message", None)
    run["input_context"] = ctx

    for step in steps:
        tool_input = step.get("tool_input") or {}
        if "code" in tool_input:
            code = tool_input["code"]
            tool_input["code"] = code[:200] + "..." if len(code) > 200 else code
        step["tool_input"] = tool_input
        preview = step.get("tool_output_preview")
        if preview and len(preview) > 300:
            step["tool_output_preview"] = preview[:300]

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
