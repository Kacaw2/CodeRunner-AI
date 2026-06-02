"""Tests for the eval CI command-line compatibility layer."""

from __future__ import annotations


def test_dataset_cases_dir_uses_harness_selector(monkeypatch, tmp_path):
    import evals.ci as ci

    captured = {}

    def fake_run_harness_cli(args):
        captured["selector"] = args.selector
        captured["report_out"] = args.report_out
        return 0

    monkeypatch.setattr(ci, "_run_harness_cli", fake_run_harness_cli)

    rc = ci.main(
        [
            "--cases-dir",
            "evals/datasets/golden",
            "--report-out",
            str(tmp_path / "eval-report.json"),
        ]
    )

    assert rc == 0
    assert captured["selector"] == "golden"
    assert captured["report_out"].endswith("eval-report.json")
