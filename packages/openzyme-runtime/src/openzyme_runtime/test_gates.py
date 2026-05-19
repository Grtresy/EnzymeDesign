from __future__ import annotations

import importlib.util
from pathlib import Path

from .settings import OpenZymeSettings
from .settings import get_settings
from .settings import reset_settings_cache


def load_current_settings() -> OpenZymeSettings:
    reset_settings_cache()
    return get_settings()


def live_llm_skip_reason(settings: OpenZymeSettings | None = None) -> str | None:
    effective = settings or load_current_settings()
    if not (effective.test.enable_live_llm or effective.test.enable_live_e2e):
        return "Live LLM tests are disabled. Set OPENZYME_TEST_ENABLE_LIVE_LLM=true."
    if not effective.llm.enabled:
        return "Live LLM tests require OPENZYME_LLM_API_KEY and provider settings."
    return None


def live_tavily_skip_reason(settings: OpenZymeSettings | None = None) -> str | None:
    effective = settings or load_current_settings()
    if not (effective.test.enable_live_tavily or effective.test.enable_live_e2e):
        return "Live Tavily tests are disabled. Set OPENZYME_TEST_ENABLE_LIVE_TAVILY=true."
    if not effective.research.tavily_enabled:
        return "Live Tavily tests require TAVILY_API_KEY."
    if importlib.util.find_spec("tavily") is None:
        return "Live Tavily tests require the optional tavily-python dependency."
    return None


def live_hpc_skip_reason(settings: OpenZymeSettings | None = None) -> str | None:
    effective = settings or load_current_settings()
    if not (effective.test.enable_live_hpc or effective.test.enable_live_e2e):
        return "Live HPC tests are disabled. Set OPENZYME_TEST_ENABLE_LIVE_HPC=true."
    if effective.execution.backend != "hpc":
        return "Live HPC tests require OPENZYME_EXECUTION_BACKEND=hpc."
    if not effective.execution.hpc_runner_config:
        return "Live HPC tests require OPENZYME_HPC_RUNNER_CONFIG or HPC_RUNNER_CONFIG."
    config_path = Path(effective.execution.hpc_runner_config).expanduser()
    if not config_path.exists():
        return f"Live HPC config not found: {config_path}"
    return None


def live_e2e_skip_reason(settings: OpenZymeSettings | None = None) -> str | None:
    effective = settings or load_current_settings()
    if not effective.test.enable_live_e2e:
        return "Live E2E tests are disabled. Set OPENZYME_TEST_ENABLE_LIVE_E2E=true."
    missing = [
        reason
        for reason in (
            live_llm_skip_reason(effective),
            live_tavily_skip_reason(effective),
            live_hpc_skip_reason(effective),
        )
        if reason is not None
    ]
    if missing:
        return "Live E2E gate prerequisites are missing: " + " | ".join(missing)
    return None


def quality_eval_skip_reason(settings: OpenZymeSettings | None = None) -> str | None:
    effective = settings or load_current_settings()
    if not effective.test.enable_quality_eval:
        return "Quality eval tests are disabled. Set OPENZYME_TEST_ENABLE_QUALITY_EVAL=true."
    return None
