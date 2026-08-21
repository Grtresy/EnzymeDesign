"""Kernel-owned checkpoint, publication, and immutable path application state.

The service never executes Git.  Publication dispatch is a separate generic
ControlledOperation.  This owner only freezes an intent and, after terminal proof,
asks the selected Git-shaped Adapter to observe the exact immutable ref.
"""

from __future__ import annotations

from collections.abc import Mapping

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublishedRevision
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import VerifiedWorkspaceCheckpoint
from openzyme_contracts import WorkspaceCheckpointProofInput
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationRemoteReceipt
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import PublicationApplicationCommand
from openzyme_extension_spi import PublicationCommandKind

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


_RECEIPT_ENTITY_TYPE = "kernel_command_receipt"


def _closed_payload(
    payload: Mapping[str, JsonValue],
    expected: frozenset[str],
    *,
    error_code: str,
) -> None:
    if set(payload) != expected:
        raise KernelContractError(
            error_code,
            "Publication command payload does not match its closed phase schema",
            details={"expected_fields": sorted(expected), "actual_fields": sorted(payload)},
        )


def _mapping(payload: JsonValue, *, field_name: str) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise KernelContractError(
            "publication_payload_invalid",
            f"{field_name} must be a closed object",
        )
    return dict(payload)


