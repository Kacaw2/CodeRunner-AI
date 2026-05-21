import json
import logging
from datetime import datetime

from langchain_core.messages import HumanMessage

from app.agents.agents.generator import GeneratorAgent, _extract_json, _validate_solution
from app.agents.config import AIConfig
from app.agents.exceptions import AIError
from app.agents.task_state import TaskStatus, validate_transition
from app.core.extensions import db

logger = logging.getLogger(__name__)


class BatchTaskRunner:
    """Runs multiple question-generation sub-tasks with per-item retry and progress tracking."""

    def __init__(self, task):
        from app.models.agent_task import AgentTask
        self.task: AgentTask = task
        self.results = []

    def _transition(self, target: TaskStatus):
        current = TaskStatus(self.task.status)
        if validate_transition(current, target):
            self.task.status = target.value
            self.task.updated_at = datetime.utcnow()
            db.session.commit()
        else:
            logger.warning("Invalid transition %s -> %s for task %s", current, target, self.task.id)

    def run(self):
        steps = self.task.plan_steps or [self.task.input_params]
        start_from = self.task.current_step or 0
        self.results = self.task.result or []

        self._transition(TaskStatus.EXECUTING)

        for i in range(start_from, len(steps)):
            self.task.current_step = i
            db.session.commit()

            try:
                result = self._run_single_with_retry(steps[i])
                self.results.append({"step": i, "status": "completed", "result": result})
            except Exception as e:
                logger.warning("Batch step %d failed: %s", i, e)
                self.results.append({"step": i, "status": "failed", "error": str(e)})

            self.task.result = self.results
            db.session.commit()

        completed = sum(1 for r in self.results if r["status"] == "completed")
        self.task.result = self.results

        if completed > 0:
            self._transition(TaskStatus.COMPLETED)
        else:
            self._transition(TaskStatus.FAILED)
            self.task.error_detail = "All batch items failed"

        self.task.completed_at = datetime.utcnow()
        db.session.commit()

    def _run_single_with_retry(self, step_params: dict, max_retries: int = 1) -> dict:
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return self._execute_step(step_params)
            except AIError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning("Batch step retry %d: %s", attempt + 1, e)
                    continue
        raise last_error

    def _execute_step(self, step_params: dict) -> dict:
        agent = GeneratorAgent()
        prompt = step_params.get("prompt", "")
        language = step_params.get("language", "python")
        difficulty = step_params.get("difficulty", "medium")

        state = {
            "messages": [HumanMessage(content=prompt)],
            "agent_type": "generator",
            "user_id": self.task.user_id,
            "user_role": "teacher",
            "context": {
                "language": language,
                "difficulty": difficulty,
                "topic": step_params.get("topic", ""),
                "test_case_count": step_params.get("test_case_count", 5),
            },
            "tool_results": [],
            "final_response": "",
        }

        result_state = agent.invoke(state)
        question_data = result_state.get("context", {}).get("generated_question")
        if not question_data:
            raise AIError("Generator did not produce a valid question")
        return question_data


def decompose_batch_params(params: dict) -> list[dict]:
    """Decompose a batch generation request into individual step params."""
    count = params.get("count", 1)
    topic = params.get("topic", "")
    language = params.get("language", "python")
    difficulty = params.get("difficulty", "medium")
    test_case_count = params.get("test_case_count", 5)

    steps = []
    for i in range(count):
        step_prompt = (
            f"Create a {difficulty} difficulty {language} programming problem "
            f"about {topic}."
        )
        if count > 1:
            step_prompt += (
                f" This is problem {i + 1} of {count}. "
                f"Make it distinct from the other problems in the batch."
            )
        steps.append({
            "prompt": step_prompt,
            "language": language,
            "difficulty": difficulty,
            "topic": topic,
            "test_case_count": test_case_count,
            "index": i,
        })
    return steps
