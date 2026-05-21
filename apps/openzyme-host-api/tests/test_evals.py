from __future__ import annotations

from openzyme_host_api.evals import run_v3_local_evals


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
