import json
import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.agents.agents.base import BaseAgent
from app.agents.config import AIConfig
from app.agents.exceptions import LLMError
from app.agents.security import SECURITY_PROMPT_ADDENDUM
from app.agents.handoff import HANDOFF_PROMPT_ADDENDUM
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


def _validate_solution(solution: str, language: str, test_cases: list,
                       agent=None, state=None) -> list[dict]:
    """Run the reference solution against every test case via the sandbox.

    When agent and state are provided, routes execution through _run_tools()
    for permission checks and tracing. Falls back to direct invocation otherwise.
    """
    from uuid import uuid4

    results = []
    for i, tc in enumerate(test_cases):
        stdin_text = tc.get("input", "")
        expected = tc.get("expected_output", "").rstrip()
        tool_args = {
            "code": solution,
            "language": language,
            "stdin_text": stdin_text,
            "expected_output": expected,
        }
        try:
            if agent and state:
                tool_call = {"name": "execute_code", "args": tool_args, "id": str(uuid4())}
                tool_msgs = agent._run_tools([tool_call], GENERATOR_TOOLS, state)
                raw = tool_msgs[0].content if tool_msgs else "{}"
                import json as _json
                try:
                    exec_result = _json.loads(raw)
                except (ValueError, TypeError):
                    exec_result = {"status": "AC" if "AC" in raw else "UNKNOWN", "stdout": raw, "stderr": ""}
            else:
                exec_result = execute_code.invoke(tool_args)
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
        parts = [GENERATOR_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM + HANDOFF_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(state["user_id"], state.get("user_role", "teacher"))
        if memory_ctx:
            parts.append(f"\n## Teacher Preferences (from profile)\n{memory_ctx}")

        similar = self._get_similar_questions(state)
        if similar:
            parts.append(similar)

        if context.get("language"):
            parts.append(f"\nTarget programming language: {context['language']}")
        if context.get("difficulty"):
            parts.append(f"Difficulty level: {context['difficulty']}")
        if context.get("topic"):
            parts.append(f"Topic / knowledge area: {context['topic']}")
        test_count = context.get("test_case_count", 5)
        parts.append(f"Required test cases: at least {test_count} (mix of visible and hidden)")
        return "\n".join(parts)

    def _get_similar_questions(self, state: dict) -> str:
        """Pre-fetch similar questions from KB for dedup awareness."""
        try:
            from app.agents.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()
        except Exception:
            return ""

        context = state.get("context", {})
        messages = state.get("messages", [])
        query = context.get("topic", "")
        if not query and messages:
            query = messages[-1].content[:200]
        if not query:
            return ""

        language = context.get("language", "python")
        results = kb.search_similar_questions(query, n=3, language=language)
        if not results:
            return ""

        lines = ["\n## Existing Similar Questions (avoid duplication)"]
        for r in results:
            sim = r.get("similarity", 0)
            title = r.get("title", "untitled")
            preview = r.get("text_preview", "")[:100]
            lines.append(f"- [{sim:.0%} similar] {title}: {preview}...")
        lines.append("Generate a question that is distinct from the above. Vary the scenario, constraints, or algorithm.")
        return "\n".join(lines)

    def invoke(self, state: AgentState) -> AgentState:
        context = state.get("context", {})
        language = context.get("language", "python")
        system_ctx = self._build_system_context(state)

        question_data = None

        for round_num in range(MAX_VALIDATION_ROUNDS + 1):
            try:
                state = self._invoke_with_tools(state, GENERATOR_TOOLS, system_ctx)
            except LLMError:
                if round_num == 0:
                    raise
                break

            response_text = state.get("final_response", "")
            question_data = _extract_json(response_text)

            if not question_data:
                if round_num < MAX_VALIDATION_ROUNDS:
                    state["messages"].append(HumanMessage(
                        content="I could not parse valid JSON from your response. "
                                "Please output the question as a single JSON object inside ```json fences."
                    ))
                    continue
                else:
                    return state

            solution = question_data.get("solution", "")
            test_cases = question_data.get("test_cases", [])

            if not solution or not test_cases:
                if round_num < MAX_VALIDATION_ROUNDS:
                    state["messages"].append(HumanMessage(
                        content="The JSON is missing 'solution' or 'test_cases'. "
                                "Please include both and try again."
                    ))
                    continue
                break

            lang = question_data.get("programming_language", language)
            validation = _validate_solution(solution, lang, test_cases,
                                            agent=self, state=state)
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
                state["messages"].append(HumanMessage(
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

        return state

    def stream(self, state: AgentState):
        """Streaming generator: yields tokens for each LLM round, plus validation events."""
        from app.agents.tracing import TraceCollector

        llm = AIConfig.get_llm()
        context = state.get("context", {})
        language = context.get("language", "python")

        system_ctx = self._build_system_context(state)
        messages = [SystemMessage(content=system_ctx)] + list(state["messages"])
        trace = TraceCollector(
            agent_type=state.get("agent_type", self.name),
            user_id=state["user_id"],
            conversation_id=context.get("conversation_id"),
        )
        if state.get("messages"):
            last_msg = state["messages"][-1]
            trace.input_message = getattr(last_msg, "content", "")
        trace.input_context = context

        question_data = None
        collected = ""
        trace_saved = False

        try:
            for round_num in range(MAX_VALIDATION_ROUNDS + 1):
                if round_num > 0:
                    yield {"type": "tool_call", "tool": "self_validate",
                           "input": f"Round {round_num + 1}: fixing based on test failures"}

                collected = ""
                try:
                    with trace.trace_llm_call() as llm_step:
                        stream = self._llm_stream(llm, messages)
                        for chunk in stream:
                            usage = getattr(chunk, "usage_metadata", None)
                            if usage:
                                input_tokens = usage.get("input_tokens", 0)
                                output_tokens = usage.get("output_tokens", 0)
                                trace.total_input_tokens += input_tokens
                                trace.total_output_tokens += output_tokens
                                llm_step["prompt_tokens"] = llm_step.get("prompt_tokens", 0) + input_tokens
                                llm_step["completion_tokens"] = llm_step.get("completion_tokens", 0) + output_tokens
                            if chunk.content:
                                collected += chunk.content
                                yield {"type": "token", "content": chunk.content}
                except LLMError as e:
                    if round_num == 0:
                        yield {"type": "error", "message": e.user_message}
                        trace.save(status="failed", error=e)
                        trace_saved = True
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
                    break

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
                with trace.trace_tool_call("execute_code", {
                    "language": lang,
                    "test_case_count": len(test_cases),
                }):
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
            state["trace_id"] = trace.run_id
            trace.save(status="completed", response=state.get("final_response", ""))
            trace_saved = True
        except GeneratorExit:
            if not trace_saved:
                trace.save(status="interrupted")
                trace_saved = True
        except Exception as e:
            if not trace_saved:
                trace.save(status="failed", error=e)
                trace_saved = True
            raise
