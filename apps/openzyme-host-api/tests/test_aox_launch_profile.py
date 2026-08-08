from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from openzyme_host_api.aox_cutover_launch import AoxCutoverLaunchError
from openzyme_host_api.aox_cutover_runtime_config import (
    AOX_DURABLE_ROUTE_POLICY_IDS,
)
from openzyme_host_api.aox_launch_profile import (
    build_aox_cutover_launch_profile,
    launch_profile_digest,
    normalize_aox_cutover_launch_profile,
    resolve_aox_cutover_launch_profile,
)
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime.reliability import ControlledOperationOwnerPolicy
from openzyme_runtime.reliability import MutationClosureMode
from openzyme_runtime.reliability import RuntimeDrainContract


def _settings() -> OpenZymeSettings:
    settings = OpenZymeSettings.from_env()
    return replace(
        settings,
        reliability=replace(
            settings.reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
            durable_execution_route_allowlist=tuple(
                sorted(AOX_DURABLE_ROUTE_POLICY_IDS)
            ),
            runtime_drain_contract=RuntimeDrainContract.COMMAND_V1,
            mutation_closure_mode=MutationClosureMode.GENERIC_V1,
        ),
    )


def _profile(
    *,
    settings: OpenZymeSettings | None = None,
) -> dict[str, object]:
    return build_aox_cutover_launch_profile(
        settings=settings or _settings(),
        ledger_path=Path("/tmp/aox-launch-profile-ledger.json"),
        source_commit="a" * 40,
        config_digest="sha256:" + "b" * 64,
        created_at="2026-08-08T00:00:00+00:00",
    )


def test_launch_profile_restores_non_sensitive_settings_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = {
        "OPENZYME_LLM_API_KEY": "llm-secret-for-profile-test",
        "TAVILY_API_KEY": "tavily-secret-for-profile-test",
        "OPENZYME_NCBI_EMAIL": "private-profile-test@example.test",
        "OPENZYME_NCBI_API_KEY": "ncbi-secret-for-profile-test",
        "SEMANTIC_SCHOLAR_API_KEY": "semantic-secret-for-profile-test",
        "OPENZYME_HOST_AUTH_TOKEN": "host-secret-for-profile-test",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENZYME_HOST_AUTH_PRINCIPALS_JSON", raising=False)
    settings = _settings()
    profile = _profile(settings=settings)
    serialized = json.dumps(profile, sort_keys=True)

    assert profile["schema_id"] == "aox_cutover_launch_profile@1"
    assert launch_profile_digest(profile) == profile["profile_digest"]
    assert all(secret not in serialized for secret in secrets.values())
    assert "api_key" not in serialized
    assert "auth_token" not in serialized
    assert "principals" not in serialized

    monkeypatch.setenv(
        "OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY",
        "legacy_only_v1",
    )
    original_tool = "ambient-tool-must-not-be-mutated"
    monkeypatch.setenv("OPENZYME_NCBI_TOOL", original_tool)
    resolved, ledger_path = resolve_aox_cutover_launch_profile(profile)

    assert resolved.reliability == settings.reliability
    assert resolved.llm.api_key == secrets["OPENZYME_LLM_API_KEY"]
    assert resolved.research.pubmed_email == secrets["OPENZYME_NCBI_EMAIL"]
    assert resolved.research.pubmed_api_key == secrets["OPENZYME_NCBI_API_KEY"]
    assert resolved.host_api.principals == ()
    assert ledger_path == Path("/tmp/aox-launch-profile-ledger.json")
    assert json.loads(json.dumps(profile)) == profile
    assert os.environ["OPENZYME_NCBI_TOOL"] == original_tool

    resolve_aox_cutover_launch_profile(
        profile,
        install_provider_environment=True,
    )
    assert os.environ["OPENZYME_NCBI_TOOL"] == settings.research.pubmed_tool


def test_launch_profile_rejects_legacy_owner_secret_urls_and_digest_drift() -> None:
    legacy = replace(
        _settings(),
        reliability=replace(
            _settings().reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.LEGACY_ONLY_V1
            ),
        ),
    )
    with pytest.raises(AoxCutoverLaunchError) as owner:
        _profile(settings=legacy)
    assert owner.value.code == "aox_launch_profile_owner_policy_invalid"

    secret_url = replace(
        _settings(),
        llm=replace(
            _settings().llm,
            base_url="https://operator:secret@example.test/v1",
        ),
    )
    with pytest.raises(AoxCutoverLaunchError) as secret:
        _profile(settings=secret_url)
    assert secret.value.code == "aox_launch_profile_secret_forbidden"

    query_secret_url = replace(
        _settings(),
        llm=replace(
            _settings().llm,
            base_url="https://example.test/v1?api_key=secret",
        ),
    )
    with pytest.raises(AoxCutoverLaunchError) as query_secret:
        _profile(settings=query_secret_url)
    assert query_secret.value.code == "aox_launch_profile_secret_forbidden"

    fragment_secret_url = replace(
        _settings(),
        host_cli=replace(
            _settings().host_cli,
            base_url="http://127.0.0.1:8000/#token=secret",
        ),
    )
    with pytest.raises(AoxCutoverLaunchError) as fragment_secret:
        _profile(settings=fragment_secret_url)
    assert fragment_secret.value.code == "aox_launch_profile_secret_forbidden"

    tampered = deepcopy(_profile())
    tampered["settings"]["host_api"]["bind_port"] += 1
    with pytest.raises(AoxCutoverLaunchError) as digest:
        normalize_aox_cutover_launch_profile(tampered)
    assert digest.value.code == "aox_launch_profile_digest_mismatch"


def test_launch_profile_rejects_ambient_credential_extension_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENZYME_LLM_EXTRA_BODY", raising=False)
    settings = _settings()
    settings = replace(
        settings,
        llm=replace(settings.llm, extra_body={"provider": "bigmodel"}),
    )
    profile = _profile(settings=settings)
    monkeypatch.setenv(
        "OPENZYME_LLM_EXTRA_BODY",
        json.dumps({"provider": "different-provider"}),
    )

    with pytest.raises(AoxCutoverLaunchError) as error:
        resolve_aox_cutover_launch_profile(profile)

    assert error.value.code == "aox_launch_profile_ambient_conflict"
