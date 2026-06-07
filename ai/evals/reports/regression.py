"""Case-level regression detection between two eval runs (Task 8).

A *regression* is a case that passed in the baseline run but no longer passes in
the current run. New failures with no baseline counterpart are reported
separately as ``new_failures`` so a freshly-added case is not mislabeled as a
regression.
"""

from __future__ import annotations


def detect_regressions(
    current_cases: list[dict],
    baseline_cases: list[dict],
) -> list[dict]:
    """Return the cases that passed in baseline but fail now.

    Each entry: ``{case_id, suite, failure_type, baseline_status, current_status}``.
    """
    baseline_by_id = {c["case_id"]: c for c in baseline_cases}
    regressions: list[dict] = []
    for cur in current_cases:
        if cur.get("passed"):
            continue
        base = baseline_by_id.get(cur["case_id"])
        if base is None or not base.get("passed"):
            continue  # new case or already-failing baseline — not a regression
        regressions.append(
            {
                "case_id": cur["case_id"],
                "suite": cur.get("suite"),
                "failure_type": cur.get("failure_type"),
                "baseline_status": base.get("status"),
                "current_status": cur.get("status"),
            }
        )
    return regressions


def detect_new_failures(
    current_cases: list[dict],
    baseline_cases: list[dict],
) -> list[dict]:
    """Return failing cases that have no passing baseline counterpart."""
    baseline_by_id = {c["case_id"]: c for c in baseline_cases}
    new_failures: list[dict] = []
    for cur in current_cases:
        if cur.get("passed"):
            continue
        base = baseline_by_id.get(cur["case_id"])
        if base is not None and base.get("passed"):
            continue  # that's a regression, reported elsewhere
        new_failures.append(
            {
                "case_id": cur["case_id"],
                "suite": cur.get("suite"),
                "failure_type": cur.get("failure_type"),
            }
        )
    return new_failures
