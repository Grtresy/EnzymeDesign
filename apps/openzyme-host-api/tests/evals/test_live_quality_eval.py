from __future__ import annotations

import pytest

from openzyme_host_api.evals import run_v3_s15_live_evals
from openzyme_runtime import get_settings


pytestmark = [
    pytest.mark.integration,
    pytest.mark.quality_eval,
    pytest.mark.live_llm,
    pytest.mark.live_tavily,
    pytest.mark.slow,
]


def test_live_workflow_eval_harness_runs_v3_scenario() -> None:
    summary = run_v3_s15_live_evals(
        upload_results=get_settings().test.upload_langsmith,
    )

    assert summary["scenario_count"] == 1
    assert summary["failed"] == 0
    result = summary["results"][0]
    assert result["scenario_id"] == "v3_aox_hmm_cutover_live_e2e"
    assert result["status"] in {"passed", "prerequisite_missing"}
    if result["status"] == "prerequisite_missing":
        assert summary["prerequisite_missing"] == 1
        assert result["passed"] is False
    else:
        assert summary["passed"] == 1
        assert result["live_cutover_eligible"] is True
