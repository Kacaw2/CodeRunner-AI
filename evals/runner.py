import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from evals.judges.judges import run_judge

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    case_id: str
    category: str = ""
    passed: bool = False
    judge_results: list = field(default_factory=list)
    response_preview: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass
class EvalReport:
    suite_name: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    duration_seconds: float = 0.0
    results: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Suite: {self.suite_name} | "
            f"Total: {self.total} | Passed: {self.passed} | Failed: {self.failed} | "
            f"Pass rate: {self.pass_rate:.1%} | Duration: {self.duration_seconds:.1f}s"
        )


class EvalRunner:
    """Runs eval suites and produces reports."""

    def __init__(self, use_real_llm: bool = True):
        self.use_real_llm = use_real_llm

    def run_suite(self, suite_path: str) -> EvalReport:
        """Run all eval cases in a suite file."""
        path = Path(suite_path)
        cases = json.loads(path.read_text(encoding="utf-8"))
        suite_name = path.stem

        results = []
        suite_start = time.monotonic()

        for case in cases:
            result = self._run_case(case)
            results.append(result)

        duration = time.monotonic() - suite_start
        passed = sum(1 for r in results if r.passed)

        report = EvalReport(
            suite_name=suite_name,
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            pass_rate=passed / len(results) if results else 0,
            duration_seconds=round(duration, 2),
            results=results,
        )
        logger.info(report.summary())
        return report

    def run_all_suites(self, cases_dir: str = "evals/cases") -> list[EvalReport]:
        """Run all eval suite files in a directory."""
        reports = []
        cases_path = Path(cases_dir)
        for suite_file in sorted(cases_path.glob("*_evals.json")):
            try:
                report = self.run_suite(str(suite_file))
                reports.append(report)
            except Exception as e:
                logger.error("Failed to run suite %s: %s", suite_file, e)
        return reports

    def _run_case(self, case: dict) -> EvalResult:
        """Run a single eval case."""
        case_id = case.get("id", "unknown")
        case_start = time.monotonic()

        try:
            state = self._build_state(case["input"])
            agent = self._get_agent(case["input"]["agent_type"])
            result_state = agent.invoke(state)
            response = result_state.get("final_response", "")
        except Exception as e:
            logger.warning("Eval case %s failed during agent invocation: %s", case_id, e)
            return EvalResult(
                case_id=case_id,
                category=case.get("category", ""),
                passed=False,
                error=str(e),
                duration_ms=int((time.monotonic() - case_start) * 1000),
            )

        judge_results = []
        for judge_config in case.get("judges", []):
            jr = run_judge(judge_config, response)
            judge_results.append(jr)

        all_passed = all(j["passed"] for j in judge_results) if judge_results else False
        duration_ms = int((time.monotonic() - case_start) * 1000)

        return EvalResult(
            case_id=case_id,
            category=case.get("category", ""),
            passed=all_passed,
            judge_results=judge_results,
            response_preview=response[:200] if response else "",
            duration_ms=duration_ms,
        )

    def _build_state(self, input_config: dict) -> dict:
        """Build an AgentState dict from eval case input."""
        from langchain_core.messages import HumanMessage

        return {
            "messages": [HumanMessage(content=input_config.get("message", ""))],
            "agent_type": input_config.get("agent_type", "tutor"),
            "user_id": input_config.get("user_id", 1),
            "user_role": input_config.get("user_role", "student"),
            "context": input_config.get("context", {}),
            "tool_results": [],
            "final_response": "",
        }

    def _get_agent(self, agent_type: str):
        from agent_host.agents import TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent

        agent_map = {
            "tutor": TutorAgent,
            "reviewer": ReviewerAgent,
            "generator": GeneratorAgent,
            "analytics": AnalyticsAgent,
        }
        cls = agent_map.get(agent_type, TutorAgent)
        return cls()


def report_to_dict(report: EvalReport) -> dict:
    """Convert an EvalReport to a JSON-serializable dict."""
    return {
        "suite_name": report.suite_name,
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": report.pass_rate,
        "duration_seconds": report.duration_seconds,
        "results": [asdict(r) for r in report.results],
    }
