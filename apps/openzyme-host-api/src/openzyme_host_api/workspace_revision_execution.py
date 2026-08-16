from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Protocol

from openzyme_core import ControlledOperationExecutionLeaseService
from openzyme_core import ControlledOperationExecutionWorkerOutcome
from openzyme_core import CoreRepositories
from openzyme_core import IssuedSchedulerCredential
from openzyme_core import SchedulerCredentialProvider
from openzyme_core import WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID
from openzyme_core import WorkspaceDispatchDisposition
from openzyme_core import WorkspaceJobBackend
from openzyme_core import WorkspaceJobDispatchResponse
from openzyme_core import WorkspaceJobObservationReceipt
from openzyme_core import WorkspaceRevisionExecutionWorker
from openzyme_core import WorkspaceRevisionSourcePreparer
from openzyme_domain import ComputeSourceManifest
from openzyme_domain import ComputeSourceManifestEntry
from openzyme_domain import ExternalJobHandle
from openzyme_domain import SchedulerCredentialOccurrence
from openzyme_domain import WorkspaceExternalBackend
from openzyme_domain import WorkspaceJobCancellationIntent
from openzyme_domain import WorkspaceJobCancellationReceipt
from openzyme_domain import WorkspaceJobDispatchIntent
from openzyme_domain import WorkspaceJobExecutionMode
from openzyme_domain import WorkspaceJobObservationState
from openzyme_domain import WorkspaceRevisionExecutionRequest
from openzyme_execution import WorkspaceRevisionRunnerAdapter


class RunnerSchedulerCredentialIssuer(Protocol):
    """Issue one opaque token for one already-reserved scheduler occurrence."""

    def issue_occurrence(self, claims: dict[str, object]) -> dict[str, str]: ...


class UnavailableRunnerSchedulerCredentialIssuer:
    def issue_occurrence(self, claims: dict[str, object]) -> dict[str, str]:
        del claims
        raise RuntimeError(
            "scheduler occurrence credential provider is not configured or qualified"
        )


RepositoryScopeFactory = Callable[[], AbstractContextManager[CoreRepositories]]


