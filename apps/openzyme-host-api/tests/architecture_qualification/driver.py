from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any
from typing import Literal

from openzyme_core import ArtifactBoundaryService
from openzyme_core import ContinuationDeliveryWorker
from openzyme_core import ControlledOperationExecutionLeaseService
from openzyme_core import ControlledOperationExecutionWorker
from openzyme_core import DurableControlledOperationAdmission
from openzyme_core import DurableControlledOperationAdmissionService
from openzyme_core import controlled_operation_approval_digest
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain.control_plane import utc_now_iso

from .composition import ProductionComposition
from .external_ports import ControlledPortOutcome


_SAFE_PART = re.compile(r"[^a-zA-Z0-9_]+")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _safe_part(value: str) -> str:
    normalized = _SAFE_PART.sub("_", value).strip("_")
    if not normalized:
        raise ValueError("qualification identity part is empty")
    return normalized[:80]


@dataclass(frozen=True, slots=True)
class AdmittedOperation:
    session_id: str
    approval_id: str
    operation_id: str
    execution_id: str
    continuation_id: str
    sandbox_workspace_id: str
    sandbox_run_id: str


def materialized_observation_response(
    *,
    bounded_result_envelope: dict[str, object],
    backend_handle_ref: str | None,
    artifact_refs: tuple[dict[str, str], ...] = (),
    origin: str = "qualification_controlled_adapter",
) -> dict[str, object]:
    return {
        "backend_handle_ref": backend_handle_ref,
        "effect_certainty": "terminal_known",
        "error_code": None,
        "kind": "result_materialized",
        "materialized_result": {
            "artifact_refs": [dict(item) for item in artifact_refs],
            "bounded_result_envelope": dict(bounded_result_envelope),
            "origin": origin,
            "terminal_outcome": "succeeded",
        },
        "retry_eligibility": "terminal",
        "safe_receipt_digest": _digest(bounded_result_envelope),
        "safe_summary": "controlled qualification result materialized",
        "terminal_outcome": "succeeded",
    }


def controlled_ncbi_result() -> dict[str, object]:
    """Return a closed deterministic Bio SDK result for the controlled port."""

    return {
        "api_version": "qualification_fixture_non_cutover",
        "artifacts": [
            {
                "content": ">P12345 qualification protein\nMPEPTIDE\n",
                "format": "fasta",
                "kind": "sequence",
                "metadata": {
                    "accessions": ["P12345"],
                    "database": "protein",
                },
                "relative_path": "provider_parsed/proteins.fasta",
                "title": "qualification-proteins.fasta",
            }
        ],
        "operation": "bio.ncbi_fetch_proteins",
        "provider": "ncbi",
        "provider_observation": {"transport": "controlled_non_cutover"},
        "summary": {
            "accession_count": 1,
            "provider": "ncbi",
            "record_count": 1,
        },
        "warnings": [],
    }


