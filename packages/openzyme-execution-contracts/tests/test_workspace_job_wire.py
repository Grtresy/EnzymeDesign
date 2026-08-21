from __future__ import annotations

from copy import deepcopy

import pytest

from openzyme_execution_contracts import WorkspaceJobWireContractError
from openzyme_execution_contracts import canonical_workspace_job_wire_digest
from openzyme_execution_contracts import parse_external_job_observation
from openzyme_execution_contracts import parse_workspace_job_cancellation_intent
from openzyme_execution_contracts import parse_workspace_job_cancellation_receipt
from openzyme_execution_contracts import parse_workspace_job_reconciliation
from openzyme_execution_contracts import parse_workspace_job_runner_handle
from openzyme_execution_contracts import serialize_workspace_job_cancellation_receipt


DIGEST = f"sha256:{'1' * 64}"
OTHER_DIGEST = f"sha256:{'2' * 64}"
NOW = "2026-08-18T00:00:00+00:00"


def _with_digest(value: dict[str, object], field: str) -> dict[str, object]:
    payload = {key: item for key, item in value.items() if key != field}
    return {**payload, field: canonical_workspace_job_wire_digest(payload)}


def _runner_handle() -> dict[str, object]:
    return _with_digest(
        {
            "schema_version": "workspace_job_runner_handle@1",
            "disposition": "accepted",
            "handle_id": "handle_1",
            "execution_id": "execution_1",
            "operation_id": "operation_1",
            "dispatch_id": "dispatch_1",
            "runner_run_id": "run_1",
            "job_root_token": "job_root_1",
            "target_profile_digest": DIGEST,
            "workspace_id": "workspace_1",
            "remote_workspace_generation": 1,
            "source_commit": "a" * 40,
            "source_manifest_digest": OTHER_DIGEST,
            "backend": "direct",
            "raw_handle_ciphertext": "private-ciphertext",
            "acceptance_receipt_digest": DIGEST,
            "accepted_at": NOW,
            "credential_consumed_at": None,
            "credential_consumption_receipt_digest": None,
            "handle_digest": "",
        },
        "handle_digest",
    )


def _cancellation_intent() -> dict[str, object]:
    return {
        "schema_version": "workspace_job_cancellation_intent@1",
        "cancellation_id": "cancel_1",
        "execution_id": "execution_1",
        "handle_id": "handle_1",
        "execution_state_version": 4,
        "execution_fencing_token": 9,
        "idempotency_key": "cancel-idempotency-1",
        "reason_digest": DIGEST,
        "created_at": NOW,
    }


def _observation() -> dict[str, object]:
    return _with_digest(
        {
            "schema_version": "external_job_observation@1",
            "observation_id": "job_observation_handle_1_1",
            "handle_id": "handle_1",
            "execution_id": "execution_1",
            "dispatch_id": "dispatch_1",
            "observation_index": 1,
            "state": "running",
            "exit_code": None,
            "terminal_receipt_digest": None,
            "bounded_stdout": "running",
            "bounded_stderr": None,
            "observed_at": NOW,
            "observation_digest": "",
        },
        "observation_digest",
    )


def test_canonical_cancellation_receipt_round_trips_through_wire() -> None:
    receipt = serialize_workspace_job_cancellation_receipt(
        receipt_id="cancel_receipt_1",
        cancellation_id="cancel_1",
        handle_id="handle_1",
        backend_receipt_digest=DIGEST,
        created_at=NOW,
    )

    assert parse_workspace_job_cancellation_receipt(receipt) == receipt
    assert receipt["receipt_id"] == "cancel_receipt_1"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda value: value.pop("receipt_id"), "workspace_job_wire_fields_mismatch"),
        (lambda value: value.update(extra="value"), "workspace_job_wire_fields_mismatch"),
        (
            lambda value: value.update(cancellation_requested=1),
            "workspace_job_wire_field_invalid",
        ),
        (
            lambda value: value.update(receipt_digest=OTHER_DIGEST),
            "workspace_job_wire_digest_mismatch",
        ),
        (
            lambda value: value.update(schema_version="workspace_job_cancellation_receipt@0"),
            "workspace_job_wire_schema_unsupported",
        ),
    ],
)
def test_cancellation_receipt_rejects_closed_contract_drift(
    mutation: object,
    error_code: str,
) -> None:
    value = serialize_workspace_job_cancellation_receipt(
        receipt_id="cancel_receipt_1",
        cancellation_id="cancel_1",
        handle_id="handle_1",
        backend_receipt_digest=DIGEST,
        created_at=NOW,
    )
    mutation(deepcopy(value))
    invalid = deepcopy(value)
    mutation(invalid)

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        parse_workspace_job_cancellation_receipt(invalid)

    assert captured.value.error_code == error_code
    assert captured.value.contract == "workspace_job_cancellation_receipt@1"


def test_cancellation_receipt_rejects_cross_cancellation_identity() -> None:
    receipt = serialize_workspace_job_cancellation_receipt(
        receipt_id="cancel_receipt_1",
        cancellation_id="cancel_1",
        handle_id="handle_1",
        backend_receipt_digest=DIGEST,
        created_at=NOW,
    )

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        parse_workspace_job_cancellation_receipt(
            receipt,
            expected={"cancellation_id": "cancel_other"},
        )

    assert captured.value.error_code == "workspace_job_wire_identity_mismatch"
    assert captured.value.field == "cancellation_id"


def test_intent_handle_observation_and_reconciliation_bind_exact_identity() -> None:
    intent = parse_workspace_job_cancellation_intent(
        _cancellation_intent(),
        expected={"execution_id": "execution_1", "handle_id": "handle_1"},
    )
    handle = parse_workspace_job_runner_handle(
        _runner_handle(),
        expected={
            "execution_id": "execution_1",
            "dispatch_id": "dispatch_1",
            "runner_run_id": "run_1",
        },
    )
    observation = parse_external_job_observation(
        _observation(),
        expected={
            "handle_id": handle["handle_id"],
            "execution_id": intent["execution_id"],
            "dispatch_id": "dispatch_1",
            "observation_index": 1,
        },
    )

    assert observation["state"] == "running"
    assert parse_workspace_job_reconciliation(
        handle,
        expected_handle={"handle_id": "handle_1", "source_commit": "a" * 40},
    ) == handle


def test_replay_identity_and_observation_digest_drift_fail_closed() -> None:
    with pytest.raises(WorkspaceJobWireContractError) as handle_error:
        parse_workspace_job_runner_handle(
            _runner_handle(),
            expected={"dispatch_id": "dispatch_other"},
        )
    assert handle_error.value.error_code == "workspace_job_wire_identity_mismatch"
    assert handle_error.value.field == "dispatch_id"

    observation = _observation()
    observation["bounded_stdout"] = "tampered"
    with pytest.raises(WorkspaceJobWireContractError) as observation_error:
        parse_external_job_observation(observation)
    assert observation_error.value.error_code == "workspace_job_wire_digest_mismatch"


def test_wire_digest_uses_closed_backend_scalar() -> None:
    assert canonical_workspace_job_wire_digest({"backend": "direct"}).startswith(
        "sha256:"
    )
