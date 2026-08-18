from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from openzyme_host_api.executor_hpc_workspaces import (
    ExecutorHpcCredentialCommandResult,
)
from openzyme_host_api.workspace_revision_execution import (
    CommandRunnerSchedulerCredentialIssuer,
)
from openzyme_host_api.workspace_revision_execution import HostWorkspaceJobBackend
from openzyme_domain import ExternalJobHandle
from openzyme_domain import WorkspaceExternalBackend
from openzyme_domain import WorkspaceJobCancellationIntent
from openzyme_domain import WorkspaceJobDispatchIntent
from openzyme_domain import WorkspaceJobExecutionMode
from openzyme_domain import WorkspaceJobWireContractError
from openzyme_domain import canonical_workspace_job_wire_digest
from openzyme_domain import serialize_workspace_job_cancellation_receipt


DIGEST = "sha256:" + "a" * 64


def _claims() -> dict[str, object]:
    return {
        "schema_version": "scheduler_occurrence_credential_claims@1",
        "occurrence_id": "occurrence_1",
        "dispatch_id": "dispatch_1",
        "execution_id": "execution_1",
        "execution_fencing_token": 3,
        "target_profile_digest": DIGEST,
        "reservation_nonce_digest": DIGEST,
        "scheduler_marker": "marker_1",
        "payload_digest": DIGEST,
        "protected_wrapper_audience": "wrapper_1",
        "expires_at": "2026-08-17T01:05:00+00:00",
    }


class _IssuerExecutor:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def run(
        self,
        argv: tuple[str, ...],
        *,
        stdin: str,
        timeout_seconds: int,
    ) -> ExecutorHpcCredentialCommandResult:
        assert argv == ("/usr/local/bin/issue-scheduler-occurrence",)
        assert timeout_seconds == 17
        self.request = json.loads(stdin)
        claims_digest = str(self.request["claims_digest"])
        return ExecutorHpcCredentialCommandResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "schema_version": (
                        "scheduler_occurrence_credential_issue_result@1"
                    ),
                    "claims_digest": claims_digest,
                    "occurrence_id": "occurrence_1",
                    "credential_fingerprint": DIGEST,
                    "authentication_receipt_digest": DIGEST,
                    "issued_at": "2026-08-17T01:00:01+00:00",
                    "opaque_token": "opaque-single-use-token",
                }
            ),
            stderr="",
        )


