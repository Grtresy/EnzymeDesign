from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

import openzyme_host_api.aox_config_contract as config_contract
from openzyme_host_api.aox_config_contract import AoxConfigContractError
from openzyme_host_api.aox_config_contract import aox_config_contract
from openzyme_host_api.aox_config_contract import build_aox_config_candidate
from openzyme_host_api.aox_config_contract import publish_aox_config_candidate
from openzyme_host_api.aox_config_contract import require_current_aox_config_candidate


def test_config_contract_projects_credential_presence_without_credential_values(
    tmp_path: Path,
) -> None:
    runner_config = tmp_path / "runner.toml"
    runner_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "ledger.sqlite3"
    first = build_aox_config_candidate(
        ledger_path=ledger,
        environ={
            "OPENZYME_LLM_API_KEY": "private-key-one",
            "OPENZYME_HPC_RUNNER_CONFIG": str(runner_config),
        },
    )
    second = build_aox_config_candidate(
        ledger_path=ledger,
        environ={
            "OPENZYME_LLM_API_KEY": "private-key-two",
            "OPENZYME_HPC_RUNNER_CONFIG": str(runner_config),
        },
    )

    assert first["schema_id"] == "aox_config_candidate@1"
    assert first["contract_digest"] == aox_config_contract()["contract_digest"]
    assert first == second
    without_credential = build_aox_config_candidate(
        ledger_path=ledger,
        environ={"OPENZYME_HPC_RUNNER_CONFIG": str(runner_config)},
    )
    assert first["candidate_id"] != without_credential["candidate_id"]
    encoded = json.dumps(
        {"candidate": first, "contract": aox_config_contract()},
        sort_keys=True,
    )
    assert "private-key" not in encoded
    assert str(tmp_path) not in encoded
    assert str(Path.cwd()) not in encoded


