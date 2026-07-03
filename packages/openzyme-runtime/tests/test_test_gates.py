from __future__ import annotations

from openzyme_runtime import live_e2e_skip_reason
from openzyme_runtime import reset_settings_cache
from openzyme_runtime import get_settings


def test_live_e2e_skip_reason_reports_all_missing_prerequisites(monkeypatch) -> None:
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_E2E", "true")
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "")
    monkeypatch.setenv("MICU_API_KEY", "")
    monkeypatch.setenv("BIGMODEL_API_KEY", "")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("OPENZYME_EXECUTION_BACKEND", "demo")
    monkeypatch.delenv("OPENZYME_HPC_RUNNER_CONFIG", raising=False)
    monkeypatch.delenv("HPC_RUNNER_CONFIG", raising=False)
    reset_settings_cache()

    reason = live_e2e_skip_reason(get_settings())

    assert reason is not None
    assert "Live E2E gate prerequisites are missing" in reason
    assert "Live LLM tests require" in reason
    assert "Live Tavily tests require" in reason
    assert "Live HPC tests require" in reason
