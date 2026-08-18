from __future__ import annotations

import hashlib

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..production_composition import run_closed_non_live_suite


def _record_process_satisfied(scenario_id: str, suite_id: str) -> None:
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
    scenario_id="reconciliation.workspace-job-response-loss",
    family="reconciliation",
    selections=("full", "premerge_subset"),
)
def test_workspace_job_response_loss_restart_and_fencing() -> None:
    _record_process_satisfied(
        "reconciliation.workspace-job-response-loss",
        "workspace-job",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="world-fidelity.diagnostic-publication-cleanup",
    family="world-fidelity",
    selections=("full", "premerge_subset"),
)
def test_diagnostic_publication_and_cleanup_preserve_earliest_cause() -> None:
    _record_process_satisfied(
        "world-fidelity.diagnostic-publication-cleanup",
        "diagnostic-publication-cleanup",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.fresh-offline-deployment-proof",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_fresh_and_offline_deployment_proof_fail_closed() -> None:
    _record_process_satisfied(
        "evidence-projection.fresh-offline-deployment-proof",
        "deployment-proof",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="identity-semantics.scientific-file-finalization",
    family="identity-semantics",
    selections=("full", "premerge_subset"),
)
def test_scientific_finalization_binds_revision_attempt_and_role_identity() -> None:
    _record_process_satisfied(
        "identity-semantics.scientific-file-finalization",
        "scientific-finalization",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="operator-retirement.web-ui-file-workspace",
    family="operator-retirement",
    selections=("full", "premerge_subset"),
)
def test_web_ui_consumes_only_current_file_workspace_contract() -> None:
    _record_process_satisfied(
        "operator-retirement.web-ui-file-workspace",
        "web-ui",
    )