def test_config_candidate_ignores_unlisted_environment_and_binds_relevant_values(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.sqlite3"
    base = build_aox_config_candidate(
        ledger_path=ledger,
        environ={"OPENZYME_TEST_ENABLE_LIVE_E2E": "0"},
    )
    unrelated = build_aox_config_candidate(
        ledger_path=ledger,
        environ={
            "OPENZYME_TEST_ENABLE_LIVE_E2E": "0",
            "OPENZYME_HOST_BASE_URL": "https://thin-client-only.example.test",
            "OPENZYME_UNLISTED_PROFILE_HINT": "ignored",
            "UNRELATED_SECRET": "also-ignored",
        },
    )
    relevant = build_aox_config_candidate(
        ledger_path=ledger,
        environ={"OPENZYME_TEST_ENABLE_LIVE_E2E": "1"},
    )

    assert unrelated == base
    assert relevant["candidate_id"] != base["candidate_id"]


def test_config_candidate_binds_invalid_relevant_input_and_path_content(
    tmp_path: Path,
) -> None:
    runner_config = tmp_path / "runner.toml"
    runner_config.write_text("revision=1\n", encoding="utf-8")
    ledger = tmp_path / "ledger.sqlite3"
    invalid_one = build_aox_config_candidate(
        ledger_path=ledger,
        environ={
            "OPENZYME_HPC_RUNNER_CONFIG": str(runner_config),
            "OPENZYME_LLM_CONTEXT_WINDOW_TOKENS": "invalid-one",
        },
    )
    invalid_two = build_aox_config_candidate(
        ledger_path=ledger,
        environ={
            "OPENZYME_HPC_RUNNER_CONFIG": str(runner_config),
            "OPENZYME_LLM_CONTEXT_WINDOW_TOKENS": "invalid-two",
        },
    )
    runner_config.write_text("revision=2\n", encoding="utf-8")
    changed_path_content = build_aox_config_candidate(
        ledger_path=ledger,
        environ={
            "OPENZYME_HPC_RUNNER_CONFIG": str(runner_config),
            "OPENZYME_LLM_CONTEXT_WINDOW_TOKENS": "invalid-two",
        },
    )

    assert invalid_one["profile_source_digest"] != invalid_two["profile_source_digest"]
    assert (
        invalid_two["runner_config_identity_digest"]
        != changed_path_content["runner_config_identity_digest"]
    )
    assert invalid_two["candidate_id"] != changed_path_content["candidate_id"]


def test_config_contract_exposes_canonical_field_and_aox_requirement_mapping() -> None:
    contract = aox_config_contract()
    fields = {field["setting_path"]: field for field in contract["profile_fields"]}

    assert fields["llm.api_key"]["environment_names"] == [
        "OPENZYME_LLM_API_KEY",
        "MICU_API_KEY",
    ]
    assert fields["llm.api_key"]["value_kind"] == "credential"
    assert fields["llm.api_key"]["safe_generic_default"] is None
    assert fields["llm.api_key"]["candidate_identity"] is True
    assert fields["llm.api_key"]["aox_eligibility"]["requirements"] == [
        {"kind": "credential_presence", "present": True}
    ]
    assert fields["execution.backend"]["aox_eligibility"]["requirements"] == [
        {"kind": "exact_value", "value": "hpc"}
    ]
    route_requirements = fields["reliability.durable_execution_route_allowlist"][
        "aox_eligibility"
    ]["requirements"]
    assert route_requirements[0] == {"kind": "sorted_unique_string_list"}
    assert route_requirements[1]["kind"] == "contains_all"
    assert contract["profile_source_projection"]["credential_values"] == (
        "presence_only"
    )
    assert contract["profile_source_projection"]["unlisted_environment"] == ("ignored")
    assert fields["host_cli.base_url"]["candidate_identity"] is False


def test_config_contract_rejects_missing_canonical_profile_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = config_contract.openzyme_settings_environment_contract()
    monkeypatch.setattr(
        config_contract,
        "openzyme_settings_environment_contract",
        lambda: [
            field for field in canonical if field["setting_path"] != "execution.backend"
        ],
    )

    with pytest.raises(AoxConfigContractError) as error:
        aox_config_contract()

    assert error.value.code == "aox_config_contract_source_drift"


def test_config_contract_rejects_constraint_projection_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = config_contract.aox_environment_profile_requirements()
    drifted = json.loads(json.dumps(canonical))
    drifted["execution.backend"]["requirements"][0]["value"] = "disabled"
    monkeypatch.setattr(
        config_contract,
        "aox_environment_profile_requirements",
        lambda: drifted,
    )

    with pytest.raises(AoxConfigContractError) as error:
        aox_config_contract()

    assert error.value.code == "aox_config_contract_source_drift"


def test_config_candidate_publication_is_atomic_no_replace(tmp_path: Path) -> None:
    target = tmp_path / "candidate.json"
    candidate = build_aox_config_candidate(
        ledger_path=tmp_path / "ledger.sqlite3",
        environ={"OPENZYME_TEST_ENABLE_LIVE_E2E": "1"},
    )

    assert publish_aox_config_candidate(target, candidate) == target
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(target.read_text(encoding="utf-8")) == candidate
    assert not list(tmp_path.glob(".openzyme-aox-config-*.tmp"))
    with pytest.raises(AoxConfigContractError) as error:
        publish_aox_config_candidate(target, candidate)
    assert error.value.code == "aox_config_candidate_output_exists"
    assert not list(tmp_path.glob(".openzyme-aox-config-*.tmp"))


@pytest.mark.parametrize(
    ("failures", "expected_code"),
    (
        (1, "aox_config_candidate_output_write_failed"),
        (2, "aox_config_candidate_publication_in_doubt"),
    ),
)
def test_config_candidate_publication_reports_cleanup_certainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
    expected_code: str,
) -> None:
    target = tmp_path / "candidate.json"
    candidate = build_aox_config_candidate(
        ledger_path=tmp_path / "ledger.sqlite3",
        environ={},
    )
    calls = 0

    def fail_directory_sync(path: Path) -> None:
        nonlocal calls
        del path
        calls += 1
        if calls <= failures:
            raise OSError("simulated directory sync failure")

    monkeypatch.setattr(config_contract, "_fsync_directory", fail_directory_sync)

    with pytest.raises(AoxConfigContractError) as error:
        publish_aox_config_candidate(target, candidate)
    assert error.value.code == expected_code
    assert not target.exists()
    assert not list(tmp_path.glob(".openzyme-aox-config-*.tmp"))


def test_config_candidate_rejects_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_E2E", "0")
    candidate = build_aox_config_candidate(ledger_path=tmp_path / "ledger.sqlite3")
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_E2E", "1")

    with pytest.raises(AoxConfigContractError) as error:
        require_current_aox_config_candidate(
            candidate,
            ledger_path=tmp_path / "ledger.sqlite3",
        )

    assert error.value.code == "aox_config_candidate_source_drift"
