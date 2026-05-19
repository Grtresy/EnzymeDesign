from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_stage_timeout_seconds
from openzyme_runtime.live_testing import log_live_phase
from openzyme_host_api.foundation import build_model_factory_from_settings
from openzyme_runtime import get_settings
from openzyme_runtime import LlmSettings
from openzyme_runtime import ReportDraft


pytestmark = [pytest.mark.integration, pytest.mark.live_llm]


class LiveLlmTestTimeoutError(TimeoutError):
    """Raised when the live LLM smoke test exceeds its local timeout budget."""


def _live_llm_settings() -> LlmSettings:
    settings = get_settings()
    live_policy = settings.test.live_llm
    return replace(
        settings.llm,
        max_tokens=300 if live_policy.max_tokens is None else live_policy.max_tokens,
        timeout=45.0 if live_policy.timeout is None else live_policy.timeout,
        max_retries=0 if live_policy.max_retries is None else live_policy.max_retries,
        structured_output_method=(
            "function_calling"
            if live_policy.structured_output_method is None
            else live_policy.structured_output_method
        ),
        structured_output_max_attempts=1
        if live_policy.structured_output_max_attempts is None
        else live_policy.structured_output_max_attempts,
        structured_output_retry_backoff_seconds=(
            0.5
            if live_policy.structured_output_retry_backoff_seconds is None
            else live_policy.structured_output_retry_backoff_seconds
        ),
        purpose_policies={},
    )


def test_live_llm_generates_structured_report_draft() -> None:
    log_live_phase("building live LLM model factory")
    settings = get_settings()
    llm_settings = _live_llm_settings()
    factory = build_model_factory_from_settings(
        replace(settings, llm=llm_settings)
    )
    assert factory is not None

    log_live_phase("creating live LLM structured invoker")
    invoker = factory.create_structured_invoker(purpose="report_review")
    stage_timeout_seconds = derive_live_stage_timeout_seconds(
        provider_timeout_seconds=llm_settings.timeout,
        attempts=llm_settings.structured_output_max_attempts,
        buffer_seconds=30,
        minimum_seconds=70,
    )
    with LiveStageTimeout(
        "invoking live LLM structured report smoke",
        stage_timeout_seconds,
        timeout_type=LiveLlmTestTimeoutError,
    ):
        result = invoker.invoke_structured(
            schema=ReportDraft,
            system_prompt=(
                "You write a concise final report for an enzyme design workflow. "
                "Return only the structured report fields."
            ),
            user_payload={
                "episode_id": "ep_live_llm",
                "objective": "Produce a concise final report for a thermostable artifact workspace",
                "research_summary": {"summary": "Two scaffold families show thermostability evidence."},
                "focused_artifact_ids": ["artifact_live_001"],
                "run_summary": {
                    "status": "succeeded",
                    "execution_mode": "demo",
                },
                "artifact_refs": [
                    {
                        "artifact_id": "artifact_live_001",
                        "kind": "result",
                        "storage_uri": "/tmp/openzyme-live/result.json",
                    }
                ],
            },
        )

    assert result.title
    assert result.summary
    assert result.stage_summary
