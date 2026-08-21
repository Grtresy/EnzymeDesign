from __future__ import annotations

from copy import deepcopy

import pytest

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationBoundaryError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationRegistryError,
)
from openzyme_host_api.architecture_qualification import REQUIRED_FAMILIES
from openzyme_host_api.architecture_qualification import PROFILE_IDS
from openzyme_host_api.architecture_qualification import (
    QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID,
)
from openzyme_host_api.architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID
from openzyme_host_api.architecture_qualification import canonical_json_document_bytes
from openzyme_host_api.architecture_qualification import load_invariant_registry
from openzyme_host_api.architecture_qualification import resolve_boundary_relation
from openzyme_host_api.architecture_qualification import (
    validate_invariant_registry_bytes,
)
from openzyme_host_api.architecture_qualification_report import _profiles
from openzyme_host_api.architecture_qualification_report import _qualification_bindings
from scripts.architecture_qualification_runner import (
    _qualification_evidence_is_green,
)

from . import production_composition
from .safety import QualificationSourcePolicyError
from .safety import validate_qualification_scenario_sources
from .scenarios.test_final_file_architecture import _require_no_replacement

from .conftest import REPO_ROOT


def test_final_file_architecture_registry_closes_required_families() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    scenarios = registry.payload["scenarios"]
    invariants = registry.payload["invariants"]
    assert isinstance(scenarios, list) and len(scenarios) >= len(REQUIRED_FAMILIES)
    assert isinstance(invariants, list) and {
        item["family"] for item in invariants
    } == set(REQUIRED_FAMILIES)
    assert {
        "boundary-scale.public-diagnostic-bounded-work",
        "supervisor-progress.semantic-progress-only",
    } <= {item["scenario_id"] for item in scenarios}
    assert tuple(item["profile_id"] for item in registry.payload["profiles"]) == (
        PROFILE_IDS
    )
    assert {
        profile_id for item in invariants for profile_id in item["profile_ids"]
    } == set(PROFILE_IDS)
    by_id = {item["invariant_id"]: item for item in invariants}
    assert by_id["authority-composition.kernel-fake-profile"]["profile_ids"] == [
        "kernel_fake_adapters@1"
    ]
    assert by_id["evidence-projection.standard-profile"]["profile_ids"] == [
        "openzyme_standard_local_file_sqlite_git@1"
    ]
    assert by_id["wire-contract.enzymedesign-catalog"]["profile_ids"] == [
        "enzymedesign_local_single_process_file_sqlite@1"
    ]
    assert by_id["identity-semantics.enzymedesign-product-cross-layer"][
        "profile_ids"
    ] == [
        "enzymedesign_local_single_process_file_sqlite@1"
    ]


def test_report_v4_binds_all_profiles_and_source_bundles() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    assert QUALIFICATION_REPORT_SCHEMA_ID.endswith("report@4")
    assert QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID.endswith("payload@4")
    profiles = _profiles(registry)
    assert tuple(item["profile_id"] for item in profiles) == PROFILE_IDS
    bindings = _qualification_bindings(
        repo_root=REPO_ROOT,
        registry=registry,
        test_manifest={"schema_id": "test-manifest-fixture@1"},
        selection={"scenario_ids": [], "selection_id": "fixture"},
    )
    assert set(bindings) == {
        "catalog_bundle_digest",
        "distribution_bundle_digest",
        "documentation_bundle_digest",
        "inventory_bundle_digest",
        "openspec_change_digest",
        "profile_bundle_digest",
        "schema_bundle_digest",
        "test_selection_digest",
        "wheel_set_digest",
    }
    assert all(value.startswith("sha256:") for value in bindings.values())


@pytest.mark.parametrize(
    "source",
    [
        "from types import SimpleNamespace\nvalue = SimpleNamespace(ok=True)\n",
        "import subprocess\nsubprocess.run(['curl', 'https://example.invalid'])\n",
    ],
)
def test_scenario_policy_rejects_simplified_fixture_and_undeclared_external_call(
    tmp_path,
    source: str,
) -> None:
    relative = (
        "apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_bad.py"
    )
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")

    with pytest.raises(QualificationSourcePolicyError):
        validate_qualification_scenario_sources(
            repo_root=tmp_path,
            source_files=(relative,),
        )


