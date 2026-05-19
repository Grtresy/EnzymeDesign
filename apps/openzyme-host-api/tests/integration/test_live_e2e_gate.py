from __future__ import annotations

import pytest

from openzyme_runtime import live_e2e_skip_reason
from openzyme_runtime import load_current_settings


pytestmark = [pytest.mark.integration, pytest.mark.live_e2e]


def test_live_e2e_gate_prerequisites_are_fully_configured() -> None:
    settings = load_current_settings()

    assert live_e2e_skip_reason(settings) is None
    assert settings.llm.enabled
    assert settings.research.tavily_enabled
    assert settings.execution.backend == "hpc"
    assert settings.execution.hpc_runner_config
