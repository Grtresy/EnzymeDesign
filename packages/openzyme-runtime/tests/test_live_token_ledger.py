from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor
import json
import sqlite3

import pytest
from pydantic import BaseModel

from openzyme_runtime.ai import LangChainStructuredInvoker
from openzyme_runtime.ai import LangChainToolCallingInvoker
from openzyme_runtime.live_token_ledger import LIVE_MICU_TOKEN_HARD_LIMIT
from openzyme_runtime.live_token_ledger import is_micu_provider_url
from openzyme_runtime.live_token_ledger import LiveMicuTokenBudgetExceededError
from openzyme_runtime.live_token_ledger import LiveMicuTokenLedger
from openzyme_runtime.live_token_ledger import LiveMicuTokenPolicyMigrationError
from openzyme_runtime.live_token_ledger import LiveMicuTokenReservationConfigurationError
from openzyme_runtime.live_token_ledger import main as live_token_ledger_main
from openzyme_runtime.live_token_ledger import migrate_legacy_live_micu_token_policy
from openzyme_runtime.live_token_ledger import summarize_live_micu_token_ledger
from openzyme_runtime.llm_invocation import LlmInvocationRuntime


class ExampleSchema(BaseModel):
    value: str


class FakeApiStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider status {status_code}")
        self.status_code = status_code
        self.response = type(
            "FakeResponse",
            (),
            {"status_code": status_code, "headers": {}},
        )()


def _reserve_from_process(payload: tuple[str, int]) -> bool:
    path, attempt = payload
    try:
        LiveMicuTokenLedger(path, hard_limit_tokens=30).reserve_attempt(
            scenario="cross-process",
            purpose="test",
            kind="tool_calling",
            model="test-model",
            attempt=attempt,
            estimated_input_tokens=1,
            reserved_output_tokens=9,
        )
    except LiveMicuTokenBudgetExceededError:
        return False
    return True


def test_micu_detection_uses_hostname_boundary() -> None:
    assert is_micu_provider_url("https://www.micuapi.ai/v1") is True
    assert is_micu_provider_url("https://micuapi.ai.evil.example/v1") is False


