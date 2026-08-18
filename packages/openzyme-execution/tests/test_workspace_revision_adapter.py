from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from openzyme_domain import WorkspaceJobWireContractError
from openzyme_domain import canonical_workspace_job_wire_digest
from openzyme_domain import serialize_workspace_job_cancellation_receipt
from openzyme_execution import WorkspaceRevisionRunnerAdapter


DIGEST = f"sha256:{'a' * 64}"
NOW = "2026-08-18T00:00:00+00:00"


def _runspec() -> dict[str, Any]:
    return {
        "selected_mode": "ssh",
        "execution_id": "execution_1",
        "operation_id": "operation_1",
        "dispatch_id": "dispatch_1",
        "runner_run_id": "run_1",
        "target_profile_digest": DIGEST,
        "executor_hpc_workspace_id": "workspace_1",
        "executor_hpc_workspace_generation": 1,
        "source_commit": "1" * 40,
        "source_manifest_digest": DIGEST,
    }


def _handle() -> dict[str, Any]:
    payload: dict[str, Any] = {
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
        "source_commit": "1" * 40,
        "source_manifest_digest": DIGEST,
        "backend": "direct",
        "raw_handle_ciphertext": "private-ciphertext",
        "acceptance_receipt_digest": DIGEST,
        "accepted_at": NOW,
        "credential_consumed_at": None,
        "credential_consumption_receipt_digest": None,
    }
    return {**payload, "handle_digest": canonical_workspace_job_wire_digest(payload)}


def _observation() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "external_job_observation@1",
        "observation_id": "job_observation_handle_1_1",
        "handle_id": "handle_1",
        "execution_id": "execution_1",
        "dispatch_id": "dispatch_1",
        "observation_index": 1,
        "state": "running",
        "exit_code": None,
        "terminal_receipt_digest": None,
        "bounded_stdout": None,
        "bounded_stderr": None,
        "observed_at": NOW,
    }
    return {
        **payload,
        "observation_digest": canonical_workspace_job_wire_digest(payload),
    }


class _Server:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, payload))
        return deepcopy(self.responses[tool_name])


def test_adapter_round_trips_all_canonical_job_contracts() -> None:
    cancellation = {
        "schema_version": "workspace_job_cancellation_intent@1",
        "cancellation_id": "cancel_1",
        "execution_id": "execution_1",
        "handle_id": "handle_1",
        "execution_state_version": 3,
        "execution_fencing_token": 7,
        "idempotency_key": "cancel-key-1",
        "reason_digest": DIGEST,
        "created_at": NOW,
    }
    cancellation_receipt = serialize_workspace_job_cancellation_receipt(
        receipt_id="cancel_receipt_1",
        cancellation_id="cancel_1",
        handle_id="handle_1",
        backend_receipt_digest=DIGEST,
        created_at=NOW,
    )
    server = _Server(
        {
            "exec.run": _handle(),
            "job.reconcile": _handle(),
            "job.observe": _observation(),
            "job.cancel": cancellation_receipt,
        }
    )
    adapter = WorkspaceRevisionRunnerAdapter(server)

    assert adapter.dispatch_direct(_runspec()) == _handle()
    assert adapter.reconcile("run_1") == _handle()
    assert adapter.observe("run_1", observation_index=1) == _observation()
    assert adapter.cancel("run_1", cancellation=cancellation) == cancellation_receipt
    assert [name for name, _payload in server.calls] == [
        "exec.run",
        "job.reconcile",
        "job.observe",
        "job.cancel",
    ]


@pytest.mark.parametrize(
    ("tool_name", "invoke", "mutate", "field"),
    [
        (
            "exec.run",
            lambda adapter: adapter.dispatch_direct(_runspec()),
            lambda value: value.update(execution_id="execution_other"),
            "handle_digest",
        ),
        (
            "job.reconcile",
            lambda adapter: adapter.reconcile("run_1"),
            lambda value: value.update(runner_run_id="run_other"),
            "handle_digest",
        ),
        (
            "job.observe",
            lambda adapter: adapter.observe("run_1", observation_index=1),
            lambda value: value.update(observation_index=2),
            "observation_digest",
        ),
    ],
)
def test_adapter_rejects_digest_or_cross_run_drift(
    tool_name: str,
    invoke: Any,
    mutate: Any,
    field: str,
) -> None:
    response = _observation() if tool_name == "job.observe" else _handle()
    mutate(response)
    adapter = WorkspaceRevisionRunnerAdapter(_Server({tool_name: response}))

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        invoke(adapter)

    assert captured.value.error_code == "workspace_job_wire_digest_mismatch"
    assert captured.value.field == field


def test_adapter_rejects_extra_cancellation_receipt_field() -> None:
    cancellation = {
        "schema_version": "workspace_job_cancellation_intent@1",
        "cancellation_id": "cancel_1",
        "execution_id": "execution_1",
        "handle_id": "handle_1",
        "execution_state_version": 3,
        "execution_fencing_token": 7,
        "idempotency_key": "cancel-key-1",
        "reason_digest": DIGEST,
        "created_at": NOW,
    }
    receipt = serialize_workspace_job_cancellation_receipt(
        receipt_id="cancel_receipt_1",
        cancellation_id="cancel_1",
        handle_id="handle_1",
        backend_receipt_digest=DIGEST,
        created_at=NOW,
    )
    receipt["legacy_state"] = "cancelled"
    adapter = WorkspaceRevisionRunnerAdapter(_Server({"job.cancel": receipt}))

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        adapter.cancel("run_1", cancellation=cancellation)

    assert captured.value.error_code == "workspace_job_wire_fields_mismatch"
