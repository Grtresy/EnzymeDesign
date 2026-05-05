from __future__ import annotations

from openzyme_host_api.evals import run_local_workflow_evals
from openzyme_host_api.evals import run_v3_local_evals


def test_local_eval_harness_covers_report_and_rejection_paths() -> None:
    summary = run_local_workflow_evals(upload_results=False)

    assert summary["scenario_count"] == 2
    assert summary["failed"] == 0
    by_id = {result["scenario_id"]: result for result in summary["results"]}
    assert by_id["happy_path_report"]["report_count"] == 1
    assert by_id["happy_path_report"]["checks"]["report_summary"] is True
    assert by_id["design_rejected"]["workflow_status"] == "interrupted"
    assert by_id["design_rejected"]["phase"] == "execution"
    assert by_id["design_rejected"]["report_count"] == 0


def test_v3_local_eval_covers_cutover_design_path() -> None:
    summary = run_v3_local_evals(upload_results=False)

    assert summary["scenario_count"] == 1
    assert summary["failed"] == 0
    result = summary["results"][0]
    assert result["scenario_id"] == "v3_design_cutover_path"
    assert result["task_count"] == 3
    assert set(result["agent_roles"]) >= {"researcher", "executor", "reporter"}
    assert set(result["capability_keys"]) >= {"deep_research", "execution"}
    assert result["report_count"] == 1
    assert all(result["checks"].values())
