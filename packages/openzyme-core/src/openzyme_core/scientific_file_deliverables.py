from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
from typing import Callable
from typing import Protocol

from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import MutationWriterKind
from openzyme_domain import PublishedRevision
from openzyme_domain import ScientificDeliverableBundle
from openzyme_domain import ScientificDeliverableRef
from openzyme_domain import ScientificDeliverableValidationReceipt
from openzyme_domain import ScientificFileStorage
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificFileEffectAdoption
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import WorkspaceJobObservationState
from openzyme_domain import WorkspaceFormalBoundary
from openzyme_domain import ScientificSelectionState
from openzyme_domain import canonical_scientific_deliverable_digest
from openzyme_domain import normalize_scientific_path

from .mutation_authority import current_mutation_write_authority
from .repositories import CoreRepositories


class ScientificFileDeliverableError(RuntimeError):
    error_code = "scientific_file_deliverable_rejected"


class ScientificPublishedByteReader(Protocol):
    """Read exact immutable objects without consulting an ambient checkout."""

    def read_git_blob(
        self,
        *,
        repository_binding_id: str,
        repository_binding_version: int,
        publication_ref: str,
        commit: str,
        path: str,
        object_id: str,
    ) -> bytes: ...

    def read_lfs_object(
        self,
        *,
        repository_binding_id: str,
        repository_binding_version: int,
        publication_ref: str,
        commit: str,
        path: str,
        lfs_oid: str,
        declared_size: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ResolvedScientificFile:
    publication_id: str
    path: str
    manifest_entry: PublicationManifestEntry
    storage: ScientificFileStorage
    actual_bytes: bytes
    content_digest: str


@dataclass(frozen=True, slots=True)
class ScientificRoleRequirement:
    scientific_role: str
    path: str
    format_contract_id: str
    format_contract_digest: str
    producer_adoption_id: str
    validate_bytes: Callable[[bytes], None]


@dataclass(frozen=True, slots=True)
class ScientificDeliverableFinalizationResult:
    refs: tuple[ScientificDeliverableRef, ...]
    bundle: ScientificDeliverableBundle
    receipt: ScientificDeliverableValidationReceipt


@dataclass(slots=True)
class ScientificFileEffectAdoptionService:
    repositories: CoreRepositories
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def adopt(
        self,
        *,
        selection_id: str,
        operation_id: str,
        execution_id: str,
        result_id: str,
        workflow_role: str,
        actor_ref: str,
        execution_fencing_token: int,
        idempotency_key: str,
    ) -> ScientificFileEffectAdoption:
        authority = current_mutation_write_authority()
        selection = self.repositories.scientific_selections.get(selection_id)
        head = (
            None
            if selection is None
            else self.repositories.scientific_selections.resolve_head(
                selection.attempt_id
            )
        )
        attempt = (
            None
            if selection is None
            else self.repositories.scientific_attempts.get(selection.attempt_id)
        )
        disposition = next(
            (
                item
                for item in self.repositories.scientific_dispositions.list_by_selection(
                    selection_id
                )
                if item.operation_id == operation_id
            ),
            None,
        )
        operation = self.repositories.controlled_operations.get(operation_id)
        execution = self.repositories.controlled_operation_executions.get(execution_id)
        workspace_result = self.repositories.workspace_revision_executions.get_result(
            result_id
        )
        controlled_result = self.repositories.controlled_operation_results.get(result_id)
        result = workspace_result
        result_digest = None if result is None else result.result_digest
        if (
            selection is None
            or attempt is None
            or head is None
            or head.head.selection_id != selection_id
            or selection.state is not ScientificSelectionState.DRAFT
            or selection.actor_ref != actor_ref
            or attempt.status is not ScientificAttemptStatus.ACTIVE
            or authority is None
            or authority.scope_id != attempt.mutation_scope_id
            or authority.owner_kind is not MutationWriterKind.CONTROLLED_OPERATION
            or disposition is None
            or disposition.attempt_id != attempt.attempt_id
            or disposition.actor_ref != actor_ref
            or disposition.kind is not ScientificOperationDispositionKind.ADOPTED
            or disposition.workflow_role != workflow_role
            or operation is None
            or operation.session_id != attempt.session_id
            or operation.status is not ControlledOperationStatus.COMPLETED
            or execution is None
            or execution.session_id != attempt.session_id
            or execution.operation_id != operation_id
            or execution.execution_id != execution_id
            or execution.fencing_token != execution_fencing_token
            or execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.TERMINAL
            or execution.terminal_outcome
            is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            or execution.effect_certainty.value not in {
                "effect_known",
                "terminal_known",
            }
            or result is None
            or result.operation_id != operation_id
            or result.execution_id != execution_id
            or result_digest != execution.result_digest
            or execution.result_handle_ref != result_id
            or (
                workspace_result is not None
                and workspace_result.terminal_state
                is not WorkspaceJobObservationState.SUCCEEDED
            )
        ):
            raise ScientificFileDeliverableError(
                "scientific file adoption does not bind one current successful producer"
            )
        execution_request = (
            self.repositories.workspace_revision_executions.get_request_by_execution(
                execution_id
            )
        )
        result_link = self.repositories.workspace_revision_executions.get_result_revision_link(
            result_id
        )
        checkpoint = (
            None
            if result_link is None
            else self.repositories.verified_workspace_checkpoints.get(
                result_link.checkpoint_id
            )
        )
        closure = (
            None
            if result_link is None
            else self.repositories.git_lfs.get_closure_manifest(
                result_link.lfs_closure_manifest_digest
            )
        )
        if (
            controlled_result is not None
            or execution_request is None
            or execution_request.scientific_basis is None
            or execution_request.scientific_basis.attempt_id != attempt.attempt_id
            or execution_request.scientific_basis.attempt_state_version
            != attempt.state_version
            or execution_request.session_id != attempt.session_id
            or result_link is None
            or checkpoint is None
            or closure is None
            or checkpoint.boundary is not WorkspaceFormalBoundary.EXTERNAL_JOB
            or result_link.result_id != result_id
            or result_link.workspace_id != checkpoint.workspace_id
            or result_link.result_commit != checkpoint.commit
            or result_link.result_tree != checkpoint.tree
            or result_link.linked_by_agent_member_id != checkpoint.agent_member_id
            or closure.manifest_digest != result_link.lfs_closure_manifest_digest
            or closure.binding_id != checkpoint.repository_binding_id
            or closure.binding_version != checkpoint.repository_binding_version
            or closure.repository_id != checkpoint.repository_id
            or closure.commit != checkpoint.commit
            or closure.tree != checkpoint.tree
        ):
            raise ScientificFileDeliverableError(
                "scientific file adoption lacks exact attempt-bound result revision"
            )
        request = {
            "schema_version": "scientific_file_effect_adoption_request@1",
            "selection_id": selection_id,
            "selection_revision": selection.revision,
            "attempt_id": attempt.attempt_id,
            "workflow_role": workflow_role,
            "operation_id": operation_id,
            "execution_id": execution_id,
            "result_id": result_id,
            "result_digest": result_digest,
            "effect_certainty": execution.effect_certainty.value,
            "actor_ref": actor_ref,
            "execution_fencing_token": execution_fencing_token,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_scientific_deliverable_digest(request)
        adoption_id = _stable_id("scientific_file_adoption", request_digest)
        existing = self.repositories.scientific_deliverables.get_adoption(adoption_id)
        if existing is not None:
            if existing.request_digest != request_digest:
                raise ScientificFileDeliverableError(
                    "scientific file adoption idempotency identity conflicts"
                )
            return existing
        record = ScientificFileEffectAdoption.create(
            adoption_id=adoption_id,
            selection_id=selection_id,
            selection_revision=selection.revision,
            attempt_id=attempt.attempt_id,
            workflow_role=workflow_role,
            operation_id=operation_id,
            execution_id=execution_id,
            result_id=result_id,
            result_digest=result_digest,
            effect_certainty=execution.effect_certainty.value,
            actor_ref=actor_ref,
            execution_fencing_token=execution_fencing_token,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            created_at=self.now().isoformat(),
        )
        with self.repositories.atomic(prefix="scientific_file_effect_adoption"):
            current_authority = current_mutation_write_authority()
            current_selection = self.repositories.scientific_selections.get(selection_id)
            current_head = self.repositories.scientific_selections.resolve_head(
                attempt.attempt_id
            )
            current_attempt = self.repositories.scientific_attempts.get(
                attempt.attempt_id
            )
            current_operation = self.repositories.controlled_operations.get(operation_id)
            current_execution = self.repositories.controlled_operation_executions.get(
                execution_id
            )
            current_workspace_result = (
                self.repositories.workspace_revision_executions.get_result(result_id)
            )
            current_controlled_result = (
                self.repositories.controlled_operation_results.get(result_id)
            )
            current_request = (
                self.repositories.workspace_revision_executions.get_request_by_execution(
                    execution_id
                )
            )
            current_result_link = (
                self.repositories.workspace_revision_executions.get_result_revision_link(
                    result_id
                )
            )
            current_checkpoint = (
                None
                if current_result_link is None
                else self.repositories.verified_workspace_checkpoints.get(
                    current_result_link.checkpoint_id
                )
            )
            current_closure = (
                None
                if current_result_link is None
                else self.repositories.git_lfs.get_closure_manifest(
                    current_result_link.lfs_closure_manifest_digest
                )
            )
            current_disposition = next(
                (
                    item
                    for item in self.repositories.scientific_dispositions.list_by_selection(
                        selection_id
                    )
                    if item.operation_id == operation_id
                ),
                None,
            )
            if (
                current_authority != authority
                or current_selection != selection
                or current_head != head
                or current_attempt != attempt
                or current_operation != operation
                or current_execution != execution
                or current_workspace_result != workspace_result
                or current_controlled_result != controlled_result
                or current_request != execution_request
                or current_result_link != result_link
                or current_checkpoint != checkpoint
                or current_closure != closure
                or current_disposition != disposition
            ):
                raise ScientificFileDeliverableError(
                    "scientific file adoption facts drifted before commit"
                )
            return self.repositories.scientific_deliverables.add_adoption(record)


def _git_blob_oid(content: bytes, *, hex_length: int) -> str:
    preimage = f"blob {len(content)}\0".encode() + content
    if hex_length == 40:
        return hashlib.sha1(preimage, usedforsecurity=False).hexdigest()
    if hex_length == 64:
        return hashlib.sha256(preimage).hexdigest()
    raise ScientificFileDeliverableError("unsupported Git object format")


def _stable_id(prefix: str, digest: str) -> str:
    return f"{prefix}_{digest.removeprefix('sha256:')[:32]}"


@dataclass(slots=True)
class ScientificPublishedFileResolver:
    repositories: CoreRepositories
    reader: ScientificPublishedByteReader

    def resolve(self, *, publication_id: str, path: str) -> ResolvedScientificFile:
        normalized_path = normalize_scientific_path(path)
        revision = self.repositories.published_revisions.get(publication_id)
        if revision is None:
            raise ScientificFileDeliverableError("unknown immutable publication")
        entry = next(
            (item for item in revision.manifest.entries if item.path == normalized_path),
            None,
        )
        if (
            entry is None
            or entry.object_kind is not PublicationManifestObjectKind.BLOB
            or entry.mode not in {"100644", "100755"}
        ):
            raise ScientificFileDeliverableError(
                "scientific path is not an ordinary file in the exact publication tree"
            )
        pointer_bytes = self.reader.read_git_blob(
            repository_binding_id=revision.repository_binding_id,
            repository_binding_version=revision.repository_binding_version,
            publication_ref=revision.publication_ref,
            commit=revision.commit,
            path=normalized_path,
            object_id=entry.object_id,
        )
        if _git_blob_oid(pointer_bytes, hex_length=len(entry.object_id)) != entry.object_id:
            raise ScientificFileDeliverableError("published Git blob bytes drifted")
        if entry.size_bytes is not None and len(pointer_bytes) != entry.size_bytes:
            raise ScientificFileDeliverableError("published Git blob size drifted")

        if entry.lfs_oid is None:
            storage = ScientificFileStorage.GIT_BLOB
            actual_bytes = pointer_bytes
        else:
            if entry.lfs_size_bytes is None:
                raise ScientificFileDeliverableError("incomplete Git LFS manifest identity")
            storage = ScientificFileStorage.GIT_LFS
            actual_bytes = self.reader.read_lfs_object(
                repository_binding_id=revision.repository_binding_id,
                repository_binding_version=revision.repository_binding_version,
                publication_ref=revision.publication_ref,
                commit=revision.commit,
                path=normalized_path,
                lfs_oid=entry.lfs_oid,
                declared_size=entry.lfs_size_bytes,
            )
            if len(actual_bytes) != entry.lfs_size_bytes:
                raise ScientificFileDeliverableError("Git LFS actual size drifted")
            if "sha256:" + hashlib.sha256(actual_bytes).hexdigest() != entry.lfs_oid:
                raise ScientificFileDeliverableError("Git LFS actual bytes drifted")
        return ResolvedScientificFile(
            publication_id=publication_id,
            path=normalized_path,
            manifest_entry=entry,
            storage=storage,
            actual_bytes=actual_bytes,
            content_digest="sha256:" + hashlib.sha256(actual_bytes).hexdigest(),
        )


@dataclass(slots=True)
class ScientificDeliverableFinalizationService:
    repositories: CoreRepositories
    resolver: ScientificPublishedFileResolver
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def _require_producer_lineage(
        self,
        *,
        adoption: ScientificFileEffectAdoption,
        requirement: ScientificRoleRequirement,
        attempt_id: str,
        selection_id: str,
        actor_ref: str,
        revision: PublishedRevision,
    ) -> tuple[object, ...]:
        operation = self.repositories.controlled_operations.get(adoption.operation_id)
        execution = self.repositories.controlled_operation_executions.get(
            adoption.execution_id
        )
        result = self.repositories.workspace_revision_executions.get_result(
            adoption.result_id
        )
        request = (
            self.repositories.workspace_revision_executions.get_request_by_execution(
                adoption.execution_id
            )
        )
        link = self.repositories.workspace_revision_executions.get_result_revision_link(
            adoption.result_id
        )
        checkpoint = (
            None
            if link is None
            else self.repositories.verified_workspace_checkpoints.get(link.checkpoint_id)
        )
        closure = (
            None
            if link is None
            else self.repositories.git_lfs.get_closure_manifest(
                link.lfs_closure_manifest_digest
            )
        )
        disposition = next(
            (
                item
                for item in self.repositories.scientific_dispositions.list_by_selection(
                    selection_id
                )
                if item.operation_id == adoption.operation_id
            ),
            None,
        )
        publication_proof = self.repositories.git_lfs.get_publication_intent_proof(
            revision.intent_id
        )
        if (
            adoption.attempt_id != attempt_id
            or adoption.selection_id != selection_id
            or adoption.selection_revision < 1
            or adoption.workflow_role != requirement.scientific_role
            or adoption.actor_ref != actor_ref
            or operation is None
            or operation.session_id != revision.session_id
            or operation.status is not ControlledOperationStatus.COMPLETED
            or execution is None
            or execution.operation_id != adoption.operation_id
            or execution.execution_id != adoption.execution_id
            or execution.session_id != revision.session_id
            or execution.fencing_token != adoption.execution_fencing_token
            or execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.TERMINAL
            or execution.terminal_outcome
            is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            or execution.effect_certainty.value != adoption.effect_certainty
            or execution.result_handle_ref != adoption.result_id
            or execution.result_digest != adoption.result_digest
            or result is None
            or result.operation_id != adoption.operation_id
            or result.execution_id != adoption.execution_id
            or result.result_digest != adoption.result_digest
            or result.terminal_state is not WorkspaceJobObservationState.SUCCEEDED
            or request is None
            or request.scientific_basis is None
            or request.scientific_basis.attempt_id != attempt_id
            or request.session_id != revision.session_id
            or link is None
            or checkpoint is None
            or closure is None
            or disposition is None
            or disposition.attempt_id != attempt_id
            or disposition.selection_id != selection_id
            or disposition.kind is not ScientificOperationDispositionKind.ADOPTED
            or disposition.workflow_role != requirement.scientific_role
            or disposition.actor_ref != actor_ref
            or checkpoint.boundary is not WorkspaceFormalBoundary.EXTERNAL_JOB
            or checkpoint.session_id != revision.session_id
            or checkpoint.workspace_id
            != revision.publisher_workspace_id
            or checkpoint.workspace_generation
            != revision.publisher_workspace_generation
            or checkpoint.agent_member_id
            != revision.publisher_agent_member_id
            or checkpoint.repository_binding_id
            != revision.repository_binding_id
            or checkpoint.repository_binding_version
            != revision.repository_binding_version
            or checkpoint.repository_id != revision.repository_id
            or checkpoint.commit != revision.commit
            or checkpoint.tree != revision.tree
            or link.workspace_id != checkpoint.workspace_id
            or link.result_commit != checkpoint.commit
            or link.result_tree != checkpoint.tree
            or link.linked_by_agent_member_id != checkpoint.agent_member_id
            or closure.manifest_digest != link.lfs_closure_manifest_digest
            or closure.binding_id != checkpoint.repository_binding_id
            or closure.binding_version != checkpoint.repository_binding_version
            or closure.repository_id != checkpoint.repository_id
            or closure.commit != checkpoint.commit
            or closure.tree != checkpoint.tree
            or closure.policy_digest
            != revision.repository_policy_digest
            or publication_proof is None
            or publication_proof.get("manifest_digest") != closure.manifest_digest
        ):
            raise ScientificFileDeliverableError(
                "producer adoption does not close over the exact published result revision"
            )
        return (
            operation,
            execution,
            result,
            request,
            link,
            checkpoint,
            closure,
            disposition,
            dict(publication_proof),
        )

    def finalize(
        self,
        *,
        publication_id: str,
        attempt_id: str,
        selection_id: str,
        actor_ref: str,
        execution_fencing_token: int,
        contract_id: str,
        contract_digest: str,
        requirements: tuple[ScientificRoleRequirement, ...],
    ) -> ScientificDeliverableFinalizationResult:
        if not requirements:
            raise ScientificFileDeliverableError("scientific role manifest is empty")
        roles = tuple(item.scientific_role for item in requirements)
        paths = tuple(item.path for item in requirements)
        if len(set(roles)) != len(roles) or len(set(paths)) != len(paths):
            raise ScientificFileDeliverableError("scientific roles and paths must be unique")
        authority = current_mutation_write_authority()

        revision = self.repositories.published_revisions.get(publication_id)
        attempt = self.repositories.scientific_attempts.get(attempt_id)
        selection = self.repositories.scientific_selections.get(selection_id)
        resolved_head = self.repositories.scientific_selections.resolve_head(attempt_id)
        publication_execution = (
            None
            if revision is None
            else self.repositories.controlled_operation_executions.get(
                revision.controlled_execution_id
            )
        )
        publication_receipt = (
            None
            if revision is None
            else self.repositories.workspace_publication_remote_receipts.get(
                revision.remote_receipt_id
            )
        )
        if (
            revision is None
            or attempt is None
            or selection is None
            or selection.attempt_id != attempt_id
            or selection.state is not ScientificSelectionState.SEALED
            or selection.actor_ref != actor_ref
            or attempt.status not in {
                ScientificAttemptStatus.ACTIVE,
                ScientificAttemptStatus.CLOSING,
            }
            or revision.session_id != attempt.session_id
            or resolved_head is None
            or resolved_head.head.selection_id != selection_id
            or authority is None
            or authority.scope_id != attempt.mutation_scope_id
            or authority.owner_kind is not MutationWriterKind.CONTROLLED_OPERATION
            or publication_execution is None
            or publication_execution.session_id != attempt.session_id
            or publication_execution.fencing_token != execution_fencing_token
            or publication_execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.TERMINAL
            or publication_execution.terminal_outcome
            is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            or publication_execution.result_handle_ref
            != f"publication:{publication_id}"
            or publication_receipt is None
            or publication_receipt.publication_id != publication_id
            or publication_receipt.intent_id != revision.intent_id
            or publication_receipt.execution_id != revision.controlled_execution_id
            or publication_receipt.execution_fencing_token
            != execution_fencing_token
            or publication_receipt.new_commit != revision.commit
            or publication_receipt.new_tree != revision.tree
            or publication_receipt.server_observed_commit != revision.commit
        ):
            raise ScientificFileDeliverableError(
                "publication, attempt, or sealed selection identity is not current"
            )

        resolved = tuple(
            self.resolver.resolve(publication_id=publication_id, path=item.path)
            for item in requirements
        )
        for requirement, file in zip(requirements, resolved, strict=True):
            requirement.validate_bytes(file.actual_bytes)
        adoptions = tuple(
            self.repositories.scientific_deliverables.get_adoption(
                item.producer_adoption_id
            )
            for item in requirements
        )
        if any(
            adoption is None
            or adoption.attempt_id != attempt_id
            or adoption.selection_id != selection_id
            or adoption.selection_revision != selection.revision
            or adoption.workflow_role != requirement.scientific_role
            for adoption, requirement in zip(adoptions, requirements, strict=True)
        ):
            raise ScientificFileDeliverableError("producer adoption chain is not exact")
        producer_lineages = tuple(
            self._require_producer_lineage(
                adoption=adoption,
                requirement=requirement,
                attempt_id=attempt_id,
                selection_id=selection_id,
                actor_ref=actor_ref,
                revision=revision,
            )
            for adoption, requirement in zip(adoptions, requirements, strict=True)
            if adoption is not None
        )

        preimage = {
            "schema_version": "scientific_deliverable_validation_preimage@1",
            "publication_digest": revision.revision_digest,
            "attempt_id": attempt_id,
            "attempt_state_version": attempt.state_version,
            "selection_id": selection_id,
            "selection_revision": selection.revision,
            "selection_adoption_digest": selection.adoption_digest,
            "actor_ref": actor_ref,
            "execution_fencing_token": execution_fencing_token,
            "contract_id": contract_id,
            "contract_digest": contract_digest,
            "entries": [
                {
                    "role": requirement.scientific_role,
                    "path": file.path,
                    "format_contract_id": requirement.format_contract_id,
                    "format_contract_digest": requirement.format_contract_digest,
                    "content_digest": file.content_digest,
                    "object_id": file.manifest_entry.object_id,
                    "lfs_oid": file.manifest_entry.lfs_oid,
                    "producer_adoption_digest": adoption.adoption_digest,
                    "producer_execution_digest": lineage[1].result_digest,
                    "producer_result_revision_link_digest": lineage[4].link_digest,
                    "producer_lfs_closure_manifest_digest": (
                        lineage[6].manifest_digest
                    ),
                }
                for requirement, file, adoption, lineage in zip(
                    requirements,
                    resolved,
                    adoptions,
                    producer_lineages,
                    strict=True,
                )
                if adoption is not None
            ],
        }
        validation_preimage_digest = canonical_scientific_deliverable_digest(preimage)
        existing_bundle = self.repositories.scientific_deliverables.get_bundle_for_attempt(
            attempt_id=attempt_id,
            selection_id=selection_id,
            contract_id=contract_id,
        )
        if existing_bundle is not None:
            existing_receipt = (
                self.repositories.scientific_deliverables.get_receipt_for_bundle(
                    existing_bundle.bundle_id
                )
            )
            existing_refs = self.repositories.scientific_deliverables.list_refs_by_bundle(
                existing_bundle.bundle_id
            )
            if (
                existing_receipt is None
                or existing_bundle.validation_preimage_digest
                != validation_preimage_digest
                or existing_bundle.publication_id != publication_id
                or existing_bundle.contract_digest != contract_digest
                or tuple(sorted(ref.ref_id for ref in existing_refs))
                != existing_bundle.ref_ids
            ):
                raise ScientificFileDeliverableError(
                    "scientific finalization idempotency identity conflicts"
                )
            return ScientificDeliverableFinalizationResult(
                refs=existing_refs,
                bundle=existing_bundle,
                receipt=existing_receipt,
            )
        created_at = self.now().isoformat()
        refs = tuple(
            ScientificDeliverableRef.create(
                ref_id=_stable_id(
                    "scientific_ref",
                    canonical_scientific_deliverable_digest(
                        {**preimage["entries"][index], "publication_id": publication_id}
                    ),
                ),
                project_id=revision.project_id,
                session_id=revision.session_id,
                repository_binding_id=revision.repository_binding_id,
                repository_binding_version=revision.repository_binding_version,
                repository_policy_digest=revision.repository_policy_digest,
                publication_id=revision.publication_id,
                publication_digest=revision.revision_digest,
                publication_ref=revision.publication_ref,
                published_commit=revision.commit,
                published_tree=revision.tree,
                path=file.path,
                storage=file.storage,
                git_blob_oid=(
                    file.manifest_entry.object_id
                    if file.storage is ScientificFileStorage.GIT_BLOB
                    else None
                ),
                lfs_oid=file.manifest_entry.lfs_oid,
                lfs_declared_size=file.manifest_entry.lfs_size_bytes,
                actual_size=len(file.actual_bytes),
                content_digest=file.content_digest,
                scientific_role=requirement.scientific_role,
                format_contract_id=requirement.format_contract_id,
                format_contract_digest=requirement.format_contract_digest,
                deliverable_contract_id=contract_id,
                deliverable_contract_digest=contract_digest,
                producer_operation_id=adoption.operation_id,
                producer_execution_id=adoption.execution_id,
                producer_result_id=adoption.result_id,
                producer_result_digest=adoption.result_digest,
                attempt_id=attempt_id,
                attempt_state_version=attempt.state_version,
                selection_id=selection_id,
                selection_revision=selection.revision,
                producer_adoption_id=adoption.adoption_id,
                selection_adoption_digest=selection.adoption_digest,
                publisher_workspace_id=revision.publisher_workspace_id,
                publisher_workspace_generation=revision.publisher_workspace_generation,
                publisher_agent_member_id=revision.publisher_agent_member_id,
                created_at=created_at,
                supersedes_ref_id=None,
            )
            for index, (requirement, file, adoption) in enumerate(
                zip(requirements, resolved, adoptions, strict=True)
            )
            if adoption is not None
        )
        role_manifest_digest = canonical_scientific_deliverable_digest(
            [
                {"role": ref.scientific_role, "path": ref.path, "ref_digest": ref.ref_digest}
                for ref in sorted(refs, key=lambda item: item.scientific_role)
            ]
        )
        bundle_id = _stable_id("scientific_bundle", validation_preimage_digest)
        bundle = ScientificDeliverableBundle.create(
            bundle_id=bundle_id,
            project_id=revision.project_id,
            session_id=revision.session_id,
            attempt_id=attempt_id,
            selection_id=selection_id,
            publication_id=publication_id,
            publication_digest=revision.revision_digest,
            contract_id=contract_id,
            contract_digest=contract_digest,
            ref_ids=tuple(ref.ref_id for ref in refs),
            role_manifest_digest=role_manifest_digest,
            validation_preimage_digest=validation_preimage_digest,
            created_at=created_at,
        )
        receipt = ScientificDeliverableValidationReceipt.create(
            receipt_id=_stable_id("scientific_receipt", bundle.bundle_digest),
            bundle_id=bundle.bundle_id,
            bundle_digest=bundle.bundle_digest,
            publication_id=publication_id,
            publication_digest=revision.revision_digest,
            attempt_id=attempt_id,
            attempt_state_version=attempt.state_version,
            selection_id=selection_id,
            selection_revision=selection.revision,
            actor_ref=actor_ref,
            execution_fencing_token=execution_fencing_token,
            validation_preimage_digest=validation_preimage_digest,
            verified_ref_digests=tuple(ref.ref_digest for ref in refs),
            created_at=created_at,
        )

        with self.repositories.atomic(prefix="scientific_file_deliverable_finalize"):
            current_attempt = self.repositories.scientific_attempts.get(attempt_id)
            current_selection = self.repositories.scientific_selections.get(selection_id)
            current_head = self.repositories.scientific_selections.resolve_head(attempt_id)
            current_revision = self.repositories.published_revisions.get(publication_id)
            current_authority = current_mutation_write_authority()
            current_publication_execution = (
                self.repositories.controlled_operation_executions.get(
                    revision.controlled_execution_id
                )
            )
            current_publication_receipt = (
                self.repositories.workspace_publication_remote_receipts.get(
                    revision.remote_receipt_id
                )
            )
            current_lineages = tuple(
                self._require_producer_lineage(
                    adoption=adoption,
                    requirement=requirement,
                    attempt_id=attempt_id,
                    selection_id=selection_id,
                    actor_ref=actor_ref,
                    revision=revision,
                )
                for adoption, requirement in zip(
                    adoptions,
                    requirements,
                    strict=True,
                )
                if adoption is not None
            )
            if (
                current_attempt != attempt
                or current_selection != selection
                or current_revision != revision
                or current_head != resolved_head
                or current_authority != authority
                or current_publication_execution != publication_execution
                or current_publication_receipt != publication_receipt
                or current_lineages != producer_lineages
            ):
                raise ScientificFileDeliverableError(
                    "scientific finalization facts drifted before commit"
                )
            stored_refs = tuple(
                self.repositories.scientific_deliverables.add_ref(ref) for ref in refs
            )
            stored_bundle = self.repositories.scientific_deliverables.add_bundle(
                bundle,
                refs=stored_refs,
            )
            stored_receipt = self.repositories.scientific_deliverables.add_receipt(receipt)
        return ScientificDeliverableFinalizationResult(
            refs=stored_refs,
            bundle=stored_bundle,
            receipt=stored_receipt,
        )


__all__ = [
    "ResolvedScientificFile",
    "ScientificDeliverableFinalizationResult",
    "ScientificDeliverableFinalizationService",
    "ScientificFileDeliverableError",
    "ScientificFileEffectAdoptionService",
    "ScientificPublishedByteReader",
    "ScientificPublishedFileResolver",
    "ScientificRoleRequirement",
]
