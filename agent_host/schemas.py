import json
import re

from jsonschema import validate, ValidationError as JsonSchemaError

QUESTION_SCHEMA = {
    "type": "object",
    "required": ["title", "description", "solution", "test_cases", "programming_language"],
    "properties": {
        "title": {"type": "string", "minLength": 3, "maxLength": 200},
        "description": {"type": "string", "minLength": 50},
        "programming_language": {"type": "string", "enum": ["python", "c", "java", "cpp"]},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        "solution": {"type": "string", "minLength": 10},
        "solution_explanation": {"type": "string"},
        "starter_code": {"type": "string"},
        "test_cases": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "required": ["input", "expected_output"],
                "properties": {
                    "input": {"type": "string"},
                    "expected_output": {"type": "string"},
                    "is_hidden": {"type": "boolean"},
                    "weight": {"type": "number", "minimum": 0},
                },
            },
        },
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["overall_score", "summary", "issues", "strengths"],
    "properties": {
        "overall_score": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "summary": {"type": "string", "minLength": 10},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "category", "message"],
                "properties": {
                    "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                    "category": {"type": "string"},
                    "message": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                },
            },
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "complexity": {"type": "object"},
    },
}

ANALYTICS_SCHEMA = {
    "type": "object",
    "required": ["summary", "progress", "recommendations"],
    "properties": {
        "summary": {"type": "string", "minLength": 20},
        "error_patterns": {"type": "array"},
        "progress": {
            "type": "object",
            "required": ["total_submissions", "acceptance_rate", "trend"],
        },
        "weak_areas": {"type": "array"},
        "strengths": {"type": "array"},
        "recommendations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["action", "reason"],
            },
        },
    },
}

AGENT_SCHEMAS = {
    "generator": QUESTION_SCHEMA,
    "reviewer": REVIEW_SCHEMA,
    "analytics": ANALYTICS_SCHEMA,
}


def validate_agent_output(agent_type: str, data: dict) -> tuple[bool, str]:
    schema = AGENT_SCHEMAS.get(agent_type)
    if not schema:
        return True, ""
    try:
        validate(instance=data, schema=schema)
        return True, ""
    except JsonSchemaError as e:
        path = "/".join(str(p) for p in e.path)
        return False, f"Schema validation failed: {e.message} at {path}" if path else f"Schema validation failed: {e.message}"


def extract_json(text: str) -> dict | None:
    fence = re.search(r"```json\s*\n?(.*?)```", text, re.DOTALL)
    raw = fence.group(1) if fence else text
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if not brace:
        return None
    try:
        return json.loads(brace.group())
    except json.JSONDecodeError:
        return None
