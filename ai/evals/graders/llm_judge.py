"""LLM-judge grader (Phase 6, Task 7 — stable interface).

Scores a response against a rubric with a fixed judge prompt. The judge is a
*quality* signal only — it must never replace deterministic safety graders.

Without a ``DEEPSEEK_API_KEY`` the grader returns a neutral ``skipped`` result.
When a key is present it calls the configured LLM, parses a JSON verdict, and
records the judge prompt/response and token cost on the result metadata.
"""

from __future__ import annotations

import json
import os
import re
import time
from decimal import Decimal

from ai.evals.graders.base import GraderResult, error_result, skipped_result, split_grader_type

GRADER_TYPE = "llm_judge"

_JUDGE_SYSTEM = (
    "You are a strict evaluator. Given a rubric and a candidate response, judge "
    "whether the response satisfies the rubric. Reply with ONLY a JSON object: "
    '{"passed": <true|false>, "score": <float 0..1>, "reason": "<short>"}.'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def run_llm_judge_grader(
    grader_type: str,
    response: str,
    params: dict | None = None,
    *,
    trace_id: str | None = None,
) -> GraderResult:
    _, name = split_grader_type(grader_type)
    params = params or {}
    start = time.perf_counter()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        result = skipped_result(
            GRADER_TYPE, name, "no DEEPSEEK_API_KEY", trace_id=trace_id
        )
        result.latency_ms = int((time.perf_counter() - start) * 1000)
        return result

    rubric = params.get("rubric", "Is the response correct and helpful?")
    prompt = f"Rubric:\n{rubric}\n\nResponse:\n{response}\n\nReturn only the JSON verdict."

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from ai.agents.config import AIConfig

        llm = AIConfig.get_llm()
        reply = llm.invoke([SystemMessage(content=_JUDGE_SYSTEM), HumanMessage(content=prompt)])
        verdict_text = getattr(reply, "content", "") or ""
        verdict = _parse_verdict(verdict_text)
    except Exception as exc:  # noqa: BLE001 — judge call boundary
        return error_result(
            GRADER_TYPE, name, f"judge call failed: {exc}", trace_id=trace_id
        )

    usage = getattr(reply, "usage_metadata", {}) or {}
    cost = _judge_cost(usage)

    return GraderResult(
        grader_type=GRADER_TYPE,
        grader_name=name,
        passed=bool(verdict.get("passed")),
        score=verdict.get("score"),
        reason=verdict.get("reason", ""),
        metadata={
            "judge_prompt": prompt[:2000],
            "judge_response": verdict_text[:2000],
            "tokens_input": usage.get("input_tokens"),
            "tokens_output": usage.get("output_tokens"),
        },
        latency_ms=int((time.perf_counter() - start) * 1000),
        cost_cny=cost,
        trace_id=trace_id,
    )


def _parse_verdict(text: str) -> dict:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        match = _JSON_RE.search(text or "")
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass
    return {"passed": False, "score": 0.0, "reason": "unparseable judge reply"}


def _judge_cost(usage: dict) -> Decimal | None:
    try:
        from core.observability.cost import compute_cost_cny
        from ai.agents.config import AIConfig

        cost = compute_cost_cny(
            AIConfig.MODEL,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
        return Decimal(str(cost)) if cost is not None else None
    except Exception:
        return None
