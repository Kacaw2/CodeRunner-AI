import json
import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.agents.agents.base import BaseAgent
from app.agents.config import AIConfig
from app.agents.exceptions import LLMError, ValidationError
from app.agents.security import SECURITY_PROMPT_ADDENDUM
from app.agents.state import AgentState
from app.agents.prompts.generator import GENERATOR_SYSTEM_PROMPT
from app.agents.tools.code_executor import execute_code
from app.agents.tools.knowledge_tools import search_similar_questions

GENERATOR_TOOLS = [execute_code, search_similar_questions]

logger = logging.getLogger(__name__)

MAX_VALIDATION_ROUNDS = 3


def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object from LLM output (possibly inside ```json fences)."""
    fence_match = re.search(r"```json\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not brace_match:
        return None
    try:
        return json.loads(brace_match.group())
    except json.JSONDecodeError:
        return None


def _validate_solution(solution: str, language: str, test_cases: list) -> list[dict]:
    """Run the reference solution against every test case via the sandbox."""
    results = []
    for i, tc in enumerate(test_cases):
        stdin_text = tc.get("input", "")
        expected = tc.get("expected_output", "").rstrip()
        try:
            exec_result = execute_code.invoke({
                "code": solution,
                "language": language,
                "stdin_text": stdin_text,
                "expected_output": expected,
            })
        except Exception as e:
            logger.warning("Validation execution failed for test case %d: %s", i, e)
            exec_result = {"status": "SYSTEM_ERROR", "stdout": "", "stderr": str(e)}

        passed = exec_result.get("status") == "AC"
        results.append({
            "index": i,
            "passed": passed,
            "input": stdin_text,
            "expected": expected,
            "actual": (exec_result.get("stdout") or "").rstrip(),
            "error": exec_result.get("stderr") or "",
            "status": exec_result.get("status", "UNKNOWN"),
        })
    return results


class GeneratorAgent(BaseAgent):
    name = "generator"
    description = "Question generation agent for teachers"

    def _build_system_context(self, state: dict) -> str:
        from app.agents.memory import MemoryService

        context = state.get("context", {})
        parts = [GENERATOR_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(state["user_id"], state.get("user_role", "teacher"))
        if memory_ctx:
            parts.append(f"\n## Teacher Preferences (from profile)\n{memory_ctx}")

        if context.get("language"):
            parts.append(f"\nTarget programming language: {context['language']}")
        if context.get("difficulty"):
            parts.append(f"Difficulty level: {context['difficulty']}")
        if context.get("topic"):
            parts.append(f"Topic / knowledge area: {context['topic']}")
        test_count = context.get("test_case_count", 5)
        parts.append(f"Required test cases: at least {test_count} (mix of visible and hidden)")
        return "\n".join(parts)

    def invoke(self, state: AgentState) -> AgentState:
        llm = AIConfig.get_llm()
        context = state.get("context", {})
        language = context.get("language", "python")

        system_ctx = self._build_system_context(state)
        messages = [SystemMessage(content=system_ctx)] + list(state["messages"])

        question_data = None
        response_text = ""

        for round_num in range(MAX_VALIDATION_ROUNDS + 1):
            try:
                response = self._llm_invoke(llm, messages)
            except LLMError:
                if round_num == 0:
                    raise
                break

            messages.append(response)
            response_text = response.content or ""

            question_data = _extract_json(response_text)
            if not question_data:
                if round_num < MAX_VALIDATION_ROUNDS:
                    messages.append(HumanMessage(
                        content="I could not parse valid JSON from your response. "
                                "Please output the question as a single JSON object inside ```json fences."
                    ))
                    continue
                else:
                    state["messages"] = messages
                    state["final_response"] = response_text
                    return state

            solution = question_data.get("solution", "")
            test_cases = question_data.get("test_cases", [])

            if not solution or not test_cases:
                if round_num < MAX_VALIDATION_ROUNDS:
                    messages.append(HumanMessage(
                        content="The JSON is missing 'solution' or 'test_cases'. "
                                "Please include both and try again."
                    ))
                    continue
                break

            lang = question_data.get("programming_language", language)
            validation = _validate_solution(solution, lang, test_cases)
            failures = [r for r in validation if not r["passed"]]

            if not failures:
                question_data["verified"] = True
                logger.info("Generator: solution verified on round %d", round_num + 1)
                break

            if round_num < MAX_VALIDATION_ROUNDS:
                failure_report = "\n".join(
                    f"- Test case {f['index']}: status={f['status']}, "
                    f"input={f['input']!r}, expected={f['expected']!r}, "
                    f"actual={f['actual']!r}, error={f['error']!r}"
                    for f in failures
                )
                messages.append(HumanMessage(
                    content=f"Verification failed for {len(failures)}/{len(test_cases)} test cases:\n"
                            f"{failure_report}\n\n"
                            "Please fix the reference solution or the test cases and output the "
                            "complete question JSON again."
                ))
            else:
                question_data["verified"] = False
                logger.warning("Generator: solution not verified after %d rounds", MAX_VALIDATION_ROUNDS)

        if question_data:
            state["context"]["generated_question"] = question_data
            wrapped = json.dumps({"question": question_data}, ensure_ascii=False, indent=2)
            state["final_response"] = wrapped
        else:
            state["final_response"] = response_text

        state["messages"] = messages
        return state

    def stream(self, state: AgentState):
        """Streaming generator: yields tokens for each LLM round, plus validation events."""
        llm = AIConfig.get_llm()
        context = state.get("context", {})
        language = context.get("language", "python")

        system_ctx = self._build_system_context(state)
        messages = [SystemMessage(content=system_ctx)] + list(state["messages"])

        question_data = None
        collected = ""

        for round_num in range(MAX_VALIDATION_ROUNDS + 1):
            if round_num > 0:
                yield {"type": "tool_call", "tool": "self_validate",
                       "input": f"Round {round_num + 1}: fixing based on test failures"}

            collected = ""
            try:
                stream = self._llm_stream(llm, messages)
                for chunk in stream:
                    if chunk.content:
                        collected += chunk.content
                        yield {"type": "token", "content": chunk.content}
            except LLMError as e:
                if round_num == 0:
                    yield {"type": "error", "message": e.user_message}
                    return
                break

            messages.append(AIMessage(content=collected))

            question_data = _extract_json(collected)
            if not question_data:
                if round_num < MAX_VALIDATION_ROUNDS:
                    fix_msg = ("I could not parse valid JSON from your response. "
                               "Please output the question as a single JSON object inside ```json fences.")
                    messages.append(HumanMessage(content=fix_msg))
                    continue
                else:
                    state["final_response"] = collected
                    state["messages"] = messages
                    return

            solution = question_data.get("solution", "")
            test_cases = question_data.get("test_cases", [])

            if not solution or not test_cases:
                if round_num < MAX_VALIDATION_ROUNDS:
                    messages.append(HumanMessage(
                        content="The JSON is missing 'solution' or 'test_cases'. "
                                "Please include both and try again."
                    ))
                    continue
                break

            yield {"type": "tool_call", "tool": "execute_code",
                   "input": f"Validating solution against {len(test_cases)} test cases"}

            lang = question_data.get("programming_language", language)
            validation = _validate_solution(solution, lang, test_cases)
            failures = [r for r in validation if not r["passed"]]
            passed_count = len(test_cases) - len(failures)

            yield {"type": "tool_result", "tool": "execute_code",
                   "summary": f"Passed {passed_count}/{len(test_cases)} test cases"}

            if not failures:
                question_data["verified"] = True
                break

            if round_num < MAX_VALIDATION_ROUNDS:
                failure_report = "\n".join(
                    f"- Test case {f['index']}: status={f['status']}, "
                    f"input={f['input']!r}, expected={f['expected']!r}, "
                    f"actual={f['actual']!r}, error={f['error']!r}"
                    for f in failures
                )
                messages.append(HumanMessage(
                    content=f"Verification failed for {len(failures)}/{len(test_cases)} test cases:\n"
                            f"{failure_report}\n\n"
                            "Please fix the reference solution or the test cases and output the "
                            "complete question JSON again."
                ))
            else:
                question_data["verified"] = False

        if question_data:
            state["context"]["generated_question"] = question_data
            wrapped = json.dumps({"question": question_data}, ensure_ascii=False, indent=2)
            state["final_response"] = wrapped
        else:
            state["final_response"] = collected

        state["messages"] = messages
