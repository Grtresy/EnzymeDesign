from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationBoundaryError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationManifestError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationRegistryError,
)
from openzyme_host_api.architecture_qualification import CollectedQualificationScenario
from openzyme_host_api.architecture_qualification import PROFILE_ID
from openzyme_host_api.architecture_qualification import REGISTRY_ID
from openzyme_host_api.architecture_qualification import REGISTRY_SCHEMA_ID
from openzyme_host_api.architecture_qualification import REQUIRED_FAMILIES
from openzyme_host_api.architecture_qualification import REQUIRED_P0_TRIGGERS
from openzyme_host_api.architecture_qualification import build_test_manifest
from openzyme_host_api.architecture_qualification import canonical_json_document_bytes
from openzyme_host_api.architecture_qualification import load_invariant_registry
from openzyme_host_api.architecture_qualification import resolve_boundary_relation
from openzyme_host_api.architecture_qualification import (
    validate_invariant_registry_bytes,
)
from openzyme_host_api.harness_owner_constraints import (
    OWNER_CONSTRAINT_REGISTRY_ID,
)
from openzyme_host_api.harness_owner_constraints import (
    OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH,
)
from openzyme_host_api.harness_owner_constraints import (
    OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID,
)
from openzyme_host_api.harness_owner_constraints import (
    load_harness_owner_constraint_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SOURCE_FILE = (
    "apps/openzyme-host-api/tests/architecture_qualification/test_registry.py"
)
CONTRACT_FILE = (
    "openspec/changes/establish-v3-executable-architecture-qualification/"
    "specs/executable-architecture-qualification/spec.md"
)
IMPLEMENTATION_FILE = (
    "apps/openzyme-host-api/src/openzyme_host_api/architecture_qualification.py"
)


def _valid_registry() -> dict[str, object]:
    owner_registry = load_harness_owner_constraint_registry(REPO_ROOT)
    invariants: list[dict[str, object]] = []
    scenarios: list[dict[str, object]] = []
    for family in REQUIRED_FAMILIES:
        invariant_id = f"{family}.contract"
        scenario_id = f"{family}.baseline"
        invariants.append(
            {
                "contract_refs": [CONTRACT_FILE],
                "failure_class": "integrity",
                "family": family,
                "invariant_id": invariant_id,
                "owner_boundary": "host.production-composition",
                "p0_trigger_ids": ["admission-bypass"],
                "profile_ids": [PROFILE_ID],
                "scenario_ids": [scenario_id],
                "title": f"Closed fixture for {family}",
            }
        )
        scenarios.append(
            {
                "boundary_ids": (
                    ["sandbox-control-frame-bytes"]
                    if family == "boundary-scale"
                    else []
                ),
                "budgets": {
                    "deadline_seconds": 1,
                    "max_effect_count": 0,
                    "max_event_delta": 1,
                    "max_state_version_delta": 1,
                    "max_steps": 1,
                    "max_ticks": 1,
                },
                "external_port_ids": [],
                "family": family,
                "fault_points": [],
                "provenance_refs": [],
                "scenario_id": scenario_id,
                "selections": ["full"],
                "source_files": [SOURCE_FILE],
                "test_selector": (
                    f"{SOURCE_FILE}::test_scenario[{family}]"
                ),
            }
        )
    return {
        "boundary_relations": [
            {
                "boundary_id": "sandbox-control-frame-bytes",
                "owner": {
                    "module": "openzyme_core.sandbox_runtime",
                    "source_file": (
                        "packages/openzyme-core/src/openzyme_core/sandbox_runtime.py"
                    ),
                    "symbol": "CONTROL_SOCKET_FRAME_MAX_BYTES",
                },
                "seams": [
                    {
                        "module": "openzyme_pipeline.client",
                        "relation": "equal",
                        "source_file": (
                            "packages/openzyme-pipeline/src/openzyme_pipeline/client.py"
                        ),
                        "symbol": "CONTROL_SOCKET_FRAME_MAX_BYTES",
                    }
                ],
            }
        ],
        "external_ports": [
            {
                "effect_ledger_required": True,
                "port_id": "llm.chat",
                "production_seams": ["openzyme_runtime.RuntimeFoundation.model_factory"],
                "qualification_mode": "controlled_adapter",
            }
        ],
        "implementation_files": [IMPLEMENTATION_FILE],
        "invariants": invariants,
        "owner_constraint_registry": {
            "content_digest": owner_registry.registry_digest,
            "path": OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH.as_posix(),
            "registry_id": OWNER_CONSTRAINT_REGISTRY_ID,
            "schema_id": OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID,
        },
        "p0_triggers": [
            {"description": trigger_id, "trigger_id": trigger_id}
            for trigger_id in REQUIRED_P0_TRIGGERS
        ],
        "profile": {
            "claims": ["trusted local Host qualification"],
            "database_mode": "file_sqlite",
            "excludes": ["distributed writer qualification"],
            "process_model": "single_process",
            "profile_id": PROFILE_ID,
            "trust_boundary": "trusted_host",
        },
        "registry_id": REGISTRY_ID,
        "required_families": list(REQUIRED_FAMILIES),
        "required_scenario_ids": [
            f"{family}.baseline" for family in REQUIRED_FAMILIES
        ],
        "scenarios": scenarios,
        "schema_id": REGISTRY_SCHEMA_ID,
    }


def _validate(payload: object):
    return validate_invariant_registry_bytes(
        canonical_json_document_bytes(payload),
        repo_root=REPO_ROOT,
    )


def test_registry_accepts_canonical_closed_document() -> None:
    content = canonical_json_document_bytes(_valid_registry())

    validated = validate_invariant_registry_bytes(content, repo_root=REPO_ROOT)

    assert validated.registry_digest == (
        f"sha256:{hashlib.sha256(content).hexdigest()}"
    )
    assert tuple(validated.payload["required_families"]) == REQUIRED_FAMILIES


def test_scripted_aox_reachability_alone_cannot_close_current_admission() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    scenarios = {
        str(item["scenario_id"]): item
        for item in registry.payload["scenarios"]
    }

    scripted_id = "evidence-projection.aox-run-class-disjoint-closure"
    transformation_ids = {
        "strategy-neutrality.public-action-permutations",
        "world-fidelity.earliest-cause-visible",
    }
    assert scripted_id in scenarios
    required_scenario_ids = registry.payload["required_scenario_ids"]
    assert isinstance(required_scenario_ids, list)
    assert transformation_ids <= set(required_scenario_ids)
    assert all(
        scenarios[scenario_id]["selections"] == ["full", "premerge_subset"]
        for scenario_id in transformation_ids
    )
    assert {
        str(scenarios[scenario_id]["family"])
        for scenario_id in transformation_ids
    } == {"strategy-neutrality", "world-fidelity"}


@pytest.mark.parametrize(
    "content",
    [
        b'{"schema_id":"one","schema_id":"two"}\n',
        b'{"schema_id":NaN}\n',
        b"\xff\n",
    ],
)
def test_registry_rejects_duplicate_nonfinite_and_non_utf8_bytes(
    content: bytes,
) -> None:
    with pytest.raises(ArchitectureQualificationRegistryError) as error:
        validate_invariant_registry_bytes(content, repo_root=REPO_ROOT)

    assert error.value.code == "architecture_qualification_registry_invalid"


def test_registry_rejects_noncanonical_or_open_top_level_bytes() -> None:
    payload = _valid_registry()
    content_without_lf = canonical_json_document_bytes(payload).removesuffix(b"\n")
    with pytest.raises(ArchitectureQualificationRegistryError, match="canonical JSON"):
        validate_invariant_registry_bytes(content_without_lf, repo_root=REPO_ROOT)

    payload["unknown"] = True
    with pytest.raises(ArchitectureQualificationRegistryError, match="not closed"):
        _validate(payload)


def test_registry_rejects_unknown_profile_and_unreadable_source() -> None:
    payload = _valid_registry()
    profile = payload["profile"]
    assert isinstance(profile, dict)
    profile["profile_id"] = "distributed@1"
    with pytest.raises(ArchitectureQualificationRegistryError, match="profile_id"):
        _validate(payload)

    payload = _valid_registry()
    implementation_files = payload["implementation_files"]
    assert isinstance(implementation_files, list)
    implementation_files.append("missing/qualification.py")
    with pytest.raises(ArchitectureQualificationRegistryError, match="does not resolve"):
        _validate(payload)


def test_registry_rejects_missing_and_orphan_scenario_closure() -> None:
    payload = _valid_registry()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenarios.pop()
    with pytest.raises(ArchitectureQualificationRegistryError, match="scenario set"):
        _validate(payload)

    payload = _valid_registry()
    scenarios = payload["scenarios"]
    required = payload["required_scenario_ids"]
    assert isinstance(scenarios, list)
    assert isinstance(required, list)
    orphan = deepcopy(scenarios[0])
    assert isinstance(orphan, dict)
    orphan["scenario_id"] = "authority-composition.orphan"
    scenarios.insert(1, orphan)
    required.insert(1, "authority-composition.orphan")
    with pytest.raises(ArchitectureQualificationRegistryError, match="orphan"):
        _validate(payload)


def test_registry_rejects_duplicate_invariant_and_scenario_ids() -> None:
    for record_key in ("invariants", "scenarios"):
        payload = _valid_registry()
        records = payload[record_key]
        assert isinstance(records, list)
        records.insert(1, deepcopy(records[0]))
        with pytest.raises(ArchitectureQualificationRegistryError, match="duplicate id"):
            _validate(payload)


def test_registry_rejects_family_port_boundary_and_trigger_drift() -> None:
    mutations = []

    missing_family = _valid_registry()
    invariants = missing_family["invariants"]
    assert isinstance(invariants, list)
    invariants.pop()
    mutations.append(missing_family)

    unknown_port = _valid_registry()
    scenarios = unknown_port["scenarios"]
    assert isinstance(scenarios, list)
    assert isinstance(scenarios[0], dict)
    scenarios[0]["external_port_ids"] = ["runner.unknown"]
    mutations.append(unknown_port)

    unknown_boundary = _valid_registry()
    scenarios = unknown_boundary["scenarios"]
    assert isinstance(scenarios, list)
    assert isinstance(scenarios[0], dict)
    scenarios[0]["boundary_ids"] = ["missing-boundary"]
    mutations.append(unknown_boundary)

    unknown_trigger = _valid_registry()
    invariants = unknown_trigger["invariants"]
    assert isinstance(invariants, list)
    assert isinstance(invariants[0], dict)
    invariants[0]["p0_trigger_ids"] = ["manual-waiver"]
    mutations.append(unknown_trigger)

    for payload in mutations:
        with pytest.raises(ArchitectureQualificationRegistryError):
            _validate(payload)


def _collected_scenarios(
    payload: dict[str, object],
) -> list[CollectedQualificationScenario]:
    raw_scenarios = payload["scenarios"]
    assert isinstance(raw_scenarios, list)
    result = []
    for raw_scenario in raw_scenarios:
        assert isinstance(raw_scenario, dict)
        source_files = raw_scenario["source_files"]
        selections = raw_scenario["selections"]
        assert isinstance(source_files, list)
        assert isinstance(selections, list)
        result.append(
            CollectedQualificationScenario(
                scenario_id=str(raw_scenario["scenario_id"]),
                family=str(raw_scenario["family"]),
                node_id=str(raw_scenario["test_selector"]),
                source_file=str(source_files[0]),
                selections=tuple(str(item) for item in selections),
            )
        )
    return result


def test_manifest_binds_registry_contract_source_and_implementation_bytes() -> None:
    payload = _valid_registry()
    registry = _validate(payload)

    manifest = build_test_manifest(
        registry,
        collected_scenarios=_collected_scenarios(payload),
        repo_root=REPO_ROOT,
    )

    assert manifest.payload["registry_digest"] == registry.registry_digest
    assert manifest.test_manifest_digest.startswith("sha256:")
    assert manifest.payload["contract_files"] == [
        {
            "content_digest": (
                "sha256:"
                + hashlib.sha256((REPO_ROOT / CONTRACT_FILE).read_bytes()).hexdigest()
            ),
            "path": CONTRACT_FILE,
        }
    ]
    implementation_files = manifest.payload["implementation_files"]
    assert isinstance(implementation_files, list)
    assert implementation_files[0]["path"] == IMPLEMENTATION_FILE
    scenarios = manifest.payload["scenarios"]
    assert isinstance(scenarios, list)
    assert len(scenarios) == len(REQUIRED_FAMILIES)
    assert scenarios[0]["source_files"][0]["path"] == SOURCE_FILE


def test_manifest_rejects_missing_duplicate_unknown_and_selector_drift() -> None:
    payload = _valid_registry()
    registry = _validate(payload)
    collected = _collected_scenarios(payload)

    invalid_collections = [
        collected[:-1],
        [*collected, collected[0]],
        [
            *collected,
            CollectedQualificationScenario(
                scenario_id="wire-contract.unknown",
                family="wire-contract",
                node_id=f"{SOURCE_FILE}::unknown",
                source_file=SOURCE_FILE,
                selections=("full",),
            ),
        ],
        [
            CollectedQualificationScenario(
                scenario_id=collected[0].scenario_id,
                family=collected[0].family,
                node_id=f"{SOURCE_FILE}::drifted",
                source_file=collected[0].source_file,
                selections=collected[0].selections,
            ),
            *collected[1:],
        ],
        [
            CollectedQualificationScenario(
                scenario_id=collected[0].scenario_id,
                family=collected[0].family,
                node_id=collected[0].node_id,
                source_file=(
                    "apps/openzyme-host-api/tests/"
                    "architecture_qualification/test_collection.py"
                ),
                selections=collected[0].selections,
            ),
            *collected[1:],
        ],
        [
            CollectedQualificationScenario(
                scenario_id=collected[0].scenario_id,
                family=collected[0].family,
                node_id=collected[0].node_id,
                source_file=collected[0].source_file,
                selections=("full", "premerge_subset"),
            ),
            *collected[1:],
        ],
    ]
    for invalid in invalid_collections:
        with pytest.raises(ArchitectureQualificationManifestError):
            build_test_manifest(
                registry,
                collected_scenarios=invalid,
                repo_root=REPO_ROOT,
            )


def test_boundary_resolver_derives_cases_and_checks_registered_seam() -> None:
    registry = _validate(_valid_registry())

    resolved = resolve_boundary_relation(
        registry,
        boundary_id="sandbox-control-frame-bytes",
        repo_root=REPO_ROOT,
    )

    assert resolved.cases == (
        resolved.owner_value - 1,
        resolved.owner_value,
        resolved.owner_value + 1,
    )
    assert set(resolved.seam_values.values()) == {resolved.owner_value}


def test_boundary_resolver_rejects_symbol_and_equality_drift() -> None:
    payload = _valid_registry()
    boundaries = payload["boundary_relations"]
    assert isinstance(boundaries, list)
    boundary = boundaries[0]
    assert isinstance(boundary, dict)
    seams = boundary["seams"]
    assert isinstance(seams, list)
    seam = seams[0]
    assert isinstance(seam, dict)
    seam.update(
        {
            "module": "openzyme_core.sandbox_runtime",
            "source_file": (
                "packages/openzyme-core/src/openzyme_core/sandbox_runtime.py"
            ),
            "symbol": "READ_MAX_LIMIT",
        }
    )
    registry = _validate(payload)
    with pytest.raises(ArchitectureQualificationBoundaryError, match="equality drifted"):
        resolve_boundary_relation(
            registry,
            boundary_id="sandbox-control-frame-bytes",
            repo_root=REPO_ROOT,
        )

    payload = _valid_registry()
    boundaries = payload["boundary_relations"]
    assert isinstance(boundaries, list)
    boundary = boundaries[0]
    assert isinstance(boundary, dict)
    owner = boundary["owner"]
    assert isinstance(owner, dict)
    owner["symbol"] = "MISSING_OWNER_LIMIT"
    registry = _validate(payload)
    with pytest.raises(ArchitectureQualificationBoundaryError, match="cannot be resolved"):
        resolve_boundary_relation(
            registry,
            boundary_id="sandbox-control-frame-bytes",
            repo_root=REPO_ROOT,
        )
