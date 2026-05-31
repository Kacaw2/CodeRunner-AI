import json
import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agents.base import BaseAgent
from agents.config import AIConfig
from core.exceptions import LLMError
from models.tiers import ModelTier
from core.security import SECURITY_PROMPT_ADDENDUM
from graph.handoff import HANDOFF_PROMPT_ADDENDUM
from core.state import AgentState
from agents.generator.prompt import GENERATOR_SYSTEM_PROMPT

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


def validate_reference_solution(
    solution: str,
    language: str,
    test_cases: list,
    *,
    user_id: int = 0,
    role: str = "teacher",
    agent_type: str = "generator",
    trace_id: str = "",
    conversation_id: str = "",
) -> list[dict]:
    """Run a teacher's reference solution against every test case.

    The generator verifies its own reference solution before a problem is saved.
    This routes through the MCP single boundary via ``coderunner.code.execute_internal``
    — a MEDIUM-risk, ``internal_only`` tool that needs no teacher approval and is
    callable only by ``agent_host`` callers. The HIGH-risk + TEACHER_REQUIRED
    ``coderunner.code.execute`` tool (for arbitrary/student-supplied code) would
    always return ``approval_required`` here, deadlocking self-validation; the
    internal tool resolves that without exposing a non-approval executor to any
    external ``code:execute`` API key (the guard's actor-type gate blocks them).
    """
    from mcp_gateway.client import MCPClientIdentity, get_mcp_tool_client

    client = get_mcp_tool_client()
    identity = MCPClientIdentity(
        user_id=user_id,
        role=role,
        agent_type=agent_type,
        conversation_id=conversation_id or None,
    )

    results = []
    for i, tc in enumerate(test_cases):
        stdin_text = tc.get("input", "")
        expected = tc.get("expected_output", "").rstrip()
        args = {
            "code": solution,
            "language": language,
            "stdin_text": stdin_text,
            "expected_output": expected,
        }
        try:
            envelope = client.call_tool("coderunner.code.execute_internal", args, identity)
        except Exception as e:
            logger.warning("Reference-solution validation failed for test case %d: %s", i, e)
            envelope = {"ok": False, "error": {"message": str(e)}}

        if envelope.get("ok"):
            exec_result = envelope.get("data") or {}
        else:
            err = envelope.get("error") or {}
            exec_result = {
                "status": "SYSTEM_ERROR",
                "stdout": "",
                "stderr": err.get("message", "validation execution failed"),
            }

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


def _validate_solution(solution: str, language: str, test_cases: list,
                       agent: BaseAgent | None = None, state: dict | None = None) -> list[dict]:
    """Validate a reference solution against test cases (trusted internal path).

    Thin wrapper that derives caller identity (for the audit record) from the
    optional ``agent``/``state`` and delegates to ``validate_reference_solution``.
    The ``agent``/``state`` arguments are kept for backward-compatibility with
    existing call sites; the former broken ``coderunner.code.execute`` MCP
    branch has been removed (see validate_reference_solution for why).
    """
    user_id = 0
    role = "teacher"
    conversation_id = ""
    if state:
        user_id = state.get("user_id", 0) or 0
        role = state.get("user_role", "teacher") or "teacher"
        ctx = state.get("context") or {}
        conversation_id = str(ctx.get("conversation_id") or "")
    agent_type = getattr(agent, "name", "generator") if agent else "generator"
    return validate_reference_solution(
        solution, language, test_cases,
        user_id=user_id, role=role, agent_type=agent_type,
        conversation_id=conversation_id,
    )


class GeneratorAgent(BaseAgent):
    name = "generator"
    description = "Problem generation agent for teachers"
    default_model_tier = ModelTier.STRONG

    def _build_system_context(self, state: dict) -> str:
        from memory.service import MemoryService

        context = state.get("context", {})
        parts = [GENERATOR_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM + HANDOFF_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(state["user_id"], state.get("user_role", "teacher"))
        if memory_ctx:
            parts.append(f"\n## Teacher Preferences (from profile)\n{memory_ctx}")

        similar = self._get_similar_problems(state)
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

    def _get_similar_problems(self, state: dict) -> str:
        """Pre-fetch similar problems from KB for dedup awareness."""
        try:
            from knowledge.store import get_knowledge_base
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
        results = kb.search_similar_problems(query, n=3, language=language)
        if not results:
            return ""

        lines = ["\n## Existing Similar Problems (avoid duplication)"]
        for r in results:
            sim = r.get("similarity", 0)
            title = r.get("title", "untitled")
            preview = r.get("text_preview", "")[:100]
            lines.append(f"- [{sim:.0%} similar] {title}: {preview}...")
        lines.append("Generate a problem that is distinct from the above. Vary the scenario, constraints, or algorithm.")
        return "\n".join(lines)

    def invoke(self, state: AgentState) -> AgentState:
        context = state.get("context", {})
        language = context.get("language", "python")
        system_ctx = self._build_system_context(state)

        question_data = None

        for round_num in range(MAX_VALIDATION_ROUNDS + 1):
            try:
                state = self._invoke_with_mcp_tools(state, self.mcp_tool_names, system_ctx)
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
            state["context"]["generated_problem"] = question_data
            wrapped = json.dumps({"question": question_data}, ensure_ascii=False, indent=2)
            state["final_response"] = wrapped

        return state

    def stream(self, state: AgentState):
        """Streaming generator: yields tokens for each LLM round, plus validation events."""
        from core.observability.tracing import TraceCollector

        llm = AIConfig.get_llm(tier=self.default_model_tier)
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
                                if round_num == 0:
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

                yield {"type": "tool_call", "tool": "coderunner.code.execute_internal",
                       "input": f"Validating solution against {len(test_cases)} test cases"}

                lang = question_data.get("programming_language", language)
                with trace.trace_tool_call("coderunner.code.execute_internal", {
                    "language": lang,
                    "test_case_count": len(test_cases),
                }):
                    validation = _validate_solution(solution, lang, test_cases,
                                                    agent=self, state=state)
                failures = [r for r in validation if not r["passed"]]
                passed_count = len(test_cases) - len(failures)

                yield {"type": "tool_result", "tool": "coderunner.code.execute_internal",
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
                state["context"]["generated_problem"] = question_data
                wrapped = json.dumps({"question": question_data}, ensure_ascii=False, indent=2)
                state["final_response"] = wrapped
                if round_num > 0:
                    yield {"type": "replace", "content": wrapped}
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
