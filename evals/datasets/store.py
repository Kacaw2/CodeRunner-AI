"""Dataset store for eval cases (Phase 5, Task 5).

Loads canonical cases from ``evals/datasets/<case_type>/<suite>.json`` and
exposes selector-based filtering. The legacy ``evals/cases/*_evals.json`` files
are read only through :meth:`DatasetStore.load_legacy_cases`, which converts
them into ``case_type="golden"`` cases with ``deterministic.`` grader names.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from evals.datasets.schema import (
    DIR_TO_CASE_TYPE,
    CASE_TYPE_TO_DIR,
    DEFAULT_BUDGET,
    EvalCase,
    EvalCaseInput,
    GraderSpec,
)

_DEFAULT_ROLE_BY_AGENT = {
    "tutor": "student",
    "reviewer": "teacher",
    "generator": "teacher",
    "analytics": "teacher",
}


class DatasetStore:
    """Loads and filters eval cases from the dataset tree."""

    def __init__(self, root: str | os.PathLike = "evals/datasets") -> None:
        self.root = Path(root)

    # ── Loading ────────────────────────────────────────────────

    def load_cases(self, selector: str = "all") -> list[EvalCase]:
        """Return cases matching *selector*.

        Selector forms: ``"all"``, ``"<case_type>"`` (e.g. ``"golden"``),
        ``"<case_type>:<suite>"`` (e.g. ``"golden:tutor"``).
        """
        case_type_filter, suite_filter = self._parse_selector(selector)

        cases: list[EvalCase] = []
        for dir_name, case_type in DIR_TO_CASE_TYPE.items():
            if case_type_filter and case_type != case_type_filter:
                continue
            cases.extend(self._load_dir(dir_name, case_type, suite_filter))
        return cases

    def _parse_selector(self, selector: str) -> tuple[str | None, str | None]:
        if not selector or selector == "all":
            return None, None
        if ":" in selector:
            case_type, suite = selector.split(":", 1)
            return case_type.strip() or None, suite.strip() or None
        return selector.strip() or None, None

    def _load_dir(self, dir_name: str, case_type: str, suite_filter: str | None) -> list[EvalCase]:
        directory = self.root / dir_name
        if not directory.is_dir():
            return []

        cases: list[EvalCase] = []
        for path in sorted(directory.glob("*.json")):
            suite = path.stem
            if suite_filter and suite != suite_filter:
                continue
            cases.extend(self._parse_file(path, case_type, suite))
        return cases

    def _parse_file(self, path: Path, case_type: str, suite: str) -> list[EvalCase]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = raw if isinstance(raw, list) else [raw]
        return [EvalCase.from_dict(rec, case_type=case_type, suite=suite) for rec in records]

    # ── Legacy shim ────────────────────────────────────────────

    def load_legacy_cases(self, legacy_root: str | os.PathLike = "evals/cases") -> list[EvalCase]:
        """Read legacy ``*_evals.json`` files as ``golden`` cases.

        Old ``judges`` entries become ``deterministic.<type>`` graders so the
        legacy corpus can run through the new grader pipeline unchanged.
        """
        legacy_dir = Path(legacy_root)
        if not legacy_dir.is_dir():
            return []

        cases: list[EvalCase] = []
        for path in sorted(legacy_dir.glob("*_evals.json")):
            suite = path.stem.replace("_evals", "")
            raw = json.loads(path.read_text(encoding="utf-8"))
            for rec in raw if isinstance(raw, list) else [raw]:
                cases.append(self._legacy_record_to_case(rec, suite))
        return cases

    def _legacy_record_to_case(self, rec: dict, suite: str) -> EvalCase:
        old_input = rec.get("input") or {}
        agent_type = old_input.get("agent_type", suite)
        graders = [
            GraderSpec(
                type=f"deterministic.{j.get('type', '')}",
                params={k: v for k, v in j.items() if k != "type"},
            )
            for j in (rec.get("judges") or [])
        ]
        return EvalCase(
            id=rec["id"],
            case_type="golden",
            suite=suite,
            agent_type=agent_type,
            input=EvalCaseInput(
                message=old_input.get("message", ""),
                user_id=old_input.get("user_id", 1),
                user_role=old_input.get("user_role")
                or _DEFAULT_ROLE_BY_AGENT.get(agent_type, "student"),
                agent_type=agent_type,
                context=dict(old_input.get("context") or {}),
            ),
            category=rec.get("category", ""),
            budget=dict(DEFAULT_BUDGET),
            graders=graders,
            expected_behavior=rec.get("expected_behavior", ""),
            description=rec.get("description", ""),
        )

    # ── Production-failure import ──────────────────────────────

    def create_from_trace(
        self,
        trace_id: str,
        *,
        case_type: str = "production_failure",
        reason: str = "",
        suite: str | None = None,
    ) -> EvalCase:
        """Build a regression case from a persisted trace run.

        Reads the trace's input preview, agent_type and conversation link, and
        writes a new case file under the matching ``case_type`` directory.
        """
        from core.db.session import db_session
        from domain.repositories.traces import SyncTraceRepository

        with db_session() as session:
            run = SyncTraceRepository(session).get_run(trace_id)
            if run is None:
                raise ValueError(f"trace {trace_id!r} not found")
            agent_type = run.agent_type or "tutor"
            message = run.input_preview or ""
            user_id = run.user_id or 1
            conversation_id = run.conversation_id

        resolved_suite = suite or agent_type
        context = {"conversation_id": conversation_id} if conversation_id else {}
        case = EvalCase(
            id=f"{resolved_suite}_{case_type}_{trace_id[:8]}",
            case_type=case_type,
            suite=resolved_suite,
            agent_type=agent_type,
            input=EvalCaseInput(
                message=message,
                user_id=user_id,
                user_role=_DEFAULT_ROLE_BY_AGENT.get(agent_type, "student"),
                agent_type=agent_type,
                context=context,
            ),
            category="regression",
            budget=dict(DEFAULT_BUDGET),
            graders=[],
            expected_behavior=reason,
            description=f"Imported from trace {trace_id} ({reason})",
        )
        self._append_case(case)
        return case

    def _append_case(self, case: EvalCase) -> None:
        directory = self.root / CASE_TYPE_TO_DIR[case.case_type]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{case.suite}.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(case.to_dict())
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
