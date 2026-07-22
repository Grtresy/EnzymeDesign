from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import Literal

import pytest

from openzyme_host_api.durable_routes import durable_adapter_policy_id

from ..composition import ProductionCompositionFactory
from ..driver import AdmittedOperation
from ..driver import controlled_ncbi_result
from ..driver import QualificationDriver
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..observation import collect_observation
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent


SealedObservationFault = Literal["missing", "tampered", "identity_drift"]

_PROVIDER_ROUTE_ID = "bio.ncbi_fetch_proteins.provider:v1"
_FAULT_ERRORS: dict[SealedObservationFault, str] = {
    "missing": "durable_provider_transcript_unavailable",
    "tampered": "durable_provider_transcript_digest_mismatch",
    "identity_drift": "durable_provider_transcript_identity_drift",
}


def _admit_and_lose_callback(
    driver: QualificationDriver,
    *,
    case_id: str,
    fault: SealedObservationFault | None,
) -> AdmittedOperation:
    session_id = f"sess_reconciliation_{case_id}"
    driver.create_session(session_id)
    ids = driver.admit_durable_operation(
        session_id=session_id,
        scenario_key=f"reconciliation_{case_id}",
        route_policy_id=_PROVIDER_ROUTE_ID,
        selected_backend="provider_http",
        adapter_policy_id=durable_adapter_policy_id(_PROVIDER_ROUTE_ID),
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
        worker_id=f"qualification:reconciliation:{case_id}:before-restart",
    )
    assert lost["action"] == "dispatch"
    assert lost["lifecycle_state"] == "reconcile_required"
    if fault is not None:
        driver.inject_sealed_observation_fault(ids, fault=fault)
    return ids


def _assert_common_records(records: dict[str, object]) -> None:
    assert records["approval"]["status"] == "approved"  # type: ignore[index]
    assert len(records["approvals"]) == 1  # type: ignore[arg-type]
    assert records["tasks"] == []


def _assert_exact_recovery(records: dict[str, object]) -> None:
    envelope = records["result"]["bounded_result_envelope"]  # type: ignore[index]
    assert records["operation"]["adapter_result_envelope"] == envelope  # type: ignore[index]
    assert records["operation"]["result_summary"] == envelope[  # type: ignore[index]
        "bounded_summary"
    ]
    assert envelope["registered_artifact_ids"] == envelope["output_artifact_ids"]
    assert len(envelope["output_artifact_ids"]) == 3
    assert envelope["bounded_summary"]["record_count"] == 1  # type: ignore[index]
    manifest = envelope["bounded_summary"]["transcript_manifest"]  # type: ignore[index]
    assert manifest["provider_request_id"] == envelope["provider_request_id"]  # type: ignore[index]
    assert {
        PurePosixPath(str(item["relative_path"])).name
        for item in manifest["files"]  # type: ignore[union-attr]
    } == {
        "proteins.fasta",
        "provider_observation.json",
        "provider_request.json",
    }


@pytest.mark.architecture_qualification_scenario(
    scenario_id="reconciliation.lost-callback-exact-recovery",
    family="reconciliation",
    selections=("full", "premerge_subset"),
)
def test_lost_callback_recovers_exact_result_after_restart_without_replay(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "reconciliation")
    first = factory.build()
    cases: tuple[tuple[str, SealedObservationFault | None], ...] = (
        ("exact", None),
        ("missing", "missing"),
        ("tampered", "tampered"),
        ("identity_drift", "identity_drift"),
    )
    admitted: dict[str, AdmittedOperation] = {}
    collected_records: dict[str, dict[str, object]] = {}
    with first as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        for case_id, fault in cases:
            admitted[case_id] = _admit_and_lose_callback(
                driver,
                case_id=case_id,
                fault=fault,
            )

    restarted = factory.restart(first)
    with restarted as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        for case_id, fault in cases:
            ids = admitted[case_id]
            recovered = driver.run_execution_once(
                ids.execution_id,
                worker_id=(
                    f"qualification:reconciliation:{case_id}:after-restart"
                ),
            )
            assert recovered["action"] == "reconcile"
            if fault is None:
                assert recovered["lifecycle_state"] == "result_ready"
                terminalized = driver.run_execution_once(
                    ids.execution_id,
                    worker_id=(
                        f"qualification:reconciliation:{case_id}:after-restart"
                    ),
                )
                assert terminalized["action"] == "terminalize_result"
                assert terminalized["lifecycle_state"] == "terminal"
                records = driver.canonical_records(ids)
                _assert_common_records(records)
                _assert_exact_recovery(records)
                collected_records[case_id] = records
                continue
            assert recovered["lifecycle_state"] == "terminal"
            records = driver.canonical_records(ids)
            _assert_common_records(records)
            error_code = _FAULT_ERRORS[fault]
            assert records["execution"]["error_code"] == error_code  # type: ignore[index]
            assert records["result"]["bounded_result_envelope"] == {  # type: ignore[index]
                "error_code": error_code,
                "output_artifact_ids": [],
                "safe_error_summary": (
                    "The durable provider operation failed without a canonical result."
                ),
                "status": "failed",
            }
            collected_records[case_id] = records
        observation = collect_observation(
            running,
            session_ids=tuple(
                f"sess_reconciliation_{case_id}" for case_id, _ in cases
            ),
        )

    exact_envelope = collected_records["exact"]["result"][  # type: ignore[index]
        "bounded_result_envelope"
    ]
    assert isinstance(exact_envelope, dict)
    assert_operation_oracle(
        collected_records["exact"],
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=exact_envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    for case_id, fault in cases:
        if fault is None:
            continue
        error_code = _FAULT_ERRORS[fault]
        assert_operation_oracle(
            collected_records[case_id],
            expected_lifecycle="terminal",
            expected_terminal_outcome="failed",
            expected_envelope={
                "error_code": error_code,
                "output_artifact_ids": [],
                "safe_error_summary": (
                    "The durable provider operation failed without a canonical "
                    "result."
                ),
                "status": "failed",
            },
            expected_result_ready_transitions=0,
            expected_terminal_transitions=1,
        )
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={
            ("bio.provider_http", "ncbi_fetch_proteins"): len(cases)
        },
        expected_effect_count=len(cases),
    )
    assert_public_authority_absent(observation.payload["public_projection"])
