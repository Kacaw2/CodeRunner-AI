"""
Domain-specific step handlers for the workflow engine.

These handlers implement the generation pipeline's logic as workflow steps,
enabling the existing generation flow to run through the generic framework.
"""

import json
import logging

from ai.agents.config import AIConfig
from ai.graph.node_registry import register_step_handler

logger = logging.getLogger(__name__)


def _handle_generate_problem(step_def: dict, context: dict) -> dict:
    """Generate a coding problem using the Generator agent's LLM."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from ai.agents.generator.prompt import GENERATOR_SYSTEM_PROMPT
    from ai.agents.generator.agent import _extract_json

    agent_context = context.get("agent_context", {})
    language = agent_context.get("language", "python")
    difficulty = agent_context.get("difficulty", "medium")
    topic = agent_context.get("topic", "")
    test_case_count = agent_context.get("test_case_count", 5)
    prompt_text = agent_context.get("prompt", step_def.get("instruction", ""))

    system_parts = [GENERATOR_SYSTEM_PROMPT]
    system_parts.append(f"\nTarget language: {language}")
    system_parts.append(f"Difficulty: {difficulty}")
    if topic:
        system_parts.append(f"Topic: {topic}")
    system_parts.append(f"Required test cases: at least {test_case_count}")

    previous_similar = context.get("step_outputs", {}).get(2, {})
    if previous_similar and previous_similar.get("is_duplicate"):
        existing = previous_similar.get("similar_titles", [])
        system_parts.append(
            f"\n## Deduplication Warning\n"
            f"These similar problems already exist: {existing}\n"
            f"You MUST create a meaningfully different problem."
        )

    critic_feedback = context.get("critic_feedback")
    if critic_feedback:
        system_parts.append(
            f"\n## Previous Attempt Rejected\n"
            f"The prior attempt was rejected for: {critic_feedback}\n"
            f"Fix these issues in this attempt."
        )

    system_ctx = "\n".join(system_parts)
    messages = [
        SystemMessage(content=system_ctx),
        HumanMessage(content=prompt_text or "Create a coding problem"),
    ]

    try:
        llm = AIConfig.get_llm()
        response = llm.invoke(messages)
        problem_data = _extract_json(response.content or "")
        if problem_data:
            return {"success": True, "problem_data": problem_data}
        return {"success": False, "error": "Failed to extract JSON from LLM response"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_validate_solution(step_def: dict, context: dict) -> dict:
    """Run reference solution against test cases in sandbox."""
    from ai.agents.generator.agent import _validate_solution

    step_outputs = context.get("step_outputs", {})
    gen_output = step_outputs.get(0, {})
    problem_data = gen_output.get("problem_data", {})

    if not problem_data:
        return {"success": False, "error": "No problem data from generation step"}

    solution = problem_data.get("solution", "")
    test_cases = problem_data.get("test_cases", [])
    language = problem_data.get("programming_language",
                                context.get("agent_context", {}).get("language", "python"))

    if not solution or not test_cases:
        return {"success": False, "error": "Missing solution or test_cases"}

    try:
        results = _validate_solution(
            solution, language, test_cases,
            state={
                "user_id": context.get("user_id", 0) or 0,
                "user_role": context.get("user_role", "teacher"),
                "context": {"conversation_id": context.get("conversation_id")},
            },
        )
        failures = [r for r in results if not r.get("passed")]
        passed = len(failures) == 0

        if passed:
            problem_data["verified"] = True

        return {
            "success": passed,
            "validation_passed": passed,
            "results": results,
            "failures": len(failures),
            "problem_data": problem_data,
            "error": f"{len(failures)} test cases failed" if not passed else None,
        }
    except Exception as e:
        return {"success": False, "error": f"Validation error: {e}"}


def _handle_dedup_check(step_def: dict, context: dict) -> dict:
    """Search knowledge base for similar existing problems."""
    from ai.knowledge.store import get_knowledge_base

    step_outputs = context.get("step_outputs", {})
    gen_output = step_outputs.get(0, {})
    problem_data = gen_output.get("problem_data", {})

    if not problem_data:
        return {"success": True, "is_duplicate": False, "similar_problems": []}

    try:
        from core.config import get_settings
        threshold = get_settings().RAG_DEDUP_THRESHOLD
        kb = get_knowledge_base()
        query_text = f"{problem_data.get('title', '')} {problem_data.get('description', '')[:200]}"
        similar = kb.search_similar_problems(
            query_text,
            n=3,
            language=problem_data.get("programming_language"),
            owner_id=context.get("user_id"),
        )
        high_similarity = [q for q in similar if q.get("similarity", 0) > threshold]
        is_duplicate = len(high_similarity) > 0

        return {
            "success": True,
            "is_duplicate": is_duplicate,
            "similar_problems": similar,
            "similar_titles": [q.get("title", "") for q in high_similarity],
        }
    except Exception as e:
        logger.warning("Dedup check failed: %s", e)
        return {"success": True, "is_duplicate": False, "similar_problems": []}


def _handle_quality_review(step_def: dict, context: dict) -> dict:
    """LLM-based quality review of generated problem."""
    from langchain_core.messages import HumanMessage
    from ai.agents.generator.agent import _extract_json

    step_outputs = context.get("step_outputs", {})
    gen_output = step_outputs.get(0, {})
    problem_data = gen_output.get("problem_data", {})

    if not problem_data:
        return {"success": True, "passed": False, "quality_score": 0, "issues": ["No problem to review"]}

    question_json = json.dumps(problem_data, indent=2, ensure_ascii=False)
    review_prompt = (
        "Review this generated coding problem for quality.\n"
        "Check:\n"
        "1. Is the description clear and unambiguous?\n"
        "2. Are input/output formats precisely specified?\n"
        "3. Are constraints reasonable?\n"
        "4. Do examples match the description?\n"
        "5. Is the difficulty appropriate?\n\n"
        f"Question:\n```json\n{question_json}\n```\n\n"
        'Output JSON: {"quality_score": 1-5, "passed": true/false, "issues": ["..."], "suggestions": ["..."]}'
    )

    try:
        llm = AIConfig.get_llm()
        response = llm.invoke([HumanMessage(content=review_prompt)])
        review_data = _extract_json(response.content or "")
        if review_data:
            review_data.setdefault("passed", review_data.get("quality_score", 3) >= 3)
            review_data["success"] = True
            return review_data
        return {"success": True, "passed": True, "quality_score": 3, "issues": []}
    except Exception as e:
        logger.warning("Quality review failed: %s", e)
        return {"success": True, "passed": True, "quality_score": 3, "issues": [f"Review skipped: {e}"]}


def _handle_finalize_draft(step_def: dict, context: dict) -> dict:
    """Assemble final draft from all previous step outputs."""
    step_outputs = context.get("step_outputs", {})
    gen_output = step_outputs.get(0, {})
    validation_output = step_outputs.get(1, {})
    dedup_output = step_outputs.get(2, {})
    quality_output = step_outputs.get(3, {})

    problem_data = gen_output.get("problem_data", {})
    if not problem_data:
        return {"success": False, "error": "No problem data to finalize"}

    draft = {
        "problem_data": problem_data,
        "validation_passed": validation_output.get("validation_passed", False),
        "validation_results": validation_output.get("results", []),
        "similar_problems": dedup_output.get("similar_problems", []),
        "is_duplicate": dedup_output.get("is_duplicate", False),
        "quality_review": {
            "score": quality_output.get("quality_score", 0),
            "issues": quality_output.get("issues", []),
            "suggestions": quality_output.get("suggestions", []),
        },
    }

    return {"success": True, "draft": draft, "waiting_approval": True}


# Register generation-specific handlers as custom step types
register_step_handler("generate_problem", _handle_generate_problem)
register_step_handler("validate_solution", _handle_validate_solution)
register_step_handler("dedup_check", _handle_dedup_check)
register_step_handler("quality_review", _handle_quality_review)
register_step_handler("finalize_draft", _handle_finalize_draft)
