"""Utilities for extracting structured JSON from LLM text."""
from __future__ import annotations

import json


def extract_first_json_object(text: str) -> dict | None:
    """Return the first valid JSON object embedded in text.

    This scans brace-balanced candidates while respecting JSON strings and
    escapes, so markdown code fences or braces inside string values do not
    truncate or extend the candidate.
    """
    if not text:
        return None

    for start, ch in enumerate(text):
        if ch != "{":
            continue

        depth = 0
        in_string = False
        escaped = False

        for pos in range(start, len(text)):
            current = text[pos]

            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue

            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:pos + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break

    return None
