from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_hpc_runner.contract_manifest import (
    ContractManifestError,
    build_discovery_runspec,
    build_smoke_runspec,
    load_contract_manifest,
    sanitize_record,
    validate_contract_manifest,
    write_contract_record,
)
from mcp_hpc_runner.validation import validate_runspec


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_contract_manifest_loads_and_covers_configured_and_documented_tools() -> None:
    contracts = load_contract_manifest()
    tool_ids = {contract.tool_id for contract in contracts}

    assert {"alphafold3", "chai_fold", "colabfold", "fpocket", "vina"}.issubset(
        tool_ids
    )
    assert {"hhblits", "p2rank", "caverdock"}.issubset(tool_ids)

    smoke = {
        contract.tool_id
        for contract in contracts
        if contract.support_status == "smoke_runnable"
    }
    assert smoke == {
        "bio_tools.cdhit",
        "bio_tools.hmmalign",
        "bio_tools.hmmbuild",
        "bio_tools.mafft",
        "fpocket",
        "vina",
    }


def test_contract_manifest_rejects_duplicate_tool_ids() -> None:
    payload = {
        "schema_version": 1,
        "tools": [
            {
                "tool_id": "fpocket",
                "stage": "evaluator",
                "deployment_mode": "sif",
                "entrypoint": {"kind": "sif", "path": "~/containers/fpocket.sif"},
                "resource_profile": {
                    "cpus": 1,
                    "mem_mb": 1024,
                    "gpus": 0,
                    "time_minutes": 5,
                },
                "required_inputs": [],
                "optional_params": [],
                "expected_outputs": [],
                "success_checks": [],
                "known_failure_signatures": [],
                "support_status": "entrypoint_only",
                "executor_relevance": "discovery_only",
            },
            {
                "tool_id": "fpocket",
                "stage": "evaluator",
                "deployment_mode": "sif",
                "entrypoint": {"kind": "sif", "path": "~/containers/fpocket.sif"},
                "resource_profile": {
                    "cpus": 1,
                    "mem_mb": 1024,
                    "gpus": 0,
                    "time_minutes": 5,
                },
                "required_inputs": [],
                "optional_params": [],
                "expected_outputs": [],
                "success_checks": [],
                "known_failure_signatures": [],
                "support_status": "entrypoint_only",
                "executor_relevance": "discovery_only",
            },
        ],
    }

    with pytest.raises(ContractManifestError, match="duplicate tool_id"):
        validate_contract_manifest(payload)


@pytest.mark.parametrize(
    "tool_id",
    [
        "fpocket",
        "vina",
        "bio_tools.cdhit",
        "bio_tools.mafft",
        "bio_tools.hmmbuild",
        "bio_tools.hmmalign",
    ],
)
def test_smoke_runspec_generation_is_valid(tool_id: str) -> None:
    contract = next(
        contract for contract in load_contract_manifest() if contract.tool_id == tool_id
    )
    spec = build_smoke_runspec(
        contract,
        _project_root() / "fixtures" / "hpc_tool_samples",
        partition="cpu",
    )

    assert validate_runspec(spec) == []
    assert spec.metadata["tool_contract"]["tool_id"] == tool_id
    assert spec.metadata["tool_contract"]["preflight_hints"]["entrypoint"]["kind"] == "sif"
    assert spec.expected_outputs


def test_discovery_runspec_generation_is_valid_for_each_contract() -> None:
    for contract in load_contract_manifest():
        spec = build_discovery_runspec(contract)
        assert validate_runspec(spec) == []
        assert spec.execution_mode == "ssh"
        assert spec.metadata["tool_contract"]["phase"] == "discovery"


def test_contract_record_sanitizer_redacts_paths_and_sensitive_values(tmp_path: Path) -> None:
    raw = json.loads(
        (_project_root() / "tests" / "fixtures" / "contract_record_raw.json").read_text(
            encoding="utf-8"
        )
    )

    sanitized = sanitize_record(raw)
    rendered = json.dumps(sanitized, sort_keys=True)
    assert "/home/user" not in rendered
    assert "user@example.org" not in rendered
    assert "should-not-survive" not in rendered
    assert "<REDACTED>" in rendered

    path = write_contract_record(tmp_path, "fpocket", raw)
    persisted = path.read_text(encoding="utf-8")
    assert "/home/user" not in persisted
    assert "user@example.org" not in persisted
