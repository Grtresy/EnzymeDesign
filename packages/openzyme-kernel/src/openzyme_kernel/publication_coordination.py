from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublishedRevision
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import VerifiedWorkspaceCheckpoint
from openzyme_contracts import WorkspacePublicationDispatchIdentity
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationIntentState
from openzyme_contracts import WorkspacePublicationManifest
from openzyme_contracts import WorkspacePublicationRemoteReceipt
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import AuthorityApplicationService
from openzyme_extension_spi import AuthorityCheckRequest
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationApplicationService
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import PublicationApplicationCommand
from openzyme_extension_spi import PublicationApplicationService
from openzyme_extension_spi import PublicationCommandKind

from .errors import KernelContractError


class PublicationCoordinationState(StrEnum):
    RECONCILE_REQUIRED = "reconcile_required"
    MATERIALIZED = "materialized"


@dataclass(frozen=True, slots=True)
class WorkspacePublicationRequest:
    """Caller intent before Kernel freezes repository and manifest identity."""

    idempotency_key: str
    workspace_id: str
    workspace_generation: int
    expected_head_commit: str
    expected_tree: str
    declared_base_commit: str
    checkpoint_id: str
    repository_binding_version: int
    parent_publication_id: str | None = None
    supersedes_publication_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "workspace_id",
            "checkpoint_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("workspace_generation", "repository_binding_version"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name in (
            "expected_head_commit",
            "expected_tree",
            "declared_base_commit",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or len(value) not in {40, 64}:
                raise ValueError(f"{field_name} must be an exact Git object id")
            if value != value.lower():
                raise ValueError(
                    f"{field_name} must be a lowercase exact Git object id"
                )
            try:
                int(value, 16)
            except ValueError as exc:
                raise ValueError(
                    f"{field_name} must be an exact Git object id"
                ) from exc
        for field_name in ("parent_publication_id", "supersedes_publication_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)


class PublicationManifestValidationResult(Protocol):
    @property
    def manifest(self) -> WorkspacePublicationManifest: ...


class PublicationManifestPolicyPort(Protocol):
    """Adapter-owned Git/LFS policy check used before freezing an intent."""

    def validate(
        self,
        *,
        binding: ProjectRepositoryBinding,
        commit: str,
        tree: str,
        manifest: WorkspacePublicationManifest,
        authorization_scope_digest: str,
    ) -> PublicationManifestValidationResult: ...


@dataclass(frozen=True, slots=True)
class PublicationCoordinationOutcome:
    publication_id: str
    operation_id: str
    state: PublicationCoordinationState
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool | None
    operation_record_digest: str
    controlled_operation_receipt_digest: str | None = None
    publication_receipt_digest: str | None = None
    remote_receipt_digest: str | None = None
    error_code: str | None = None
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.publication_id, field_name="publication_id")
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(
            self.operation_record_digest,
            field_name="operation_record_digest",
        )
        for value, field_name in (
            (
                self.controlled_operation_receipt_digest,
                "controlled_operation_receipt_digest",
            ),
            (self.publication_receipt_digest, "publication_receipt_digest"),
            (self.remote_receipt_digest, "remote_receipt_digest"),
        ):
            if value is not None:
                require_digest(value, field_name=field_name)
        if self.error_code is not None:
            require_identifier(self.error_code, field_name="error_code")
        if self.fallback_performed:
            raise ValueError("publication coordination cannot perform hidden fallback")
        if self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.mutation_applied is not None:
                raise ValueError("dispatch_in_doubt requires an unknown mutation fact")
            if self.state is not PublicationCoordinationState.RECONCILE_REQUIRED:
                raise ValueError("dispatch_in_doubt requires reconciliation")
        elif self.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN:
            if self.mutation_applied is not True:
                raise ValueError("materialized publication requires a known mutation")
            if self.state is not PublicationCoordinationState.MATERIALIZED:
                raise ValueError("terminal publication must be materialized")
        else:
            raise ValueError("publication outcome must be uncertain or terminal")


class PublicationCoordinationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
    ) -> None:
        super().__init__(message)
        require_identifier(code, field_name="code")
        if effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if mutation_applied is not False:
                raise ValueError("no_effect publication error requires mutation_applied=false")
        elif effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if mutation_applied is not None:
                raise ValueError(
                    "dispatch_in_doubt publication error requires unknown mutation"
                )
        elif mutation_applied is None:
            raise ValueError("known publication effect requires a mutation fact")
        self.code = code
        self.effect_certainty = effect_certainty
        self.mutation_applied = mutation_applied
        self.fallback_performed = False


