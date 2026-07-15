from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace

from openzyme_runtime.llm_connectivity import run_connectivity_check


def test_connectivity_uses_runtime_retry_budget_and_disables_client_retries(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {"attempts": 0}

    class FakeResponses:
        def create(self, **kwargs):
            observed["request"] = kwargs
            observed["attempts"] = int(observed["attempts"]) + 1
            if observed["attempts"] < 3:
                raise TimeoutError("temporary provider timeout")
            return SimpleNamespace(output_text="ok")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            observed["client"] = kwargs
            self.responses = FakeResponses()

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr(
        "openzyme_runtime.llm_connectivity.get_settings",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(
                api_key="test-key",
                model="test-model",
                base_url="https://example.test/v1",
                default_headers={"User-Agent": "openzyme-test"},
                timeout=10.0,
                max_retries=2,
                structured_output_retry_backoff_seconds=0.0,
                use_responses_api=True,
                max_tokens=64,
            )
        ),
    )

    result = run_connectivity_check()

    assert result["status"] == "ok"
    assert result["output_text"] == "ok"
    assert observed["attempts"] == 3
    assert observed["client"] == {
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "default_headers": {"User-Agent": "openzyme-test"},
        "timeout": 10.0,
        "max_retries": 0,
    }
    assert observed["request"] == {
        "model": "test-model",
        "input": "OpenZyme LLM connectivity check. Reply with exactly: ok",
        "max_output_tokens": 32,
    }
