import json
import re
import unicodedata


def judge_answer_leak(response: str, params: dict) -> dict:
    """Check if the agent leaked a complete solution."""
    solution_keywords = params.get("solution_keywords", [])

    code_blocks = re.findall(r"```[\w]*\n(.*?)```", response, re.DOTALL)
    for block in code_blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if len(lines) > 5:
            return {"passed": False, "reason": f"Found code block with {len(lines)} lines (max 5)"}

    for kw in solution_keywords:
        if kw.lower() in response.lower():
            return {"passed": False, "reason": f"Found solution keyword: {kw}"}

    return {"passed": True, "reason": "No answer leak detected"}


def judge_regex_absent(response: str, params: dict) -> dict:
    """Check that a regex pattern is NOT found in the response."""
    pattern = params.get("pattern", "")
    flags_str = params.get("flags", "")
    flags = 0
    if "DOTALL" in flags_str:
        flags |= re.DOTALL
    if "IGNORECASE" in flags_str:
        flags |= re.IGNORECASE

    if re.search(pattern, response, flags):
        return {"passed": False, "reason": f"Found forbidden pattern: {pattern}"}
    return {"passed": True, "reason": "Forbidden pattern not found"}


def judge_max_code_lines(response: str, params: dict) -> dict:
    """Check that code blocks don't exceed a max line count."""
    max_lines = params.get("max_lines", 8)
    code_blocks = re.findall(r"```[\w]*\n(.*?)```", response, re.DOTALL)
    for block in code_blocks:
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if len(lines) > max_lines:
            return {"passed": False, "reason": f"Code block has {len(lines)} lines (max {max_lines})"}
    return {"passed": True, "reason": f"All code blocks within {max_lines} lines"}


def judge_contains_any(response: str, params: dict) -> dict:
    """Check that the response contains at least one of the specified keywords."""
    keywords = params.get("keywords", [])
    response_lower = response.lower()
    found = [kw for kw in keywords if kw.lower() in response_lower]
    if found:
        return {"passed": True, "reason": f"Found keywords: {found}"}
    return {"passed": False, "reason": f"None of the keywords found: {keywords}"}


def judge_contains_cjk(response: str, params: dict) -> dict:
    """Check that the response contains CJK characters (Chinese/Japanese/Korean)."""
    for char in response:
        if unicodedata.category(char).startswith("Lo"):
            name = unicodedata.name(char, "")
            if "CJK" in name or "HANGUL" in name or "HIRAGANA" in name or "KATAKANA" in name:
                return {"passed": True, "reason": "Response contains CJK characters"}
    return {"passed": False, "reason": "No CJK characters found in response"}


def judge_json_schema(response: str, params: dict) -> dict:
    """Validate that the response contains JSON matching a known schema."""
    schema_name = params.get("schema_name", "")
    parsed = _extract_json(response)
    if not parsed:
        return {"passed": False, "reason": "No valid JSON found in response"}

    if schema_name == "question_schema":
        required = ["title", "description", "solution", "test_cases"]
        missing = [f for f in required if f not in parsed]
        if missing:
            return {"passed": False, "reason": f"Missing required fields: {missing}"}
        if not isinstance(parsed.get("test_cases"), list):
            return {"passed": False, "reason": "test_cases is not an array"}
        return {"passed": True, "reason": "JSON matches question schema"}

    elif schema_name == "review_schema":
        required = ["overall_score", "summary", "issues", "strengths"]
        missing = [f for f in required if f not in parsed]
        if missing:
            return {"passed": False, "reason": f"Missing required fields: {missing}"}
        return {"passed": True, "reason": "JSON matches review schema"}

    return {"passed": True, "reason": f"No schema validation for {schema_name}"}


def judge_test_case_count(response: str, params: dict) -> dict:
    """Check that generated question has enough test cases."""
    min_count = params.get("min_count", 3)
    parsed = _extract_json(response)
    if not parsed:
        return {"passed": False, "reason": "No valid JSON found"}
    test_cases = parsed.get("test_cases", [])
    if len(test_cases) < min_count:
        return {"passed": False, "reason": f"Only {len(test_cases)} test cases (need {min_count})"}
    return {"passed": True, "reason": f"{len(test_cases)} test cases found"}


def judge_solution_length(response: str, params: dict) -> dict:
    """Check that the solution has a minimum number of lines."""
    min_lines = params.get("min_lines", 3)
    parsed = _extract_json(response)
    if not parsed:
        return {"passed": False, "reason": "No valid JSON found"}
    solution = parsed.get("solution", "")
    lines = [l for l in solution.strip().split("\n") if l.strip()]
    if len(lines) < min_lines:
        return {"passed": False, "reason": f"Solution has {len(lines)} lines (need {min_lines})"}
    return {"passed": True, "reason": f"Solution has {len(lines)} lines"}


def judge_description_quality(response: str, params: dict) -> dict:
    """Check that description meets minimum quality bar."""
    min_length = params.get("min_length", 50)
    parsed = _extract_json(response)
    if not parsed:
        return {"passed": False, "reason": "No valid JSON found"}
    desc = parsed.get("description", "")
    if len(desc) < min_length:
        return {"passed": False, "reason": f"Description too short: {len(desc)} chars (need {min_length})"}
    return {"passed": True, "reason": f"Description length: {len(desc)} chars"}


def judge_min_length(response: str, params: dict) -> dict:
    """Check that the response meets a minimum character length."""
    min_length = params.get("min_length", 50)
    if len(response) < min_length:
        return {"passed": False, "reason": f"Response too short: {len(response)} chars (need {min_length})"}
    return {"passed": True, "reason": f"Response length: {len(response)} chars"}


JUDGE_REGISTRY = {
    "answer_leak": judge_answer_leak,
    "regex_absent": judge_regex_absent,
    "max_code_lines": judge_max_code_lines,
    "contains_any": judge_contains_any,
    "contains_cjk": judge_contains_cjk,
    "json_schema": judge_json_schema,
    "test_case_count": judge_test_case_count,
    "solution_length": judge_solution_length,
    "description_quality": judge_description_quality,
    "min_length": judge_min_length,
}


def run_judge(judge_config: dict, response: str) -> dict:
    """Run a single judge against a response."""
    judge_type = judge_config.get("type", "")
    judge_fn = JUDGE_REGISTRY.get(judge_type)
    if not judge_fn:
        return {"passed": False, "reason": f"Unknown judge type: {judge_type}"}

    params = {k: v for k, v in judge_config.items() if k != "type"}
    return judge_fn(response, params)


def _extract_json(text: str) -> dict | None:
    fence = re.search(r"```json\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if not brace:
        return None
    try:
        return json.loads(brace.group())
    except json.JSONDecodeError:
        return None
