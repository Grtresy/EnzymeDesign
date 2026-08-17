from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Iterator

from openzyme_core import AgentCapsuleControlHandler
from openzyme_core import AgentCapsuleControlHandlerFactory
from openzyme_core import AgentCapsuleHostAuthority
from openzyme_core import ControlledOperationExecutionLeaseService
from openzyme_core import CoreRepositories
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import FileWorkspaceControlDispatcher
from openzyme_core import FileWorkspaceHostOperation
from openzyme_core import FileWorkspaceHostRequest
from openzyme_core import FileWorkspaceSandboxHostGateway
from openzyme_core import MutationWriterTurnFactory
from openzyme_core import SandboxHostCallContext
from openzyme_core import ScientificFileEffectAdoptionService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import WorkspaceRevisionExecutionAdmission
from openzyme_core import WorkspaceRevisionExecutionAdmissionService
from openzyme_core import WorkspaceRevisionExecutionWorker
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import MutationWriterKind
from openzyme_domain import WorkspaceRevisionCleanObservation
from openzyme_domain import WorkspaceRevisionExecutionRequest

from .aox_file_bundle_finalizer import AoxFileBundleFinalizer
from .scientific_publication_reader import DurableScientificPublicationReader
from .workspace_revision_execution import HostRunnerSchedulerCredentialProvider
from .workspace_revision_execution import HostWorkspaceJobBackend
from .workspace_revision_execution import HostWorkspaceRevisionSourcePreparer
from .workspace_revision_execution import RunnerSchedulerCredentialIssuer
from .workspace_revision_execution import WorkspaceRevisionRunnerAdapter


class FileWorkspaceControlGatewayError(RuntimeError):
    error_code = "file_workspace_control_gateway_rejected"
    retryable = False


