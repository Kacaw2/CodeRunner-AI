"""
Multi-agent generation pipeline (Phase 4, Task 16).

Chains multiple specialized stages for question generation:
  1. generate  — LLM produces the question JSON
  2. validate  — run solution against test cases in sandbox
  3. dedup     — search knowledge base for similar existing questions
  4. quality   — LLM reviews description clarity, examples, constraints
  5. finalize  — assemble the draft with all metadata

Built on LangGraph StateGraph for explicit state transitions and retry edges.
"""

import json
import logging
from typing import TypedDict, Literal

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from app.agents.config import AIConfig

logger = logging.getLogger(__name__)

MAX_GENERATE_RETRIES = 3
MAX_DEDUP_REGENERATIONS = 2
SIMILARITY_THRESHOLD = 0.8


class PipelineState(TypedDict):
    teacher_id: int
    language: str
    difficulty: str
    topic: str
    test_case_count: int
    prompt: str
    teacher_context: str
    generated_question: dict | None
    validation_results: list
    validation_passed: bool
    similar_questions: list
    is_duplicate: bool
    dedup_attempts: int
    quality_review: dict | None
    generate_attempts: int
    final_draft: dict | None
    error: str | None
    status: str


def _generate_question(state: PipelineState) -> PipelineState:
    """Use the Generator agent's LLM to produce question JSON."""
    from app.agents.prompts.generator import GENERATOR_SYSTEM_PROMPT
    from app.agents.agents.generator import _extract_json

    llm = AIConfig.get_llm()

    system_parts = [GENERATOR_SYSTEM_PROMPT]
    if state.get("teacher_context"):
        system_parts.append(f"\n## Teacher Preferences\n{state['teacher_context']}")
    system_parts.append(f"\nTarget language: {state.get('language', 'python')}")
    system_parts.append(f"Difficulty: {state.get('difficulty', 'medium')}")
    if state.get("topic"):
        system_parts.append(f"Topic: {state['topic']}")
    system_parts.append(f"Required test cases: at least {state.get('test_case_count', 5)}")

    if state.get("similar_questions") and state.get("is_duplicate"):
        existing_titles = [q["title"] for q in state["similar_questions"][:3]]
        system_parts.append(
            f"\n## Deduplication Warning\n"
            f"The following similar questions already exist: {existing_titles}\n"
            f"You MUST create a meaningfully different question."
        )

    system_ctx = "\n".join(system_parts)
    messages = [HumanMessage(content=state.get("prompt", "Create a coding problem"))]

    from langchain_core.messages import SystemMessage
    full_messages = [SystemMessage(content=system_ctx)] + messages

    attempt = state.get("generate_attempts", 0) + 1
    state["generate_attempts"] = attempt

    try:
        response = llm.invoke(full_messages)
        question_data = _extract_json(response.content or "")
        if question_data:
            state["generated_question"] = question_data
            state["error"] = None
        else:
            state["error"] = "Failed to extract JSON from LLM response"
            state["generated_question"] = None
    except Exception as e:
        logger.error("Generation failed (attempt %d): %s", attempt, e)
        state["error"] = str(e)
        state["generated_question"] = None

    return state


def _validate_question(state: PipelineState) -> PipelineState:
    """Run the reference solution against all test cases via sandbox."""
    from app.agents.agents.generator import _validate_solution

    question = state.get("generated_question")
    if not question:
        state["validation_passed"] = False
        state["validation_results"] = []
        return state

    solution = question.get("solution", "")
    test_cases = question.get("test_cases", [])
    language = question.get("programming_language", state.get("language", "python"))

    if not solution or not test_cases:
        state["validation_passed"] = False
        state["validation_results"] = [{"error": "Missing solution or test_cases"}]
        return state

    results = _validate_solution(solution, language, test_cases)
    failures = [r for r in results if not r["passed"]]

    state["validation_results"] = results
    state["validation_passed"] = len(failures) == 0

    if state["validation_passed"]:
        question["verified"] = True
    else:
        question["verified"] = False
        failure_summary = "; ".join(
            f"TC{f['index']}:{f['status']}" for f in failures
        )
        state["error"] = f"Validation failed: {failure_summary}"

    return state


def _check_duplicates(state: PipelineState) -> PipelineState:
    """Search the knowledge base for similar existing questions."""
    question = state.get("generated_question", {})
    if not question:
        state["is_duplicate"] = False
        state["similar_questions"] = []
        return state

    try:
        from app.agents.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        query_text = f"{question.get('title', '')} {question.get('description', '')[:200]}"
        similar = kb.search_similar_questions(
            query_text,
            n=3,
            language=question.get("programming_language"),
        )
        high_similarity = [q for q in similar if q.get("similarity", 0) > SIMILARITY_THRESHOLD]
        state["similar_questions"] = similar
        state["is_duplicate"] = len(high_similarity) > 0
        state["dedup_attempts"] = state.get("dedup_attempts", 0) + (1 if state["is_duplicate"] else 0)
    except Exception as e:
        logger.warning("Dedup check failed: %s", e)
        state["is_duplicate"] = False
        state["similar_questions"] = []

    return state