@dataclass(slots=True)
class WorkspaceRevisionExecutionDurableWorker:
    repository_scope_factory: RepositoryScopeFactory
    runner: WorkspaceRevisionRunnerAdapter
    scheduler_credential_issuer: RunnerSchedulerCredentialIssuer
    worker_id: str
    lease_seconds: int = 30

    def run_once(self) -> ControlledOperationExecutionWorkerOutcome:
        with self.repository_scope_factory() as repositories:
            candidates = tuple(
                execution
                for execution in repositories.controlled_operation_executions.list_claimable(
                    now_iso=self._now_iso(),
                    limit=32,
                )
                if execution.route_policy_id
                == WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID
            )
        if not candidates:
            return ControlledOperationExecutionWorkerOutcome(
                execution_id=None,
                action="idle",
                semantic_progress=False,
                lifecycle_state=None,
                state_version=None,
                effect_certainty=None,
                retry_eligibility=None,
            )
        with self.repository_scope_factory() as repositories:
            claimed = ControlledOperationExecutionLeaseService(repositories).claim(
                candidates[0].execution_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if claimed is None:
                return ControlledOperationExecutionWorkerOutcome(
                    execution_id=candidates[0].execution_id,
                    action="claim_raced",
                    semantic_progress=False,
                    lifecycle_state=None,
                    state_version=None,
                    effect_certainty=None,
                    retry_eligibility=None,
                )
            service = WorkspaceRevisionExecutionWorker(
                repositories=repositories,
                source_preparer=HostWorkspaceRevisionSourcePreparer(
                    repositories,
                    self.runner,
                ),
                backend=HostWorkspaceJobBackend(repositories, self.runner),
                scheduler_credentials=HostRunnerSchedulerCredentialProvider(
                    self.scheduler_credential_issuer
                ),
            )
            try:
                intent = (
                    repositories.workspace_revision_executions.get_dispatch_intent_by_execution(
                        claimed.execution_id
                    )
                )
                if claimed.lifecycle_state.value in {"claimed", "dispatching"}:
                    if intent is None:
                        request = repositories.workspace_revision_executions.get_request_by_execution(
                            claimed.execution_id
                        )
                        if request is None:
                            raise RuntimeError(
                                "workspace execution request disappeared before dispatch"
                            )
                        updated = service.dispatch(
                            claimed,
                            scheduler_credential_expires_at=request.absolute_deadline,
                        )
                        action = "dispatched"
                    else:
                        updated = service.reconcile(claimed)
                        action = "reconciled"
                elif claimed.lifecycle_state.value == "reconcile_required":
                    updated = service.reconcile(claimed)
                    action = "reconciled"
                elif claimed.lifecycle_state.value == "waiting_external":
                    updated = service.observe(claimed)
                    action = "observed"
                else:
                    updated = claimed
                    action = "not_claimable"
            except Exception:
                current = repositories.controlled_operation_executions.get(
                    claimed.execution_id
                )
                if (
                    current is not None
                    and current.lease_token == claimed.lease_token
                    and current.fencing_token == claimed.fencing_token
                    and current.lease_token is not None
                ):
                    ControlledOperationExecutionLeaseService(repositories).release(
                        current.execution_id,
                        lease_token=current.lease_token,
                        fencing_token=current.fencing_token,
                        expected_state_version=current.state_version,
                    )
                raise
        return ControlledOperationExecutionWorkerOutcome(
            execution_id=updated.execution_id,
            action=action,
            semantic_progress=updated.state_version != claimed.state_version,
            lifecycle_state=updated.lifecycle_state.value,
            state_version=updated.state_version,
            effect_certainty=updated.effect_certainty.value,
            retry_eligibility=updated.retry_eligibility.value,
        )

    @staticmethod
    def _now_iso() -> str:
        from datetime import UTC
        from datetime import datetime

        return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class HostRunnerSchedulerCredentialProvider(SchedulerCredentialProvider):
    issuer: RunnerSchedulerCredentialIssuer

    def issue(
        self,
        occurrence: SchedulerCredentialOccurrence,
    ) -> IssuedSchedulerCredential:
        response = self.issuer.issue_occurrence(
            {
                "schema_version": "scheduler_occurrence_credential_claims@1",
                "occurrence_id": occurrence.occurrence_id,
                "dispatch_id": occurrence.dispatch_id,
                "execution_id": occurrence.execution_id,
                "execution_fencing_token": occurrence.execution_fencing_token,
                "target_profile_digest": occurrence.target_profile_digest,
                "reservation_nonce_digest": occurrence.reservation_nonce_digest,
                "scheduler_marker": occurrence.scheduler_marker,
                "payload_digest": occurrence.payload_digest,
                "protected_wrapper_audience": occurrence.protected_wrapper_audience,
                "expires_at": occurrence.expires_at,
            }
        )
        expected = {
            "occurrence_id",
            "credential_fingerprint",
            "authentication_receipt_digest",
            "issued_at",
            "opaque_token",
        }
        if not isinstance(response, dict) or set(response) != expected:
            raise ValueError("scheduler credential issuer response fields are closed")
        return IssuedSchedulerCredential(**response)


@dataclass(slots=True)
class HostWorkspaceRevisionSourcePreparer(WorkspaceRevisionSourcePreparer):
    repositories: CoreRepositories
    runner: WorkspaceRevisionRunnerAdapter

    def prepare(
        self,
        request: WorkspaceRevisionExecutionRequest,
    ) -> ComputeSourceManifest:
        workspace = self.repositories.executor_hpc_workspaces.get(
            request.executor_hpc_workspace_id
        )
        binding = self.repositories.project_repository_bindings.get(
            request.repository_binding_id
        )
        target = self.repositories.executor_hpc_workspaces.get_target_qualification(
            request.target_profile_id
        )
        if workspace is None or binding is None or target is None:
            raise ValueError("workspace source preparation identity is unavailable")
        response = self.runner.prepare_source(
            {
                "schema_version": "workspace_revision_source_prepare_request@1",
                "request_id": request.request_id,
                "workspace_id": request.executor_hpc_workspace_id,
                "remote_workspace_generation": request.remote_workspace_generation,
                "repository_binding_id": request.repository_binding_id,
                "repository_binding_version": request.repository_binding_version,
                "repository_binding_digest": binding.canonical_digest,
                "repository_policy_digest": binding.repository_policy_digest,
                "target_profile_digest": request.target_profile_digest,
                "runner_policy_digest": request.runner_policy_digest,
                "source_commit": request.source_commit,
                "source_tree": request.source_tree,
                "source_ref": request.source_ref,
                "lfs_closure_manifest_digest": (
                    request.lfs_closure_manifest_digest
                ),
                "toolchain_digest": target.toolchain_digest,
                "owner_identity_digest": workspace.os_principal_identity_digest,
                "absolute_deadline": request.absolute_deadline,
                "request_digest": request.request_digest,
            }
        )
        entries = response.get("entries")
        if not isinstance(entries, list):
            raise ValueError("runner source manifest entries are invalid")
        return ComputeSourceManifest(
            manifest_id=response["manifest_id"],
            request_id=response["request_id"],
            workspace_id=response["workspace_id"],
            source_commit=response["source_commit"],
            source_tree=response["source_tree"],
            lfs_closure_manifest_digest=response["lfs_closure_manifest_digest"],
            binding_digest=response["binding_digest"],
            repository_policy_digest=response["repository_policy_digest"],
            toolchain_digest=response["toolchain_digest"],
            owner_identity_digest=response["owner_identity_digest"],
            entries=tuple(
                ComputeSourceManifestEntry(
                    path=item["path"],
                    object_id=item["object_id"],
                    mode=item["mode"],
                    size_bytes=item["size_bytes"],
                    content_digest=item["content_digest"],
                    lfs_oid=item["lfs_oid"],
                )
                for item in entries
            ),
            created_at=response["created_at"],
            manifest_digest=response["manifest_digest"],
        )


@dataclass(slots=True)
class HostWorkspaceJobBackend(WorkspaceJobBackend):
    repositories: CoreRepositories
    runner: WorkspaceRevisionRunnerAdapter

    def dispatch(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
        intent: WorkspaceJobDispatchIntent,
        scheduler_credential: IssuedSchedulerCredential | None,
    ) -> WorkspaceJobDispatchResponse:
        runspec = self._runspec(request=request, manifest=manifest, intent=intent)
        try:
            if intent.selected_mode is WorkspaceJobExecutionMode.SBATCH:
                if scheduler_credential is None:
                    raise ValueError(
                        "Slurm dispatch lacks its issued occurrence credential"
                    )
                occurrence = (
                    self.repositories.workspace_revision_executions.get_scheduler_occurrence(
                        scheduler_credential.occurrence_id
                    )
                )
                if occurrence is None:
                    raise ValueError("issued scheduler occurrence disappeared")
                response = self.runner.dispatch_slurm(
                    runspec,
                    scheduler_credential={
                        "schema_version": "scheduler_occurrence_credential@1",
                        "occurrence_id": occurrence.occurrence_id,
                        "dispatch_id": occurrence.dispatch_id,
                        "execution_id": occurrence.execution_id,
                        "target_profile_digest": occurrence.target_profile_digest,
                        "reservation_nonce_digest": occurrence.reservation_nonce_digest,
                        "scheduler_marker": occurrence.scheduler_marker,
                        "payload_digest": occurrence.payload_digest,
                        "protected_wrapper_audience": (
                            occurrence.protected_wrapper_audience
                        ),
                        "expires_at": occurrence.expires_at,
                        "opaque_token": scheduler_credential.opaque_token,
                    },
                )
            else:
                if scheduler_credential is not None:
                    raise ValueError("direct dispatch rejects a scheduler credential")
                response = self.runner.dispatch_direct(runspec)
        except Exception as exc:
            error_code = str(getattr(exc, "error_code", "workspace_dispatch_rejected"))
            disposition = (
                WorkspaceDispatchDisposition.IN_DOUBT
                if error_code == "workspace_revision_job_dispatch_in_doubt"
                else WorkspaceDispatchDisposition.REJECTED_NO_EFFECT
            )
            return WorkspaceJobDispatchResponse(
                disposition=disposition,
                safe_error_code=error_code,
            )
        return self._dispatch_response(response)

    def reconcile(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
        intent: WorkspaceJobDispatchIntent,
    ) -> WorkspaceJobDispatchResponse:
        return self._dispatch_response(
            self.runner.reconcile(intent.runner_run_id)
        )

    def observe(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
        handle: ExternalJobHandle,
        observation_index: int,
    ) -> WorkspaceJobObservationReceipt:
        response = self.runner.observe(
            handle.runner_run_id,
            observation_index=observation_index,
        )
        return WorkspaceJobObservationReceipt(
            observation_id=response["observation_id"],
            observation_index=response["observation_index"],
            state=WorkspaceJobObservationState(response["state"]),
            observed_at=response["observed_at"],
            exit_code=response["exit_code"],
            terminal_receipt_digest=response["terminal_receipt_digest"],
            bounded_stdout=response["bounded_stdout"],
            bounded_stderr=response["bounded_stderr"],
            observation_digest=response["observation_digest"],
        )

    def cancel(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
        handle: ExternalJobHandle,
        cancellation: WorkspaceJobCancellationIntent,
    ) -> WorkspaceJobCancellationReceipt:
        response = self.runner.cancel(
            handle.runner_run_id,
            cancellation=cancellation.payload,
        )
        return WorkspaceJobCancellationReceipt(
            receipt_id=response["receipt_id"],
            cancellation_id=response["cancellation_id"],
            handle_id=response["handle_id"],
            cancellation_requested=response["cancellation_requested"],
            terminal_settlement_proven=response["terminal_settlement_proven"],
            backend_receipt_digest=response["backend_receipt_digest"],
            created_at=response["created_at"],
            receipt_digest=response["receipt_digest"],
        )

    def _require_manifest(
        self,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
    ) -> ComputeSourceManifest:
        manifest = self.repositories.workspace_revision_executions.get_manifest_by_request(
            request.request_id
        )
        if manifest is None or manifest.manifest_digest != intent.source_manifest_digest:
            raise ValueError("workspace job manifest identity drifted")
        return manifest

    def _runspec(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
        intent: WorkspaceJobDispatchIntent,
    ) -> dict[str, Any]:
        binding = self.repositories.project_repository_bindings.get(
            request.repository_binding_id
        )
        target = self.repositories.executor_hpc_workspaces.get_target_qualification(
            request.target_profile_id
        )
        if binding is None or target is None:
            raise ValueError("workspace job binding or target identity disappeared")
        return {
            "schema_version": "executor_workspace_runspec@2",
            "execution_id": intent.execution_id,
            "operation_id": intent.operation_id,
            "dispatch_id": intent.dispatch_id,
            "runner_run_id": intent.runner_run_id,
            "executor_hpc_workspace_id": intent.workspace_id,
            "executor_hpc_workspace_generation": intent.remote_workspace_generation,
            "repository_binding_id": request.repository_binding_id,
            "repository_binding_version": request.repository_binding_version,
            "repository_binding_digest": binding.canonical_digest,
            "repository_policy_digest": binding.repository_policy_digest,
            "source_manifest_id": manifest.manifest_id,
            "source_request_id": manifest.request_id,
            "source_commit": request.source_commit,
            "source_tree": request.source_tree,
            "lfs_closure_manifest_digest": request.lfs_closure_manifest_digest,
            "source_manifest": [entry.to_dict() for entry in manifest.entries],
            "source_manifest_digest": manifest.manifest_digest,
            "source_owner_identity_digest": manifest.owner_identity_digest,
            "source_manifest_created_at": manifest.created_at,
            "target_profile_digest": intent.target_profile_digest,
            "runner_policy_digest": request.runner_policy_digest,
            "toolchain_digest": target.toolchain_digest,
            "cwd": request.cwd,
            "command": list(request.command),
            "command_digest": intent.command_digest,
            "environment_policy_digest": request.environment_policy_digest,
            "resources": request.resources,
            "resource_digest": intent.resource_digest,
            "selected_mode": intent.selected_mode.value,
            "scheduler_marker": intent.scheduler_marker,
            "payload_digest": intent.payload_digest,
            "absolute_deadline": intent.absolute_deadline,
        }

    @staticmethod
    def _dispatch_response(response: dict[str, Any]) -> WorkspaceJobDispatchResponse:
        disposition = WorkspaceDispatchDisposition(response["disposition"])
        if disposition is not WorkspaceDispatchDisposition.ACCEPTED:
            return WorkspaceJobDispatchResponse(
                disposition=disposition,
                safe_error_code=response.get("safe_error_code"),
                safe_receipt_digest=response.get("reconciliation_receipt_digest"),
            )
        return WorkspaceJobDispatchResponse(
            disposition=disposition,
            backend=WorkspaceExternalBackend(response["backend"]),
            raw_handle_ciphertext=response["raw_handle_ciphertext"],
            acceptance_receipt_digest=response["acceptance_receipt_digest"],
            accepted_at=response["accepted_at"],
            job_root_token=response["job_root_token"],
            credential_consumed_at=response["credential_consumed_at"],
            credential_consumption_receipt_digest=response[
                "credential_consumption_receipt_digest"
            ],
        )


__all__ = [
    "HostRunnerSchedulerCredentialProvider",
    "HostWorkspaceJobBackend",
    "HostWorkspaceRevisionSourcePreparer",
    "RunnerSchedulerCredentialIssuer",
    "UnavailableRunnerSchedulerCredentialIssuer",
    "WorkspaceRevisionExecutionDurableWorker",
]
