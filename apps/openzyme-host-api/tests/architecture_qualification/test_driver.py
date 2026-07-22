from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_host_api.durable_routes import durable_adapter_policy_id

from .composition import ProductionCompositionFactory
from .driver import controlled_ncbi_result
from .driver import QualificationDriver
from .driver import materialized_observation_response
from .external_ports import ControlledPortOutcome
from .external_ports import EffectAcceptance
from .observation import collect_observation


def _envelope() -> dict[str, object]:
    return {
        "bounded_summary": {
            "record_count": 2,
            "status": "completed",
            "transcript_manifest": {
                "files": ["request.json", "observation.json"],
                "provider_request_id": "provider_qualification",
            },
        },
        "output_artifact_ids": [],
        "provider_request_id": "provider_qualification",
        "registered_artifact_ids": [],
        "status": "succeeded",
    }


def test_driver_uses_admission_service_public_approval_and_production_worker(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "driver-success")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        driver.create_session("sess_qualification_driver")
        ids = driver.admit_durable_operation(
            session_id="sess_qualification_driver",
            scenario_key="driver_success",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=materialized_observation_response(
                    bounded_result_envelope=_envelope(),
                    backend_handle_ref=None,
                ),
            ),
        )
        resolved = driver.resolve_approval(ids.approval_id)
        dispatched = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:driver-success",
        )
        terminalized = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:driver-success",
        )
        records = driver.canonical_records(ids)
        observation = collect_observation(
            running,
            session_ids=(ids.session_id,),
        )

    assert resolved["status"] == "completed"
    assert dispatched["action"] == "dispatch"
    assert dispatched["lifecycle_state"] == "result_ready"
    assert terminalized["action"] == "terminalize_result"
    assert terminalized["lifecycle_state"] == "terminal"
    assert records["execution"]["terminal_outcome"] == "succeeded"  # type: ignore[index]
    assert records["result"]["bounded_result_envelope"] == _envelope()  # type: ignore[index]
    assert records["operation"]["adapter_result_envelope"] == _envelope()  # type: ignore[index]
    assert records["operation"]["result_summary"] == _envelope()[  # type: ignore[index]
        "bounded_summary"
    ]
    assert records["tasks"] == []
    assert observation.counts.effect_count == 1


def test_driver_lost_callback_reconciles_exact_result_without_second_effect(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "driver-reconcile")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        driver.create_session("sess_qualification_reconcile")
        ids = driver.admit_durable_operation(
            session_id="sess_qualification_reconcile",
            scenario_key="driver_lost_callback",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        exact_response = materialized_observation_response(
            bounded_result_envelope=_envelope(),
            backend_handle_ref=None,
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.ACCEPTED,
                effect_attempted=True,
                response=exact_response,
                error_code="simulated_lost_callback",
            ),
        )
        driver.queue_external(
            "bio.provider_http",
            "reconcile",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                response=exact_response,
            ),
        )
        driver.resolve_approval(ids.approval_id)
        lost = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:driver-reconcile",
        )
        recovered = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:driver-reconcile",
        )
        terminalized = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:driver-reconcile",
        )
        records = driver.canonical_records(ids)

    assert lost["lifecycle_state"] == "reconcile_required"
    assert recovered["action"] == "reconcile"
    assert recovered["lifecycle_state"] == "result_ready"
    assert terminalized["lifecycle_state"] == "terminal"
    assert records["result"]["bounded_result_envelope"] == _envelope()  # type: ignore[index]
    assert factory.external_effect_ledger.count_effects() == 1
    assert factory.external_effect_ledger.count(operation="dispatch") == 1
    assert factory.external_effect_ledger.count(operation="reconcile") == 1