def _review_quality(state: PipelineState) -> PipelineState:
    """Use LLM to review the generated question's description quality."""
    question = state.get("generated_question")
    if not question:
        state["quality_review"] = {"quality_score": 0, "issues": ["No question to review"]}
        return state

    llm = AIConfig.get_llm()
    question_json = json.dumps(question, indent=2, ensure_ascii=False)

    review_prompt = (
        "Review this generated coding question for quality.\n"
        "Check:\n"
        "1. Is the description clear and unambiguous?\n"
        "2. Are input/output formats precisely specified?\n"
        "3. Are constraints reasonable?\n"
        "4. Do examples match the description?\n"
        "5. Is the difficulty appropriate?\n\n"
        f"Question:\n```json\n{question_json}\n```\n\n"
        'Output a JSON: {"quality_score": 1-5, "issues": ["..."], "suggestions": ["..."]}'
    )

    try:
        response = llm.invoke([HumanMessage(content=review_prompt)])
        from app.agents.agents.generator import _extract_json
        review_data = _extract_json(response.content or "")
        state["quality_review"] = review_data or {
            "quality_score": 3,
            "issues": [],
            "suggestions": ["Could not parse quality review output"],
        }
    except Exception as e:
        logger.warning("Quality review failed: %s", e)
        state["quality_review"] = {
            "quality_score": 3,
            "issues": [],
            "suggestions": [f"Quality review skipped: {e}"],
        }

    return state


def _finalize_draft(state: PipelineState) -> PipelineState:
    """Assemble all pipeline results into the final draft."""
    question = state.get("generated_question")
    if not question:
        state["final_draft"] = None
        state["status"] = "failed"
        return state

    state["final_draft"] = {
        "question_data": question,
        "validation_results": state.get("validation_results", []),
        "validation_passed": state.get("validation_passed", False),
        "similar_questions": state.get("similar_questions", []),
        "quality_review": state.get("quality_review"),
        "generate_attempts": state.get("generate_attempts", 1),
        "dedup_attempts": state.get("dedup_attempts", 0),
    }
    state["status"] = "completed"
    state["error"] = None
    return state


def _after_validate(state: PipelineState) -> str:
    if state.get("validation_passed"):
        return "passed"
    if state.get("generate_attempts", 0) < MAX_GENERATE_RETRIES:
        return "retry"
    return "failed"


def _after_dedup(state: PipelineState) -> str:
    if not state.get("is_duplicate"):
        return "unique"
    if state.get("dedup_attempts", 0) < MAX_DEDUP_REGENERATIONS:
        return "duplicate"
    return "unique"


def build_generation_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("generate", _generate_question)
    graph.add_node("validate", _validate_question)
    graph.add_node("dedup_check", _check_duplicates)
    graph.add_node("quality_review", _review_quality)
    graph.add_node("finalize", _finalize_draft)

    graph.set_entry_point("generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", _after_validate, {
        "passed": "dedup_check",
        "retry": "generate",
        "failed": "finalize",
    })
    graph.add_conditional_edges("dedup_check", _after_dedup, {
        "unique": "quality_review",
        "duplicate": "generate",
    })
    graph.add_edge("quality_review", "finalize")
    graph.add_edge("finalize", END)

    return graph


_compiled_pipeline = None


def get_generation_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_generation_pipeline().compile()
    return _compiled_pipeline


def run_generation_pipeline(
    teacher_id: int,
    prompt: str,
    language: str = "python",
    difficulty: str = "medium",
    topic: str = "",
    test_case_count: int = 5,
    teacher_context: str = "",
) -> dict:
    """Run the full multi-agent generation pipeline and return the final draft."""
    pipeline = get_generation_pipeline()

    initial_state: PipelineState = {
        "teacher_id": teacher_id,
        "language": language,
        "difficulty": difficulty,
        "topic": topic,
        "test_case_count": test_case_count,
        "prompt": prompt,
        "teacher_context": teacher_context,
        "generated_question": None,
        "validation_results": [],
        "validation_passed": False,
        "similar_questions": [],
        "is_duplicate": False,
        "dedup_attempts": 0,
        "quality_review": None,
        "generate_attempts": 0,
        "final_draft": None,
        "error": None,
        "status": "running",
    }

    result = pipeline.invoke(initial_state)
    return result
