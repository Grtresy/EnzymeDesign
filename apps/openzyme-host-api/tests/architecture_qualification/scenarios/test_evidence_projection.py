from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_host_api.architecture_qualification import (
    canonical_json_document_bytes,
)
from openzyme_host_api.durable_routes import durable_adapter_policy_id

from ..composition import ProductionCompositionFactory
from ..driver import QualificationDriver
from ..driver import controlled_ncbi_result
from ..driver import materialized_observation_response
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..observation import collect_observation
from ..observation import find_private_projection_fields
from ..observation import verify_observation_offline
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent


_PROVIDER_ROUTE_ID = "bio.ncbi_fetch_proteins.provider:v1"
_FAILURE_CODE = "durable_provider_transcript_identity_drift"


def _changed_database_tables(
    before: object,
    after: object,
) -> tuple[str, ...]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise AssertionError("database observation is not an object")
    before_tables = {
        str(item["table"]): item
        for item in before["tables"]
        if isinstance(item, dict)
    }
    after_tables = {
        str(item["table"]): item
        for item in after["tables"]
        if isinstance(item, dict)
    }
    return tuple(
        name
        for name in sorted(set(before_tables) | set(after_tables))
        if before_tables.get(name) != after_tables.get(name)
    )


def _public_sessions(observation: object) -> dict[str, dict[str, object]]:
    if not isinstance(observation, dict):
        raise AssertionError("public projection is not an object")
    sessions = observation.get("sessions")
    if not isinstance(sessions, list):
        raise AssertionError("public sessions are not a list")
    return {
        str(item["session_id"]): item
        for item in sessions
        if isinstance(item, dict)
    }


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.restart-cross-layer-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_success_failure_restart_and_offline_evidence_close_exact_identity(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "evidence-projection")
    first = factory.build()
    success_envelope = {
        "bounded_summary": {
            "status": "completed",
            "transcript_manifest": {"files": ["sealed-observation.json"]},
        },
        "output_artifact_ids": [],
        "registered_artifact_ids": [],
        "status": "succeeded",
    }
    with first as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)

        success_session_id = "sess_evidence_success"
        driver.create_session(success_session_id)
        success_ids = driver.admit_durable_operation(
            session_id=success_session_id,
            scenario_key="evidence_success",
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
                    bounded_result_envelope=success_envelope,
                    backend_handle_ref=None,
                ),
            ),
        )
        driver.resolve_approval(success_ids.approval_id)
        driver.run_execution_once(
            success_ids.execution_id,
            worker_id="qualification:evidence-success",
        )
        driver.run_execution_once(
            success_ids.execution_id,
            worker_id="qualification:evidence-success",
        )
        success_before_restart = driver.canonical_records(success_ids)

        failure_session_id = "sess_evidence_failure"
        driver.create_session(failure_session_id)
        failure_ids = driver.admit_durable_operation(
            session_id=failure_session_id,
            scenario_key="evidence_failure",
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
        driver.resolve_approval(failure_ids.approval_id)
        lost = driver.run_execution_once(
            failure_ids.execution_id,
            worker_id="qualification:evidence-failure",
        )
        driver.inject_sealed_observation_fault(
            failure_ids,
            fault="identity_drift",
        )
        failure_before_restart = driver.canonical_records(failure_ids)
        before = collect_observation(
            running,
            session_ids=(success_session_id, failure_session_id),
        )

    second = factory.restart(first)
    with second as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        failed = driver.run_execution_once(
            failure_ids.execution_id,
            worker_id="qualification:evidence-failure",
        )
        success_after_failure = driver.canonical_records(success_ids)
        failure_terminal = driver.canonical_records(failure_ids)
        after_failure = collect_observation(
            running,
            session_ids=(success_session_id, failure_session_id),
        )

    third = factory.restart(second)
    with third as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        success_final = driver.canonical_records(success_ids)
        failure_final = driver.canonical_records(failure_ids)
        final = collect_observation(
            running,
            session_ids=(success_session_id, failure_session_id),
        )
        offline_content = canonical_json_document_bytes(final.payload)
        final_digest = final.observation_digest

    offline_receipt = verify_observation_offline(
        offline_content,
        expected_observation_digest=final_digest,
    )

    assert lost["lifecycle_state"] == "reconcile_required"
    assert failed["action"] == "reconcile"
    assert failed["lifecycle_state"] == "terminal"
    assert success_before_restart == success_after_failure == success_final
    assert failure_before_restart["result"] is None
    assert failure_terminal == failure_final
    assert_operation_oracle(
        success_final,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=success_envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    failure_envelope = {
        "error_code": _FAILURE_CODE,
        "output_artifact_ids": [],
        "safe_error_summary": (
            "The durable provider operation failed without a canonical result."
        ),
        "status": "failed",
    }
    assert_operation_oracle(
        failure_final,
        expected_lifecycle="terminal",
        expected_terminal_outcome="failed",
        expected_envelope=failure_envelope,
        expected_result_ready_transitions=0,
        expected_terminal_transitions=1,
    )
    assert failure_final["execution"]["error_code"] == _FAILURE_CODE  # type: ignore[index]

    changed_after_fault = _changed_database_tables(
        before.payload["database"],
        after_failure.payload["database"],
    )
    assert {
        "continuation_state_records",
        "controlled_operation_execution_events",
        "controlled_operation_execution_records",
        "controlled_operation_result_handles",
        "durable_event_records",
    } <= set(changed_after_fault)
    assert _changed_database_tables(
        after_failure.payload["database"],
        final.payload["database"],
    ) == ()
    assert before.payload["roots"] == after_failure.payload["roots"]
    assert after_failure.payload["roots"] == final.payload["roots"]
    assert before.payload["effect_ledger"] == after_failure.payload["effect_ledger"]
    assert after_failure.payload["effect_ledger"] == final.payload["effect_ledger"]
    assert after_failure.payload["public_projection"] == final.payload[
        "public_projection"
    ]

    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={
            ("bio.provider_http", "dispatch"): 1,
            ("bio.provider_http", "ncbi_fetch_proteins"): 1,
        },
        expected_effect_count=2,
    )
    assert_public_authority_absent(final.payload["public_projection"])
    assert find_private_projection_fields(
        final.payload["public_projection"],
        forbidden_fields=frozenset(
            {
                "storage_uri",
                "backend_handle_ref",
                "claim_owner",
                "raw_diagnostic",
            }
        ),
    ) == ()
    public_sessions = _public_sessions(final.payload["public_projection"])
    assert set(public_sessions) == {success_session_id, failure_session_id}
    for session in public_sessions.values():
        artifacts = session["workspace"]["scientific_evidence"]["artifacts"]  # type: ignore[index]
        assert artifacts
        assert all("storage_uri" not in artifact for artifact in artifacts)
        assert all(
            artifact["sealed_digest"] is None
            or (
                isinstance(artifact["sealed_digest"], str)
                and artifact["sealed_digest"].startswith("sha256:")
                and len(artifact["sealed_digest"]) == 71
            )
            for artifact in artifacts
        )

    receipt = offline_receipt.payload
    assert receipt["observation_digest"] == final_digest
    assert receipt["effect_ledger_digest"] == final.payload["effect_ledger"][  # type: ignore[index]
        "ledger_digest"
    ]
    assert receipt["artifact_digest_count"] > 0  # type: ignore[operator]
    assert receipt["public_artifact_count"] > 0  # type: ignore[operator]
    assert set(receipt["root_digests"]) == {  # type: ignore[arg-type]
        "artifacts",
        "blobs",
        "sandboxes",
        "workspace_projections",
    }
    assert success_final["tasks"] == failure_final["tasks"] == []
