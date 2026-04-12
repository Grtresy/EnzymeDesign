from __future__ import annotations

from openzyme_host_api.evals import run_local_workflow_evals


def test_local_eval_harness_covers_report_and_rejection_paths() -> None:
    summary = run_local_workflow_evals(upload_results=False)

    assert summary["scenario_count"] == 2
    assert summary["failed"] == 0
    by_id = {result["scenario_id"]: result for result in summary["results"]}
    assert by_id["happy_path_report"]["report_count"] == 1
    assert by_id["happy_path_report"]["checks"]["report_summary"] is True
    assert by_id["design_rejected"]["workflow_status"] == "failed"
    assert by_id["design_rejected"]["report_count"] == 0
