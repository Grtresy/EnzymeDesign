from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from openzyme_host_api import aox_cutover_launch as launch
from openzyme_pipeline import aox_motif
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import ControlledOperationOwnerPolicy
from openzyme_runtime import HostApiSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import LiveLlmTestSettings
from openzyme_runtime import LlmSettings
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import MutationClosureMode
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import ResearchSettings
from openzyme_runtime import TestSettings as RuntimeTestSettings
from openzyme_runtime import TracingSettings
from openzyme_runtime import V3BackgroundRuntimeSettings


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _settings(*, ledger_path: Path, hpc_config_path: Path) -> OpenZymeSettings:
    return OpenZymeSettings(
        llm=LlmSettings(
            api_key="test-key",
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
            purpose_policies={},
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


def _effective(tmp_path: Path) -> launch.AoxCutoverEffectiveConfig:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("[cluster]\nssh_target='test-host'\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"
    return launch.build_aox_cutover_effective_config(
        _settings(ledger_path=ledger, hpc_config_path=hpc_config),
        ledger_path=ledger,
    )


def test_effective_config_is_deterministic_policy_free_world_v5(tmp_path: Path) -> None:
    first = _effective(tmp_path)
    second = _effective(tmp_path)

    assert first.digest == second.digest
    assert first.payload == second.payload
    assert first.payload["schema_id"] == "aox_blank_world_runtime_config@5"
    assert "driver" not in first.payload
    assert "conductor" not in first.payload
    assert first.payload["host"]["background_runtime_enabled"] is False
    assert first.settings.llm.max_tokens == 1_024
    assert first.settings.llm.timeout == 45.0


def test_effective_config_is_public_and_does_not_embed_local_paths(tmp_path: Path) -> None:
    effective = _effective(tmp_path)
    encoded = json.dumps(effective.payload, sort_keys=True)

    assert str(tmp_path) not in encoded
    assert "test-key" not in encoded
    assert "test-host" not in encoded
    assert effective.payload["scientific_workflow_contract"] == {
        "schema_id": launch.AOX_SELECTED_CHAIN_CONTRACT_V2.schema_id,
        "contract_id": launch.AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,
        "workflow_id": launch.AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "workflow_contract_digest": launch.AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
    }


@pytest.mark.parametrize("field", ("conductor", "driver", "automatic_rollover"))
def test_effective_config_rejects_runtime_policy_shadow_truth(
    tmp_path: Path,
    field: str,
) -> None:
    payload = json.loads(json.dumps(_effective(tmp_path).payload))
    payload[field] = {}

    with pytest.raises(launch.AoxRuntimeConfigSchemaError) as error:
        launch.normalize_aox_blank_world_runtime_config(
            payload,
            expected_runner_contracts=launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
        )

    assert error.value.path == "effective_config"


def test_effective_config_rejects_historical_driver_crossgrade(tmp_path: Path) -> None:
    payload = json.loads(json.dumps(_effective(tmp_path).payload))
    payload["schema_id"] = "aox_blank_world_runtime_config@3"
    payload["driver"] = {}

    with pytest.raises(launch.AoxRuntimeConfigSchemaError):
        launch.normalize_aox_blank_world_runtime_config(
            payload,
            expected_runner_contracts=launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
        )


def test_effective_config_v4_remains_explicit_read_only_compatible(
    tmp_path: Path,
) -> None:
    payload = json.loads(json.dumps(_effective(tmp_path).payload))
    payload["schema_id"] = "aox_blank_world_runtime_config@4"
    payload["conductor"] = {
        "scenario": "aox_blank_world_cutover",
        "orchestration_owner": "codex_tester",
        "public_command_surface": "host_api_cli_v3",
        "receipt_chain_schema_id": "openzyme_public_api_receipt_chain@1",
        "supervised_host_schema_id": "aox_supervised_host_receipt@1",
        "automatic_runtime_drain": False,
        "automatic_approval": False,
        "automatic_rollover": False,
        "micu_hard_limit_tokens": 500_000_000,
        "micu_ledger_identity_digest": "sha256:" + "1" * 64,
    }

    normalized = launch.normalize_aox_blank_world_runtime_config(
        payload,
        expected_runner_contracts=launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
    )

    assert normalized == payload
    payload["schema_id"] = "aox_blank_world_runtime_config@5"
    with pytest.raises(launch.AoxRuntimeConfigSchemaError):
        launch.normalize_aox_blank_world_runtime_config(
            payload,
            expected_runner_contracts=launch.AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
        )


def test_authority_wall_time_owns_long_operation_hierarchy() -> None:
    assert launch.validate_aox_authority_wall_time(7_200) == 7_200.0

    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.validate_aox_authority_wall_time(7_199)

    assert error.value.code == "aox_authority_wall_time_invalid"
    assert error.value.details == {}


def test_identity_and_prerequisite_schemas_remain_exact(tmp_path: Path) -> None:
    effective = _effective(tmp_path)
    identity = {
        "git_commit": "a" * 40,
        "config_digest": effective.digest,
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    normalized = launch.validate_aox_cutover_identity(identity)
    prerequisites = launch.build_aox_cutover_allowed_prerequisites(
        identity=normalized,
        settings=effective.settings,
        toolchain_image_digests={
            toolchain_id: (
                _digest("hmmer")
                if toolchain_id
                in {launch.HMMALIGN_TOOLCHAIN_ID, launch.HMMBUILD_TOOLCHAIN_ID}
                else _digest(toolchain_id)
            )
            for toolchain_id in launch.TOOLCHAIN_IDS
        },
    )

    assert launch.validate_aox_cutover_allowed_prerequisites(
        prerequisites,
        identity=normalized,
    ) == prerequisites
    with pytest.raises(launch.AoxCutoverLaunchError) as error:
        launch.validate_aox_cutover_identity({**identity, "driver": "retired"})
    assert error.value.code == "aox_launch_identity_schema_invalid"


def test_effective_config_maps_closed_schema_failure_to_launch_error(
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
        launch.build_aox_cutover_effective_config(settings, ledger_path=ledger)

    assert error.value.code == "aox_launch_effective_config_schema_invalid"
    assert error.value.details == {"identity": "effective_config.llm"}
    assert error.value.public_details == {"identity": "effective_config.llm"}


def test_effective_config_uses_canonical_host_mcp_capability(
    tmp_path: Path,
) -> None:
    hpc_config = tmp_path / "hpc.toml"
    hpc_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "micu.sqlite3"

    effective = launch.build_aox_cutover_effective_config(
        _settings(ledger_path=ledger, hpc_config_path=hpc_config),
        ledger_path=ledger,
    )

    research = effective.payload["research"]
    assert isinstance(research, dict)
    assert research["mcp_enabled"] is True
