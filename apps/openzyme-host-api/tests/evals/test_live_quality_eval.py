from __future__ import annotations

import pytest

from openzyme_host_api.evals import run_live_workflow_evals
from openzyme_runtime import get_settings


pytestmark = [
    pytest.mark.integration,
    pytest.mark.quality_eval,
    pytest.mark.live_llm,
    pytest.mark.live_tavily,
    pytest.mark.slow,
]


def test_live_workflow_eval_harness_runs_seeded_scenarios() -> None:
    summary = run_live_workflow_evals(
        upload_results=get_settings().test.upload_langsmith,
    )

    assert summary["scenario_count"] == 2
    assert summary["failed"] == 0
