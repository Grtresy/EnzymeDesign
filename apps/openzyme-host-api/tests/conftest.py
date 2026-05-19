from __future__ import annotations

import pytest

from openzyme_runtime import live_e2e_skip_reason
from openzyme_runtime import live_hpc_skip_reason
from openzyme_runtime import live_llm_skip_reason
from openzyme_runtime import live_tavily_skip_reason
from openzyme_runtime import load_current_settings
from openzyme_runtime import quality_eval_skip_reason


def _skip_if_needed(reason: str | None) -> None:
    if reason is not None:
        pytest.skip(reason)


def pytest_runtest_setup(item: pytest.Item) -> None:
    settings = load_current_settings()
    if item.get_closest_marker("live_llm"):
        _skip_if_needed(live_llm_skip_reason(settings))
    if item.get_closest_marker("live_tavily"):
        _skip_if_needed(live_tavily_skip_reason(settings))
    if item.get_closest_marker("live_hpc"):
        _skip_if_needed(live_hpc_skip_reason(settings))
    if item.get_closest_marker("live_e2e"):
        reason = live_e2e_skip_reason(settings)
        if reason is not None:
            pytest.fail(reason, pytrace=False)
    if item.get_closest_marker("quality_eval"):
        _skip_if_needed(quality_eval_skip_reason(settings))
    if item.get_closest_marker("seeded_live_smoke"):
        missing = [
            reason
            for reason in (
                live_llm_skip_reason(settings),
                live_tavily_skip_reason(settings),
                live_hpc_skip_reason(settings),
            )
            if reason is not None
        ]
        if missing:
            _skip_if_needed(
                "Seeded live smoke prerequisites are missing: " + " | ".join(missing)
            )