def test_ledger_persists_and_reconciles_without_storing_request_content(tmp_path) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = LiveMicuTokenLedger(path, hard_limit_tokens=1_000)
    reservation = ledger.reserve_attempt(
        scenario="live_llm",
        purpose="report_review",
        kind="structured",
        model="test-model",
        attempt=1,
        estimated_input_tokens=100,
        reserved_output_tokens=200,
    )
    assert ledger.summary()["charged_tokens"] == 300

    restarted = LiveMicuTokenLedger(path, hard_limit_tokens=1_000)
    restarted.reconcile_success(
        reservation,
        {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
    )

    summary = restarted.summary()
    entries = restarted.list_attempts()
    assert summary == {
        "path": str(path),
        "hard_limit_tokens": 1_000,
        "charged_tokens": 30,
        "remaining_tokens": 970,
        "hard_limit_overage_tokens": 0,
        "attempt_count": 1,
        "estimated_attempt_count": 0,
        "input_tokens": 20,
        "output_tokens": 10,
        "actual_input_tokens": 20,
        "actual_output_tokens": 10,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
        "by_scenario": [
            {
                "scenario": "live_llm",
                "attempt_count": 1,
                "charged_tokens": 30,
                "input_tokens": 20,
                "output_tokens": 10,
                "actual_input_tokens": 20,
                "actual_output_tokens": 10,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_attempt_count": 0,
                "reservation_overage_tokens": 0,
                "hard_limit_breach_count": 0,
            }
        ],
        "by_model": [
            {
                "model": "test-model",
                "attempt_count": 1,
                "charged_tokens": 30,
                "input_tokens": 20,
                "output_tokens": 10,
                "actual_input_tokens": 20,
                "actual_output_tokens": 10,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_attempt_count": 0,
                "reservation_overage_tokens": 0,
                "hard_limit_breach_count": 0,
            }
        ],
    }
    assert entries[0]["input_tokens"] == 20
    assert entries[0]["output_tokens"] == 10
    assert entries[0]["cumulative_tokens"] == 30
    assert entries[0]["created_at"]
    assert entries[0]["updated_at"]
    assert "prompt" not in json.dumps(entries).lower()


def test_existing_ledger_limit_can_only_decrease_without_resetting_usage(tmp_path) -> None:
    path = tmp_path / "lowered-limit.sqlite3"
    first = LiveMicuTokenLedger(path, hard_limit_tokens=1_000)
    first.reserve_attempt(
        scenario="live_llm",
        purpose="preserve-history",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=40,
        reserved_output_tokens=60,
    )

    lowered = LiveMicuTokenLedger(path, hard_limit_tokens=200)
    lowered.reserve_attempt(
        scenario="live_llm",
        purpose="persist-lower-limit",
        kind="tool_calling",
        model="test-model",
        attempt=2,
        estimated_input_tokens=1,
        reserved_output_tokens=1,
    )
    summary = lowered.summary()
    assert summary["hard_limit_tokens"] == 200
    assert summary["charged_tokens"] == 102
    assert summary["remaining_tokens"] == 98

    attempted_raise = LiveMicuTokenLedger(path, hard_limit_tokens=1_000)
    assert attempted_raise.summary()["hard_limit_tokens"] == 200
    assert attempted_raise.summary()["charged_tokens"] == 102


def test_legacy_fixed_hundred_million_policy_migrates_without_resetting_usage(
    tmp_path,
) -> None:
    path = tmp_path / "legacy-fixed-limit.sqlite3"
    legacy = LiveMicuTokenLedger(path, hard_limit_tokens=100_000_000)
    legacy.reserve_attempt(
        scenario="live_llm",
        purpose="legacy-policy",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=40,
        reserved_output_tokens=60,
    )
    assert legacy.summary()["hard_limit_tokens"] == 100_000_000

    read_only_before_migration = summarize_live_micu_token_ledger(path)
    assert read_only_before_migration["hard_limit_tokens"] == 100_000_000
    assert read_only_before_migration["charged_tokens"] == 100

    # Constructing or using the new default ledger must not reinterpret an
    # existing caller-selected lower limit as the new repository ceiling.
    current = LiveMicuTokenLedger(path)
    current.reserve_attempt(
        scenario="live_llm",
        purpose="default-does-not-auto-migrate",
        kind="tool_calling",
        model="test-model",
        attempt=2,
        estimated_input_tokens=1,
        reserved_output_tokens=1,
    )
    with sqlite3.connect(path) as connection:
        stored_limit_before = connection.execute(
            "SELECT hard_limit_tokens FROM live_micu_token_state WHERE id = 1"
        ).fetchone()[0]
        attempts_before = connection.execute(
            "SELECT * FROM live_micu_token_attempts ORDER BY id"
        ).fetchall()
    assert stored_limit_before == 100_000_000

    migrated = migrate_legacy_live_micu_token_policy(path)
    assert migrated["policy_migrated"] is True
    assert migrated["hard_limit_tokens"] == LIVE_MICU_TOKEN_HARD_LIMIT
    assert migrated["charged_tokens"] == 102
    assert migrated["attempt_count"] == 2

    with sqlite3.connect(path) as connection:
        stored_limit_after = connection.execute(
            "SELECT hard_limit_tokens FROM live_micu_token_state WHERE id = 1"
        ).fetchone()[0]
        attempts_after = connection.execute(
            "SELECT * FROM live_micu_token_attempts ORDER BY id"
        ).fetchall()
    assert stored_limit_after == LIVE_MICU_TOKEN_HARD_LIMIT
    assert attempts_after == attempts_before

    idempotent = migrate_legacy_live_micu_token_policy(path)
    assert idempotent["policy_migrated"] is False
    assert idempotent["charged_tokens"] == 102


def test_policy_migration_rejects_noncanonical_limit_without_mutation(tmp_path) -> None:
    path = tmp_path / "caller-lowered-limit.sqlite3"
    ledger = LiveMicuTokenLedger(path, hard_limit_tokens=200_000_000)
    ledger.reserve_attempt(
        scenario="live_llm",
        purpose="caller-lowered-limit",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=40,
        reserved_output_tokens=60,
    )
    with sqlite3.connect(path) as connection:
        before = list(connection.iterdump())

    with pytest.raises(
        LiveMicuTokenPolicyMigrationError,
        match="not on the exact legacy fixed 100M policy",
    ):
        migrate_legacy_live_micu_token_policy(path)

    with sqlite3.connect(path) as connection:
        after = list(connection.iterdump())
    assert after == before


def test_policy_migration_cli_is_explicit_and_preserves_attempts(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "cli-migration.sqlite3"
    ledger = LiveMicuTokenLedger(path, hard_limit_tokens=100_000_000)
    ledger.reserve_attempt(
        scenario="live_llm",
        purpose="cli-migration",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=40,
        reserved_output_tokens=60,
    )

    live_token_ledger_main(["--path", str(path)])
    read_only_output = json.loads(capsys.readouterr().out)
    assert read_only_output["hard_limit_tokens"] == 100_000_000
    assert "policy_migrated" not in read_only_output

    live_token_ledger_main(
        ["--path", str(path), "--migrate-legacy-fixed-policy", "--attempts", "1"]
    )
    migrated_output = json.loads(capsys.readouterr().out)
    assert migrated_output["policy_migrated"] is True
    assert migrated_output["hard_limit_tokens"] == LIVE_MICU_TOKEN_HARD_LIMIT
    assert migrated_output["charged_tokens"] == 100
    assert migrated_output["attempt_count"] == 1
    assert len(migrated_output["attempts"]) == 1


def test_ledger_begin_immediate_prevents_concurrent_oversubscription(tmp_path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    first = LiveMicuTokenLedger(path, hard_limit_tokens=100).reserve_attempt(
        scenario="concurrency",
        purpose="test",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=1,
        reserved_output_tokens=9,
    )
    assert first.reserved_tokens == 10

    def reserve(index: int) -> bool:
        try:
            LiveMicuTokenLedger(path, hard_limit_tokens=100).reserve_attempt(
                scenario="concurrency",
                purpose="test",
                kind="tool_calling",
                model="test-model",
                attempt=index + 2,
                estimated_input_tokens=1,
                reserved_output_tokens=9,
            )
        except LiveMicuTokenBudgetExceededError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(reserve, range(19)))

    summary = LiveMicuTokenLedger(path, hard_limit_tokens=100).summary()
    assert sum(results) == 9
    assert summary["attempt_count"] == 10
    assert summary["charged_tokens"] == 100
    assert summary["remaining_tokens"] == 0


def test_ledger_begin_immediate_is_atomic_across_processes(tmp_path) -> None:
    path = tmp_path / "cross-process.sqlite3"
    LiveMicuTokenLedger(path, hard_limit_tokens=30).reserve_attempt(
        scenario="cross-process",
        purpose="test",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=1,
        reserved_output_tokens=9,
    )

    with ProcessPoolExecutor(max_workers=5) as executor:
        results = list(
            executor.map(
                _reserve_from_process,
                ((str(path), attempt) for attempt in range(2, 7)),
            )
        )

    summary = LiveMicuTokenLedger(path, hard_limit_tokens=30).summary()
    assert sum(results) == 2
    assert summary["attempt_count"] == 3
    assert summary["charged_tokens"] == 30


def test_missing_usage_and_failed_retry_keep_conservative_reservations(tmp_path) -> None:
    path = tmp_path / "retry.sqlite3"
    ledger = LiveMicuTokenLedger(path, hard_limit_tokens=10_000)
    provider_calls = 0

    def provider_call():
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            raise FakeApiStatusError(503)
        return {"content": "ok", "usage": {"input_tokens": 3, "output_tokens": 2}}

    response = LlmInvocationRuntime(
        purpose="v3_harness_loop",
        kind="tool_calling",
        model="test-model",
        base_url="https://www.micuapi.ai/v1",
        max_attempts=2,
        retry_backoff_seconds=0.0,
        diagnostic_label="live-provider",
        live_token_ledger=ledger,
        live_token_scenario="live_e2e",
        reserved_output_tokens=20,
    ).invoke(
        request={"messages": [{"role": "user", "content": "retry me"}]},
        call=provider_call,
        phase="testing metered retry",
    )

    attempts = list(reversed(ledger.list_attempts()))
    assert response["content"] == "ok"
    assert provider_calls == 2
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert [item["status"] for item in attempts] == [
        "failed_estimated",
        "succeeded",
    ]
    assert attempts[0]["estimated"] == 1
    assert attempts[1]["estimated"] == 0
    assert attempts[1]["charged_tokens"] == 5
    summary = ledger.summary()
    assert summary["charged_tokens"] == attempts[0]["charged_tokens"] + 5
    assert summary["actual_input_tokens"] == 3
    assert summary["actual_output_tokens"] == 2
    assert summary["estimated_input_tokens"] == attempts[0]["input_tokens"]
    assert summary["estimated_output_tokens"] == attempts[0]["output_tokens"]
    assert summary["by_model"][0]["model"] == "test-model"


def test_budget_exhaustion_fails_before_provider_call(tmp_path) -> None:
    ledger = LiveMicuTokenLedger(tmp_path / "exhausted.sqlite3", hard_limit_tokens=100)
    provider_calls = 0

    def provider_call():
        nonlocal provider_calls
        provider_calls += 1
        return {"content": "should not run"}

    runtime = LlmInvocationRuntime(
        purpose="v3_harness_loop",
        kind="tool_calling",
        model="test-model",
        base_url="https://www.micuapi.ai/v1",
        diagnostic_label="live-provider",
        live_token_ledger=ledger,
        live_token_scenario="live_llm",
        reserved_output_tokens=1,
    )

    with pytest.raises(LiveMicuTokenBudgetExceededError):
        runtime.invoke(
            request={"prompt": "a request whose conservative estimate exceeds the limit"},
            call=provider_call,
            phase="testing budget rejection",
        )

    assert provider_calls == 0
    assert ledger.summary()["attempt_count"] == 0


def test_missing_output_reservation_fails_before_provider_call(tmp_path) -> None:
    ledger = LiveMicuTokenLedger(tmp_path / "unbounded.sqlite3", hard_limit_tokens=1_000)
    provider_calls = 0

    def provider_call():
        nonlocal provider_calls
        provider_calls += 1
        return {"content": "should not run"}

    runtime = LlmInvocationRuntime(
        purpose="v3_harness_loop",
        kind="tool_calling",
        model="test-model",
        base_url="https://www.micuapi.ai/v1",
        diagnostic_label="live-provider",
        live_token_ledger=ledger,
        live_token_scenario="live_llm",
        reserved_output_tokens=None,
    )

    with pytest.raises(LiveMicuTokenReservationConfigurationError):
        runtime.invoke(request={}, call=provider_call, phase="missing output reservation")

    assert provider_calls == 0
    assert ledger.summary()["attempt_count"] == 0


def test_reported_overage_is_explicit_and_keeps_future_calls_fail_closed(
    tmp_path,
) -> None:
    ledger = LiveMicuTokenLedger(tmp_path / "overage.sqlite3", hard_limit_tokens=500)
    reservation = ledger.reserve_attempt(
        scenario="live_llm",
        purpose="report_review",
        kind="structured",
        model="test-model",
        attempt=1,
        estimated_input_tokens=100,
        reserved_output_tokens=100,
    )
    ledger.reconcile_success(
        reservation,
        {"input_tokens": 400, "output_tokens": 200},
    )

    entry = ledger.list_attempts()[0]
    summary = ledger.summary()
    assert entry["status"] == "succeeded_limit_breached"
    assert entry["reservation_overage_tokens"] == 400
    assert entry["hard_limit_breached"] == 1
    assert summary["charged_tokens"] == 600
    assert summary["remaining_tokens"] == 0
    assert summary["hard_limit_overage_tokens"] == 100
    assert summary["reservation_overage_tokens"] == 400
    assert summary["hard_limit_breach_count"] == 1

    provider_calls = 0

    def provider_call():
        nonlocal provider_calls
        provider_calls += 1
        return {"content": "should not run"}

    with pytest.raises(LiveMicuTokenBudgetExceededError):
        LlmInvocationRuntime(
            purpose="v3_harness_loop",
            kind="tool_calling",
            model="test-model",
            base_url="https://www.micuapi.ai/v1",
            diagnostic_label="live-provider",
            live_token_ledger=ledger,
            live_token_scenario="live_llm",
            reserved_output_tokens=1,
        ).invoke(request={}, call=provider_call, phase="post-breach call")

    assert provider_calls == 0


def test_non_micu_or_non_diagnostic_calls_are_not_metered(tmp_path) -> None:
    ledger = LiveMicuTokenLedger(tmp_path / "disabled.sqlite3", hard_limit_tokens=1_000)
    provider_calls = 0

    def provider_call():
        nonlocal provider_calls
        provider_calls += 1
        return {"content": "ok"}

    common = {
        "purpose": "test",
        "kind": "tool_calling",
        "model": "test-model",
        "live_token_ledger": ledger,
        "live_token_scenario": "live_llm",
        "reserved_output_tokens": 10,
    }
    LlmInvocationRuntime(
        **common,
        base_url="https://example.test/v1",
        diagnostic_label="live-provider",
    ).invoke(request={}, call=provider_call, phase="non-MICU")
    LlmInvocationRuntime(
        **common,
        base_url="https://www.micuapi.ai/v1",
        diagnostic_label=None,
    ).invoke(request={}, call=provider_call, phase="non-diagnostic")

    assert provider_calls == 2
    assert summarize_live_micu_token_ledger(
        ledger.path,
        fallback_hard_limit=1_000,
    )["attempt_count"] == 0


def test_structured_and_tool_invokers_record_attempts_without_network(tmp_path) -> None:
    ledger = LiveMicuTokenLedger(tmp_path / "invokers.sqlite3", hard_limit_tokens=10_000)

    class FakeStructuredRunnable:
        def invoke(self, messages):
            del messages
            return ExampleSchema(value="ok")

    class FakeStructuredModel:
        def with_structured_output(self, schema, *, method: str):
            assert schema is ExampleSchema
            assert method == "function_calling"
            return FakeStructuredRunnable()

    class FakeToolRunnable:
        def invoke(self, messages):
            del messages
            return {
                "content": "ok",
                "tool_calls": [],
                "usage_metadata": {"input_tokens": 7, "output_tokens": 3},
            }

    class FakeToolModel:
        def bind_tools(self, tools):
            assert tools == []
            return FakeToolRunnable()

    common = {
        "model_name": "test-model",
        "base_url": "https://www.micuapi.ai/v1",
        "diagnostic_label": "live-provider",
        "live_token_ledger": ledger,
        "live_token_scenario": "live_llm",
        "reserved_output_tokens": 20,
    }
    structured = LangChainStructuredInvoker(
        model=FakeStructuredModel(),
        purpose="report_review",
        structured_output_method="function_calling",
        **common,
    )
    tool_calling = LangChainToolCallingInvoker(
        model=FakeToolModel(),
        purpose="v3_harness_loop",
        **common,
    )

    assert structured.invoke_structured(
        schema=ExampleSchema,
        system_prompt="Return schema.",
        user_payload={"value": "ignored"},
    ).value == "ok"
    assert tool_calling.invoke_with_tools(
        system_prompt="Use tools.",
        messages=[],
        tools=[],
    )["content"] == "ok"

    attempts = list(reversed(ledger.list_attempts()))
    assert [item["kind"] for item in attempts] == ["structured", "tool_calling"]
    assert [item["status"] for item in attempts] == [
        "succeeded_estimated",
        "succeeded",
    ]
    assert attempts[1]["input_tokens"] == 7
    assert attempts[1]["output_tokens"] == 3
    for sqlite_file in tmp_path.glob("invokers.sqlite3*"):
        contents = sqlite_file.read_bytes()
        assert b"Return schema." not in contents
        assert b"Use tools." not in contents


def test_hard_limit_cannot_be_constructed_above_five_hundred_million(tmp_path) -> None:
    ledger = LiveMicuTokenLedger(
        tmp_path / "hard-limit.sqlite3",
        hard_limit_tokens=LIVE_MICU_TOKEN_HARD_LIMIT * 2,
    )

    assert ledger.hard_limit_tokens == LIVE_MICU_TOKEN_HARD_LIMIT
    assert ledger.summary()["hard_limit_tokens"] == LIVE_MICU_TOKEN_HARD_LIMIT
