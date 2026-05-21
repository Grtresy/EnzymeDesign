from __future__ import annotations

import pytest

from openzyme_host_api.evals import run_v3_live_evals
from openzyme_runtime import get_settings


pytestmark = [
    pytest.mark.integration,
    pytest.mark.quality_eval,
    pytest.mark.live_llm,
    pytest.mark.live_tavily,
    pytest.mark.slow,
]


def test_live_workflow_eval_harness_runs_v3_scenario() -> None:
    summary = run_v3_live_evals(
        upload_results=get_settings().test.upload_langsmith,
    )

    assert summary["scenario_count"] == 1
    assert summary["failed"] == 0
