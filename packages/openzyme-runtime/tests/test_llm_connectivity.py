from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace

from openzyme_runtime.llm_connectivity import run_connectivity_check
from openzyme_runtime.live_token_ledger import LiveMicuTokenLedger


def test_connectivity_uses_runtime_retry_budget_and_disables_client_retries(
    monkeypatch,
    tmp_path,
) -> None:
    observed: dict[str, object] = {"attempts": 0}
    ledger_path = tmp_path / "connectivity-ledger.sqlite3"

    class FakeResponses:
        def create(self, **kwargs):
            observed["request"] = kwargs
            observed["attempts"] = int(observed["attempts"]) + 1
            if observed["attempts"] < 3:
                raise TimeoutError("temporary provider timeout")
            return SimpleNamespace(
                output_text="ok",
                usage={"input_tokens": 4, "output_tokens": 1},
            )

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
                base_url="https://www.micuapi.ai/v1",
                default_headers={"User-Agent": "openzyme-test"},
                timeout=10.0,
                max_retries=2,
                structured_output_retry_backoff_seconds=0.0,
                use_responses_api=True,
                max_tokens=64,
            ),
            test=SimpleNamespace(
                live_llm=SimpleNamespace(token_ledger_path=str(ledger_path))
            ),
        ),
    )

    result = run_connectivity_check()

    assert result["status"] == "ok"
    assert result["output_text"] == "ok"
    assert observed["attempts"] == 3
    assert observed["client"] == {
        "api_key": "test-key",
        "base_url": "https://www.micuapi.ai/v1",
        "default_headers": {"User-Agent": "openzyme-test"},
        "timeout": 10.0,
        "max_retries": 0,
    }
    assert observed["request"] == {
        "model": "test-model",
        "input": "OpenZyme LLM connectivity check. Reply with exactly: ok",
        "max_output_tokens": 32,
    }
    ledger = LiveMicuTokenLedger(ledger_path)
    attempts = list(reversed(ledger.list_attempts()))
    assert [item["attempt"] for item in attempts] == [1, 2, 3]
    assert [item["kind"] for item in attempts] == ["connectivity"] * 3
    assert [item["status"] for item in attempts] == [
        "failed_estimated",
        "failed_estimated",
        "succeeded",
    ]
    assert attempts[-1]["input_tokens"] == 4
    assert attempts[-1]["output_tokens"] == 1
