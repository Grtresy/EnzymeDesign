from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import replace
import threading
import time

from fastapi.testclient import TestClient
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_host_api.app import V3ExecutionRunnerAdapter
from openzyme_host_api.app import create_app
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_host_api.foundation import build_local_eval_foundation
from openzyme_host_api.foundation import build_model_factory_from_env
from openzyme_host_api.foundation import build_model_factory_from_settings
from openzyme_host_api.foundation import DeterministicExecutionAdapter
from openzyme_host_api.foundation import DeterministicResearchAdapter
from openzyme_host_api.eval_support import DeterministicLocalModelFactory
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_BASE_URL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_MODEL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_USER_AGENT
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import HostApiSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import LiveLlmTestSettings as RuntimeLiveLlmTestSettings
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import LlmPurposePolicy
from openzyme_runtime import LlmSettings
from openzyme_runtime import OpenAICompatibleChatModelFactory
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import ResearchSettings
from openzyme_runtime import reset_settings_cache
from openzyme_runtime import TestSettings as RuntimeTestSettings
from openzyme_runtime import TracingSettings
from openzyme_runtime import V3BackgroundRuntimeSettings


def _settings() -> OpenZymeSettings:
    return OpenZymeSettings(
        llm=LlmSettings(
            api_key="llm-key",
            model="glm-5.1",
            base_url="https://open.bigmodel.cn/api/coding/paas/v4",
            extra_body={"provider": "bigmodel"},
            default_headers={"User-Agent": "openzyme-test-agent"},
            use_responses_api=False,
            max_tokens=800,
            timeout=30.0,
            max_retries=5,
            temperature=0.0,
            structured_output_method="function_calling",
            structured_output_retry_backoff_seconds=1.0,
            purpose_policies={},
        ),
        research=ResearchSettings(
            max_units=3,
            allow_clarification=False,
            max_research_iterations=3,
            max_react_tool_calls=4,
            max_concurrent_research_units=3,
            tavily_api_key=None,
            tavily_max_results=3,
            tavily_topic="general",
            mcp_enabled=False,
        ),
        tracing=TracingSettings(enabled=False, project_name="openzyme-test"),
        host_cli=HostCliSettings(
            base_url="http://127.0.0.1:8000",
            project_id=None,
            output_format="text",
        ),
        host_api=HostApiSettings(bind_host="127.0.0.1", bind_port=8000),
        v3_background_runtime=V3BackgroundRuntimeSettings(
            enabled=True,
            poll_interval_seconds=2.0,
            max_signals_per_tick=3,
            max_steps_per_agent=8,
            shutdown_timeout_seconds=10.0,
        ),
        execution=ExecutionSettings(backend="demo", hpc_runner_config=None),
        test=RuntimeTestSettings(
            enable_live_llm=False,
            enable_live_tavily=False,
            enable_live_hpc=False,
            enable_live_e2e=False,
            enable_quality_eval=False,
            upload_langsmith=False,
            live_llm=RuntimeLiveLlmTestSettings(
                max_tokens=None,
                timeout=None,
                max_retries=None,
                structured_output_method=None,
                structured_output_retry_backoff_seconds=None,
            ),
        ),
    )


def test_configured_foundation_uses_demo_adapters_without_live_integrations() -> None:
    foundation = build_configured_foundation(
        settings=_settings(),
    )

    assert isinstance(foundation.execution_adapter, DeterministicExecutionAdapter)
    assert isinstance(foundation.research_adapter, DeterministicResearchAdapter)
    assert isinstance(foundation.model_factory, OpenAICompatibleChatModelFactory)