def test_scheduler_credential_command_is_exact_and_scheduler_only() -> None:
    executor = _IssuerExecutor()
    issuer = CommandRunnerSchedulerCredentialIssuer(
        issue_command=("/usr/local/bin/issue-scheduler-occurrence",),
        executor=executor,
        timeout_seconds=17,
    )

    issued = issuer.issue_occurrence(_claims())

    assert issued["occurrence_id"] == "occurrence_1"
    assert issued["opaque_token"] == "opaque-single-use-token"
    assert executor.request is not None
    assert executor.request["login_or_file_authority"] is False
    assert executor.request["interactive_authority"] is False
    encoded = json.dumps(
        _claims(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert executor.request["claims_digest"] == (
        "sha256:" + hashlib.sha256(encoded).hexdigest()
    )


def test_scheduler_credential_command_rejects_open_or_drifted_claims() -> None:
    issuer = CommandRunnerSchedulerCredentialIssuer(
        issue_command=("/usr/local/bin/issue-scheduler-occurrence",),
        executor=_IssuerExecutor(),
    )

    with pytest.raises(ValueError, match="claims are not closed"):
        issuer.issue_occurrence({**_claims(), "ssh_private_key": "forbidden"})


def _runner_handle() -> dict[str, Any]:
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
        "accepted_at": "2026-08-18T00:00:00+00:00",
        "credential_consumed_at": None,
        "credential_consumption_receipt_digest": None,
    }
    return {**payload, "handle_digest": canonical_workspace_job_wire_digest(payload)}


def _domain_handle() -> ExternalJobHandle:
    return ExternalJobHandle.create(
        handle_id="handle_1",
        execution_id="execution_1",
        operation_id="operation_1",
        dispatch_id="dispatch_1",
        runner_run_id="run_1",
        job_root_token="job_root_1",
        target_profile_digest=DIGEST,
        workspace_id="workspace_1",
        remote_workspace_generation=1,
        source_commit="1" * 40,
        source_manifest_digest=DIGEST,
        backend=WorkspaceExternalBackend.DIRECT,
        raw_handle_ciphertext="private-ciphertext",
        acceptance_receipt_digest=DIGEST,
        accepted_at="2026-08-18T00:00:00+00:00",
    )


def _intent() -> WorkspaceJobDispatchIntent:
    return WorkspaceJobDispatchIntent.create(
        dispatch_id="dispatch_1",
        execution_id="execution_1",
        operation_id="operation_1",
        execution_state_version=2,
        execution_fencing_token=7,
        request_id="request_1",
        request_digest=DIGEST,
        runner_run_id="run_1",
        workspace_id="workspace_1",
        remote_workspace_generation=1,
        source_manifest_digest=DIGEST,
        selected_mode=WorkspaceJobExecutionMode.SSH,
        command_digest=DIGEST,
        resource_digest=DIGEST,
        target_profile_digest=DIGEST,
        scheduler_marker="marker_1",
        payload_digest=DIGEST,
        absolute_deadline="2027-08-18T00:00:00+00:00",
        created_at="2026-08-18T00:00:00+00:00",
    )


class _CanonicalRunner:
    def observe(self, runner_run_id: str, *, observation_index: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "external_job_observation@1",
            "observation_id": "job_observation_handle_1_1",
            "handle_id": "handle_1",
            "execution_id": "execution_1",
            "dispatch_id": "dispatch_1",
            "observation_index": observation_index,
            "state": "running",
            "exit_code": None,
            "terminal_receipt_digest": None,
            "bounded_stdout": None,
            "bounded_stderr": None,
            "observed_at": "2026-08-18T00:00:00+00:00",
        }
        assert runner_run_id == "run_1"
        return {
            **payload,
            "observation_digest": canonical_workspace_job_wire_digest(payload),
        }

    def cancel(
        self,
        runner_run_id: str,
        *,
        cancellation: dict[str, Any],
    ) -> dict[str, Any]:
        assert runner_run_id == "run_1"
        return serialize_workspace_job_cancellation_receipt(
            receipt_id="cancel_receipt_1",
            cancellation_id=str(cancellation["cancellation_id"]),
            handle_id=str(cancellation["handle_id"]),
            backend_receipt_digest=DIGEST,
            created_at="2026-08-18T00:00:00+00:00",
        )


class _ReconcileOnlyRunner:
    def __init__(self) -> None:
        self.reconcile_calls = 0

    def reconcile(self, runner_run_id: str) -> dict[str, Any]:
        assert runner_run_id == "run_1"
        self.reconcile_calls += 1
        return _runner_handle()

    def dispatch_direct(self, _runspec: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("Host restart reconciliation must not dispatch")


def test_host_maps_canonical_runner_handle_without_rebuilding_wire_digest() -> None:
    response = HostWorkspaceJobBackend._dispatch_response(
        _runner_handle(),
        expected_handle={
            "execution_id": "execution_1",
            "operation_id": "operation_1",
            "dispatch_id": "dispatch_1",
            "runner_run_id": "run_1",
            "target_profile_digest": DIGEST,
            "workspace_id": "workspace_1",
            "remote_workspace_generation": 1,
            "source_commit": "1" * 40,
            "source_manifest_digest": DIGEST,
            "backend": "direct",
        },
    )

    assert response.backend is WorkspaceExternalBackend.DIRECT
    assert response.raw_handle_ciphertext == "private-ciphertext"
    assert response.acceptance_receipt_digest == DIGEST


def test_host_rejects_caller_raw_handle_injection_and_extra_wire_fields() -> None:
    injected = _runner_handle()
    injected["raw_handle"] = "ssh://private-host/caller-controlled"

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        HostWorkspaceJobBackend._dispatch_response(
            injected,
            expected_handle={
                "execution_id": "execution_1",
                "operation_id": "operation_1",
                "dispatch_id": "dispatch_1",
                "runner_run_id": "run_1",
                "target_profile_digest": DIGEST,
                "workspace_id": "workspace_1",
                "remote_workspace_generation": 1,
                "source_commit": "1" * 40,
                "source_manifest_digest": DIGEST,
                "backend": "direct",
            },
        )

    assert captured.value.error_code == "workspace_job_wire_fields_mismatch"


def test_reconstructed_host_backend_reconciles_exact_runner_identity_without_dispatch() -> None:
    runner = _ReconcileOnlyRunner()
    request = SimpleNamespace(source_commit="1" * 40)
    intent = _intent()

    first = HostWorkspaceJobBackend(
        repositories=SimpleNamespace(),  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
    ).reconcile(
        request=request,  # type: ignore[arg-type]
        manifest=SimpleNamespace(),  # type: ignore[arg-type]
        intent=intent,
    )
    restarted = HostWorkspaceJobBackend(
        repositories=SimpleNamespace(),  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
    ).reconcile(
        request=request,  # type: ignore[arg-type]
        manifest=SimpleNamespace(),  # type: ignore[arg-type]
        intent=intent,
    )

    assert first == restarted
    assert first.disposition.value == "accepted"
    assert runner.reconcile_calls == 2


def test_host_round_trips_observation_and_cancellation_into_domain_records() -> None:
    backend = HostWorkspaceJobBackend(
        repositories=SimpleNamespace(),  # type: ignore[arg-type]
        runner=_CanonicalRunner(),  # type: ignore[arg-type]
    )
    intent = _intent()
    handle = _domain_handle()
    cancellation = WorkspaceJobCancellationIntent.create(
        cancellation_id="cancel_1",
        execution_id="execution_1",
        handle_id="handle_1",
        execution_state_version=3,
        execution_fencing_token=7,
        idempotency_key="cancel-key-1",
        reason_digest=DIGEST,
        created_at="2026-08-18T00:00:00+00:00",
    )

    observation = backend.observe(
        request=SimpleNamespace(),  # type: ignore[arg-type]
        intent=intent,
        handle=handle,
        observation_index=1,
    )
    receipt = backend.cancel(
        request=SimpleNamespace(),  # type: ignore[arg-type]
        intent=intent,
        handle=handle,
        cancellation=cancellation,
    )

    assert observation.observation_id == "job_observation_handle_1_1"
    assert observation.observation_digest is not None
    assert receipt.receipt_id == "cancel_receipt_1"
    assert receipt.cancellation_requested is True
    assert receipt.terminal_settlement_proven is False