def _validate_payload(payload: dict[str, object]):
    return validate_invariant_registry_bytes(
        canonical_json_document_bytes(payload),
        repo_root=REPO_ROOT,
    )


def test_boundary_relation_drift_fails_before_scenario_credit() -> None:
    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    boundary = next(
        item
        for item in payload["boundary_relations"]
        if item["boundary_id"] == "diagnostic-public-bytes"
    )
    boundary["seams"][0]["relation"] = "equal"
    registry = _validate_payload(payload)

    with pytest.raises(
        ArchitectureQualificationBoundaryError, match="equality drifted"
    ):
        resolve_boundary_relation(
            registry,
            boundary_id="diagnostic-public-bytes",
            repo_root=REPO_ROOT,
        )


def test_undeclared_external_port_fails_registry_validation() -> None:
    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    scenario = next(
        item
        for item in payload["scenarios"]
        if item["scenario_id"] == "operator-retirement.web-ui-file-workspace"
    )
    scenario["external_port_ids"] = ["undeclared-network-port"]

    with pytest.raises(
        ArchitectureQualificationRegistryError, match="unknown external port"
    ):
        _validate_payload(payload)


def test_missing_cutover_family_fails_registry_validation() -> None:
    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    removed = "identity-semantics.scientific-file-finalization"
    payload["scenarios"] = [
        item for item in payload["scenarios"] if item["scenario_id"] != removed
    ]
    payload["required_scenario_ids"] = [
        item for item in payload["required_scenario_ids"] if item != removed
    ]
    payload["invariants"] = [
        item for item in payload["invariants"] if item["invariant_id"] != removed
    ]

    with pytest.raises(
        ArchitectureQualificationRegistryError, match="cutover production"
    ):
        _validate_payload(payload)


def test_profile_identity_refs_and_layered_digests_fail_closed() -> None:
    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    payload["profiles"][0]["layered_composition_digests"]["extension_bundle_digest"] = (
        "sha256:invalid"
    )
    with pytest.raises(ArchitectureQualificationRegistryError, match="is invalid"):
        _validate_payload(payload)

    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    payload["profiles"][1]["component_manifest_refs"] = ["missing.json"]
    with pytest.raises(ArchitectureQualificationRegistryError, match="readable"):
        _validate_payload(payload)


def test_profile_external_port_and_exact_set_fail_closed() -> None:
    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    payload["profiles"][1]["allowed_external_port_ids"] = ["undeclared-port"]
    with pytest.raises(
        ArchitectureQualificationRegistryError,
        match="undeclared external port",
    ):
        _validate_payload(payload)

    payload = deepcopy(load_invariant_registry(repo_root=REPO_ROOT).payload)
    payload["profiles"].pop()
    with pytest.raises(
        ArchitectureQualificationRegistryError,
        match="exact three composition profiles",
    ):
        _validate_payload(payload)


def test_failed_production_process_preserves_receipt_and_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        production_composition.subprocess,
        "run",
        lambda *_args, **_kwargs: production_composition.subprocess.CompletedProcess(
            args=("npm", "test"),
            returncode=2,
            stdout=b"one failing UI test",
            stderr=b"contract drift",
        ),
    )

    with pytest.raises(AssertionError, match="receipt=.*returncode.*2"):
        production_composition.run_closed_non_live_suite("web-ui")


def test_no_replacement_oracle_rejects_inferred_fallback() -> None:
    expected = {
        "field_or_operation": "request.storage_uri",
        "mutation_applied": False,
        "replacement_inferred": False,
        "schema_id": "unsupported_current_file_workspace_contract@1",
    }
    with pytest.raises(AssertionError, match="inferred a replacement"):
        _require_no_replacement(
            {**expected, "replacement_inferred": True},
            expected=expected,
        )


def test_non_admission_green_uses_generic_live_campaign_fact() -> None:
    payload = {
        "external_effects_real": False,
        "harness": {"outcome": "pass"},
        "invariants": [{"status": "satisfied"}],
        "live_campaign_started": False,
        "not_run_scenario_ids": [],
        "p0_records": [],
        "run_failure": None,
        "scenario_results": [{"qualification_status": "satisfied"}],
    }

    assert _qualification_evidence_is_green(payload) is True
    payload["live_campaign_started"] = True
    assert _qualification_evidence_is_green(payload) is False