def test_configured_foundation_uses_hpc_and_tavily_when_enabled(monkeypatch) -> None:
    configured_settings = replace(
        _settings(),
        research=ResearchSettings(
            max_units=5,
            allow_clarification=False,
            max_research_iterations=3,
            max_react_tool_calls=4,
            max_concurrent_research_units=3,
            tavily_api_key="tavily-key",
            tavily_max_results=4,
            tavily_topic="news",
            mcp_enabled=False,
        ),
        execution=ExecutionSettings(backend="hpc", hpc_runner_config="/tmp/hpc.toml"),
    )
    calls: dict[str, object] = {}

    class FakeMCPHpcServer:
        def __init__(self, config_path: str | None) -> None:
            calls["server_config_path"] = config_path

    class FakeHpcRunnerExecutionAdapter:
        def __init__(self, config_path: str | None, **kwargs) -> None:
            calls["limiter_registry"] = kwargs.get("limiter_registry")
            calls["config_path"] = config_path
            calls["server"] = kwargs.get("server")

    monkeypatch.setattr(
        "openzyme_host_api.foundation.MCPHpcServer",
        FakeMCPHpcServer,
    )
    monkeypatch.setattr(
        "openzyme_host_api.foundation.HpcRunnerExecutionAdapter",
        FakeHpcRunnerExecutionAdapter,
    )

    foundation = build_configured_foundation(
        settings=configured_settings,
    )

    assert calls["config_path"] == "/tmp/hpc.toml"
    assert calls["server_config_path"] == "/tmp/hpc.toml"
    assert type(calls["server"]).__name__ == "FakeMCPHpcServer"
    assert calls["limiter_registry"] is foundation.limiter_registry
    assert type(foundation.execution_adapter).__name__ == "FakeHpcRunnerExecutionAdapter"
    assert type(foundation.research_adapter).__name__ == "TavilyResearchAdapter"


def test_apply_live_llm_test_budget_constrains_live_e2e_llm_settings() -> None:
    base = _settings()
    configured_settings = replace(
        base,
        llm=replace(
            base.llm,
            max_tokens=800,
            timeout=60.0,
            max_retries=2,
            structured_output_method="json_schema",
            structured_output_retry_backoff_seconds=2.0,
            purpose_policies={"report_review": LlmPurposePolicy(timeout=90.0)},
        ),
        test=replace(
            base.test,
            enable_live_e2e=True,
            live_llm=RuntimeLiveLlmTestSettings(
                max_tokens=256,
                timeout=12.0,
                max_retries=0,
                structured_output_method="function_calling",
                structured_output_retry_backoff_seconds=0.25,
            ),
        ),
    )

    constrained = apply_live_llm_test_budget(configured_settings)

    assert constrained.llm.max_tokens == 256
    assert constrained.llm.timeout == 12.0
    assert constrained.llm.max_retries == 0
    assert constrained.llm.structured_output_method == "function_calling"
    assert constrained.llm.structured_output_retry_backoff_seconds == 0.25
    assert constrained.llm.purpose_policies == {}


def test_apply_live_llm_test_budget_respects_long_env_driven_budget() -> None:
    base = _settings()
    configured_settings = replace(
        base,
        test=replace(
            base.test,
            enable_live_llm=True,
            live_llm=RuntimeLiveLlmTestSettings(
                max_tokens=512,
                timeout=240.0,
                max_retries=0,
                structured_output_method="function_calling",
                structured_output_retry_backoff_seconds=0.5,
            ),
        ),
    )

    constrained = apply_live_llm_test_budget(configured_settings)

    assert constrained.llm.max_tokens == 512
    assert constrained.llm.timeout == 240.0
    assert constrained.llm.max_retries == 0
    assert constrained.llm.structured_output_retry_backoff_seconds == 0.5


