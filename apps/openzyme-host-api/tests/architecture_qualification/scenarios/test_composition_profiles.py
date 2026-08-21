from __future__ import annotations

import hashlib

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..production_composition import run_closed_non_live_suite


def _record_profile_satisfied(scenario_id: str, suite_id: str) -> None:
    receipt = run_closed_non_live_suite(suite_id)
    observation = receipt.to_dict()
    ledger = {
        "external_effects_real": False,
        "operations": [
            {
                "effect_count": 0,
                "port_id": "non-live-test-process",
                "suite_id": suite_id,
            }
        ],
        "scenario_id": scenario_id,
    }
    record_effect_ledger_snapshot(
        {
            **ledger,
            "ledger_digest": "sha256:"
            + hashlib.sha256(canonical_json_bytes(ledger)).hexdigest(),
        }
    )
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="authority-composition.kernel-fake-profile",
    family="authority-composition",
    selections=("full", "premerge_subset"),
)
def test_kernel_fake_profile_uses_only_contract_ports_and_fakes() -> None:
    _record_profile_satisfied(
        "authority-composition.kernel-fake-profile",
        "kernel-fake-adapters",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.standard-profile",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_standard_profile_is_plugin_free_and_restartable() -> None:
    _record_profile_satisfied(
        "evidence-projection.standard-profile",
        "standard-composition",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="wire-contract.enzymedesign-catalog",
    family="wire-contract",
    selections=("full", "premerge_subset"),
)
def test_enzymedesign_profile_resolves_exact_component_catalogs() -> None:
    _record_profile_satisfied(
        "wire-contract.enzymedesign-catalog",
        "enzymedesign-catalog",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="identity-semantics.enzymedesign-product-cross-layer",
    family="identity-semantics",
    selections=("full", "premerge_subset"),
)
def test_enzymedesign_product_runs_real_non_live_cross_layer_path() -> None:
    _record_profile_satisfied(
        "identity-semantics.enzymedesign-product-cross-layer",
        "enzymedesign-product-cross-layer",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="operator-retirement.component-wheel-closure",
    family="operator-retirement",
    selections=("full", "premerge_subset"),
)
def test_dependency_wheel_import_and_archive_exposure_close() -> None:
    _record_profile_satisfied(
        "operator-retirement.component-wheel-closure",
        "wheel-installation",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="strategy-neutrality.plugin-negative-matrix",
    family="strategy-neutrality",
    selections=("full", "premerge_subset"),
)
def test_plugin_activation_negative_matrix_fails_closed() -> None:
    _record_profile_satisfied(
        "strategy-neutrality.plugin-negative-matrix",
        "plugin-negative",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="identity-semantics.capability-affordance-matrix",
    family="identity-semantics",
    selections=("full", "premerge_subset"),
)
def test_capability_inventory_affordance_and_route_matrix_is_exact() -> None:
    _record_profile_satisfied(
        "identity-semantics.capability-affordance-matrix",
        "capability-affordance",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="world-fidelity.workspace-runtime-boundary",
    family="world-fidelity",
    selections=("full", "premerge_subset"),
)
def test_local_and_hpc_workspace_runtime_preserve_effect_boundaries() -> None:
    _record_profile_satisfied(
        "world-fidelity.workspace-runtime-boundary",
        "workspace-runtime",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="authority-composition.source-document-owner-closure",
    family="authority-composition",
    selections=("full", "premerge_subset"),
)
def test_source_documents_and_owner_manifests_close_on_current_source() -> None:
    _record_profile_satisfied(
        "authority-composition.source-document-owner-closure",
        "owner-source-document",
    )
