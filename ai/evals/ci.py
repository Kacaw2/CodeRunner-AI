"""CI entry point for the agent eval suite (F3).

Runs every eval suite under ``evals/cases`` with the real LLM, then compares
each suite's pass rate against a committed baseline. Exits non-zero if any
suite regresses below ``baseline - tolerance`` so the eval workflow can fail.

This is intentionally NOT wired into the per-PR ``tests.yml`` gate: it needs a
real ``DEEPSEEK_API_KEY`` and costs tokens. It runs from ``evals.yml`` on a
nightly schedule and on manual ``workflow_dispatch``.

Usage:
    python -m evals.ci                       # run + compare against baseline
    python -m evals.ci --update-baseline     # run + (re)write baseline.json
    python -m evals.ci --report-out out.json # also dump a full JSON report
    python -m evals.ci --tolerance 0.10      # allow a 10pp drop before failing

    # Harness mode (DB-backed): run the EvalHarness over a dataset selector,
    # persist results, then emit a full ReportGenerator report and gate on it.
    python -m evals.ci --use-harness --selector all \
        --report-out eval-report.json

    # Harness mode in CI on an empty SQLite DB (creates the schema first):
    python -m evals.ci --use-harness --bootstrap-schema \
        --db-url sqlite:///eval_ci.db --selector all --report-out eval-report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ai.evals.runner import EvalRunner, report_to_dict

logger = logging.getLogger("evals.ci")

BASELINE_PATH = Path(__file__).parent / "baseline.json"


def _load_baseline(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("Could not read baseline %s: %s", path, exc)
        return {}


def _run_harness_cli(args) -> int:
    """Entry wrapper for harness mode: own a Flask app context (+ optional schema).

    The DB-backed harness drives *real* agents (which read/write through Flask
    models) and persists results into the runtime-neutral ``agent_trace_*`` /
    ``eval_*`` tables. A CLI/CI invocation has none of the pytest fixtures that
    normally provide an app context and a ready schema, so we establish both here:

    - always run inside ``create_app().app_context()`` so agents can resolve
      services / models / MCP transports;
    - when ``--bootstrap-schema`` is set (CI on an empty SQLite file), mirror the
      test harness setup — create Flask + core ``Base`` tables on one engine — so
      the harness has somewhere to write. Production omits the flag and keeps its
      migrated MySQL schema and separately-configured core session untouched.
    """
    from app import create_app

    config_name = "testing" if args.bootstrap_schema else None
    app = create_app(config_name) if config_name else create_app()
    if args.bootstrap_schema and args.db_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = args.db_url

    with app.app_context():
        if args.bootstrap_schema:
            _bootstrap_eval_schema()
        return _run_harness_mode(args)


def _bootstrap_eval_schema() -> None:
    """Create shared Domain tables on one engine (CI / empty DB).

    Mirrors ``tests/conftest.py``: trace/eval tables are declared on
    ``DomainBase.metadata``, so we point the core session at the Flask engine
    and create the shared metadata there. This is a test/CI convenience only;
    production owns this schema via Alembic.
    """
    from sqlalchemy.orm import sessionmaker

    from app.core.extensions import db as _db
    import core.db.session as core_session
    from domain.base import DomainBase
    import domain.models.observability  # noqa: F401  register Domain tables

    _db.create_all()
    core_session._engine = _db.engine
    core_session._SessionLocal = sessionmaker(bind=_db.engine, expire_on_commit=False)
    DomainBase.metadata.create_all(bind=_db.engine)


def _run_harness_mode(args) -> int:
    """Run the EvalHarness, emit a full report, and gate on it.

    Gate fails when any case regressed against ``--compare-to`` or when the
    overall pass rate falls below ``baseline floor - tolerance`` (baseline reused
    from ``baseline.json`` keyed by suite, falling back to the whole run).
    """
    from ai.evals.harness.eval_harness import EvalHarness
    from ai.evals.reports.generator import ReportGenerator

    run_report = EvalHarness().run(selector=args.selector)
    report = ReportGenerator().build(
        eval_run_id=run_report.eval_run_id,
        compare_to_eval_run_id=args.compare_to,
    )
    summary = report.summary

    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Wrote report JSON to %s", args.report_out)
    Path(args.report_md_out).write_text(report.to_markdown(), encoding="utf-8")
    Path(args.regressions_out).write_text(
        json.dumps(summary.get("regressions", []), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n=== Eval report ===")
    print(report.to_markdown())

    regressions = summary.get("regressions", [])
    pass_rate = summary.get("pass_rate", 0.0)
    suite = summary.get("suite_name") or args.selector

    # Calibration: write this run's pass rate as the new baseline floor and exit
    # 0 without gating. Lets the harness path self-calibrate baseline.json the way
    # the legacy runner does via --update-baseline.
    if getattr(args, "update_baseline", False):
        Path(args.baseline).write_text(
            json.dumps(
                {suite: {"min_pass_rate": round(pass_rate, 4)}},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        logger.info("Updated baseline at %s (suite=%s)", args.baseline, suite)
        return 0

    baseline = _load_baseline(Path(args.baseline))
    floor = float(baseline.get(suite, {}).get("min_pass_rate", 0.0))
    threshold = floor - args.tolerance

    failed = False
    if regressions:
        failed = True
        print(f"\nEval gate FAILED — {len(regressions)} case(s) regressed:")
        for r in regressions:
            print(f"  - {r['case_id']} ({r.get('failure_type') or 'failed'})")
    if floor and pass_rate < threshold:
        failed = True
        print(
            f"\nEval gate FAILED — pass rate {pass_rate:.1%} < "
            f"baseline {floor:.1%} - tolerance {args.tolerance:.0%}"
        )

    if failed:
        return 1
    print("\nEval gate PASSED.")
    return 0


def _selector_from_dataset_cases_dir(cases_dir: str) -> str | None:
    """Map evals/datasets paths to DatasetStore selectors.

    The legacy CI runner uses ``evals/cases`` suites. Phase 5 moved canonical
    cases under ``evals/datasets/{golden,hidden,regression,production_failures}``,
    so a cases-dir pointing there should use the DB-backed harness path.
    """
    path = Path(cases_dir)
    parts = [part.lower() for part in path.parts]
    if not parts:
        return None

    if parts[-1] == "datasets":
        return "all"

    dataset_types = {"golden", "hidden", "regression", "production_failures"}
    if len(parts) >= 2 and parts[-2] == "datasets" and parts[-1] in dataset_types:
        return parts[-1]

    return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Run agent eval suites for CI.")
    parser.add_argument("--cases-dir", default="ai/evals/cases")
    parser.add_argument("--baseline", default=str(BASELINE_PATH))
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Allowed drop below baseline pass_rate before failing (0.05 = 5pp).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write the observed pass rates as the new baseline and exit 0.",
    )
    parser.add_argument(
        "--report-out",
        default="",
        help="Optional path to write a full per-case JSON report.",
    )
    parser.add_argument(
        "--use-harness",
        action="store_true",
        help="Run the DB-backed EvalHarness and gate on a full report.",
    )
    parser.add_argument(
        "--selector",
        default="all",
        help="Harness-mode dataset selector (all / <type> / <type>:<suite>).",
    )
    parser.add_argument(
        "--compare-to",
        type=int,
        default=0,
        help="Harness-mode prior eval_run_id to compare against for regressions.",
    )
    parser.add_argument(
        "--report-md-out",
        default="eval-report.md",
        help="Harness-mode path for the Markdown report.",
    )
    parser.add_argument(
        "--regressions-out",
        default="eval-regressions.json",
        help="Harness-mode path for the regressions JSON.",
    )
    parser.add_argument(
        "--bootstrap-schema",
        action="store_true",
        help="Harness-mode: create Flask + core tables on an empty DB (CI only).",
    )
    parser.add_argument(
        "--db-url",
        default="",
        help="Harness-mode: override SQLALCHEMY_DATABASE_URI when bootstrapping.",
    )
    args = parser.parse_args(argv)

    dataset_selector = _selector_from_dataset_cases_dir(args.cases_dir)
    if dataset_selector and not args.use_harness:
        args.use_harness = True
        if args.selector == "all":
            args.selector = dataset_selector

    if args.use_harness:
        return _run_harness_cli(args)

    runner = EvalRunner(use_real_llm=True)
    reports = runner.run_all_suites(args.cases_dir)

    if not reports:
        logger.error("No eval suites found under %s", args.cases_dir)
        return 1

    observed = {r.suite_name: round(r.pass_rate, 4) for r in reports}

    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps([report_to_dict(r) for r in reports], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Wrote full report to %s", args.report_out)

    print("\n=== Eval results ===")
    for r in reports:
        print(f"  {r.summary()}")

    if args.update_baseline:
        baseline_out = {
            suite: {"min_pass_rate": rate} for suite, rate in observed.items()
        }
        Path(args.baseline).write_text(
            json.dumps(baseline_out, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Updated baseline at %s", args.baseline)
        return 0

    baseline = _load_baseline(Path(args.baseline))
    if not baseline:
        logger.error(
            "No baseline at %s. Run once with --update-baseline to establish it.",
            args.baseline,
        )
        return 1

    failures = []
    print("\n=== Baseline gate (tolerance %.0fpp) ===" % (args.tolerance * 100))
    for r in reports:
        floor = float(baseline.get(r.suite_name, {}).get("min_pass_rate", 0.0))
        threshold = floor - args.tolerance
        status = "OK"
        if r.pass_rate < threshold:
            status = "FAIL"
            failures.append((r.suite_name, r.pass_rate, floor))
        print(
            f"  [{status}] {r.suite_name}: {r.pass_rate:.1%} "
            f"(baseline {floor:.1%}, min {max(threshold, 0):.1%})"
        )

    if failures:
        print("\nEval gate FAILED — the following suites regressed:")
        for name, rate, floor in failures:
            print(f"  - {name}: {rate:.1%} < baseline {floor:.1%} - tolerance")
        return 1

    print("\nEval gate PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