@dataclass(frozen=True, slots=True)
class FileWorkspaceRepositoryScopes:
    provider: SQLiteRepositoryProvider | None
    legacy_repositories: CoreRepositories | None = None

    def __post_init__(self) -> None:
        if (self.provider is None) == (self.legacy_repositories is None):
            raise ValueError("one exact repository scope owner is required")

    @contextmanager
    def open(self) -> Iterator[CoreRepositories]:
        if self.provider is not None:
            with self.provider.connection_scope() as scope:
                yield scope.repositories
            return
        assert self.legacy_repositories is not None
        yield self.legacy_repositories

    def mutation_writer_scope(
        self,
        *,
        session_id: str,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> object:
        return MutationWriterTurnFactory(
            repository_scope_factory=self.open
        ).open(
            session_id=session_id,
            owner_kind=owner_kind,
            owner_ref=owner_ref,
            process_epoch=process_epoch,
        )


@dataclass(frozen=True, slots=True)
class HostAgentCapsuleControlHandlerFactory(AgentCapsuleControlHandlerFactory):
    scopes: FileWorkspaceRepositoryScopes
    roots: DurableRepositoryRootManager | None
    runner: WorkspaceRevisionRunnerAdapter | None
    scheduler_credential_issuer: RunnerSchedulerCredentialIssuer | None
    durable_work_notifier: object | None = None

    def create(
        self,
        *,
        authority: AgentCapsuleHostAuthority,
    ) -> AgentCapsuleControlHandler:
        return HostAgentCapsuleControlHandler(factory=self, authority=authority)


@dataclass(frozen=True, slots=True)
class HostAgentCapsuleControlHandler(AgentCapsuleControlHandler):
    factory: HostAgentCapsuleControlHandlerFactory
    authority: AgentCapsuleHostAuthority

    def dispatch(self, method: str, params: dict[str, object]) -> dict[str, object]:
        with self.factory.scopes.open() as repositories:
            context = SandboxHostCallContext(
                repositories=repositories,
                owner=self.authority,
                mutation_writer_scope_factory=(
                    self.factory.scopes.mutation_writer_scope
                ),
            )
            dispatcher = FileWorkspaceControlDispatcher(
                session_id=self.authority.session_id,
                gateway=HostFileWorkspaceControlGateway(
                    repositories=repositories,
                    roots=self.factory.roots,
                    runner=self.factory.runner,
                    scheduler_credential_issuer=(
                        self.factory.scheduler_credential_issuer
                    ),
                    durable_work_notifier=self.factory.durable_work_notifier,
                ),
                context=context,
            )
            return dispatcher.dispatch(method, params)


@dataclass(slots=True)
class HostFileWorkspaceControlGateway(FileWorkspaceSandboxHostGateway):
    repositories: CoreRepositories
    roots: DurableRepositoryRootManager | None
    runner: WorkspaceRevisionRunnerAdapter | None
    scheduler_credential_issuer: RunnerSchedulerCredentialIssuer | None
    durable_work_notifier: object | None = None

    def invoke_control_plane(
        self,
        *,
        request: FileWorkspaceHostRequest,
        context: SandboxHostCallContext,
    ) -> dict[str, object]:
        context.require_session(request.session_id)
        authority = context.require_current_agent_capsule()
        if request.operation is FileWorkspaceHostOperation.EXTERNAL_JOB_DISPATCH:
            return self._submit(request.body, context=context, authority=authority)
        if request.operation is FileWorkspaceHostOperation.EXTERNAL_JOB_RECONCILE:
            return self._observe(request.body, authority=authority)
        if request.operation is FileWorkspaceHostOperation.EXTERNAL_JOB_CANCEL:
            return self._cancel(request.body, context=context, authority=authority)
        if request.operation is FileWorkspaceHostOperation.SCIENTIFIC_DELIVERABLE_ADOPT:
            return self._adopt_scientific_result(
                request.body,
                context=context,
                authority=authority,
            )
        if request.operation is FileWorkspaceHostOperation.SCIENTIFIC_DELIVERABLE_FINALIZE:
            return self._finalize(request.body, context=context, authority=authority)
        raise FileWorkspaceControlGatewayError(
            f"operation {request.operation.value!r} is not installed on the capsule gateway"
        )

    def _submit(
        self,
        body: dict[str, object],
        *,
        context: SandboxHostCallContext,
        authority: AgentCapsuleHostAuthority,
    ) -> dict[str, object]:
        if set(body) != {
            "schema_version",
            "operation",
            "execution_request",
            "clean_observation",
        } or body.get("schema_version") != "workspace_revision_job_admission_request@1":
            raise FileWorkspaceControlGatewayError(
                "workspace revision admission request fields are closed"
            )
        operation = _controlled_operation(body["operation"])
        execution_request = WorkspaceRevisionExecutionRequest.from_dict(
            _object(body["execution_request"], "execution_request")
        )
        observation = WorkspaceRevisionCleanObservation.from_dict(
            _object(body["clean_observation"], "clean_observation")
        )
        hpc_workspace = self.repositories.executor_hpc_workspaces.get(
            execution_request.executor_hpc_workspace_id
        )
        if (
            operation.session_id != authority.session_id
            or execution_request.session_id != authority.session_id
            or execution_request.executor_agent_member_id
            != authority.agent_member_id
            or execution_request.capability_lease_id
            != authority.capability_lease_id
            or execution_request.capability_lease_version
            != authority.capability_lease_version
            or hpc_workspace is None
            or hpc_workspace.local_workspace_id != authority.workspace_id
            or hpc_workspace.local_workspace_generation
            != authority.workspace_generation
        ):
            raise FileWorkspaceControlGatewayError(
                "workspace revision request crossed its capsule owner or lease boundary"
            )
        with context.child_mutation_writer(
            owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
            owner_ref=operation.operation_id,
            process_epoch=authority.process_epoch,
        ):
            with self.repositories.atomic(prefix="capsule_workspace_job_admission"):
                existing = self.repositories.controlled_operations.get(
                    operation.operation_id
                )
                if existing is None:
                    self.repositories.controlled_operations.save(operation)
                elif existing != operation:
                    raise FileWorkspaceControlGatewayError(
                        "workspace execution operation identity conflicts"
                    )
                execution = WorkspaceRevisionExecutionAdmissionService(
                    self.repositories
                ).admit(
                    WorkspaceRevisionExecutionAdmission(
                        operation=operation,
                        request=execution_request,
                        clean_observation=observation,
                    )
                )
        notifier = self.durable_work_notifier
        if notifier is not None:
            notify = getattr(notifier, "notify", None)
            if notify is None:
                raise FileWorkspaceControlGatewayError(
                    "durable work notifier does not implement the closed notify contract"
                )
            notify(authority.session_id)
        return {
            "schema_version": "workspace_revision_job_admission_result@1",
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "request_id": execution_request.request_id,
            "lifecycle_state": execution.lifecycle_state.value,
            "effect_certainty": execution.effect_certainty.value,
            "state_version": execution.state_version,
            "pending_human_approval_created": False,
        }

    def _observe(
        self,
        body: dict[str, object],
        *,
        authority: AgentCapsuleHostAuthority,
    ) -> dict[str, object]:
        execution, execution_request = self._require_job_identity(body, authority)
        result = self.repositories.workspace_revision_executions.get_result_by_execution(
            execution.execution_id
        )
        return {
            "schema_version": "workspace_revision_job_observation@1",
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "request_id": execution_request.request_id,
            "lifecycle_state": execution.lifecycle_state.value,
            "effect_certainty": execution.effect_certainty.value,
            "retry_eligibility": execution.retry_eligibility.value,
            "state_version": execution.state_version,
            "terminal_outcome": (
                None
                if execution.terminal_outcome is None
                else execution.terminal_outcome.value
            ),
            "result": None if result is None else result.to_safe_dict(),
        }

    def _cancel(
        self,
        body: dict[str, object],
        *,
        context: SandboxHostCallContext,
        authority: AgentCapsuleHostAuthority,
    ) -> dict[str, object]:
        if set(body) != {"execution_id", "operation_id", "request_id", "reason_code"}:
            raise FileWorkspaceControlGatewayError(
                "workspace cancellation request fields are closed"
            )
        execution, execution_request = self._require_job_identity(
            {key: body[key] for key in ("execution_id", "operation_id", "request_id")},
            authority,
        )
        reason_code = body["reason_code"]
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise FileWorkspaceControlGatewayError("cancellation reason_code is required")
        if self.runner is None or self.scheduler_credential_issuer is None:
            raise FileWorkspaceControlGatewayError(
                "workspace cancellation backend is not configured"
            )
        cancellation_id = "workspace_cancel_" + _digest(
            {
                "execution_id": execution.execution_id,
                "request_id": execution_request.request_id,
                "reason_code": reason_code,
            }
        ).removeprefix("sha256:")[:32]
        existing = self.repositories.workspace_revision_executions.get_cancellation_receipt(
            cancellation_id
        )
        if existing is not None:
            return {"schema_version": "workspace_revision_job_cancel_result@1", **existing.payload}
        with context.child_mutation_writer(
            owner_kind=MutationWriterKind.RUNNER_CALLBACK,
            owner_ref=execution.execution_id,
            process_epoch=authority.process_epoch,
        ):
            claimed = ControlledOperationExecutionLeaseService(
                self.repositories
            ).claim(
                execution.execution_id,
                worker_id=f"capsule-cancel:{authority.process_epoch}",
                lease_seconds=30,
            )
            if claimed is None:
                raise FileWorkspaceControlGatewayError(
                    "workspace execution is currently owned by another durable worker"
                )
            try:
                service = WorkspaceRevisionExecutionWorker(
                    repositories=self.repositories,
                    source_preparer=HostWorkspaceRevisionSourcePreparer(
                        self.repositories,
                        self.runner,
                    ),
                    backend=HostWorkspaceJobBackend(self.repositories, self.runner),
                    scheduler_credentials=HostRunnerSchedulerCredentialProvider(
                        self.scheduler_credential_issuer
                    ),
                )
                receipt = service.cancel(
                    claimed,
                    cancellation_id=cancellation_id,
                    idempotency_key=cancellation_id,
                    reason_digest=_digest({"reason_code": reason_code}),
                    created_at=datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
                )
            finally:
                current = self.repositories.controlled_operation_executions.get(
                    claimed.execution_id
                )
                if (
                    current is not None
                    and current.lease_token == claimed.lease_token
                    and current.fencing_token == claimed.fencing_token
                    and current.lease_token is not None
                ):
                    ControlledOperationExecutionLeaseService(
                        self.repositories
                    ).release(
                        current.execution_id,
                        lease_token=current.lease_token,
                        fencing_token=current.fencing_token,
                        expected_state_version=current.state_version,
                    )
        return {"schema_version": "workspace_revision_job_cancel_result@1", **receipt.payload}

    def _adopt_scientific_result(
        self,
        body: dict[str, object],
        *,
        context: SandboxHostCallContext,
        authority: AgentCapsuleHostAuthority,
    ) -> dict[str, object]:
        expected = {
            "schema_version",
            "selection_id",
            "operation_id",
            "execution_id",
            "result_id",
            "workflow_role",
            "execution_fencing_token",
            "idempotency_key",
        }
        if (
            set(body) != expected
            or body.get("schema_version")
            != "scientific_file_effect_adoption_request@1"
        ):
            raise FileWorkspaceControlGatewayError(
                "scientific result adoption request fields are closed"
            )
        values = {
            name: body[name]
            for name in (
                "selection_id",
                "operation_id",
                "execution_id",
                "result_id",
                "workflow_role",
                "idempotency_key",
            )
        }
        if any(
            not isinstance(value, str) or not value.strip()
            for value in values.values()
        ):
            raise FileWorkspaceControlGatewayError(
                "scientific result adoption identities must be non-empty strings"
            )
        fence = body["execution_fencing_token"]
        if isinstance(fence, bool) or not isinstance(fence, int) or fence < 1:
            raise FileWorkspaceControlGatewayError(
                "scientific result adoption fence must be a positive integer"
            )
        with context.child_mutation_writer(
            owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
            owner_ref=str(body["operation_id"]),
            process_epoch=authority.process_epoch,
        ):
            adoption = ScientificFileEffectAdoptionService(self.repositories).adopt(
                selection_id=str(body["selection_id"]),
                operation_id=str(body["operation_id"]),
                execution_id=str(body["execution_id"]),
                result_id=str(body["result_id"]),
                workflow_role=str(body["workflow_role"]),
                actor_ref=authority.agent_id,
                execution_fencing_token=fence,
                idempotency_key=str(body["idempotency_key"]),
            )
        return {
            "schema_version": "scientific_file_effect_adoption_result@1",
            "adoption": adoption.to_dict(),
            "selection_transition_performed": False,
            "attempt_transition_performed": False,
            "task_transition_performed": False,
        }

    def _finalize(
        self,
        body: dict[str, object],
        *,
        context: SandboxHostCallContext,
        authority: AgentCapsuleHostAuthority,
    ) -> dict[str, object]:
        expected = {
            "schema_version",
            "publication_id",
            "attempt_id",
            "selection_id",
            "execution_fencing_token",
            "producer_adoption_ids_by_role",
            "calculation_receipts",
        }
        if set(body) != expected or body.get("schema_version") != "aox_scientific_file_finalize_request@1":
            raise FileWorkspaceControlGatewayError(
                "scientific finalization request fields are closed"
            )
        if self.roots is None:
            raise FileWorkspaceControlGatewayError(
                "durable repository roots are required for scientific finalization"
            )
        adoptions = _object(
            body["producer_adoption_ids_by_role"],
            "producer_adoption_ids_by_role",
        )
        receipts = body["calculation_receipts"]
        if not isinstance(receipts, list) or not all(
            isinstance(item, dict) for item in receipts
        ):
            raise FileWorkspaceControlGatewayError(
                "calculation_receipts must be an array of objects"
            )
        fence = body["execution_fencing_token"]
        if isinstance(fence, bool) or not isinstance(fence, int) or fence < 1:
            raise FileWorkspaceControlGatewayError(
                "scientific finalization fence must be a positive integer"
            )
        with context.child_mutation_writer(
            owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
            owner_ref=f"scientific-finalize:{body['attempt_id']}",
            process_epoch=authority.process_epoch,
        ):
            return AoxFileBundleFinalizer(
                repositories=self.repositories,
                reader=DurableScientificPublicationReader(
                    repositories=self.repositories,
                    roots=self.roots,
                ),
            ).finalize(
                publication_id=str(body["publication_id"]),
                attempt_id=str(body["attempt_id"]),
                selection_id=str(body["selection_id"]),
                actor_ref=authority.agent_id,
                execution_fencing_token=fence,
                producer_adoption_ids_by_role={
                    str(key): str(value) for key, value in adoptions.items()
                },
                calculation_receipts=tuple(dict(item) for item in receipts),
            )

    def _require_job_identity(
        self,
        body: dict[str, object],
        authority: AgentCapsuleHostAuthority,
    ) -> tuple[object, WorkspaceRevisionExecutionRequest]:
        if set(body) != {"execution_id", "operation_id", "request_id"}:
            raise FileWorkspaceControlGatewayError(
                "workspace job identity fields are closed"
            )
        execution = self.repositories.controlled_operation_executions.get(
            str(body["execution_id"])
        )
        execution_request = self.repositories.workspace_revision_executions.get_request_by_execution(
            str(body["execution_id"])
        )
        hpc_workspace = (
            None
            if execution_request is None
            else self.repositories.executor_hpc_workspaces.get(
                execution_request.executor_hpc_workspace_id
            )
        )
        if (
            execution is None
            or execution_request is None
            or execution.operation_id != body["operation_id"]
            or execution_request.request_id != body["request_id"]
            or execution.session_id != authority.session_id
            or execution_request.executor_agent_member_id != authority.agent_member_id
            or execution_request.capability_lease_id != authority.capability_lease_id
            or execution_request.capability_lease_version
            != authority.capability_lease_version
            or hpc_workspace is None
            or hpc_workspace.local_workspace_id != authority.workspace_id
            or hpc_workspace.local_workspace_generation
            != authority.workspace_generation
        ):
            raise FileWorkspaceControlGatewayError(
                "workspace job is not owned by the current capsule authority"
            )
        return execution, execution_request


def _object(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FileWorkspaceControlGatewayError(f"{field_name} must be an object")
    return dict(value)


def _controlled_operation(value: object) -> ControlledOperation:
    data = _object(value, "operation")
    if set(data) != set(ControlledOperation.__dataclass_fields__):
        raise FileWorkspaceControlGatewayError(
            "controlled operation admission fields are closed"
        )
    data["status"] = ControlledOperationStatus(data["status"])
    data["owner_mode"] = ControlledOperationOwnerMode(data["owner_mode"])
    return ControlledOperation(**data)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FileWorkspaceControlGatewayError",
    "FileWorkspaceRepositoryScopes",
    "HostAgentCapsuleControlHandlerFactory",
    "HostFileWorkspaceControlGateway",
]