def test_model_factory_enables_ledger_only_for_explicit_live_micu(tmp_path) -> None:
    base = _settings()
    ledger_path = tmp_path / "live-ledger.sqlite3"
    live_micu = replace(
        base,
        llm=replace(
            base.llm,
            base_url="https://www.micuapi.ai/v1",
            max_tokens=300,
        ),
        test=replace(
            base.test,
            enable_live_llm=True,
            live_llm=replace(
                base.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )

    metered = build_model_factory_from_settings(live_micu)
    non_live = build_model_factory_from_settings(
        replace(live_micu, test=replace(live_micu.test, enable_live_llm=False))
    )
    non_micu = build_model_factory_from_settings(
        replace(live_micu, llm=replace(live_micu.llm, base_url="https://example.test/v1"))
    )

    assert metered is not None
    assert metered.live_token_ledger is not None
    assert metered.live_token_ledger.path == ledger_path
    assert metered.live_token_scenario == "live_llm"
    assert metered.diagnostic_label == "live-provider"
    assert non_live is not None
    assert non_live.live_token_ledger is None
    assert non_live.live_token_scenario is None
    assert non_micu is not None
    assert non_micu.live_token_ledger is None

    quality_eval = build_model_factory_from_settings(
        replace(
            live_micu,
            test=replace(live_micu.test, enable_quality_eval=True),
        )
    )
    assert quality_eval is not None
    assert quality_eval.live_token_scenario == "live_llm+quality_eval"


def test_local_eval_foundation_wires_deterministic_components() -> None:
    foundation = build_local_eval_foundation()

    assert isinstance(foundation.execution_adapter, DeterministicExecutionAdapter)
    assert isinstance(foundation.research_adapter, DeterministicResearchAdapter)
    assert isinstance(foundation.model_factory, DeterministicLocalModelFactory)
    assert foundation.research_tool_provider is not None


def test_local_eval_foundation_owns_deterministic_model_factory() -> None:
    foundation = build_local_eval_foundation()
    configured = build_configured_foundation(
        settings=replace(_settings(), llm=replace(_settings().llm, api_key=None)),
    )

    assert isinstance(foundation.model_factory, DeterministicLocalModelFactory)
    assert configured.model_factory is None


def test_app_can_mount_ui_when_dist_exists(tmp_path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>ui</body></html>")
    (dist_dir / "debug.html").write_text("<html><body>debug</body></html>")

    @dataclass(frozen=True, slots=True)
    class DummyDependencies:
        def build_projection_loader(self):
            raise AssertionError("not used in this test")

        def build_service(self):
            raise AssertionError("not used in this test")

    client = TestClient(create_app(DummyDependencies(), ui_dist_dir=dist_dir))  # type: ignore[arg-type]

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/ui/"
    assert client.get("/debug").text == "<html><body>debug</body></html>"


def test_deterministic_execution_adapter_scopes_run_ids_per_session_and_call_count() -> None:
    adapter = DeterministicExecutionAdapter()

    first = adapter.submit_execution("sess_local", {})
    second = adapter.submit_execution("sess_local", {})
    third = adapter.submit_execution("sess_other", {})

    assert first.run_id == "run_sess_local_1"
    assert second.run_id == "run_sess_local_2"
    assert third.run_id == "run_sess_other_1"
    assert first.status is RunStatus.SUCCEEDED
    assert first.remote_run_dir == ""
    assert first.artifacts[0].kind is ArtifactKind.LOG


def test_v3_execution_runner_adapter_limits_execution_methods() -> None:
    @dataclass(frozen=True, slots=True)
    class FakeOutcome:
        run_id: str = "run_001"
        status: RunStatus = RunStatus.SUCCEEDED
        execution_mode: str = "demo"
        raw_result: dict[str, object] = None  # type: ignore[assignment]
        artifacts: tuple[object, ...] = ()
        exit_code: int | None = 0

        def __post_init__(self) -> None:
            if self.raw_result is None:
                object.__setattr__(self, "raw_result", {"status": "completed"})

    @dataclass(frozen=True, slots=True)
    class FakeSnapshot:
        run_id: str = "run_001"
        status: RunStatus = RunStatus.SUCCEEDED
        raw_result: dict[str, object] = None  # type: ignore[assignment]
        exit_code: int | None = 0

        def __post_init__(self) -> None:
            if self.raw_result is None:
                object.__setattr__(self, "raw_result", {"state": "completed"})

    class FakeExecutionAdapter:
        def __init__(self) -> None:
            self.active = 0
            self.observed_max = 0
            self.lock = threading.Lock()

        def _call(self, result):
            with self.lock:
                self.active += 1
                self.observed_max = max(self.observed_max, self.active)
            try:
                time.sleep(0.01)
                return result
            finally:
                with self.lock:
                    self.active -= 1

        def submit_execution(self, session_id: str, payload: dict[str, object]):
            del session_id, payload
            return self._call(FakeOutcome())

        def get_execution_status(self, *, run_id: str):
            del run_id
            return self._call(FakeSnapshot())

        def fetch_execution_artifacts(self, *, run_id: str):
            del run_id
            return self._call(FakeOutcome())

        def cancel_execution(self, *, run_id: str):
            del run_id
            return self._call(FakeOutcome(status=RunStatus.CANCELLED))

    fake = FakeExecutionAdapter()
    adapter = V3ExecutionRunnerAdapter(
        fake,
        LimiterRegistry({"execution_provider": 1}),
    )

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            *(executor.submit(adapter.submit_execution, "sess_001", {}) for _ in range(3)),
            executor.submit(adapter.get_execution_status, run_id="run_001"),
            executor.submit(adapter.fetch_execution_artifacts, run_id="run_001"),
            executor.submit(adapter.cancel_execution, run_id="run_001"),
        ]
        for future in futures:
            future.result(timeout=2)

    assert fake.observed_max == 1


def test_v3_execution_runner_adapter_fails_cancel_when_boundary_unsupported() -> None:
    @dataclass(frozen=True, slots=True)
    class FakeOutcome:
        run_id: str = "run_unsupported_cancel"
        status: RunStatus = RunStatus.SUCCEEDED
        execution_mode: str = "demo"
        raw_result: dict[str, object] = None  # type: ignore[assignment]
        artifacts: tuple[object, ...] = ()
        exit_code: int | None = 0

        def __post_init__(self) -> None:
            if self.raw_result is None:
                object.__setattr__(self, "raw_result", {"status": "completed"})

    class FakeExecutionAdapter:
        def submit_execution(self, session_id: str, payload: dict[str, object]):
            del session_id, payload
            return FakeOutcome()

    adapter = V3ExecutionRunnerAdapter(FakeExecutionAdapter())
    submitted = adapter.submit_execution("sess_cancel", {})
    assert submitted.remote_run_dir == "opaque://run_unsupported_cancel"

    cancelled = adapter.cancel_execution(
        run_id=submitted.run_id,
    )

    assert cancelled.status is RunStatus.FAILED
    assert cancelled.raw_result["status"] == "unsupported"
    assert cancelled.raw_result["error_code"] == "cancel_execution_unsupported"


def test_v3_execution_runner_adapter_does_not_project_runner_storage_in_raw_result() -> None:
    @dataclass(frozen=True, slots=True)
    class FakeOutcome:
        run_id: str = "run_private_projection"
        status: RunStatus = RunStatus.SUCCEEDED
        execution_mode: str = "ssh"
        raw_result: dict[str, object] = None  # type: ignore[assignment]
        artifacts: tuple[object, ...] = ()
        exit_code: int | None = 0

        def __post_init__(self) -> None:
            if self.raw_result is None:
                object.__setattr__(
                    self,
                    "raw_result",
                    {
                        "status": "completed",
                        "artifacts": {"result.json": "/host/private/result.json"},
                        "job_id": "12345",
                        "remote_run_dir": "/cluster/private/run",
                    },
                )

    class FakeExecutionAdapter:
        def submit_execution(self, session_id: str, payload: dict[str, object]):
            del session_id, payload
            return FakeOutcome()

    outcome = V3ExecutionRunnerAdapter(FakeExecutionAdapter()).submit_execution(
        "sess_projection",
        {},
    )

    assert outcome.raw_result == {"status": "completed"}
    assert "/host/private" not in str(outcome)


def test_build_model_factory_from_env_returns_none_without_api_key(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "")
    monkeypatch.setenv("MICU_API_KEY", "")
    monkeypatch.setenv("BIGMODEL_API_KEY", "")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "")

    assert build_model_factory_from_env() is None


def test_build_model_factory_from_env_uses_micu_responses_defaults(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setattr("openzyme_runtime.settings.load_env_files", lambda: None)
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "test-key")
    monkeypatch.delenv("OPENZYME_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_EXTRA_BODY", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_USER_AGENT", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_USE_RESPONSES_API", raising=False)
    monkeypatch.setenv("OPENZYME_LLM_MAX_RETRIES", "5")

    factory = build_model_factory_from_env()

    assert isinstance(factory, OpenAICompatibleChatModelFactory)
    assert factory.model == DEFAULT_OPENAI_COMPAT_MODEL
    assert factory.base_url == DEFAULT_OPENAI_COMPAT_BASE_URL
    assert factory.api_key == "test-key"
    assert factory.extra_body is None
    assert factory.default_headers == {"User-Agent": DEFAULT_OPENAI_COMPAT_USER_AGENT}
    assert factory.use_responses_api is DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API
    assert factory.max_retries == 5
    reset_settings_cache()
