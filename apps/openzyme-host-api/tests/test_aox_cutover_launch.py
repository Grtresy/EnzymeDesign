from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from openzyme_host_api import aox_cutover_launch as launch
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST,
)
from openzyme_pipeline import aox_motif
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import ControlledOperationOwnerPolicy
from openzyme_runtime import HostApiSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import LiveLlmTestSettings
from openzyme_runtime import LlmPurposePolicy
from openzyme_runtime import LlmSettings
from openzyme_runtime import MutationClosureMode
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import ResearchSettings
from openzyme_runtime import RuntimeDrainContract
from openzyme_runtime import TestSettings as RuntimeTestSettings
from openzyme_runtime import TracingSettings
from openzyme_runtime import V3BackgroundRuntimeSettings
from openzyme_tools import get_hpc_tool_contract
from openzyme_tools import render_contract_command


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _architecture_qualification() -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest=_digest("qualification-report"),
        registry_digest=_digest("qualification-registry"),
        test_manifest_digest=_digest("qualification-manifest"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
    )


@pytest.fixture(autouse=True)
def _verified_architecture_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launch,
        "verify_aox_architecture_qualification_report",
        lambda path, *, repo_root: _architecture_qualification(),
    )


def _settings(*, ledger_path: Path, hpc_config_path: Path) -> OpenZymeSettings:
    return OpenZymeSettings(
        llm=LlmSettings(
            api_key="llm-test-key",
            model="micu-test-model",
            base_url="https://www.micuapi.ai/v1",
            extra_body={"reasoning": {"enabled": True}},
            default_headers={"User-Agent": "openzyme-launch-test"},
            use_responses_api=True,
            max_tokens=9_999,
            timeout=123.0,
            max_retries=7,
            temperature=0.0,
            structured_output_method="json_schema",
            structured_output_retry_backoff_seconds=3.0,
            purpose_policies={
                "master": LlmPurposePolicy(max_tokens=8_888, timeout=99.0)
            },
            context_window_tokens=200_000,
            default_output_tokens=4_000,
            tokenizer_enabled=True,
        ),
        research=ResearchSettings(
            max_units=3,
            allow_clarification=False,
            max_research_iterations=3,
            max_react_tool_calls=4,
            max_concurrent_research_units=2,
            tavily_api_key=None,
            tavily_max_results=3,
            tavily_topic="general",
            mcp_enabled=True,
            mcp_tool_allowlist=("pubmed.search",),
            pubmed_email="ncbi@example.org",
            pubmed_tool="openzyme-aox",
            pubmed_api_key="ncbi-test-key",
            semantic_scholar_api_key=None,
            provider_timeout_seconds=20.0,
            provider_max_attempts=2,
        ),
        tracing=TracingSettings(enabled=False, project_name="launch-test"),
        host_cli=HostCliSettings(
            base_url="http://127.0.0.1:8000",
            project_id=None,
            output_format="text",
        ),
        host_api=HostApiSettings(
            bind_host="127.0.0.1",
            bind_port=8000,
            deployment_profile="local-dev",
        ),
        v3_background_runtime=V3BackgroundRuntimeSettings(
            enabled=True,
            poll_interval_seconds=2.0,
            max_signals_per_tick=3,
            max_steps_per_agent=12,
            shutdown_timeout_seconds=10.0,
        ),
        execution=ExecutionSettings(
            backend="hpc",
            hpc_runner_config=str(hpc_config_path),
        ),
        reliability=ReliabilityRefactorSettings(
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
            ),
            mutation_closure_mode=MutationClosureMode.GENERIC_V1,
        ),
        test=RuntimeTestSettings(
            enable_live_llm=True,
            enable_live_tavily=False,
            enable_live_hpc=True,
            enable_live_e2e=True,
            enable_quality_eval=False,
            upload_langsmith=False,
            live_llm=LiveLlmTestSettings(
                max_tokens=1_024,
                timeout=45.0,
                max_retries=3,
                structured_output_method="function_calling",
                structured_output_retry_backoff_seconds=0.5,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )


def _probes(checkout: list[str] | None = None) -> launch.AoxCutoverLaunchProbes:
    commits = checkout or ["a" * 40]

    def checkout_probe(_: Path) -> str:
        return commits[-1]

    return launch.AoxCutoverLaunchProbes(
        checkout=checkout_probe,
        workflow_ref=lambda: f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        scoring_identity=lambda: (
            aox_motif.CONTRACT_DIGEST,
            aox_motif.IMPLEMENTATION_DIGEST,
        ),
        sandbox_runtime_identity=lambda: {
            "image_digest": _digest("image"),
            "pipeline_sdk_digest": _digest("sdk"),
        },
        sandbox_scientific_backend=lambda _identity, _repo_root: None,
        source_tree_digest=lambda _: _digest("sdk"),
    )


def _declared_inputs(
    settings: OpenZymeSettings,
    *,
    ledger_path: Path,
    driver: launch.AoxCutoverDriverConfig,
    probes: launch.AoxCutoverLaunchProbes,
    repo_root: Path = launch.REPO_ROOT,
) -> tuple[dict[str, str], dict[str, object]]:
    effective = launch.build_aox_cutover_effective_config(
        settings,
        driver=driver,
        ledger_path=ledger_path,
        repo_root=repo_root,
        source_tree_digest=probes.source_tree_digest,
    )
    identity = {
        "git_commit": "a" * 40,
        "config_digest": effective.digest,
        "workflow_ref": probes.workflow_ref(),
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    prerequisites = launch.build_aox_cutover_allowed_prerequisites(
        identity=identity,
        settings=effective.settings,
        toolchain_image_digests={
            key: _digest("toolchain") for key in launch.TOOLCHAIN_IDS
        },
    )
    return identity, prerequisites


def _stage_runner_contract_manifest(repo_root: Path) -> None:
    source = launch.REPO_ROOT / launch.RUNNER_CONTRACT_MANIFEST_RELATIVE_PATH
    destination = repo_root / launch.RUNNER_CONTRACT_MANIFEST_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _pin_runner_expectations() -> dict[str, object]:
    return {
        "contracts": {
            str(contract["tool_id"]): {
                "adapter_id": str(contract["adapter_id"]),
                "command_template_id": str(contract["command_template_id"]),
                "runner_contract_digest": _digest(
                    f"runner-contract:{contract['tool_id']}"
                ),
            }
            for contract in launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS.values()
        }
    }


class _FakePinServer:
    def __init__(
        self,
        output_root: Path,
        *,
        add_private_identity_field: bool = False,
    ) -> None:
        self.output_root = output_root
        self.add_private_identity_field = add_private_identity_field
        self.calls: list[dict[str, object]] = []
        self.resolved_artifact_refs: list[str] = []
        self._artifact_paths: dict[str, str] = {}
        self.expectations = _pin_runner_expectations()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None,
    ) -> dict[str, object]:
        assert name == "exec.run"
        assert arguments is not None
        assert arguments["mode_override"] == "ssh"
        runspec = dict(arguments["runspec"])
        metadata = dict(runspec["metadata"])
        tool_contract = dict(metadata["tool_contract"])
        tool_id = str(tool_contract["tool_id"])
        contract = get_hpc_tool_contract(tool_id)
        assert runspec["execution_mode"] == "ssh"
        assert runspec["command"] == render_contract_command(
            contract,
            dict(metadata["tool_inputs"]),
        )
        self.calls.append(runspec)
        artifacts: dict[str, str] = {}
        run_id = f"run-{len(self.calls)}"
        for output in contract.expected_outputs:
            materialized = self.output_root / tool_id / output.path
            materialized.parent.mkdir(parents=True, exist_ok=True)
            materialized.write_text(f"fixture output for {tool_id}\n", encoding="utf-8")
            artifact_ref = f"runner-artifact://{run_id}/{output.path}"
            artifacts[output.path] = artifact_ref
            self._artifact_paths[artifact_ref] = str(materialized)
        runner_contract = dict(self.expectations["contracts"])[tool_id]
        image_label = "hmmer" if "hmm" in tool_id else tool_id
        identity: dict[str, str] = {
            "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
            "attestation_scope": "same_ssh_login_shell_pre_exec",
            "execution_mode": "ssh",
            "tool_id": tool_id,
            "adapter_id": str(tool_contract["adapter_id"]),
            "command_template_id": str(tool_contract["command_template_id"]),
            "runner_contract_digest": str(runner_contract["runner_contract_digest"]),
            "image_digest": _digest(image_label),
        }
        if self.add_private_identity_field:
            identity["sif_locator"] = "private-location"
        return {
            "run_id": run_id,
            "status": "completed",
            "selected_mode": "ssh",
            "exit_code": 0,
            "error_code": None,
            "artifacts": artifacts,
            "logs": {},
            "toolchain_runtime_identity": identity,
        }

    def resolve_artifact_ref(self, artifact_ref: str) -> str:
        self.resolved_artifact_refs.append(artifact_ref)
        try:
            return self._artifact_paths[artifact_ref]
        except KeyError as exc:
            raise ValueError("unknown runner artifact reference") from exc


def test_effective_config_is_deterministic_and_uses_live_budget(tmp_path: Path) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("[cluster]\nssh_target='trusted-host'\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    driver = launch.AoxCutoverDriverConfig()

    first = launch.build_aox_cutover_effective_config(
        settings,
        driver=driver,
        ledger_path=ledger,
    )
    second = launch.build_aox_cutover_effective_config(
        settings,
        driver=driver,
        ledger_path=ledger,
    )

    assert first.digest == second.digest
    assert first.payload == second.payload
    assert first.settings.llm.max_tokens == 1_024
    assert first.settings.llm.timeout == 45.0
    assert first.settings.llm.purpose_policies == {}
    assert first.payload["driver"]["micu_hard_limit_tokens"] == 500_000_000
    assert first.payload["driver"]["max_signals_per_drain"] == 1
    assert first.payload["host"]["storage_profile"] == "single_process_sqlite"
    assert first.payload["schema_id"] == "aox_blank_world_runtime_config@3"
    assert first.payload["reliability"] == {
        "shadow_observability": "disabled",
        "controlled_operation_owner_policy": "durable_only_v1",
        "durable_execution_route_allowlist": [],
        "runtime_drain_contract": "command_v1",
        "mutation_closure_mode": "generic_v1",
        "shadow_max_observations": 256,
    }
    assert first.payload["scientific_workflow_contract"] == {
        "schema_id": launch.AOX_SELECTED_CHAIN_CONTRACT_V2.schema_id,
        "contract_id": launch.AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,
        "workflow_id": launch.AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "workflow_contract_digest": (
            launch.AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        ),
    }
    runner_expectations = first.payload["execution"]["aox_runner_contract_expectations"]
    assert runner_expectations["schema_id"] == "aox_runner_contract_expectations@1"
    assert set(runner_expectations["contracts"]) == {
        contract["tool_id"]
        for contract in launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS.values()
    }
    assert all(
        set(contract) == {"adapter_id", "command_template_id", "runner_contract_digest"}
        for contract in runner_expectations["contracts"].values()
    )
    assert str(tmp_path) not in json.dumps(first.payload, sort_keys=True)
    assert "llm-test-key" not in json.dumps(first.payload, sort_keys=True)
    assert "ncbi@example.org" not in json.dumps(first.payload, sort_keys=True)


def test_effective_config_rejects_multi_signal_cutover_drain(tmp_path: Path) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.build_aox_cutover_effective_config(
            _settings(ledger_path=ledger, hpc_config_path=hpc_config),
            driver=launch.AoxCutoverDriverConfig(max_signals_per_drain=2),
            ledger_path=ledger,
        )

    assert error.value.code == "aox_launch_signal_fence_invalid"
    assert error.value.details == {
        "expected_max_signals_per_drain": 1,
        "observed_max_signals_per_drain": 2,
    }


@pytest.mark.parametrize(
    ("tamper", "expected_path"),
    (
        ("missing_top_level", "effective_config"),
        ("extra_top_level", "effective_config"),
        ("missing_nested", "effective_config.llm"),
        ("extra_nested", "effective_config.research.credential_slots"),
        (
            "invalid_nested_range",
            "effective_config.driver.browser_approval_timeout_seconds",
        ),
        ("unsafe_driver_timeout", "effective_config.driver.timeout_seconds"),
        ("missing_context_window", "effective_config.llm.context_window_tokens"),
        ("unsafe_context_window", "effective_config.llm.context_window_tokens"),
        (
            "historical_scientific_contract",
            "effective_config.scientific_workflow_contract",
        ),
    ),
)
def test_effective_config_closed_schema_rejects_tamper(
    tmp_path: Path,
    tamper: str,
    expected_path: str,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    effective = launch.build_aox_cutover_effective_config(
        _settings(ledger_path=ledger, hpc_config_path=hpc_config),
        driver=launch.AoxCutoverDriverConfig(),
        ledger_path=ledger,
    )
    payload = json.loads(json.dumps(effective.payload))
    if tamper == "missing_top_level":
        payload.pop("limits")
    elif tamper == "extra_top_level":
        payload["legacy_compatibility"] = True
    elif tamper == "missing_nested":
        payload["llm"].pop("model")
    elif tamper == "extra_nested":
        payload["research"]["credential_slots"]["legacy"] = False
    elif tamper == "missing_context_window":
        payload["llm"]["context_window_tokens"] = None
    elif tamper == "unsafe_context_window":
        payload["llm"]["context_window_tokens"] = 1_050_000
    elif tamper == "historical_scientific_contract":
        payload["scientific_workflow_contract"][
            "workflow_contract_digest"
        ] = AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST
    elif tamper == "unsafe_driver_timeout":
        payload["driver"]["timeout_seconds"] = 3_599.0
    else:
        payload["driver"]["browser_approval_timeout_seconds"] = 0.0

    with pytest.raises(launch.AoxRuntimeConfigSchemaError) as error:
        launch.normalize_aox_blank_world_runtime_config(
            payload,
            expected_runner_contracts=launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
        )

    assert error.value.path == expected_path


def test_effective_config_normalizer_canonicalizes_numeric_durations(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    effective = launch.build_aox_cutover_effective_config(
        _settings(ledger_path=ledger, hpc_config_path=hpc_config),
        driver=launch.AoxCutoverDriverConfig(timeout_seconds=7_200),
        ledger_path=ledger,
    )

    assert effective.payload["driver"]["timeout_seconds"] == 7_200.0
    assert type(effective.payload["driver"]["timeout_seconds"]) is float
    assert effective.payload["driver"]["browser_observation_mode"] == (
        "chrome_devtools_mcp_file_handoff"
    )
    assert (
        effective.payload["driver"][
            "browser_observation_submission_timeout_seconds"
        ]
        == 180.0
    )


def test_effective_config_rejects_nonpositive_observation_submission_timeout(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.build_aox_cutover_effective_config(
            _settings(ledger_path=ledger, hpc_config_path=hpc_config),
            driver=launch.AoxCutoverDriverConfig(
                browser_observation_submission_timeout_seconds=0.0
            ),
            ledger_path=ledger,
        )

    assert error.value.code == "aox_launch_driver_bounds_invalid"
    assert error.value.details == {
        "fields": ["browser_observation_submission_timeout_seconds"]
    }


def test_effective_config_rejects_attempt_timeout_below_long_operation_hierarchy(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.build_aox_cutover_effective_config(
            _settings(ledger_path=ledger, hpc_config_path=hpc_config),
            driver=launch.AoxCutoverDriverConfig(timeout_seconds=7_199.0),
            ledger_path=ledger,
        )

    assert error.value.code == "aox_launch_timeout_hierarchy_invalid"
    assert error.value.details == {
        "hmmer_poll_timeout_seconds": 3_300.0,
        "sandbox_exec_timeout_seconds": 3_600,
        "sandbox_exec_max_timeout_seconds": 3_600,
        "minimum_timeout_seconds": 7_200.0,
        "timeout_seconds": 7_199.0,
    }


def test_effective_config_builder_maps_closed_schema_failure_to_launch_error(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    settings = replace(
        settings,
        llm=replace(
            settings.llm,
            context_warn_ratio=0.9,
            context_auto_compact_ratio=0.85,
        ),
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.build_aox_cutover_effective_config(
            settings,
            driver=launch.AoxCutoverDriverConfig(),
            ledger_path=ledger,
        )

    assert error.value.code == "aox_launch_effective_config_schema_invalid"
    assert error.value.details == {"identity": "effective_config.llm"}


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tool_id", "bio_tools.compatibility_fallback"),
        ("adapter_id", "bio_tools.compatibility_fallback"),
        ("command_template_id", "compatibility_template_v1"),
    ),
)
def test_runner_manifest_required_identity_drift_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    _stage_runner_contract_manifest(tmp_path)
    manifest_path = tmp_path / launch.RUNNER_CONTRACT_MANIFEST_RELATIVE_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mafft = next(
        item for item in manifest["tools"] if item.get("tool_id") == "bio_tools.mafft"
    )
    mafft[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch._aox_runner_contract_expectations(tmp_path)

    assert error.value.code == "aox_launch_runner_contract_manifest_drift"


def test_effective_config_changes_for_driver_or_hpc_config_drift(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    baseline = launch.build_aox_cutover_effective_config(
        settings,
        driver=launch.AoxCutoverDriverConfig(),
        ledger_path=ledger,
    )

    changed_driver = launch.build_aox_cutover_effective_config(
        settings,
        driver=launch.AoxCutoverDriverConfig(max_drains=121),
        ledger_path=ledger,
    )
    hpc_config.write_text("revision=2\n", encoding="utf-8")
    changed_hpc = launch.build_aox_cutover_effective_config(
        settings,
        driver=launch.AoxCutoverDriverConfig(),
        ledger_path=ledger,
    )

    assert changed_driver.digest != baseline.digest
    assert changed_hpc.digest != baseline.digest


@pytest.mark.parametrize(
    ("setting_name", "expected_code"),
    (
        ("enable_live_llm", "aox_launch_live_llm_disabled"),
        ("enable_live_hpc", "aox_launch_live_hpc_disabled"),
    ),
)
def test_effective_config_rejects_disabled_live_dependencies_before_roots(
    tmp_path: Path,
    setting_name: str,
    expected_code: str,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    settings = replace(
        settings,
        test=replace(settings.test, **{setting_name: False}),
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.build_aox_cutover_effective_config(
            settings,
            driver=launch.AoxCutoverDriverConfig(),
            ledger_path=ledger,
        )

    assert error.value.code == expected_code
    assert not (tmp_path / "campaign").exists()


@pytest.mark.parametrize(
    ("reliability", "expected_identity"),
    (
        (
            ReliabilityRefactorSettings(
                mutation_closure_mode=MutationClosureMode.GENERIC_V1,
            ),
            "effective_config.reliability.controlled_operation_owner_policy",
        ),
        (
            ReliabilityRefactorSettings(
                controlled_operation_owner_policy=(
                    ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
                ),
                mutation_closure_mode=MutationClosureMode.GENERIC_V1,
            ),
            "effective_config.reliability.durable_execution_route_allowlist",
        ),
        (
            ReliabilityRefactorSettings(
                controlled_operation_owner_policy=(
                    ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
                ),
                runtime_drain_contract=RuntimeDrainContract.SYNC_V1,
                mutation_closure_mode=MutationClosureMode.GENERIC_V1,
            ),
            "effective_config.reliability.runtime_drain_contract",
        ),
        (
            ReliabilityRefactorSettings(
                controlled_operation_owner_policy=(
                    ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
                ),
            ),
            "effective_config.reliability.mutation_closure_mode",
        ),
    ),
)
def test_effective_config_rejects_ineligible_reliability_before_roots(
    tmp_path: Path,
    reliability: ReliabilityRefactorSettings,
    expected_identity: str,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = replace(
        _settings(ledger_path=ledger, hpc_config_path=hpc_config),
        reliability=reliability,
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.build_aox_cutover_effective_config(
            settings,
            driver=launch.AoxCutoverDriverConfig(),
            ledger_path=ledger,
        )

    assert error.value.code == "aox_launch_effective_config_schema_invalid"
    assert error.value.details == {"identity": expected_identity}
    assert not (tmp_path / "campaign").exists()


def test_prepare_launch_validates_actual_identity_and_guard_detects_drift(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    driver = launch.AoxCutoverDriverConfig()
    commits = ["a" * 40]
    probes = _probes(commits)
    _stage_runner_contract_manifest(tmp_path)
    identity, prerequisites = _declared_inputs(
        settings,
        ledger_path=ledger,
        driver=driver,
        probes=probes,
        repo_root=tmp_path,
    )

    snapshot = launch.prepare_aox_cutover_launch(
        settings=settings,
        driver=driver,
        ledger_path=ledger,
        declared_identity=identity,
        declared_prerequisites=prerequisites,
        architecture_qualification_report=tmp_path / "qualification.json",
        repo_root=tmp_path,
        probes=probes,
    )
    snapshot.assert_unchanged()
    commits.append("b" * 40)

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        snapshot.assert_unchanged()

    assert error.value.code == "aox_launch_snapshot_drift"
    assert error.value.details == {"fields": ["git_commit"]}


@pytest.mark.parametrize("removed", sorted(launch.IDENTITY_FIELDS))
def test_identity_rejects_every_missing_field(removed: str) -> None:
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": _digest("contract"),
        "scoring_implementation_digest": _digest("implementation"),
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    identity.pop(removed)

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.validate_aox_cutover_identity(identity)

    assert error.value.code == "aox_launch_identity_schema_invalid"
    assert removed in error.value.details["missing"]


@pytest.mark.parametrize("removed", sorted(launch.ALLOWED_PREREQUISITE_FIELDS))
def test_prerequisites_require_all_nine_fields_and_identity_alignment(
    removed: str,
) -> None:
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": _digest("contract"),
        "scoring_implementation_digest": _digest("implementation"),
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    prerequisites = {
        **{key: identity[key] for key in launch.IDENTITY_PREREQUISITE_FIELDS},
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi"),
        "prompt_accessions": launch.canonical_prompt_accessions(),
        "toolchain_image_digests": {
            key: _digest("toolchain") for key in launch.TOOLCHAIN_IDS
        },
    }
    missing = dict(prerequisites)
    missing.pop(removed)
    with pytest.raises(launch.AoxCutoverLaunchError) as missing_error:
        launch.validate_aox_cutover_allowed_prerequisites(
            missing,
            identity=identity,
        )
    assert missing_error.value.code == "aox_launch_prerequisite_schema_invalid"
    assert missing_error.value.details["missing"] == [removed]

    drifted = dict(prerequisites)
    drifted["config_digest"] = _digest("drift")
    with pytest.raises(launch.AoxCutoverLaunchError) as drift_error:
        launch.validate_aox_cutover_allowed_prerequisites(
            drifted,
            identity=identity,
        )
    assert drift_error.value.code == "aox_launch_prerequisite_identity_mismatch"


@pytest.mark.parametrize("unexpected", ("architecture_qualification", "force"))
def test_prerequisites_reject_unexpected_field(unexpected: str) -> None:
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": _digest("contract"),
        "scoring_implementation_digest": _digest("implementation"),
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    prerequisites = {
        **{key: identity[key] for key in launch.IDENTITY_PREREQUISITE_FIELDS},
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi"),
        "prompt_accessions": launch.canonical_prompt_accessions(),
        "toolchain_image_digests": {
            key: _digest("toolchain") for key in launch.TOOLCHAIN_IDS
        },
        unexpected: True,
    }

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.validate_aox_cutover_allowed_prerequisites(
            prerequisites,
            identity=identity,
        )

    assert error.value.code == "aox_launch_prerequisite_schema_invalid"
    assert error.value.details["unexpected"] == [unexpected]
    assert len(launch.ALLOWED_PREREQUISITE_FIELDS) == 9


def test_prerequisites_reject_distinct_hmmer_sif_digests() -> None:
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": _digest("contract"),
        "scoring_implementation_digest": _digest("implementation"),
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    prerequisites = {
        **{key: identity[key] for key in launch.IDENTITY_PREREQUISITE_FIELDS},
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi"),
        "prompt_accessions": launch.canonical_prompt_accessions(),
        "toolchain_image_digests": {key: _digest(key) for key in launch.TOOLCHAIN_IDS},
    }

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.validate_aox_cutover_allowed_prerequisites(
            prerequisites,
            identity=identity,
        )

    assert error.value.code == "aox_launch_hmmer_image_identity_mismatch"


def test_prepare_launch_rejects_declared_config_digest_drift(tmp_path: Path) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    driver = launch.AoxCutoverDriverConfig()
    probes = _probes()
    _stage_runner_contract_manifest(tmp_path)
    identity, prerequisites = _declared_inputs(
        settings,
        ledger_path=ledger,
        driver=driver,
        probes=probes,
        repo_root=tmp_path,
    )
    identity["config_digest"] = _digest("operator-stale-config")
    prerequisites["config_digest"] = identity["config_digest"]

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.prepare_aox_cutover_launch(
            settings=settings,
            driver=driver,
            ledger_path=ledger,
            declared_identity=identity,
            declared_prerequisites=prerequisites,
            architecture_qualification_report=tmp_path / "qualification.json",
            repo_root=tmp_path,
            probes=probes,
        )

    assert error.value.code == "aox_launch_identity_mismatch"
    assert error.value.details == {"fields": ["config_digest"]}


def test_prepare_launch_rejects_sandbox_sdk_identity_drift(tmp_path: Path) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    driver = launch.AoxCutoverDriverConfig()
    baseline = _probes()
    _stage_runner_contract_manifest(tmp_path)
    identity, prerequisites = _declared_inputs(
        settings,
        ledger_path=ledger,
        driver=driver,
        probes=baseline,
        repo_root=tmp_path,
    )
    drifted = replace(
        baseline,
        sandbox_runtime_identity=lambda: {
            "image_digest": _digest("image"),
            "pipeline_sdk_digest": _digest("drifted-sdk"),
        },
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.prepare_aox_cutover_launch(
            settings=settings,
            driver=driver,
            ledger_path=ledger,
            declared_identity=identity,
            declared_prerequisites=prerequisites,
            architecture_qualification_report=tmp_path / "qualification.json",
            repo_root=tmp_path,
            probes=drifted,
        )

    assert error.value.code == "aox_launch_sandbox_sdk_mismatch"


def _sandbox_backend_probe_payload() -> dict[str, object]:
    return {
        "schema_id": launch.AOX_SANDBOX_SCIENTIFIC_BACKEND_PROBE_SCHEMA_ID,
        "calculation_id": launch.aox_similarity.CALCULATION_ID,
        "alignment_backend_id": launch.aox_similarity.ALIGNMENT_BACKEND_ID,
        "biopython_version": launch.aox_similarity.BIOPYTHON_VERSION,
        "numpy_version": launch.aox_similarity.NUMPY_VERSION,
        "algorithm": launch.aox_similarity.ALIGNMENT_BACKEND_ALGORITHM,
        "exact_calculation_manifest": (
            launch.aox_finalization.installed_calculation_manifest()
        ),
    }


def _sandbox_sdk_digest() -> str:
    return launch.immutable_source_tree_digest(
        launch.REPO_ROOT / "packages" / "openzyme-pipeline" / "src"
    )


def _canonical_probe_stdout(payload: object) -> str:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def test_sandbox_scientific_backend_probe_uses_immutable_offline_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_digest = _digest("calibrated-image")
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        observed.update(
            {
                "command": command,
                "check": check,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
            }
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_canonical_probe_stdout(_sandbox_backend_probe_payload()),
            stderr="",
        )

    monkeypatch.setattr(launch.subprocess, "run", fake_run)

    launch._probe_aox_sandbox_scientific_backend(
        {
            "image_digest": image_digest,
            "immutable_image_ref": image_digest,
            "pipeline_sdk_digest": _sandbox_sdk_digest(),
        },
        launch.REPO_ROOT,
    )

    command = observed["command"]
    assert isinstance(command, list)
    assert command[0:3] == ["podman", "run", "--rm"]
    assert "--pull=never" in command
    assert "--network=none" in command
    assert image_digest in command
    assert "localhost/openzyme-pipeline-sandbox:dev" not in command
    assert observed["timeout"] == 30


def test_sandbox_scientific_backend_probe_rejects_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_digest = _digest("stale-image")
    monkeypatch.setattr(
        launch.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'Bio'",
        ),
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch._probe_aox_sandbox_scientific_backend(
            {
                "image_digest": image_digest,
                "immutable_image_ref": image_digest,
                "pipeline_sdk_digest": _sandbox_sdk_digest(),
            },
            launch.REPO_ROOT,
        )

    assert error.value.code == "aox_launch_sandbox_scientific_backend_failed"
    assert error.value.details == {"exit_code": 1}
    assert "Bio" not in str(error.value.details)


def test_sandbox_scientific_backend_probe_rejects_contract_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_digest = _digest("wrong-version-image")
    payload = _sandbox_backend_probe_payload()
    payload["biopython_version"] = "1.86"
    monkeypatch.setattr(
        launch.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=_canonical_probe_stdout(payload),
            stderr="",
        ),
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch._probe_aox_sandbox_scientific_backend(
            {
                "image_digest": image_digest,
                "immutable_image_ref": image_digest,
                "pipeline_sdk_digest": _sandbox_sdk_digest(),
            },
            launch.REPO_ROOT,
        )

    assert error.value.code == "aox_launch_sandbox_scientific_backend_mismatch"
    assert error.value.details == {"fields": ["biopython_version"]}


def test_prepare_launch_fails_before_use_when_sandbox_backend_probe_fails(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    driver = launch.AoxCutoverDriverConfig()
    baseline = _probes()
    _stage_runner_contract_manifest(tmp_path)
    identity, prerequisites = _declared_inputs(
        settings,
        ledger_path=ledger,
        driver=driver,
        probes=baseline,
        repo_root=tmp_path,
    )

    def reject_backend(
        _runtime_identity: object,
        _repo_root: Path,
    ) -> None:
        raise launch.AoxCutoverLaunchError(
            "aox_launch_sandbox_scientific_backend_failed",
            "missing backend",
        )

    probes = replace(
        baseline,
        sandbox_scientific_backend=reject_backend,
    )
    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.prepare_aox_cutover_launch(
            settings=settings,
            driver=driver,
            ledger_path=ledger,
            declared_identity=identity,
            declared_prerequisites=prerequisites,
            architecture_qualification_report=tmp_path / "qualification.json",
            repo_root=tmp_path,
            probes=probes,
        )

    assert error.value.code == "aox_launch_sandbox_scientific_backend_failed"


def test_clean_checkout_probe_rejects_tracked_or_untracked_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_git(_: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        if args == ("rev-parse", "--verify", "HEAD"):
            return "a" * 40
        return " M tracked.py\n?? untracked.txt"

    monkeypatch.setattr(launch, "_git", fake_git)

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch._probe_clean_checkout(tmp_path)

    assert error.value.code == "aox_launch_worktree_dirty"
    assert error.value.details == {"entry_count": 2}


def test_toolchain_pin_uses_production_ssh_commands_and_chains_hmmbuild(
    tmp_path: Path,
) -> None:
    server = _FakePinServer(tmp_path / "runner-outputs")

    digests = launch.attest_aox_toolchain_image_digests(
        server=server,
        repo_root=launch.REPO_ROOT,
        runner_contract_expectations=server.expectations,
    )

    assert [
        dict(dict(spec["metadata"])["tool_contract"])["tool_id"]
        for spec in server.calls
    ] == [
        "bio_tools.mafft",
        "bio_tools.cdhit",
        "bio_tools.hmmbuild",
        "bio_tools.hmmalign",
    ]
    hmmalign = server.calls[-1]
    hmmalign_inputs = list(hmmalign["inputs"])
    assert hmmalign_inputs[0]["remote_path"] == "model.hmm"
    assert hmmalign_inputs[0]["local_path"].endswith(
        "bio_tools/hmmbuild/model.hmm"
    )
    assert hmmalign_inputs[1]["remote_path"] == "input.fasta"
    assert server.resolved_artifact_refs
    assert all(
        artifact_ref.startswith("runner-artifact://")
        for artifact_ref in server.resolved_artifact_refs
    )
    assert digests == {
        "cdhit_4.8.1.hpc_apptainer_sif:v1": _digest("bio_tools.cdhit"),
        "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1": _digest("hmmer"),
        "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1": _digest("hmmer"),
        "mafft_7.525.hpc_apptainer_sif:v1": _digest("bio_tools.mafft"),
    }


def test_toolchain_pin_rejects_nonclosed_runtime_identity(tmp_path: Path) -> None:
    server = _FakePinServer(
        tmp_path / "runner-outputs",
        add_private_identity_field=True,
    )

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.attest_aox_toolchain_image_digests(
            server=server,
            repo_root=launch.REPO_ROOT,
            runner_contract_expectations=server.expectations,
        )

    assert error.value.code == "aox_launch_toolchain_pin_identity_missing"
    assert error.value.details == {"tool_id": "bio_tools.mafft"}


def test_toolchain_pin_rejects_unresolvable_runner_artifact_ref(
    tmp_path: Path,
) -> None:
    class UnresolvablePinServer(_FakePinServer):
        def resolve_artifact_ref(self, artifact_ref: str) -> str:
            del artifact_ref
            raise ValueError("private runner path must remain redacted")

    server = UnresolvablePinServer(tmp_path / "runner-outputs")

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.attest_aox_toolchain_image_digests(
            server=server,
            repo_root=launch.REPO_ROOT,
            runner_contract_expectations=server.expectations,
        )

    assert error.value.code == "aox_launch_toolchain_pin_output_invalid"
    assert error.value.details == {
        "tool_id": "bio_tools.mafft",
        "output_id": "bio_tools/mafft/alignment.fasta",
        "failure_type": "ValueError",
    }
    projected = json.dumps(error.value.details, sort_keys=True)
    assert "private runner path" not in projected


def test_toolchain_pin_redacts_runner_exception_details() -> None:
    class RaisingServer:
        def call_tool(
            self,
            name: str,
            arguments: dict[str, object] | None,
        ) -> dict[str, object]:
            del name, arguments
            raise RuntimeError("credential and /private/runner/path")

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.attest_aox_toolchain_image_digests(
            server=RaisingServer(),
            repo_root=launch.REPO_ROOT,
            runner_contract_expectations=_pin_runner_expectations(),
        )

    projected = json.dumps(
        {
            "message": str(error.value),
            "details": error.value.details,
        },
        sort_keys=True,
    )
    assert error.value.code == "aox_launch_toolchain_pin_execution_failed"
    assert "credential" not in projected
    assert "/private/" not in projected


def test_pin_rejects_ineligible_reliability_before_runner_attestation(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = replace(
        _settings(ledger_path=ledger, hpc_config_path=hpc_config),
        reliability=ReliabilityRefactorSettings(),
    )
    _stage_runner_contract_manifest(tmp_path)
    factory_calls = 0

    def runner_server_factory(_: str | Path | None) -> object:
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.pin_aox_cutover_launch(
            settings=settings,
            driver=launch.AoxCutoverDriverConfig(),
            ledger_path=ledger,
            architecture_qualification_report=tmp_path / "qualification.json",
            repo_root=tmp_path,
            probes=_probes(),
            runner_server_factory=runner_server_factory,
        )

    assert error.value.code == "aox_launch_effective_config_schema_invalid"
    assert error.value.details == {
        "identity": (
            "effective_config.reliability.controlled_operation_owner_policy"
        )
    }
    assert factory_calls == 0


def test_pin_launch_self_validates_generated_identity_and_prerequisites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    settings = _settings(ledger_path=ledger, hpc_config_path=hpc_config)
    driver = launch.AoxCutoverDriverConfig()
    probes = _probes()
    _stage_runner_contract_manifest(tmp_path)
    effective = launch.build_aox_cutover_effective_config(
        settings,
        driver=driver,
        ledger_path=ledger,
        repo_root=tmp_path,
        source_tree_digest=probes.source_tree_digest,
    )
    expected_identity = launch._resolve_actual_identity(
        repo_root=tmp_path,
        config_digest=effective.digest,
        probes=probes,
    )
    toolchain_digests = {
        key: _digest("hmmer" if "hmmer" in key else key)
        for key in launch.TOOLCHAIN_IDS
    }
    expected_prerequisites = launch.build_aox_cutover_allowed_prerequisites(
        identity=expected_identity,
        settings=effective.settings,
        toolchain_image_digests=toolchain_digests,
    )
    captured: dict[str, object] = {}
    real_prepare = launch.prepare_aox_cutover_launch

    def fake_attest(**kwargs: object) -> dict[str, str]:
        captured["attest"] = kwargs
        return toolchain_digests

    def recording_prepare(**kwargs: object) -> launch.AoxCutoverLaunchSnapshot:
        captured["prepare"] = kwargs
        return real_prepare(**kwargs)

    monkeypatch.setattr(launch, "attest_aox_toolchain_image_digests", fake_attest)
    monkeypatch.setattr(launch, "prepare_aox_cutover_launch", recording_prepare)

    snapshot = launch.pin_aox_cutover_launch(
        settings=settings,
        driver=driver,
        ledger_path=ledger,
        architecture_qualification_report=tmp_path / "qualification.json",
        repo_root=tmp_path,
        probes=probes,
        runner_server_factory=lambda _: object(),
    )

    assert captured["prepare"]["declared_identity"] == expected_identity
    assert captured["prepare"]["declared_prerequisites"] == expected_prerequisites
    assert snapshot.identity == expected_identity
    assert snapshot.allowed_prerequisites == expected_prerequisites
    assert snapshot.architecture_qualification == _architecture_qualification()