class WorkspacePublicationCoordinator:
    """Coordinate one create-only publication through generic Kernel truth.

    The coordinator records a pessimistic dispatch-in-doubt fact immediately
    before entering the Adapter effect boundary.  Therefore an existing
    ``reconcile_required`` operation can only be observed; it is never
    redispatched or moved to another route.
    """

    def __init__(
        self,
        *,
        reader: KernelRecordReaderPort,
        authority: AuthorityApplicationService,
        publications: PublicationApplicationService,
        controlled_operations: ControlledOperationApplicationService,
        revision_backend: WorkspaceRevisionBackendPort,
        manifest_policy: PublicationManifestPolicyPort | None = None,
    ) -> None:
        self._reader = reader
        self._authority = authority
        self._publications = publications
        self._controlled_operations = controlled_operations
        self._revision_backend = revision_backend
        self._manifest_policy = manifest_policy

    def prepare_and_publish(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspacePublicationRequest,
        created_at: str,
    ) -> tuple[WorkspacePublicationIntent, PublicationCoordinationOutcome]:
        """Freeze the exact Adapter-observed intent, then cross one effect boundary."""

        intent, operation_id = self.prepare_intent(
            context=context,
            request=request,
            created_at=created_at,
        )
        return intent, self.publish(
            context=context,
            intent=intent,
            operation_id=operation_id,
        )

    def prepare_intent(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspacePublicationRequest,
        created_at: str,
    ) -> tuple[WorkspacePublicationIntent, str]:
        """Create one deterministic frozen intent without dispatching publication."""

        require_identifier(created_at, field_name="created_at")
        seed = canonical_sha256_digest(
            {
                "session_id": context.session_id,
                "idempotency_key": request.idempotency_key,
            }
        ).removeprefix("sha256:")
        publication_id = f"publication_{seed[:32]}"
        intent_id = f"publication_intent_{seed[:32]}"
        operation_id = f"publication_operation_{seed[:32]}"
        existing = self._reader.read(
            entity_type="workspace_publication_intent",
            entity_id=publication_id,
        )
        if existing is not None:
            try:
                intent = WorkspacePublicationIntent.from_dict(dict(existing.payload))
            except (TypeError, ValueError) as exc:
                raise KernelContractError(
                    "publication_intent_invalid",
                    "Stored publication intent is invalid",
                ) from exc
            self._require_preparation_replay(context, request, intent)
            return intent, operation_id

        if self._manifest_policy is None:
            raise KernelContractError(
                "publication_manifest_policy_unavailable",
                "Publication preparation requires the selected workspace policy Port",
            )
        session = self._reader.read(
            entity_type="session",
            entity_id=context.session_id,
        )
        if (
            session is None
            or session.state_version != context.expected_session_version
            or session.payload.get("status") != "active"
        ):
            raise KernelContractError(
                "publication_session_identity_stale",
                "Publication preparation requires the exact active Session version",
            )
        workspace = self._workspace(request.workspace_id)
        if (
            workspace.session_id != context.session_id
            or workspace.owner_member_id != context.actor_id
            or workspace.generation != request.workspace_generation
            or context.workspace_generation != workspace.generation
        ):
            raise KernelContractError(
                "publication_workspace_identity_stale",
                "Publication request differs from current workspace owner or generation",
            )
        pin = self._session_pin(context.session_id)
        binding = self._binding_from_pin(pin)
        if session.payload.get("project_id") != binding.project_id:
            raise KernelContractError(
                "publication_project_identity_stale",
                "Session and repository binding belong to different Projects",
            )
        if (
            request.repository_binding_version != pin.binding_version
            or request.declared_base_commit != pin.resolved_base_commit
        ):
            raise KernelContractError(
                "publication_repository_identity_stale",
                "Publication request differs from the Session-pinned repository base",
            )
        checkpoint = self._checkpoint(request.checkpoint_id)
        if (
            checkpoint.boundary.value != "publication"
            or checkpoint.session_id != context.session_id
            or checkpoint.agent_member_id != context.actor_id
            or checkpoint.workspace_id != request.workspace_id
            or checkpoint.workspace_generation != request.workspace_generation
            or checkpoint.repository_binding_id != pin.binding_id
            or checkpoint.repository_binding_version != pin.binding_version
            or checkpoint.commit != request.expected_head_commit
            or checkpoint.tree != request.expected_tree
        ):
            raise KernelContractError(
                "publication_checkpoint_stale",
                "Publication request differs from its exact verified checkpoint",
            )
        self._authorize_workspace(context, request.workspace_id)
        self._require_publication_relationships(
            context=context,
            binding=binding,
            request=request,
        )
        try:
            commit = self._revision_backend.observe_commit(
                binding,
                commit=request.expected_head_commit,
            )
            observed_manifest = self._revision_backend.observe_manifest(
                binding,
                commit=request.expected_head_commit,
            )
        except Exception as exc:
            raise PublicationCoordinationError(
                "publication_source_observation_failed",
                "Publication source observation failed before dispatch",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            ) from exc
        if (
            commit.repository_binding_id != binding.binding_id
            or commit.repository_binding_version != binding.binding_version
            or commit.repository_id != binding.repository_id
            or commit.commit != request.expected_head_commit
            or commit.tree != request.expected_tree
            or observed_manifest.repository_binding_id != binding.binding_id
            or observed_manifest.repository_binding_version != binding.binding_version
            or observed_manifest.repository_id != binding.repository_id
            or observed_manifest.commit != request.expected_head_commit
            or observed_manifest.tree != request.expected_tree
        ):
            raise KernelContractError(
                "publication_source_identity_mismatch",
                "Adapter source observation differs from the requested commit/tree",
            )
        try:
            validation = self._manifest_policy.validate(
                binding=binding,
                commit=request.expected_head_commit,
                tree=request.expected_tree,
                manifest=observed_manifest.manifest,
                authorization_scope_digest=canonical_sha256_digest(
                    {
                        "schema_version": "publication_authorization_scope@1",
                        "binding_id": binding.binding_id,
                        "binding_version": binding.binding_version,
                        "session_id": context.session_id,
                        "agent_member_id": context.actor_id,
                        "workspace_generation": workspace.generation,
                        "authority_lease_id": context.authority_lease_id,
                    }
                ),
            )
        except (KernelContractError, PublicationCoordinationError):
            raise
        except Exception as exc:
            raise PublicationCoordinationError(
                "publication_manifest_policy_failed",
                "Publication manifest policy failed before dispatch",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            ) from exc
        manifest = validation.manifest
        if not isinstance(manifest, WorkspacePublicationManifest):
            raise KernelContractError(
                "publication_manifest_policy_invalid",
                "Publication policy Port returned an invalid manifest",
            )
        intent = WorkspacePublicationIntent.create(
            intent_id=intent_id,
            publication_id=publication_id,
            idempotency_key=request.idempotency_key,
            project_id=binding.project_id,
            session_id=context.session_id,
            agent_member_id=context.actor_id,
            agent_id=checkpoint.agent_id,
            workspace_id=workspace.workspace_id,
            workspace_generation=workspace.generation,
            capability_lease_id=context.authority_lease_id,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            expected_head_commit=request.expected_head_commit,
            expected_tree=request.expected_tree,
            git_parent_commits=commit.parent_commits,
            declared_base_commit=request.declared_base_commit,
            parent_publication_id=request.parent_publication_id,
            supersedes_publication_id=request.supersedes_publication_id,
            publication_ref=(
                f"{binding.ref_namespace_policy.publication_prefix}/{publication_id}"
            ),
            manifest=manifest,
            repository_policy_version=binding.repository_policy_version,
            repository_policy_digest=binding.repository_policy_digest,
            checkpoint_id=checkpoint.checkpoint_id,
            state=WorkspacePublicationIntentState.FROZEN,
            created_at=created_at,
        )
        return intent, operation_id

    def _workspace(self, workspace_id: str) -> WorkspaceRuntimeBinding:
        record = self._reader.read(
            entity_type="workspace_runtime_binding",
            entity_id=workspace_id,
        )
        if record is None:
            raise KernelContractError(
                "workspace_binding_not_found",
                "Publication workspace binding is absent",
            )
        try:
            return WorkspaceRuntimeBinding.from_dict(dict(record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_binding_invalid",
                "Publication workspace binding is invalid",
            ) from exc

    def _session_pin(self, session_id: str) -> SessionRepositoryBindingPin:
        record = self._reader.read(
            entity_type="session_repository_binding_pin",
            entity_id=session_id,
        )
        if record is None:
            raise KernelContractError(
                "repository_binding_pin_missing",
                "Publication Session repository pin is absent",
            )
        try:
            return SessionRepositoryBindingPin.from_dict(dict(record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "repository_binding_pin_invalid",
                "Publication Session repository pin is invalid",
            ) from exc

    def _binding_from_pin(
        self,
        pin: SessionRepositoryBindingPin,
    ) -> ProjectRepositoryBinding:
        record = self._reader.read(
            entity_type="project_repository_binding",
            entity_id=pin.binding_id,
        )
        if record is None:
            raise KernelContractError(
                "repository_binding_not_found",
                "Publication repository binding is absent",
            )
        try:
            binding = ProjectRepositoryBinding.from_dict(dict(record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "repository_binding_invalid",
                "Publication repository binding is invalid",
            ) from exc
        if (
            binding.project_id != pin.project_id
            or binding.binding_version != pin.binding_version
            or binding.repository_id != pin.repository_id
            or binding.canonical_digest != pin.binding_canonical_digest
        ):
            raise KernelContractError(
                "repository_binding_pin_stale",
                "Publication repository binding differs from its Session pin",
            )
        return binding

    def _checkpoint(self, checkpoint_id: str) -> VerifiedWorkspaceCheckpoint:
        record = self._reader.read(
            entity_type="verified_workspace_checkpoint",
            entity_id=checkpoint_id,
        )
        if record is None:
            raise KernelContractError(
                "publication_checkpoint_missing",
                "Publication requires an exact verified checkpoint",
            )
        try:
            return VerifiedWorkspaceCheckpoint.from_dict(dict(record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "publication_checkpoint_invalid",
                "Publication checkpoint is invalid",
            ) from exc

    def _authorize_workspace(
        self,
        context: KernelCommandContext,
        workspace_id: str,
    ) -> None:
        decision = self._authority.authorize(
            AuthorityCheckRequest(
                context=context.to_query_context(),
                operation="workspace.publish",
                scope_id=workspace_id,
                expected_generation=context.authority_generation,
                expected_fence=context.authority_fence,
            )
        )
        if (
            decision.operation != "workspace.publish"
            or decision.scope_id != workspace_id
            or decision.authority_lease_id != context.authority_lease_id
            or decision.generation != context.authority_generation
            or decision.fence != context.authority_fence
        ):
            raise KernelContractError(
                "publication_authority_decision_mismatch",
                "Authority response differs from publication preparation identity",
            )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "publication_authority_denied",
                "AgentAuthorityLease denies publication preparation",
            )

    def _require_publication_relationships(
        self,
        *,
        context: KernelCommandContext,
        binding: ProjectRepositoryBinding,
        request: WorkspacePublicationRequest,
    ) -> None:
        for publication_id in (
            request.parent_publication_id,
            request.supersedes_publication_id,
        ):
            if publication_id is None:
                continue
            record = self._reader.read(
                entity_type="published_revision",
                entity_id=publication_id,
            )
            if record is None:
                raise KernelContractError(
                    "publication_relationship_invalid",
                    "Related publication is absent",
                )
            try:
                revision = PublishedRevision.from_dict(dict(record.payload))
            except (TypeError, ValueError) as exc:
                raise KernelContractError(
                    "publication_relationship_invalid",
                    "Related publication is invalid",
                ) from exc
            if (
                revision.session_id != context.session_id
                or revision.repository_binding_id != binding.binding_id
                or revision.repository_binding_version != binding.binding_version
            ):
                raise KernelContractError(
                    "publication_relationship_invalid",
                    "Related publication differs from the exact Session binding",
                )

    @staticmethod
    def _require_preparation_replay(
        context: KernelCommandContext,
        request: WorkspacePublicationRequest,
        intent: WorkspacePublicationIntent,
    ) -> None:
        if (
            intent.session_id != context.session_id
            or intent.agent_member_id != context.actor_id
            or intent.capability_lease_id != context.authority_lease_id
            or intent.workspace_id != request.workspace_id
            or intent.workspace_generation != request.workspace_generation
            or intent.expected_head_commit != request.expected_head_commit
            or intent.expected_tree != request.expected_tree
            or intent.declared_base_commit != request.declared_base_commit
            or intent.checkpoint_id != request.checkpoint_id
            or intent.repository_binding_version
            != request.repository_binding_version
            or intent.parent_publication_id != request.parent_publication_id
            or intent.supersedes_publication_id
            != request.supersedes_publication_id
        ):
            raise KernelContractError(
                "publication_idempotency_conflict",
                "Publication idempotency replay changes frozen identity",
            )

    def publish(
        self,
        *,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        operation_id: str,
    ) -> PublicationCoordinationOutcome:
        self._validate_context(context, intent, operation_id=operation_id)
        materialized = self._reader.read(
            entity_type="published_revision",
            entity_id=intent.publication_id,
        )
        if materialized is not None:
            return self._materialized_replay(
                context=context,
                intent=intent,
                operation_id=operation_id,
                revision_digest=materialized.record_digest,
            )

        self._publications.execute(
            PublicationApplicationCommand(
                context=_phase_context(context, "publication-admit"),
                operation=PublicationCommandKind.PUBLISH,
                resource_id=intent.publication_id,
                workspace_id=intent.workspace_id,
                expected_workspace_generation=intent.workspace_generation,
                payload={"phase": "admit", "intent": intent.to_dict()},
            )
        )
        operation = self._reader.read(
            entity_type="controlled_operation",
            entity_id=operation_id,
        )
        if operation is None:
            self._controlled_operations.execute(
                ControlledOperationApplicationCommand(
                    context=_phase_context(context, "operation-admit"),
                    operation=ControlledOperationCommandKind.ADMIT,
                    operation_id=operation_id,
                    intent_digest=intent.canonical_digest,
                    payload={
                        "workspace_id": intent.workspace_id,
                        "workspace_generation": intent.workspace_generation,
                        "operation_name": "workspace.publish",
                        "authority_operation": "workspace.publish",
                        "scope_id": intent.workspace_id,
                        "publication_id": intent.publication_id,
                        "request_digest": intent.canonical_digest,
                        "fallback_performed": False,
                    },
                )
            )
            operation = self._required_operation(operation_id, intent, context)
        else:
            self._require_operation_identity(operation, intent, context)

        state = operation.payload.get("state")
        if state == "settled":
            return self._recover_terminal_materialization(
                context=context,
                intent=intent,
                operation_id=operation_id,
                operation=operation,
            )
        if state == "reconcile_required":
            return self.reconcile(
                context=context,
                intent=intent,
                operation_id=operation_id,
            )
        if state != "admitted":
            raise KernelContractError(
                "publication_controlled_operation_state_invalid",
                "Publication operation is neither admitted nor reconcilable",
            )

        self._authorize_dispatch(context, intent)
        pending = self._controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(
                    context,
                    f"dispatch-intent-{operation.state_version}",
                ),
                operation=ControlledOperationCommandKind.RECONCILE,
                operation_id=operation_id,
                intent_digest=intent.canonical_digest,
                payload={
                    "effect_certainty": ExternalEffectCertainty.DISPATCH_IN_DOUBT.value,
                    "mutation_applied": None,
                    "error_code": "publication_dispatch_pending",
                    "fallback_performed": False,
                },
            )
        )
        operation = self._required_operation(operation_id, intent, context)
        binding = self._binding(intent)
        dispatch = self._dispatch_identity(
            intent=intent,
            operation_id=operation_id,
            operation=operation,
            context=context,
        )
        try:
            receipt = self._revision_backend.dispatch_publication(
                binding,
                intent,
                dispatch,
            )
            self._require_remote_receipt(intent, dispatch, receipt)
        except Exception:
            return self._outcome(
                intent=intent,
                operation_id=operation_id,
                state=PublicationCoordinationState.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                operation_record=self._required_operation(
                    operation_id,
                    intent,
                    context,
                ),
                controlled_receipt=pending,
                error_code="publication_dispatch_in_doubt",
            )
        return self._settle_and_materialize(
            context=context,
            intent=intent,
            operation_id=operation_id,
            operation=operation,
            receipt=receipt,
            phase="dispatch-observed",
        )

    def reconcile(
        self,
        *,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        operation_id: str,
    ) -> PublicationCoordinationOutcome:
        self._validate_context(context, intent, operation_id=operation_id)
        materialized = self._reader.read(
            entity_type="published_revision",
            entity_id=intent.publication_id,
        )
        if materialized is not None:
            return self._materialized_replay(
                context=context,
                intent=intent,
                operation_id=operation_id,
                revision_digest=materialized.record_digest,
            )
        operation = self._required_operation(operation_id, intent, context)
        if operation.payload.get("state") == "settled":
            return self._recover_terminal_materialization(
                context=context,
                intent=intent,
                operation_id=operation_id,
                operation=operation,
            )
        if operation.payload.get("state") != "reconcile_required":
            raise KernelContractError(
                "publication_reconcile_not_required",
                "Publication reconciliation requires dispatch_in_doubt",
            )
        binding = self._binding(intent)
        dispatch = self._dispatch_identity(
            intent=intent,
            operation_id=operation_id,
            operation=operation,
            context=context,
        )
        receipt: WorkspacePublicationRemoteReceipt | None
        try:
            receipt = self._revision_backend.reconcile_publication(
                binding,
                intent,
                dispatch,
            )
            if receipt is not None:
                self._require_remote_receipt(intent, dispatch, receipt)
        except Exception:
            receipt = None
        if receipt is None:
            pending = self._controlled_operations.execute(
                ControlledOperationApplicationCommand(
                    context=_phase_context(
                        context,
                        f"reconcile-pending-{operation.state_version}",
                    ),
                    operation=ControlledOperationCommandKind.RECONCILE,
                    operation_id=operation_id,
                    intent_digest=intent.canonical_digest,
                    payload={
                        "effect_certainty": (
                            ExternalEffectCertainty.DISPATCH_IN_DOUBT.value
                        ),
                        "mutation_applied": None,
                        "error_code": "publication_observation_pending",
                        "fallback_performed": False,
                    },
                )
            )
            return self._outcome(
                intent=intent,
                operation_id=operation_id,
                state=PublicationCoordinationState.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                operation_record=self._required_operation(
                    operation_id,
                    intent,
                    context,
                ),
                controlled_receipt=pending,
                error_code="publication_observation_pending",
            )
        return self._settle_and_materialize(
            context=context,
            intent=intent,
            operation_id=operation_id,
            operation=operation,
            receipt=receipt,
            phase=f"reconcile-observed-{operation.state_version}",
        )

    def _recover_terminal_materialization(
        self,
        *,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        operation_id: str,
        operation,  # noqa: ANN001
    ) -> PublicationCoordinationOutcome:
        binding = self._binding(intent)
        dispatch = self._dispatch_identity(
            intent=intent,
            operation_id=operation_id,
            operation=operation,
            context=context,
        )
        try:
            receipt = self._revision_backend.reconcile_publication(
                binding,
                intent,
                dispatch,
            )
        except Exception as exc:
            raise PublicationCoordinationError(
                "publication_terminal_receipt_unavailable",
                "Known publication effect could not be re-observed for materialization",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                mutation_applied=True,
            ) from exc
        if receipt is None:
            raise PublicationCoordinationError(
                "publication_terminal_receipt_unavailable",
                "Known publication effect lacks its exact Adapter receipt",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                mutation_applied=True,
            )
        self._require_remote_receipt(intent, dispatch, receipt)
        terminal_digest = operation.payload.get("terminal_receipt_digest")
        if terminal_digest != receipt.receipt_digest:
            raise PublicationCoordinationError(
                "publication_terminal_receipt_mismatch",
                "Re-observed publication receipt differs from controlled truth",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                mutation_applied=True,
            )
        return self._materialize(
            context=context,
            intent=intent,
            operation_id=operation_id,
            operation=operation,
            receipt=receipt,
            controlled_receipt=None,
            phase=f"materialize-recovery-{operation.state_version}",
        )

    def _settle_and_materialize(
        self,
        *,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        operation_id: str,
        operation,  # noqa: ANN001
        receipt: WorkspacePublicationRemoteReceipt,
        phase: str,
    ) -> PublicationCoordinationOutcome:
        terminal = self._controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(context, phase),
                operation=ControlledOperationCommandKind.RECONCILE,
                operation_id=operation_id,
                intent_digest=intent.canonical_digest,
                payload={
                    "adapter_receipt_digest": receipt.receipt_digest,
                    "effect_certainty": ExternalEffectCertainty.TERMINAL_KNOWN.value,
                    "mutation_applied": True,
                    "result_handle": f"publication:{intent.publication_id}",
                    "terminal_receipt_digest": receipt.receipt_digest,
                    "fallback_performed": False,
                },
            )
        )
        settled = self._required_operation(operation_id, intent, context)
        return self._materialize(
            context=context,
            intent=intent,
            operation_id=operation_id,
            operation=settled,
            receipt=receipt,
            controlled_receipt=terminal,
            phase=f"materialize-{settled.state_version}",
        )

    def _materialize(
        self,
        *,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        operation_id: str,
        operation,  # noqa: ANN001
        receipt: WorkspacePublicationRemoteReceipt,
        controlled_receipt: KernelMutationReceipt | None,
        phase: str,
    ) -> PublicationCoordinationOutcome:
        materialized = self._publications.execute(
            PublicationApplicationCommand(
                context=_phase_context(context, phase),
                operation=PublicationCommandKind.PUBLISH,
                resource_id=intent.publication_id,
                workspace_id=intent.workspace_id,
                expected_workspace_generation=intent.workspace_generation,
                payload={
                    "phase": "materialize",
                    "controlled_operation_id": operation_id,
                    "remote_receipt": receipt.to_dict(),
                },
            )
        )
        return self._outcome(
            intent=intent,
            operation_id=operation_id,
            state=PublicationCoordinationState.MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            operation_record=operation,
            controlled_receipt=controlled_receipt,
            publication_receipt=materialized,
            remote_receipt=receipt,
        )

    def _authorize_dispatch(
        self,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
    ) -> None:
        decision = self._authority.authorize(
            AuthorityCheckRequest(
                context=context.to_query_context(),
                operation="workspace.publish",
                scope_id=intent.workspace_id,
                expected_generation=context.authority_generation,
                expected_fence=context.authority_fence,
            )
        )
        if (
            decision.operation != "workspace.publish"
            or decision.scope_id != intent.workspace_id
            or decision.authority_lease_id != context.authority_lease_id
            or decision.generation != context.authority_generation
            or decision.fence != context.authority_fence
        ):
            raise KernelContractError(
                "publication_authority_decision_mismatch",
                "Authority response differs from publication dispatch identity",
            )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "publication_authority_denied",
                "AgentAuthorityLease denies publication dispatch",
            )

    def _binding(self, intent: WorkspacePublicationIntent) -> ProjectRepositoryBinding:
        record = self._reader.read(
            entity_type="project_repository_binding",
            entity_id=intent.repository_binding_id,
        )
        if record is None:
            raise KernelContractError(
                "repository_binding_not_found",
                "Publication repository binding is absent",
            )
        try:
            binding = ProjectRepositoryBinding.from_dict(dict(record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "repository_binding_invalid",
                "Publication repository binding is invalid",
            ) from exc
        if (
            binding.binding_version != intent.repository_binding_version
            or binding.repository_id != intent.repository_id
            or binding.repository_policy_version != intent.repository_policy_version
            or binding.repository_policy_digest != intent.repository_policy_digest
        ):
            raise KernelContractError(
                "repository_binding_stale",
                "Publication intent differs from repository binding identity",
            )
        return binding

    def _required_operation(
        self,
        operation_id: str,
        intent: WorkspacePublicationIntent,
        context: KernelCommandContext,
    ):
        operation = self._reader.read(
            entity_type="controlled_operation",
            entity_id=operation_id,
        )
        if operation is None:
            raise KernelContractError(
                "publication_controlled_operation_missing",
                "Publication ControlledOperation is absent",
            )
        self._require_operation_identity(operation, intent, context)
        return operation

    @staticmethod
    def _require_operation_identity(
        operation,  # noqa: ANN001
        intent: WorkspacePublicationIntent,
        context: KernelCommandContext,
    ) -> None:
        if (
            operation.payload.get("session_id") != intent.session_id
            or operation.payload.get("actor_id") != intent.agent_member_id
            or operation.payload.get("intent_digest") != intent.canonical_digest
            or operation.payload.get("route_id") != context.route_id
            or operation.payload.get("authority_lease_id")
            != context.authority_lease_id
            or operation.payload.get("authority_generation")
            != context.authority_generation
            or operation.payload.get("authority_fence") != context.authority_fence
            or operation.payload.get("scope_id") != intent.workspace_id
        ):
            raise KernelContractError(
                "publication_controlled_operation_identity_stale",
                "Publication ControlledOperation differs from frozen intent",
            )

    @staticmethod
    def _dispatch_identity(
        *,
        intent: WorkspacePublicationIntent,
        operation_id: str,
        operation,  # noqa: ANN001
        context: KernelCommandContext,
    ) -> WorkspacePublicationDispatchIdentity:
        generation = operation.payload.get("dispatch_generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise KernelContractError(
                "publication_dispatch_generation_invalid",
                "Publication ControlledOperation lacks a dispatch generation",
            )
        digest = canonical_sha256_digest(
            {
                "publication_id": intent.publication_id,
                "operation_id": operation_id,
                "dispatch_generation": generation,
                "authority_fence": context.authority_fence,
            }
        ).removeprefix("sha256:")
        return WorkspacePublicationDispatchIdentity(
            receipt_id=f"publication_dispatch_{digest[:24]}",
            execution_id=operation_id,
            dispatch_generation=generation,
            fencing_token=context.authority_fence,
        )

    @staticmethod
    def _require_remote_receipt(
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
        receipt: WorkspacePublicationRemoteReceipt,
    ) -> None:
        if (
            receipt.receipt_id != dispatch.receipt_id
            or receipt.intent_id != intent.intent_id
            or receipt.publication_id != intent.publication_id
            or receipt.execution_id != dispatch.execution_id
            or receipt.execution_dispatch_generation != dispatch.dispatch_generation
            or receipt.execution_fencing_token != dispatch.fencing_token
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
                "Adapter receipt differs from frozen publication dispatch",
            )

    @staticmethod
    def _validate_context(
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        *,
        operation_id: str,
    ) -> None:
        require_identifier(operation_id, field_name="operation_id")
        if context.route_id is None:
            raise KernelContractError(
                "publication_route_missing",
                "Publication dispatch requires an explicit route",
            )
        if (
            context.session_id != intent.session_id
            or context.actor_id != intent.agent_member_id
            or context.authority_lease_id != intent.capability_lease_id
            or context.workspace_generation != intent.workspace_generation
        ):
            raise KernelContractError(
                "publication_context_identity_stale",
                "Publication context differs from authority, owner, or workspace identity",
            )

    def _materialized_replay(
        self,
        *,
        context: KernelCommandContext,
        intent: WorkspacePublicationIntent,
        operation_id: str,
        revision_digest: str,
    ) -> PublicationCoordinationOutcome:
        operation = self._reader.read(
            entity_type="controlled_operation",
            entity_id=operation_id,
        )
        if operation is None or operation.payload.get("state") != "settled":
            raise KernelContractError(
                "publication_materialized_operation_missing",
                "Published revision lacks its terminal ControlledOperation",
            )
        self._require_operation_identity(operation, intent, context)
        return PublicationCoordinationOutcome(
            publication_id=intent.publication_id,
            operation_id=operation_id,
            state=PublicationCoordinationState.MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            operation_record_digest=operation.record_digest,
            publication_receipt_digest=revision_digest,
        )

    @staticmethod
    def _outcome(
        *,
        intent: WorkspacePublicationIntent,
        operation_id: str,
        state: PublicationCoordinationState,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        operation_record,  # noqa: ANN001
        controlled_receipt: KernelMutationReceipt | None,
        publication_receipt: KernelMutationReceipt | None = None,
        remote_receipt: WorkspacePublicationRemoteReceipt | None = None,
        error_code: str | None = None,
    ) -> PublicationCoordinationOutcome:
        return PublicationCoordinationOutcome(
            publication_id=intent.publication_id,
            operation_id=operation_id,
            state=state,
            effect_certainty=effect_certainty,
            mutation_applied=mutation_applied,
            operation_record_digest=operation_record.record_digest,
            controlled_operation_receipt_digest=(
                None if controlled_receipt is None else controlled_receipt.receipt_digest
            ),
            publication_receipt_digest=(
                None
                if publication_receipt is None
                else publication_receipt.receipt_digest
            ),
            remote_receipt_digest=(
                None if remote_receipt is None else remote_receipt.receipt_digest
            ),
            error_code=error_code,
        )


def _phase_context(context: KernelCommandContext, phase: str) -> KernelCommandContext:
    return replace(
        context,
        command_id=f"{context.command_id}.{phase}",
        idempotency_key=f"{context.idempotency_key}.{phase}",
    )


__all__ = [
    "PublicationCoordinationError",
    "PublicationCoordinationOutcome",
    "PublicationCoordinationState",
    "PublicationManifestPolicyPort",
    "PublicationManifestValidationResult",
    "WorkspacePublicationRequest",
    "WorkspacePublicationCoordinator",
]