class QualificationDriver:
    """Drive product services/workers while keeping scenario files repository-blind."""

    def __init__(self, composition: ProductionComposition) -> None:
        if composition.client is None:
            raise RuntimeError("qualification driver requires an entered composition")
        self.composition = composition

    @property
    def client(self):  # type: ignore[no-untyped-def]
        client = self.composition.client
        if client is None:
            raise RuntimeError("qualification composition is not entered")
        return client

    def create_session(self, session_id: str) -> dict[str, object]:
        response = self.client.post(
            "/v3/sessions",
            headers={"Idempotency-Key": f"qualification:create:{session_id}"},
            json={
                "session_id": session_id,
                "project_id": "proj_architecture_qualification",
                "objective": "Deterministic architecture qualification scenario.",
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"qualification session creation failed: {response.text}")
        return dict(response.json())

    def queue_external(
        self,
        port_id: str,
        operation: str,
        *outcomes: ControlledPortOutcome,
    ) -> None:
        try:
            port = self.composition.external_ports[port_id]
        except KeyError as exc:
            raise ValueError(f"qualification port {port_id!r} is unavailable") from exc
        port.queue(operation, *outcomes)

    def inject_sealed_observation_fault(
        self,
        ids: AdmittedOperation,
        *,
        fault: Literal["missing", "tampered", "identity_drift"],
    ) -> None:
        """Inject a storage fault below the product recovery boundary."""

        with self.composition.dependencies.v3_repository_scope(
            mode="read"
        ) as repositories:
            candidates = tuple(
                record
                for record in repositories.artifacts.list_by_session(ids.session_id)
                if dict(record.metadata or {}).get("controlled_operation_id")
                == ids.operation_id
                and PurePosixPath(str(record.relative_path)).name
                == "provider_observation.json"
            )
        if len(candidates) != 1:
            raise RuntimeError(
                "qualification fault requires one sealed provider observation"
            )
        record = candidates[0]
        storage_path = Path(record.storage_uri)
        if fault == "missing":
            storage_path.rename(storage_path.with_name(f"{storage_path.name}.missing"))
            return
        payload = storage_path.read_bytes()
        if fault == "tampered":
            if not payload:
                raise RuntimeError("sealed provider observation is empty")
            storage_path.chmod(0o600)
            storage_path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
            return
        if fault != "identity_drift":
            raise AssertionError(f"unsupported qualification fault {fault!r}")
        document = json.loads(payload)
        if not isinstance(document, dict):
            raise RuntimeError("sealed provider observation is not an object")
        document["provider_request_id"] = "provider_req_qualification_identity_drift"
        drifted_payload = json.dumps(
            document,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        drifted_digest = f"sha256:{hashlib.sha256(drifted_payload).hexdigest()}"
        drifted_path = (
            self.composition.roots.blob_root
            / "qualification-faults"
            / drifted_digest.removeprefix("sha256:")
        )
        drifted_path.parent.mkdir(parents=True, exist_ok=True)
        drifted_path.write_bytes(drifted_payload)
        drifted_path.chmod(0o400)
        metadata = dict(record.metadata or {})
        metadata.update(
            {
                "content_digest": drifted_digest,
                "sealed_digest": drifted_digest,
                "source_digest": drifted_digest,
            }
        )
        provenance = dict(metadata.get("provenance") or {})
        provenance.update(
            {
                "sealed_digest": drifted_digest,
                "source_digest": drifted_digest,
            }
        )
        metadata["provenance"] = provenance
        with self.composition.dependencies.v3_mutation_writer_scope(
            session_id=ids.session_id,
            owner_kind=MutationWriterKind.ENGINE_CALLBACK,
            owner_ref=(
                "architecture-qualification-fault:sealed-observation-identity-drift"
            ),
        ):
            with self.composition.dependencies.v3_repository_scope(
                mode="connection"
            ) as repositories:
                repositories.artifacts.save(
                    replace(
                        record,
                        storage_uri=str(drifted_path),
                        metadata=metadata,
                    )
                )

    def seal_external_input(
        self,
        *,
        session_id: str,
        filename: str,
        content: str,
        format: str,
        kind: ArtifactKind = ArtifactKind.RESULT,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with self.composition.dependencies.v3_mutation_writer_scope(
            session_id=session_id,
            owner_kind=MutationWriterKind.ENGINE_CALLBACK,
            owner_ref=f"architecture-qualification-external-input:{filename}",
        ):
            with self.composition.dependencies.v3_repository_scope(
                mode="connection"
            ) as repositories:
                registered = ArtifactBoundaryService(
                    repositories,
                    blob_store_root=self.composition.roots.blob_root,
                ).seal_external_bytes(
                    session_id=session_id,
                    content=content.encode("utf-8"),
                    filename=filename,
                    kind=kind,
                    format=format,
                    title=filename,
                    provider="architecture_qualification",
                    provenance={
                        "request_digest": _digest(
                            {"filename": filename, "session_id": session_id}
                        ),
                        "retrieved_at": utc_now_iso(),
                    },
                    metadata={
                        **dict(metadata or {}),
                        "qualification_fixture_non_cutover": True,
                    },
                    license_scope="qualification_fixture_non_cutover",
                )
        return registered.artifact.to_dict()

    def admit_durable_operation(
        self,
        *,
        session_id: str,
        scenario_key: str,
        route_policy_id: str,
        selected_backend: str,
        adapter_policy_id: str,
        request_envelope: dict[str, object] | None = None,
        attached_process: bool = False,
        backend_category: str = "qualification_fixture_non_cutover",
        sdk_module: str = "qualification",
        function_name: str = "controlled_operation",
    ) -> AdmittedOperation:
        key = _safe_part(scenario_key)
        now = utc_now_iso()
        ids = AdmittedOperation(
            session_id=session_id,
            approval_id=f"appr_{key}",
            operation_id=f"op_{key}",
            execution_id=f"exec_{key}",
            continuation_id=f"cont_{key}",
            sandbox_workspace_id=f"sw_{key}",
            sandbox_run_id=f"srun_{key}",
        )
        envelope = request_envelope or {
            "adapter_params": {"scenario_id": scenario_key},
            "schema_version": "durable_route_request@1",
        }
        request_digest = _digest(envelope)
        approval = ApprovalRequest(
            approval_id=ids.approval_id,
            session_id=session_id,
            task_id=None,
            lane_id=None,
            kind="sdk_controlled_operation",
            requested_action=f"Approve qualification operation {scenario_key}.",
            status=ApprovalRequestStatus.PENDING,
            request_ref=ids.operation_id,
            resolution_ref=None,
            created_at=now,
        )
        operation_digest = _digest(
            {
                "request_digest": request_digest,
                "route_policy_id": route_policy_id,
                "scenario_key": scenario_key,
            }
        )
        operation = ControlledOperation(
            operation_id=ids.operation_id,
            session_id=session_id,
            sandbox_workspace_id=ids.sandbox_workspace_id,
            sandbox_run_id=ids.sandbox_run_id,
            logical_operation_key=f"qualification.{key}",
            operation_digest=operation_digest,
            params_digest=request_digest,
            backend_category=backend_category,
            status=ControlledOperationStatus.WAITING_APPROVAL,
            approval_id=ids.approval_id,
            approval_state=ApprovalRequestStatus.PENDING.value,
            route_reason="architecture_qualification_controlled_route",
            adapter_envelope_schema_version="s12.adapter_envelope.v1",
            sdk_module=sdk_module,
            function_name=function_name,
            route_policy_id=route_policy_id,
            selected_backend=selected_backend,
            planned_fetch_intent={},
            approval_requirement={"required": True},
            adapter_approval_envelope={"qualification_fixture_non_cutover": True},
            adapter_result_envelope={},
            expected_outputs_summary={},
            resource_estimate={"external_effects_real": False},
            result_summary={},
            idempotency_key=f"qualification:{scenario_key}",
            owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
            created_at=now,
            updated_at=now,
        )
        execution = ControlledOperationExecution(
            execution_id=ids.execution_id,
            operation_id=ids.operation_id,
            session_id=session_id,
            owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
            operation_digest=operation_digest,
            approval_digest=controlled_operation_approval_digest(approval),
            route_policy_id=route_policy_id,
            selected_backend=selected_backend,
            adapter_policy_id=adapter_policy_id,
            input_identity_digest=_digest({"inputs": []}),
            expected_output_contract_digest=_digest({"outputs": []}),
            runtime_identity_digest=_digest(
                {"fixture": "qualification_fixture_non_cutover"}
            ),
            lifecycle_state=ControlledOperationExecutionLifecycle.AWAITING_APPROVAL,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            dispatch_generation=0,
            state_version=1,
            fencing_token=0,
            approval_id=ids.approval_id,
            created_at=now,
            updated_at=now,
        )
        request_bytes = json.dumps(
            envelope,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        request = ControlledOperationDispatchRequest(
            request_id=f"dispatch_{key}",
            execution_id=ids.execution_id,
            operation_id=ids.operation_id,
            session_id=session_id,
            request_digest=request_digest,
            request_envelope=envelope,
            request_size_bytes=len(request_bytes),
            created_at=now,
        )
        continuation = ContinuationState(
            continuation_id=ids.continuation_id,
            session_id=session_id,
            operation_id=ids.operation_id,
            sandbox_run_id=ids.sandbox_run_id,
            approval_id=ids.approval_id,
            status=ContinuationStateStatus.WAITING_APPROVAL,
            originating_signal_id=(
                f"sig_{key}" if attached_process else None
            ),
            originating_agent_id=("agent:master" if attached_process else None),
            originating_tool_call_id=(
                f"tool_call_{key}" if attached_process else None
            ),
            originating_invocation_id=(
                f"invocation_{key}" if attached_process else None
            ),
            sandbox_workspace_id=(
                ids.sandbox_workspace_id if attached_process else None
            ),
            sandbox_runtime_identity=(
                _digest({"sandbox_runtime": key}) if attached_process else None
            ),
            process_epoch=1 if attached_process else None,
            resume_strategy=(
                ContinuationResumeStrategy.ATTACHED_PROCESS
                if attached_process
                else ContinuationResumeStrategy.LEGACY_NON_RESUMABLE
            ),
            delivery_state=(
                ContinuationDeliveryState.AWAITING_RESULT
                if attached_process
                else ContinuationDeliveryState.LEGACY_UNAVAILABLE
            ),
            delivery_generation=1 if attached_process else 0,
            state_version=1 if attached_process else 0,
            created_at=now,
            updated_at=now,
        )
        event = ControlledOperationExecutionEvent(
            event_id=f"evt_admission_{key}",
            execution_id=ids.execution_id,
            operation_id=ids.operation_id,
            session_id=session_id,
            state_version=1,
            dispatch_generation=0,
            phase=ControlledOperationExecutionPhase.ADMISSION,
            lifecycle_state=ControlledOperationExecutionLifecycle.AWAITING_APPROVAL,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            fencing_token=0,
            created_at=now,
        )
        with self.composition.dependencies.v3_mutation_writer_scope(
            session_id=session_id,
            owner_kind=MutationWriterKind.ENGINE_CALLBACK,
            owner_ref=f"architecture-qualification-admission:{key}",
        ):
            with self.composition.dependencies.v3_repository_scope(
                mode="connection"
            ) as repositories:
                master = repositories.agents.get(session_id, "agent:master")
                if master is None or master.member_id is None:
                    raise RuntimeError("qualification session has no master identity")
                repositories.sandbox_workspaces.save(
                    SandboxWorkspaceRecord(
                        sandbox_workspace_id=ids.sandbox_workspace_id,
                        session_id=session_id,
                        agent_member_id=master.member_id,
                        agent_id=master.agent_id,
                        status=SandboxWorkspaceStatus.ATTACHED,
                        image_ref="qualification://sandbox",
                        image_digest=_digest({"image": "qualification"}),
                        image_version="qualification_fixture_non_cutover",
                        sandbox_protocol_version="qualification@1",
                        image_compatibility=(
                            SandboxImageCompatibility.COMPATIBLE_NON_CUTOVER_GRADE
                        ),
                        manifest_version="qualification_fixture_non_cutover",
                        created_at=now,
                        last_attached_at=now,
                        quota_summary={"external_effects_real": False},
                        directory_summary={},
                    )
                )
                source_path = (
                    Path(self.composition.roots.sandbox_root)
                    / ids.sandbox_workspace_id
                    / "src"
                    / "qualification_scenario.py"
                )
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(
                    "# Deterministic architecture qualification source.\n"
                    f"SCENARIO_ID = {json.dumps(scenario_key)}\n",
                    encoding="utf-8",
                )
                source_snapshot = ArtifactBoundaryService(
                    repositories,
                    workspace_root=self.composition.roots.sandbox_root,
                    blob_store_root=self.composition.roots.blob_root,
                ).snapshot_code(
                    session_id=session_id,
                    sandbox_workspace_id=ids.sandbox_workspace_id,
                    paths=None,
                    entrypoint="qualification_scenario.py",
                    metadata={
                        "producer": "architecture_qualification_driver",
                        "qualification_fixture_non_cutover": True,
                    },
                )
                operation = replace(
                    operation,
                    source_snapshot_artifact_id=source_snapshot.artifact.artifact_id,
                    source_snapshot_digest=source_snapshot.source_tree_digest,
                )
                execution = replace(
                    execution,
                    runtime_identity_digest=_digest(
                        {
                            "fixture": "qualification_fixture_non_cutover",
                            "source_snapshot_artifact_id": (
                                source_snapshot.artifact.artifact_id
                            ),
                            "source_tree_digest": source_snapshot.source_tree_digest,
                        }
                    ),
                )
                repositories.sandbox_runs.save(
                    SandboxRunRecord(
                        sandbox_run_id=ids.sandbox_run_id,
                        session_id=session_id,
                        sandbox_workspace_id=ids.sandbox_workspace_id,
                        agent_id=master.agent_id,
                        argv=("qualification_fixture_non_cutover", scenario_key),
                        argv_digest=_digest(
                            ["qualification_fixture_non_cutover", scenario_key]
                        ),
                        cwd="/workspace",
                        env_digest=_digest({"credentials": "scrubbed"}),
                        status=SandboxRunStatus.RUNNING,
                        created_at=now,
                        updated_at=now,
                        resource_policy={"external_effects_real": False},
                        source_snapshot_artifact_id=(
                            source_snapshot.artifact.artifact_id
                        ),
                        source_tree_digest=source_snapshot.source_tree_digest,
                        changed_files_summary={},
                        compatibility={"qualification_fixture_non_cutover": True},
                        started_at=now,
                    )
                )
                DurableControlledOperationAdmissionService(repositories).admit(
                    DurableControlledOperationAdmission(
                        operation=operation,
                        approval=approval,
                        execution=execution,
                        dispatch_request=request,
                        continuation=continuation,
                        event=event,
                    )
                )
        return ids

    def resolve_approval(
        self,
        approval_id: str,
        *,
        decision: str = "approved",
    ) -> dict[str, object]:
        response = self.client.post(
            f"/v3/approvals/{approval_id}/resolve",
            headers={
                "Idempotency-Key": f"qualification:resolve:{approval_id}:{decision}"
            },
            json={"decision": decision},
        )
        if response.status_code != 200:
            raise RuntimeError(f"qualification approval failed: {response.text}")
        return dict(response.json())

    def run_execution_once(self, execution_id: str, *, worker_id: str) -> dict[str, Any]:
        coordinator = self.composition.durable_supervisor.worker_factory(worker_id)
        execution_worker = next(
            (
                worker
                for worker in coordinator.workers
                if isinstance(worker, ControlledOperationExecutionWorker)
            ),
            None,
        )
        if execution_worker is None:
            raise RuntimeError("production coordinator has no execution worker")
        outcome = execution_worker.run_execution_once(execution_id)
        return {
            "action": outcome.action,
            "effect_certainty": outcome.effect_certainty,
            "execution_id": outcome.execution_id,
            "lifecycle_state": outcome.lifecycle_state,
            "retry_eligibility": outcome.retry_eligibility,
            "state_version": outcome.state_version,
        }

    def claim_execution(
        self,
        execution_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now_iso: str | None = None,
    ) -> dict[str, Any]:
        with self.composition.dependencies.v3_repository_scope(
            mode="read"
        ) as repositories:
            execution = repositories.controlled_operation_executions.get(
                execution_id
            )
        if execution is None:
            raise RuntimeError("qualification execution is absent")
        with self.composition.dependencies.v3_mutation_writer_scope(
            session_id=execution.session_id,
            owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
            owner_ref=f"architecture-qualification-claim:{worker_id}",
        ):
            with self.composition.dependencies.v3_repository_scope(
                mode="connection"
            ) as repositories:
                claimed = ControlledOperationExecutionLeaseService(
                    repositories
                ).claim(
                    execution_id,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    now_iso=now_iso,
                )
        if claimed is None:
            raise RuntimeError("qualification execution was not claimable")
        return claimed.to_dict()

    def run_continuation_once(self, *, worker_id: str) -> dict[str, Any]:
        coordinator = self.composition.durable_supervisor.worker_factory(worker_id)
        delivery_worker = next(
            (
                worker
                for worker in coordinator.workers
                if isinstance(worker, ContinuationDeliveryWorker)
            ),
            None,
        )
        if delivery_worker is None:
            raise RuntimeError("production coordinator has no continuation worker")
        outcome = delivery_worker.run_once()
        return {
            "action": outcome.action,
            "continuation_id": outcome.continuation_id,
            "delivery_state": outcome.delivery_state,
            "state_version": outcome.state_version,
        }

    def continuation_state(self, continuation_id: str) -> ContinuationState:
        with self.composition.dependencies.v3_repository_scope(
            mode="read"
        ) as repositories:
            continuation = repositories.continuation_states.get(continuation_id)
        if continuation is None:
            raise RuntimeError("qualification continuation is absent")
        return continuation

    def canonical_records(self, ids: AdmittedOperation) -> dict[str, object]:
        with self.composition.dependencies.v3_repository_scope(
            mode="read"
        ) as repositories:
            execution = repositories.controlled_operation_executions.get(
                ids.execution_id
            )
            operation = repositories.controlled_operations.get(ids.operation_id)
            approval = repositories.approvals.get(ids.approval_id)
            approvals = repositories.approvals.list_by_session(ids.session_id)
            result = repositories.controlled_operation_results.get_by_execution_id(
                ids.execution_id
            )
            artifacts = repositories.artifacts.list_by_session(ids.session_id)
            result_artifacts = (
                ()
                if result is None
                else repositories.controlled_operation_result_artifacts.list_by_result_handle(
                    result.result_handle_id
                )
            )
            events = (
                repositories.controlled_operation_execution_events.list_by_execution(
                    ids.execution_id
                )
            )
            tasks = repositories.tasks.list_by_session(ids.session_id)
        return {
            "approval": None if approval is None else approval.to_dict(),
            "approvals": [item.to_dict() for item in approvals],
            "artifacts": [item.to_dict() for item in artifacts],
            "events": [item.to_dict() for item in events],
            "execution": None if execution is None else execution.to_dict(),
            "operation": None if operation is None else operation.to_dict(),
            "result": None if result is None else result.to_dict(),
            "result_artifacts": [item.identity() for item in result_artifacts],
            "tasks": [item.to_dict() for item in tasks],
        }


__all__ = [
    "AdmittedOperation",
    "QualificationDriver",
    "materialized_observation_response",
]
