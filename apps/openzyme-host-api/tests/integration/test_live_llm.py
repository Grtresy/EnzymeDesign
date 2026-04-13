from __future__ import annotations

import signal
from dataclasses import replace

import pytest

from openzyme_host_api.foundation import build_model_factory_from_settings
from openzyme_runtime import get_settings
from openzyme_runtime import LlmSettings
from openzyme_runtime import ReportDraft


pytestmark = [pytest.mark.integration, pytest.mark.live_llm]


class LiveLlmTestTimeoutError(TimeoutError):
    """Raised when the live LLM smoke test exceeds its local timeout budget."""


class _AlarmTimeout:
    def __init__(self, seconds: int) -> None:
        self._seconds = seconds
        self._previous_handler = None

    def __enter__(self) -> "_AlarmTimeout":
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self._seconds)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        signal.alarm(0)
        if self._previous_handler is not None:
            signal.signal(signal.SIGALRM, self._previous_handler)
        return None

    @staticmethod
    def _handle_timeout(signum: int, frame: object | None) -> None:
        del signum, frame
        raise LiveLlmTestTimeoutError("live_llm smoke test exceeded its local timeout budget.")


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
    settings = get_settings()
    factory = build_model_factory_from_settings(
        replace(settings, llm=_live_llm_settings())
    )
    assert factory is not None

    invoker = factory.create_structured_invoker(purpose="report_review")
    with _AlarmTimeout(70):
        result = invoker.invoke_structured(
            schema=ReportDraft,
            system_prompt=(
                "You write a concise final report for an enzyme design workflow. "
                "Return only the structured report fields."
            ),
            user_payload={
                "episode_id": "ep_live_llm",
                "objective": "Produce a concise final report for a thermostable candidate",
                "research_summary": {"summary": "Two scaffold families show thermostability evidence."},
                "selected_candidate_id": "cand_live_001",
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