def test_driver_real_provider_route_recovers_sealed_artifacts_after_lost_callback(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "driver-real-provider")
    composition = factory.build()
    route_policy_id = "bio.ncbi_fetch_proteins.provider:v1"
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        driver.create_session("sess_qualification_real_provider")
        ids = driver.admit_durable_operation(
            session_id="sess_qualification_real_provider",
            scenario_key="real_provider_lost_callback",
            route_policy_id=route_policy_id,
            selected_backend="provider_http",
            adapter_policy_id=durable_adapter_policy_id(route_policy_id),
            backend_category="bio_provider",
            sdk_module="bio",
            function_name="ncbi_fetch_proteins",
            request_envelope={
                "adapter_params": {
                    "accessions": ["P12345"],
                    "fields": ["accession", "sequence"],
                    "output_dir": "/workspace/output/provider/ncbi",
                },
                "qualification_fault": "lost_callback_after_materialization",
                "schema_version": "s12.adapter_envelope.v1",
            },
        )
        driver.queue_external(
            "bio.provider_http",
            "ncbi_fetch_proteins",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=controlled_ncbi_result(),
            ),
        )
        driver.resolve_approval(ids.approval_id)
        lost = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:real-provider",
        )
    restarted = factory.restart(composition)
    with restarted as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        recovered = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:real-provider",
        )
        terminalized = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:real-provider",
        )
        records = driver.canonical_records(ids)

    assert lost["lifecycle_state"] == "reconcile_required"
    assert recovered["action"] == "reconcile"
    assert recovered["lifecycle_state"] == "result_ready"
    assert terminalized["lifecycle_state"] == "terminal"
    envelope = records["result"]["bounded_result_envelope"]  # type: ignore[index]
    assert envelope["provider_request_id"].startswith("provider_req_")
    assert envelope["registered_artifact_ids"] == envelope["output_artifact_ids"]
    assert len(envelope["output_artifact_ids"]) == 3
    assert envelope["bounded_summary"]["record_count"] == 1
    assert envelope["bounded_summary"]["transcript_manifest"][  # type: ignore[index]
        "provider_request_id"
    ] == envelope["provider_request_id"]
    assert factory.external_effect_ledger.count_effects() == 1
    assert factory.external_effect_ledger.count(operation="ncbi_fetch_proteins") == 1


@pytest.mark.parametrize(
    ("fault", "expected_error_code"),
    [
        ("missing", "durable_provider_transcript_unavailable"),
        ("tampered", "durable_provider_transcript_digest_mismatch"),
        ("identity_drift", "durable_provider_transcript_identity_drift"),
    ],
)
def test_driver_real_provider_route_fails_closed_on_sealed_observation_fault(
    tmp_path: Path,
    fault: str,
    expected_error_code: str,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / f"driver-{fault}")
    composition = factory.build()
    route_policy_id = "bio.ncbi_fetch_proteins.provider:v1"
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        driver.create_session(f"sess_qualification_{fault}")
        ids = driver.admit_durable_operation(
            session_id=f"sess_qualification_{fault}",
            scenario_key=f"real_provider_{fault}",
            route_policy_id=route_policy_id,
            selected_backend="provider_http",
            adapter_policy_id=durable_adapter_policy_id(route_policy_id),
            backend_category="bio_provider",
            sdk_module="bio",
            function_name="ncbi_fetch_proteins",
            request_envelope={
                "adapter_params": {
                    "accessions": ["P12345"],
                    "fields": ["accession", "sequence"],
                    "output_dir": "/workspace/output/provider/ncbi",
                },
                "qualification_fault": "lost_callback_after_materialization",
                "schema_version": "s12.adapter_envelope.v1",
            },
        )
        driver.queue_external(
            "bio.provider_http",
            "ncbi_fetch_proteins",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=controlled_ncbi_result(),
            ),
        )
        driver.resolve_approval(ids.approval_id)
        lost = driver.run_execution_once(
            ids.execution_id,
            worker_id=f"qualification:{fault}",
        )
        driver.inject_sealed_observation_fault(ids, fault=fault)  # type: ignore[arg-type]
    restarted = factory.restart(composition)
    with restarted as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        failed = driver.run_execution_once(
            ids.execution_id,
            worker_id=f"qualification:{fault}",
        )
        records = driver.canonical_records(ids)

    assert lost["lifecycle_state"] == "reconcile_required"
    assert failed["action"] == "reconcile"
    assert failed["lifecycle_state"] == "terminal"
    assert records["execution"]["error_code"] == expected_error_code  # type: ignore[index]
    assert records["result"]["bounded_result_envelope"] == {  # type: ignore[index]
        "error_code": expected_error_code,
        "output_artifact_ids": [],
        "safe_error_summary": (
            "The durable provider operation failed without a canonical result."
        ),
        "status": "failed",
    }
    assert records["approval"]["status"] == "approved"  # type: ignore[index]
    assert len(records["approvals"]) == 1  # type: ignore[arg-type]
    assert factory.external_effect_ledger.count_effects() == 1
    assert factory.external_effect_ledger.count(operation="ncbi_fetch_proteins") == 1
