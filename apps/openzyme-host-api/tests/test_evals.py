from __future__ import annotations

import pytest

from openzyme_host_api.evals import run_v3_local_evals


@pytest.fixture(scope="module")
def local_eval_summary() -> dict[str, object]:
    return run_v3_local_evals(upload_results=False)


def test_v3_local_eval_covers_cutover_design_path(local_eval_summary: dict[str, object]) -> None:
    summary = local_eval_summary
    assert summary["scenario_count"] == 2
    assert summary["failed"] == 0
    result = next(item for item in summary["results"] if item["scenario_id"] == "v3_design_cutover_path")
    assert result["scenario_id"] == "v3_design_cutover_path"
    assert result["task_count"] == 3
    assert set(result["agent_roles"]) >= {"researcher", "executor", "reporter"}
    assert set(result["capability_keys"]) >= {"deep_research", "execution"}
    assert result["report_count"] == 1
    assert all(result["checks"].values())


def test_v3_local_eval_covers_aox_hmm_prompt_e2e(local_eval_summary: dict[str, object]) -> None:
    summary = local_eval_summary
    result = next(item for item in summary["results"] if item["scenario_id"] == "v3_aox_hmm_prompt_e2e")
    assert result["task_count"] == 1
    assert result["candidate_count"] == 5
    assert result["artifact_count"] >= result["required_artifact_count"]
    assert all(result["checks"].values())