def _receipt_from_payload(payload: Mapping[str, JsonValue]) -> KernelMutationReceipt:
    value = payload.get("receipt")
    if not isinstance(value, Mapping):
        raise KernelContractError(
            "publication_idempotency_record_invalid",
            "Stored publication command receipt is invalid",
        )
    try:
        return KernelMutationReceipt(
            command_id=str(value["command_id"]),
            service_id=str(value["service_id"]),
            operation=str(value["operation"]),
            mutation_applied=value["mutation_applied"] is True,
            effect_certainty=ExternalEffectCertainty(str(value["effect_certainty"])),
            fallback_performed=value["fallback_performed"] is True,
            entity_refs=tuple(
                KernelEntityRef(
                    entity_kind=str(item["entity_kind"]),
                    entity_id=str(item["entity_id"]),
                    state_version=int(item["state_version"]),
                    entity_digest=str(item["entity_digest"]),
                )
                for item in value["entity_refs"]
            ),
            event_refs=tuple(str(item) for item in value["event_refs"]),
            result=value["result"],
            receipt_digest=str(value["receipt_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelContractError(
            "publication_idempotency_record_invalid",
            "Stored publication command receipt failed closed validation",
        ) from exc


class PublicationKernelApplicationService:
    """Sole generic owner of immutable revision collaboration facts."""

    service_id = "openzyme.kernel.publication-application"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: KernelRecordReaderPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        revision_backend: WorkspaceRevisionBackendPort,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids
        self._revision_backend = revision_backend

    def execute(
        self,
        command: PublicationApplicationCommand,
    ) -> KernelMutationReceipt:
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "context": command.context.to_dict(),
                "operation": command.operation.value,
                "resource_id": command.resource_id,
                "workspace_id": command.workspace_id,
                "expected_workspace_generation": command.expected_workspace_generation,
                "payload": json_compatible(command.payload),
            }
        )
        replay = self._reader.read(
            entity_type=_RECEIPT_ENTITY_TYPE,
            entity_id=command.context.idempotency_key,
        )
        if replay is not None:
            if replay.payload.get("command_digest") != command_digest:
                raise KernelContractError(
                    "publication_idempotency_conflict",
                    "Publication idempotency identity was reused for another command",
                )
            return _receipt_from_payload(replay.payload)

        session, workspace, pin, binding = self._load_identity(command)
        if command.operation is PublicationCommandKind.VERIFY_CHECKPOINT:
            return self._verify_checkpoint(
                command, command_digest, session, workspace, pin, binding
            )
        if command.operation is PublicationCommandKind.PUBLISH:
            phase = command.payload.get("phase")
            if phase == "admit":
                return self._admit_publication(
                    command, command_digest, session, workspace, pin, binding
                )
            if phase == "materialize":
                return self._materialize_publication(
                    command, command_digest, session, workspace, pin, binding
                )
            raise KernelContractError(
                "publication_phase_invalid",
                "PUBLISH requires an exact admit or materialize phase",
            )
        return self._verify_revision_path(
            command, command_digest, session, workspace, pin, binding
        )

    def _load_identity(self, command):  # noqa: ANN001
        session = self._reader.read(
            entity_type="session", entity_id=command.context.session_id
        )
        if session is None:
            raise KernelContractError("session_not_found", "Publication requires a Session")
        if session.state_version != command.context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale",
                "Session changed before publication command admission",
            )
        workspace_record = self._reader.read(
            entity_type="workspace_runtime_binding", entity_id=command.workspace_id
        )
        if workspace_record is None:
            raise KernelContractError(
                "workspace_binding_not_found", "Workspace runtime binding is absent"
            )
        try:
            workspace = WorkspaceRuntimeBinding.from_dict(dict(workspace_record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_binding_invalid", "Workspace runtime binding is invalid"
            ) from exc
        if (
            workspace.session_id != command.context.session_id
            or workspace.owner_member_id != command.context.actor_id
            or workspace.generation != command.expected_workspace_generation
            or command.context.workspace_generation != workspace.generation
        ):
            raise KernelContractError(
                "workspace_identity_stale",
                "Publication command differs from canonical workspace owner or generation",
            )
        pin_record = self._reader.read(
            entity_type="session_repository_binding_pin",
            entity_id=command.context.session_id,
        )
        if pin_record is None:
            raise KernelContractError(
                "repository_binding_pin_missing",
                "Session has no immutable repository binding pin",
            )
        try:
            pin = SessionRepositoryBindingPin.from_dict(dict(pin_record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "repository_binding_pin_invalid", "Session repository pin is invalid"
            ) from exc
        binding_record = self._reader.read(
            entity_type="project_repository_binding", entity_id=pin.binding_id
        )
        if binding_record is None:
            raise KernelContractError(
                "repository_binding_not_found", "Pinned repository binding is absent"
            )
        try:
            binding = ProjectRepositoryBinding.from_dict(dict(binding_record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "repository_binding_invalid", "Pinned repository binding is invalid"
            ) from exc
        if (
            pin.session_id != command.context.session_id
            or pin.binding_id != binding.binding_id
            or pin.binding_version != binding.binding_version
            or pin.repository_id != binding.repository_id
            or pin.binding_canonical_digest != binding.canonical_digest
        ):
            raise KernelContractError(
                "repository_binding_pin_stale",
                "Session repository pin differs from the exact binding identity",
            )
        return session, workspace, pin, binding

    def _verify_checkpoint(
        self, command, command_digest, session, workspace, pin, binding  # noqa: ANN001
    ) -> KernelMutationReceipt:
        _closed_payload(
            command.payload,
            frozenset({"proof"}),
            error_code="checkpoint_payload_invalid",
        )
        try:
            proof = WorkspaceCheckpointProofInput.from_dict(
                _mapping(command.payload["proof"], field_name="proof")
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "checkpoint_proof_invalid", "Checkpoint proof failed closed validation"
            ) from exc
        self._require_proof_identity(command, proof, workspace, pin, binding)
        self._authorize(command, operation="workspace.checkpoint.verify")
        observed = self._revision_backend.observe_private_ref(binding, proof)
        if observed != proof.remote_observation:
            raise KernelContractError(
                "checkpoint_remote_observation_mismatch",
                "Adapter observation differs from the frozen checkpoint proof",
            )
        checkpoint = VerifiedWorkspaceCheckpoint.create(
            checkpoint_id=command.resource_id,
            boundary=proof.boundary,
            workspace_id=proof.workspace_id,
            session_id=proof.session_id,
            agent_member_id=proof.agent_member_id,
            agent_id=proof.agent_id,
            workspace_generation=proof.workspace_generation,
            repository_binding_id=proof.repository_binding_id,
            repository_binding_version=proof.repository_binding_version,
            repository_id=binding.repository_id,
            commit=proof.commit,
            tree=proof.tree,
            private_ref=proof.private_ref,
            prior_commit=observed.prior_commit,
            advance_kind=observed.advance_kind,
            remote_observed_at=observed.observed_at,
            verified_at=self._clock.now_iso(),
        )
        return self._commit_create(
            command=command,
            command_digest=command_digest,
            session=session,
            entity_type="verified_workspace_checkpoint",
            entity_id=checkpoint.checkpoint_id,
            payload=checkpoint.to_dict(),
            event_type="workspace.checkpoint.verified",
            result={
                "checkpoint_id": checkpoint.checkpoint_id,
                "checkpoint_digest": checkpoint.checkpoint_digest,
                "boundary": checkpoint.boundary.value,
            },
        )

    def _admit_publication(
        self, command, command_digest, session, workspace, pin, binding  # noqa: ANN001
    ) -> KernelMutationReceipt:
        _closed_payload(
            command.payload,
            frozenset({"phase", "intent"}),
            error_code="publication_admission_payload_invalid",
        )
        try:
            intent = WorkspacePublicationIntent.from_dict(
                _mapping(command.payload["intent"], field_name="intent")
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "publication_intent_invalid", "Publication intent failed closed validation"
            ) from exc
        self._require_intent_identity(command, intent, workspace, pin, binding)
        self._authorize(command, operation="workspace.publish")
        checkpoint_record = self._reader.read(
            entity_type="verified_workspace_checkpoint", entity_id=intent.checkpoint_id
        )
        if checkpoint_record is None:
            raise KernelContractError(
                "publication_checkpoint_missing",
                "Publication requires an exact verified checkpoint",
            )
        try:
            checkpoint = VerifiedWorkspaceCheckpoint.from_dict(
                dict(checkpoint_record.payload)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "publication_checkpoint_invalid", "Stored checkpoint is invalid"
            ) from exc
        if (
            checkpoint.boundary.value != "publication"
            or checkpoint.workspace_id != intent.workspace_id
            or checkpoint.workspace_generation != intent.workspace_generation
            or checkpoint.commit != intent.expected_head_commit
            or checkpoint.tree != intent.expected_tree
        ):
            raise KernelContractError(
                "publication_checkpoint_stale",
                "Publication intent differs from its exact publication checkpoint",
            )
        return self._commit_create(
            command=command,
            command_digest=command_digest,
            session=session,
            entity_type="workspace_publication_intent",
            entity_id=intent.publication_id,
            payload=intent.to_dict(),
            event_type="workspace.publication.intent_frozen",
            result={
                "phase": "admit",
                "publication_id": intent.publication_id,
                "intent_id": intent.intent_id,
                "intent_digest": intent.canonical_digest,
                "dispatch_performed": False,
            },
        )

    def _materialize_publication(
        self, command, command_digest, session, workspace, pin, binding  # noqa: ANN001
    ) -> KernelMutationReceipt:
        _closed_payload(
            command.payload,
            frozenset({"phase", "controlled_operation_id", "remote_receipt"}),
            error_code="publication_materialization_payload_invalid",
        )
        operation_id = command.payload["controlled_operation_id"]
        if not isinstance(operation_id, str):
            raise KernelContractError(
                "publication_controlled_operation_invalid",
                "controlled_operation_id must be an exact identifier",
            )
        intent_record = self._reader.read(
            entity_type="workspace_publication_intent", entity_id=command.resource_id
        )
        if intent_record is None:
            raise KernelContractError(
                "publication_intent_not_found", "Frozen publication intent is absent"
            )
        try:
            intent = WorkspacePublicationIntent.from_dict(dict(intent_record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "publication_intent_invalid", "Stored publication intent is invalid"
            ) from exc
        self._require_intent_identity(command, intent, workspace, pin, binding)
        operation = self._reader.read(
            entity_type="controlled_operation", entity_id=operation_id
        )
        if (
            operation is None
            or operation.payload.get("session_id") != command.context.session_id
            or operation.payload.get("actor_id") != command.context.actor_id
            or operation.payload.get("state") != "settled"
            or operation.payload.get("effect_certainty") != "terminal_known"
            or operation.payload.get("mutation_applied") is not True
            or operation.payload.get("intent_digest") != intent.canonical_digest
            or operation.payload.get("scope_id") != command.workspace_id
            or operation.payload.get("authority_lease_id")
            != command.context.authority_lease_id
            or operation.payload.get("authority_generation")
            != command.context.authority_generation
            or operation.payload.get("authority_fence")
            != command.context.authority_fence
            or operation.payload.get("result_handle")
            != f"publication:{intent.publication_id}"
        ):
            raise KernelContractError(
                "publication_controlled_operation_unsettled",
                "Publication ref has no exact terminal ControlledOperation proof",
            )
        remote_receipt = command.payload["remote_receipt"]
        if not isinstance(remote_receipt, Mapping):
            raise KernelContractError(
                "publication_remote_receipt_invalid",
                "remote_receipt must be a closed receipt object",
            )
        try:
            expected_receipt = WorkspacePublicationRemoteReceipt.from_dict(
                dict(remote_receipt)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "publication_remote_receipt_invalid",
                "remote_receipt failed closed contract validation",
            ) from exc
        if (
            operation.payload.get("terminal_receipt_digest")
            != expected_receipt.receipt_digest
            or expected_receipt.execution_dispatch_generation
            != operation.payload.get("dispatch_generation")
            or expected_receipt.execution_fencing_token
            != operation.payload.get("authority_fence")
            or expected_receipt.internal_git_service_id
            != binding.internal_git_service_id
        ):
            raise KernelContractError(
                "publication_terminal_receipt_mismatch",
                "ControlledOperation terminal receipt differs from supplied receipt",
            )
        receipt = self._revision_backend.observe_publication(
            binding, intent, expected_receipt
        )
        self._require_remote_receipt(intent, operation_id, receipt)
        if expected_receipt.receipt_digest != receipt.receipt_digest:
            raise KernelContractError(
                "publication_terminal_receipt_mismatch",
                "ControlledOperation terminal receipt differs from Adapter observation",
            )
        revision = PublishedRevision.create(
            publication_id=intent.publication_id,
            intent_id=intent.intent_id,
            project_id=intent.project_id,
            session_id=intent.session_id,
            repository_binding_id=intent.repository_binding_id,
            repository_binding_version=intent.repository_binding_version,
            repository_id=intent.repository_id,
            commit=intent.expected_head_commit,
            tree=intent.expected_tree,
            git_parent_commits=intent.git_parent_commits,
            declared_base_commit=intent.declared_base_commit,
            parent_publication_id=intent.parent_publication_id,
            publisher_agent_member_id=intent.agent_member_id,
            publisher_agent_id=intent.agent_id,
            publisher_workspace_id=intent.workspace_id,
            publisher_workspace_generation=intent.workspace_generation,
            publication_ref=intent.publication_ref,
            manifest=intent.manifest,
            repository_policy_version=intent.repository_policy_version,
            repository_policy_digest=intent.repository_policy_digest,
            controlled_execution_id=operation_id,
            remote_receipt_id=receipt.receipt_id,
            supersedes_publication_id=intent.supersedes_publication_id,
            created_at=self._clock.now_iso(),
        )
        return self._commit_create(
            command=command,
            command_digest=command_digest,
            session=session,
            entity_type="published_revision",
            entity_id=revision.publication_id,
            payload=revision.to_dict(),
            event_type="workspace.publication.materialized",
            result={
                "phase": "materialize",
                "publication_id": revision.publication_id,
                "revision_digest": revision.revision_digest,
                "remote_receipt_digest": receipt.receipt_digest,
                "dispatch_performed": False,
            },
            require_current_authority=False,
        )

    def _verify_revision_path(
        self, command, command_digest, session, workspace, pin, binding  # noqa: ANN001
    ) -> KernelMutationReceipt:
        _closed_payload(
            command.payload,
            frozenset({"ref"}),
            error_code="revision_path_payload_invalid",
        )
        try:
            ref = RevisionPathRef.from_dict(
                _mapping(command.payload["ref"], field_name="ref")
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "revision_path_ref_invalid", "RevisionPathRef failed closed validation"
            ) from exc
        if command.resource_id != ref.ref_id:
            raise KernelContractError(
                "revision_path_identity_mismatch", "Command resource differs from ref identity"
            )
        if (
            ref.session_id != command.context.session_id
            or ref.repository_binding_id != pin.binding_id
            or ref.repository_binding_version != pin.binding_version
            or ref.repository_id != pin.repository_id
        ):
            raise KernelContractError(
                "revision_path_binding_stale",
                "RevisionPathRef differs from the Session repository pin",
            )
        self._authorize(command, operation="workspace.revision.verify")
        revision_record = self._reader.read(
            entity_type="published_revision", entity_id=ref.publication_id
        )
        if revision_record is None:
            raise KernelContractError(
                "published_revision_not_found", "RevisionPathRef publication is absent"
            )
        try:
            revision = PublishedRevision.from_dict(dict(revision_record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "published_revision_invalid", "Stored PublishedRevision is invalid"
            ) from exc
        if (
            ref.commit != revision.commit
            or ref.tree != revision.tree
            or not revision.contains_path(ref.path)
        ):
            raise KernelContractError(
                "revision_path_not_in_publication",
                "RevisionPathRef is not bound to the exact published tree",
            )
        receipt = self._revision_backend.verify_revision_path(binding, revision, ref)
        if (
            receipt.ref_id != ref.ref_id
            or receipt.publication_id != ref.publication_id
            or receipt.commit != ref.commit
            or receipt.tree != ref.tree
            or receipt.path != ref.path
            or receipt.object_id != ref.object_id
            or receipt.lfs_oid != ref.lfs_oid
            or receipt.lfs_size_bytes != ref.lfs_size_bytes
        ):
            raise KernelContractError(
                "revision_path_verification_mismatch",
                "Adapter path verification differs from RevisionPathRef",
            )
        payload = {**receipt.identity_payload, "verification_digest": receipt.verification_digest}
        return self._commit_create(
            command=command,
            command_digest=command_digest,
            session=session,
            entity_type="revision_path_verification",
            entity_id=ref.ref_id,
            payload=payload,
            event_type="workspace.revision_path.verified",
            result={
                "ref_id": ref.ref_id,
                "publication_id": ref.publication_id,
                "verification_digest": receipt.verification_digest,
            },
        )

    def _commit_create(
        self,
        *,
        command,
        command_digest: str,
        session,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, JsonValue] | dict[str, object],
        event_type: str,
        result: Mapping[str, JsonValue],
        require_current_authority: bool = True,
    ) -> KernelMutationReceipt:
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=command.context.command_id,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            authority_generation=command.context.authority_generation,
            authority_fence=command.context.authority_fence,
            expected_session_version=command.context.expected_session_version,
            idempotency_key=command.context.idempotency_key,
            command_digest=command_digest,
        )
        unit = self._store.begin(request)
        try:
            current_session = unit.read(
                entity_type="session", entity_id=command.context.session_id
            )
            if current_session is None or current_session.record_digest != session.record_digest:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before publication fact commit",
                )
            if require_current_authority:
                self._authorize(
                    command,
                    operation=self._operation_authority(command),
                    unit=unit,
                )
            if unit.read(entity_type=entity_type, entity_id=entity_id) is not None:
                raise KernelContractError(
                    "publication_immutable_identity_conflict",
                    "Immutable publication fact identity already exists",
                )
            normalized_payload = json_compatible(payload)
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_state_version=None,
                payload=normalized_payload,
            )
            unit.stage(mutation)
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=event_type,
                source_entity_type=entity_type,
                source_entity_id=entity_id,
                source_state_version=1,
                command_id=command.context.command_id,
                payload={
                    "resource_id": entity_id,
                    "resource_digest": canonical_sha256_digest(normalized_payload),
                    "fallback_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "resource_id": entity_id,
                "event_type": event_type,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.publication-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=self._clock.now_iso(),
                )
            )
            snapshot = KernelRecordSnapshot.create(
                entity_type=entity_type,
                entity_id=entity_id,
                state_version=1,
                payload=normalized_payload,
            )
            receipt = KernelMutationReceipt.create(
                command_id=command.context.command_id,
                service_id=self.service_id,
                operation=command.operation.value,
                mutation_applied=True,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                entity_refs=(
                    KernelEntityRef(
                        entity_kind=entity_type,
                        entity_id=entity_id,
                        state_version=1,
                        entity_digest=snapshot.record_digest,
                    ),
                ),
                event_refs=(event.event_id,),
                result=result,
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type=_RECEIPT_ENTITY_TYPE,
                    entity_id=command.context.idempotency_key,
                    expected_state_version=None,
                    payload={
                        "session_id": command.context.session_id,
                        "command_digest": command_digest,
                        "receipt": receipt.to_dict(),
                        "created_at": self._clock.now_iso(),
                    },
                )
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        if not committed.committed:
            raise KernelContractError(
                "publication_commit_failed", "Control Store did not commit publication fact"
            )
        return receipt

    def _authorize(self, command, *, operation: str, unit=None) -> None:  # noqa: ANN001
        source = self._reader if unit is None else unit
        lease = source.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found", "Publication authority lease is absent"
            )
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            operation=operation,
            scope_id=command.workspace_id,
            expected_generation=command.context.authority_generation,
            expected_fence=command.context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies publication operation",
            )

    @staticmethod
    def _operation_authority(command) -> str:  # noqa: ANN001
        if command.operation is PublicationCommandKind.VERIFY_CHECKPOINT:
            return "workspace.checkpoint.verify"
        if command.operation is PublicationCommandKind.VERIFY_REVISION_PATH:
            return "workspace.revision.verify"
        return "workspace.publish"

    @staticmethod
    def _require_proof_identity(command, proof, workspace, pin, binding) -> None:  # noqa: ANN001
        if (
            proof.workspace_id != command.workspace_id
            or proof.session_id != command.context.session_id
            or proof.agent_member_id != command.context.actor_id
            or proof.workspace_generation != workspace.generation
            or proof.repository_binding_id != pin.binding_id
            or proof.repository_binding_version != pin.binding_version
            or proof.remote_observation.repository_id != binding.repository_id
        ):
            raise KernelContractError(
                "checkpoint_identity_stale",
                "Checkpoint proof differs from Session, workspace, or repository identity",
            )

    @staticmethod
    def _require_intent_identity(command, intent, workspace, pin, binding) -> None:  # noqa: ANN001
        if (
            command.resource_id != intent.publication_id
            or intent.session_id != command.context.session_id
            or intent.agent_member_id != command.context.actor_id
            or intent.workspace_id != command.workspace_id
            or intent.workspace_generation != workspace.generation
            or intent.capability_lease_id != command.context.authority_lease_id
            or intent.repository_binding_id != pin.binding_id
            or intent.repository_binding_version != pin.binding_version
            or intent.repository_id != binding.repository_id
            or intent.repository_policy_version != binding.repository_policy_version
            or intent.repository_policy_digest != binding.repository_policy_digest
        ):
            raise KernelContractError(
                "publication_intent_identity_stale",
                "Publication intent differs from canonical authority, workspace, or binding",
            )

    @staticmethod
    def _require_remote_receipt(intent, operation_id: str, receipt) -> None:  # noqa: ANN001
        if (
            receipt.intent_id != intent.intent_id
            or receipt.publication_id != intent.publication_id
            or receipt.execution_id != operation_id
            or receipt.repository_binding_id != intent.repository_binding_id
            or receipt.repository_binding_version != intent.repository_binding_version
            or receipt.repository_id != intent.repository_id
            or receipt.publication_ref != intent.publication_ref
            or receipt.new_commit != intent.expected_head_commit
            or receipt.new_tree != intent.expected_tree
            or receipt.server_observed_commit != intent.expected_head_commit
        ):
            raise KernelContractError(
                "publication_remote_receipt_mismatch",
                "Adapter observation differs from frozen publication intent",
            )


__all__ = ["PublicationKernelApplicationService"]
