from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
from typing import Protocol

from openzyme_domain import AgentCapability
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import PublicationFetchIdentity
from openzyme_domain import PublishedRevision
from openzyme_domain import RepositoryBindingLifecycleStatus
from openzyme_domain import RetryEligibility
from openzyme_domain import WorkspacePublicationIntent
from openzyme_domain import WorkspacePublicationIntentState
from openzyme_domain import WorkspacePublicationManifest
from openzyme_domain import WorkspacePublicationRemoteReceipt
from openzyme_domain import WorkspaceFormalBoundary
from openzyme_domain import canonical_publication_digest

from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .agent_capability_service import AgentCapabilityError
from .controlled_operation_execution import InvalidExecutionTransitionError
from .controlled_operation_execution import (
    validate_controlled_operation_execution_transition,
)
from .git_lfs_work_products import PublicationManifestValidation
from .git_lfs_work_products import publication_authorization_scope_digest
from .repositories import CoreRepositories
from .repositories import DurableEventRecord
from .workspace_checkpoints import WorkspaceCheckpointError
from .workspace_checkpoints import WorkspaceCheckpointService


PUBLICATION_ROUTE_POLICY_ID = "workspace_publication_create_only@1"
PUBLICATION_ADAPTER_POLICY_ID = "host_internal_git_publication@1"
PUBLICATION_RUNTIME_IDENTITY = "openzyme_host_publication_route@1"


class WorkspacePublicationError(RuntimeError):
    error_code = "workspace_publication_rejected"


class WorkspacePublicationIdentityError(WorkspacePublicationError):
    error_code = "workspace_publication_identity_conflict"


class WorkspacePublicationGitReader(Protocol):
    def list_refs(
        self,
        binding: ProjectRepositoryBinding,
        *,
        prefix: str,
    ) -> tuple[tuple[str, str], ...]: ...

    def read_commit_tree(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> str: ...

    def read_commit_parents(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> tuple[str, ...]: ...

    def read_whole_tree_manifest(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> WorkspacePublicationManifest: ...

    def read_exact_ref(
        self,
        binding: ProjectRepositoryBinding,
        *,
        ref_name: str,
    ) -> str | None: ...


class WorkspacePublicationRemoteRoute(Protocol):
    def create_publication_ref_if_absent(
        self,
        binding: ProjectRepositoryBinding,
        *,
        publication_id: str,
        ref_name: str,
        commit: str,
    ) -> str: ...


class PublicationManifestPolicyValidator(Protocol):
    def validate(
        self,
        *,
        binding: ProjectRepositoryBinding,
        commit: str,
        tree: str,
        manifest: WorkspacePublicationManifest,
        authorization_scope_digest: str,
    ) -> PublicationManifestValidation: ...


@dataclass(frozen=True, slots=True)
class CurrentPublicationManifestPolicyValidator:
    """C4 seam extended fail-closed by the following Git LFS change."""

    def validate(
        self,
        *,
        binding: ProjectRepositoryBinding,
        commit: str,
        tree: str,
        manifest: WorkspacePublicationManifest,
        authorization_scope_digest: str,
    ) -> PublicationManifestValidation:
        del commit, tree, authorization_scope_digest
        if not manifest.entries:
            raise WorkspacePublicationError(
                "whole-repository publication manifest is empty"
            )
        if not binding.repository_policy_digest:
            raise WorkspacePublicationError(
                "repository publication policy identity is missing"
            )
        return PublicationManifestValidation(
            manifest=manifest,
            lfs_closure=None,
            lfs_verification=None,
        )


@dataclass(frozen=True, slots=True)
class WorkspacePublishCommand:
    idempotency_key: str
    workspace_id: str
    workspace_generation: int
    expected_head_commit: str
    expected_tree: str
    declared_base_commit: str
    checkpoint_id: str
    whole_repository: bool
    repository_binding_version: int
    parent_publication_id: str | None = None
    supersedes_publication_id: str | None = None
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspacePublicationState:
    intent: WorkspacePublicationIntent
    execution: ControlledOperationExecution
    revision: PublishedRevision | None


@dataclass(slots=True)
class WorkspacePublicationService:
    repositories: CoreRepositories
    git_reader: WorkspacePublicationGitReader
    remote_route: WorkspacePublicationRemoteRoute
    manifest_policy: PublicationManifestPolicyValidator = (
        CurrentPublicationManifestPolicyValidator()
    )

    def publish(
        self,
        *,
        session_id: str,
        agent_id: str,
        command: WorkspacePublishCommand,
    ) -> WorkspacePublicationState:
        state = self.admit(
            session_id=session_id,
            agent_id=agent_id,
            command=command,
        )
        if state.revision is not None:
            with self.repositories.atomic(prefix="workspace_publication_event_recovery"):
                self._record_materialized_event(state.revision)
            return state
        if state.execution.lifecycle_state.is_terminal:
            return state
        if state.execution.effect_certainty is not ExternalEffectCertainty.NO_EFFECT:
            return self.reconcile(intent_id=state.intent.intent_id)
        return self._dispatch(state.intent, state.execution)

    def admit(
        self,
        *,
        session_id: str,
        agent_id: str,
        command: WorkspacePublishCommand,
    ) -> WorkspacePublicationState:
        normalized_key = command.idempotency_key.strip()
        if not normalized_key or normalized_key != command.idempotency_key:
            raise WorkspacePublicationError("publication idempotency key is invalid")
        existing = self.repositories.workspace_publication_intents.get_by_idempotency_key(
            session_id=session_id,
            idempotency_key=normalized_key,
        )
        if existing is not None:
            self._require_replay_matches(
                existing,
                agent_id=agent_id,
                command=command,
            )
            return self._state(existing)
        if not command.whole_repository:
            raise WorkspacePublicationError(
                "workspace publication accepts only the complete repository tree"
            )
        workspace = self.repositories.agent_git_workspaces.get(command.workspace_id)
        if (
            workspace is None
            or workspace.session_id != session_id
            or workspace.agent_id != agent_id
            or workspace.workspace_generation != command.workspace_generation
            or workspace.repository_binding_version
            != command.repository_binding_version
        ):
            raise WorkspacePublicationError(
                "publication request does not match the exact current workspace"
            )
        claims = ActiveAgentCapabilityLeaseValidator(
            self.repositories
        ).require_current_agent(
            session_id=session_id,
            agent_id=agent_id,
            expected_lease_id=workspace.capability_lease_id,
            expected_workspace_generation=workspace.workspace_generation,
            service_id="workspace_publication",
            protocol="host_create_only_ref",
            operation_class="workspace_publish",
            required_capabilities=(AgentCapability.GIT,),
            target_id="repository:session-pinned",
        )
        try:
            clean_proof = WorkspaceCheckpointService(
                self.repositories,
                self.git_reader,
            ).validate_clean_committed_revision(
                workspace_id=workspace.workspace_id,
                expected_commit=command.expected_head_commit,
                expected_tree=command.expected_tree,
            )
        except WorkspaceCheckpointError as exc:
            raise WorkspacePublicationError(str(exc)) from exc
        if clean_proof.verified_checkpoint_id != command.checkpoint_id:
            raise WorkspacePublicationError(
                "publication request does not name the exact verified checkpoint"
            )
        checkpoint = self.repositories.verified_workspace_checkpoints.get(
            clean_proof.verified_checkpoint_id
        )
        if (
            checkpoint is None
            or checkpoint.boundary is not WorkspaceFormalBoundary.PUBLICATION
        ):
            raise WorkspacePublicationError(
                "workspace publication requires a publication-boundary checkpoint"
            )
        binding = self._require_session_binding(
            session_id=session_id,
            binding_id=workspace.repository_binding_id,
        )
        if (
            binding.binding_version != workspace.repository_binding_version
            or binding.repository_id != workspace.repository_id
            or binding.canonical_digest != workspace.repository_binding_digest
            or binding.repository_policy_version
            != workspace.repository_policy_version
            or binding.repository_policy_digest
            != workspace.repository_policy_digest
        ):
            raise WorkspacePublicationError(
                "workspace repository identity differs from the pinned binding"
            )
        if command.declared_base_commit != workspace.base_commit:
            raise WorkspacePublicationError(
                "publication declared base does not match the workspace base"
            )
        self._require_publication_relationships(
            session_id=session_id,
            binding=binding,
            command=command,
        )
        tree = self.git_reader.read_commit_tree(
            binding,
            commit=command.expected_head_commit,
        )
        if tree != command.expected_tree:
            raise WorkspacePublicationError(
                "publication commit tree differs from the requested exact tree"
            )
        parents = self.git_reader.read_commit_parents(
            binding,
            commit=command.expected_head_commit,
        )
        manifest = self.git_reader.read_whole_tree_manifest(
            binding,
            commit=command.expected_head_commit,
        )
        validation = self.manifest_policy.validate(
            binding=binding,
            commit=command.expected_head_commit,
            tree=command.expected_tree,
            manifest=manifest,
            authorization_scope_digest=publication_authorization_scope_digest(
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                session_id=session_id,
                agent_member_id=workspace.agent_member_id,
                workspace_generation=workspace.workspace_generation,
                capability_lease_id=claims.lease.lease_id,
            ),
        )
        manifest = validation.manifest
        publication_id = _stable_id("publication", session_id, normalized_key)
        intent_id = _stable_id("publication_intent", session_id, normalized_key)
        publication_ref = (
            f"{binding.ref_namespace_policy.publication_prefix}/{publication_id}"
        )
        now = _utc_now_iso()
        intent = WorkspacePublicationIntent.create(
            intent_id=intent_id,
            publication_id=publication_id,
            idempotency_key=normalized_key,
            project_id=binding.project_id,
            session_id=session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_id=workspace.workspace_id,
            workspace_generation=workspace.workspace_generation,
            capability_lease_id=claims.lease.lease_id,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            expected_head_commit=command.expected_head_commit,
            expected_tree=command.expected_tree,
            git_parent_commits=parents,
            declared_base_commit=command.declared_base_commit,
            parent_publication_id=command.parent_publication_id,
            supersedes_publication_id=command.supersedes_publication_id,
            publication_ref=publication_ref,
            manifest=manifest,
            repository_policy_version=binding.repository_policy_version,
            repository_policy_digest=binding.repository_policy_digest,
            checkpoint_id=command.checkpoint_id,
            state=WorkspacePublicationIntentState.FROZEN,
            created_at=now,
        )
        execution = self._initial_execution(intent, command=command, created_at=now)
        event = self._event(
            execution,
            phase=ControlledOperationExecutionPhase.ADMISSION,
            previous=None,
            summary="publication intent admitted without human approval",
        )
        with self.repositories.atomic(prefix="workspace_publication_admission"):
            ActiveAgentCapabilityLeaseValidator(
                self.repositories
            ).require_current_agent(
                session_id=session_id,
                agent_id=agent_id,
                expected_lease_id=intent.capability_lease_id,
                expected_workspace_generation=intent.workspace_generation,
                service_id="workspace_publication",
                protocol="host_create_only_ref",
                operation_class="workspace_publish",
                required_capabilities=(AgentCapability.GIT,),
                target_id="repository:session-pinned",
            )
            concurrent = (
                self.repositories.workspace_publication_intents.get_by_idempotency_key(
                    session_id=session_id,
                    idempotency_key=normalized_key,
                )
            )
            if concurrent is not None:
                self._require_replay_matches(
                    concurrent,
                    agent_id=agent_id,
                    command=command,
                )
                canonical_intent = concurrent
                canonical_execution = (
                    self.repositories.workspace_publication_executions.get_by_intent(
                        concurrent.intent_id
                    )
                )
                if canonical_execution is None:
                    raise WorkspacePublicationIdentityError(
                        "concurrent publication intent has no controlled execution"
                    )
            else:
                canonical_intent = (
                    self.repositories.workspace_publication_intents.add_or_get_exact(
                        intent
                    )
                )
                canonical_execution = (
                    self.repositories.workspace_publication_executions.add(
                        intent=canonical_intent,
                        execution=execution,
                    )
                )
                self.repositories.workspace_publication_execution_events.append(event)
            if (validation.lfs_closure is None) != (
                validation.lfs_verification is None
            ):
                raise WorkspacePublicationIdentityError(
                    "Git LFS closure and fresh verification must be frozen together"
                )
            if (
                validation.lfs_closure is not None
                and validation.lfs_verification is not None
            ):
                existing_proof = (
                    self.repositories.git_lfs.get_publication_intent_proof(
                        canonical_intent.intent_id
                    )
                )
                if existing_proof is None:
                    self.repositories.git_lfs.link_publication_intent_proof(
                        intent_id=canonical_intent.intent_id,
                        publication_id=canonical_intent.publication_id,
                        closure=validation.lfs_closure,
                        verification=validation.lfs_verification,
                        created_at=now,
                    )
                elif (
                    existing_proof["manifest_digest"]
                    != validation.lfs_closure.manifest_digest
                ):
                    raise WorkspacePublicationIdentityError(
                        "idempotent publication replay produced another LFS closure"
                    )
        return WorkspacePublicationState(
            intent=canonical_intent,
            execution=canonical_execution,
            revision=None,
        )

    def reconcile(self, *, intent_id: str) -> WorkspacePublicationState:
        intent = self.repositories.workspace_publication_intents.get(intent_id)
        if intent is None:
            raise WorkspacePublicationError("publication intent does not exist")
        state = self._state(intent)
        if state.revision is not None or state.execution.lifecycle_state.is_terminal:
            return state
        if state.execution.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            raise WorkspacePublicationError(
                "publication with no dispatch intent cannot be reconciled"
            )
        binding = self._require_intent_binding(intent)
        try:
            observed = self.git_reader.read_exact_ref(
                binding,
                ref_name=intent.publication_ref,
            )
        except Exception:
            return self._ensure_reconcile_required(intent, state.execution)
        if observed is None:
            return self._ensure_reconcile_required(intent, state.execution)
        if observed != intent.expected_head_commit:
            failed = self._terminal_execution(
                intent,
                state.execution,
                outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                error_code="publication_ref_integrity_conflict",
                summary="publication ref exists at another commit",
            )
            return WorkspacePublicationState(intent, failed, None)
        return self._confirm_and_materialize(
            intent,
            state.execution,
            observed_commit=observed,
        )

    def fetch_identity(self, publication_id: str) -> PublicationFetchIdentity:
        revision = self.repositories.published_revisions.get(publication_id)
        if revision is None:
            raise WorkspacePublicationError("published revision does not exist")
        return PublicationFetchIdentity(
            publication_id=revision.publication_id,
            repository_binding_id=revision.repository_binding_id,
            repository_binding_version=revision.repository_binding_version,
            repository_id=revision.repository_id,
            publication_ref=revision.publication_ref,
            commit=revision.commit,
            tree=revision.tree,
            manifest_digest=revision.manifest.manifest_digest,
        )

    def validate_reference(
        self,
        *,
        publication_id: str,
        revision: str,
        path: str,
    ) -> PublishedRevision:
        published = self.repositories.published_revisions.get(publication_id)
        if (
            published is None
            or published.commit != revision
            or not published.contains_path(path)
        ):
            raise WorkspacePublicationError(
                "publication reference revision or manifest path is invalid"
            )
        return published

    def audit_session_namespace(self, session_id: str) -> dict[str, object]:
        revisions = self.repositories.published_revisions.list_by_session(session_id)
        expected_by_binding: dict[str, dict[str, str]] = {}
        bindings: dict[str, ProjectRepositoryBinding] = {}
        for revision in revisions:
            intent = self.repositories.workspace_publication_intents.get(
                revision.intent_id
            )
            if intent is None:
                raise WorkspacePublicationIdentityError(
                    f"published revision {revision.publication_id!r} has no frozen intent"
                )
            binding = self._require_intent_binding(intent)
            bindings[binding.binding_id] = binding
            expected_by_binding.setdefault(binding.binding_id, {})[
                revision.publication_ref
            ] = revision.commit
        issues: list[dict[str, str]] = []
        observed_count = 0
        for binding_id, binding in bindings.items():
            observed = dict(
                self.git_reader.list_refs(
                    binding,
                    prefix=f"{binding.ref_namespace_policy.publication_prefix}/",
                )
            )
            observed_count += len(observed)
            expected = expected_by_binding[binding_id]
            for ref_name, commit in expected.items():
                observed_commit = observed.get(ref_name)
                if observed_commit != commit:
                    issues.append(
                        {
                            "code": "publication_ref_missing_or_moved",
                            "publication_ref": ref_name,
                            "expected_commit": commit,
                            "observed_commit": observed_commit or "absent",
                        }
                    )
            for ref_name, commit in observed.items():
                if ref_name not in expected:
                    issues.append(
                        {
                            "code": "unmaterialized_publication_ref",
                            "publication_ref": ref_name,
                            "expected_commit": "no_canonical_revision",
                            "observed_commit": commit,
                        }
                    )
        return {
            "schema_version": "workspace_publication_namespace_audit@1",
            "session_id": session_id,
            "canonical_publication_count": len(revisions),
            "observed_publication_ref_count": observed_count,
            "issues": issues,
            "ok": not issues,
            "mutation_performed": False,
            "private_or_historical_refs_scanned": False,
        }

    def _dispatch(
        self,
        intent: WorkspacePublicationIntent,
        execution: ControlledOperationExecution,
    ) -> WorkspacePublicationState:
        try:
            ActiveAgentCapabilityLeaseValidator(
                self.repositories
            ).require_current_agent(
                session_id=intent.session_id,
                agent_id=intent.agent_id,
                expected_lease_id=intent.capability_lease_id,
                expected_workspace_generation=intent.workspace_generation,
                service_id="workspace_publication",
                protocol="host_create_only_ref",
                operation_class="workspace_publish",
                required_capabilities=(AgentCapability.GIT,),
                target_id="repository:session-pinned",
            )
        except AgentCapabilityError:
            terminal = self._terminal_execution(
                intent,
                execution,
                outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                error_code="publication_capability_inactive_before_dispatch",
                summary="publication lease became inactive before dispatch",
            )
            return WorkspacePublicationState(intent, terminal, None)
        dispatching = self._claim_and_begin_dispatch(intent, execution)
        binding = self._require_intent_binding(intent)
        try:
            observed = self.remote_route.create_publication_ref_if_absent(
                binding,
                publication_id=intent.publication_id,
                ref_name=intent.publication_ref,
                commit=intent.expected_head_commit,
            )
        except Exception:
            return self._ensure_reconcile_required(intent, dispatching)
        if observed != intent.expected_head_commit:
            return self._ensure_reconcile_required(intent, dispatching)
        return self._confirm_and_materialize(
            intent,
            dispatching,
            observed_commit=observed,
        )

    def _claim_and_begin_dispatch(
        self,
        intent: WorkspacePublicationIntent,
        execution: ControlledOperationExecution,
    ) -> ControlledOperationExecution:
        now = _utc_now_iso()
        claimed = replace(
            execution,
            lifecycle_state=ControlledOperationExecutionLifecycle.CLAIMED,
            state_version=execution.state_version + 1,
            lease_owner="host:workspace-publication",
            lease_token=_stable_id(
                "publication_lease",
                execution.execution_id,
                str(execution.state_version + 1),
            ),
            lease_expires_at=(
                datetime.now(tz=UTC) + timedelta(seconds=60)
            ).isoformat(),
            fencing_token=execution.fencing_token + 1,
            updated_at=now,
        )
        dispatching = replace(
            claimed,
            lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            dispatch_generation=claimed.dispatch_generation + 1,
            state_version=claimed.state_version + 1,
            backend_handle_ref=f"publication_ref:{intent.publication_ref}",
            updated_at=now,
        )
        with self.repositories.atomic(prefix="workspace_publication_dispatch_intent"):
            self._persist_transition(
                execution,
                claimed,
                phase=ControlledOperationExecutionPhase.CLAIM,
                summary="publication execution claimed",
            )
            self._persist_transition(
                claimed,
                dispatching,
                phase=ControlledOperationExecutionPhase.DISPATCH,
                summary="create-only publication ref dispatch intent persisted",
            )
        return dispatching

    def _ensure_reconcile_required(
        self,
        intent: WorkspacePublicationIntent,
        execution: ControlledOperationExecution,
    ) -> WorkspacePublicationState:
        if (
            execution.lifecycle_state
            is ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED
        ):
            return WorkspacePublicationState(intent, execution, None)
        updated = replace(
            execution,
            lifecycle_state=ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            state_version=execution.state_version + 1,
            updated_at=_utc_now_iso(),
        )
        self._persist_transition(
            execution,
            updated,
            phase=ControlledOperationExecutionPhase.RECONCILE,
            summary="publication outcome requires exact-ref reconciliation",
        )
        return WorkspacePublicationState(intent, updated, None)

    def _confirm_and_materialize(
        self,
        intent: WorkspacePublicationIntent,
        execution: ControlledOperationExecution,
        *,
        observed_commit: str,
    ) -> WorkspacePublicationState:
        existing = self.repositories.published_revisions.get(intent.publication_id)
        if existing is not None:
            with self.repositories.atomic(prefix="workspace_publication_event_recovery"):
                self._record_materialized_event(existing)
            return WorkspacePublicationState(intent, execution, existing)
        now = _utc_now_iso()
        terminal = replace(
            execution,
            lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            state_version=execution.state_version + 1,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            result_handle_ref=f"publication:{intent.publication_id}",
            result_digest=intent.canonical_digest,
            artifact_set_digest=intent.manifest.manifest_digest,
            updated_at=now,
            terminal_at=now,
        )
        receipt = WorkspacePublicationRemoteReceipt.create(
            receipt_id=_stable_id("publication_receipt", intent.intent_id),
            intent_id=intent.intent_id,
            publication_id=intent.publication_id,
            execution_id=terminal.execution_id,
            execution_dispatch_generation=terminal.dispatch_generation,
            execution_fencing_token=terminal.fencing_token,
            internal_git_service_id=self._require_intent_binding(
                intent
            ).internal_git_service_id,
            repository_binding_id=intent.repository_binding_id,
            repository_binding_version=intent.repository_binding_version,
            repository_id=intent.repository_id,
            publication_ref=intent.publication_ref,
            expected_previous_commit=None,
            new_commit=intent.expected_head_commit,
            new_tree=intent.expected_tree,
            server_observed_commit=observed_commit,
            observed_at=now,
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
            controlled_execution_id=terminal.execution_id,
            remote_receipt_id=receipt.receipt_id,
            supersedes_publication_id=intent.supersedes_publication_id,
            created_at=now,
        )
        with self.repositories.atomic(prefix="workspace_publication_materialize"):
            self._persist_transition(
                execution,
                terminal,
                phase=ControlledOperationExecutionPhase.TERMINAL,
                summary="exact publication ref confirmed",
                safe_receipt_digest=receipt.receipt_digest,
            )
            self.repositories.workspace_publication_remote_receipts.add(receipt)
            canonical = self.repositories.published_revisions.add(revision)
            policy = self.repositories.git_lfs.get_policy(
                binding_id=intent.repository_binding_id,
                binding_version=intent.repository_binding_version,
            )
            if policy is not None:
                proof = self.repositories.git_lfs.get_publication_intent_proof(
                    intent.intent_id
                )
                if proof is None:
                    raise WorkspacePublicationError(
                        "published revision has no frozen Git LFS closure proof"
                    )
                closure = self.repositories.git_lfs.get_closure_manifest(
                    str(proof["manifest_digest"])
                )
                verification = self.repositories.git_lfs.get_closure_verification(
                    str(proof["verification_id"])
                )
                if (
                    closure is None
                    or verification is None
                    or verification.verification_digest
                    != proof["verification_digest"]
                ):
                    raise WorkspacePublicationError(
                        "frozen Git LFS publication proof is incomplete or drifted"
                    )
                self.repositories.git_lfs.pin_publication(
                    publication_id=canonical.publication_id,
                    closure=closure,
                    verification=verification,
                    pinned_at=now,
                )
            self._record_materialized_event(canonical)
        return WorkspacePublicationState(intent, terminal, canonical)

    def _record_materialized_event(self, revision: PublishedRevision) -> None:
        pending = self.repositories.published_revisions.pending_event(
            revision.publication_id
        )
        if pending is None:
            return
        payload = {
            "publication_id": revision.publication_id,
            "session_id": revision.session_id,
            "repository_binding_id": revision.repository_binding_id,
            "repository_binding_version": revision.repository_binding_version,
            "commit": revision.commit,
            "tree": revision.tree,
            "revision_digest": revision.revision_digest,
            "supersedes_publication_id": revision.supersedes_publication_id,
            "outbox_id": pending["outbox_id"],
            "event_digest": pending["event_digest"],
        }
        self.repositories.durable_events.append(
            DurableEventRecord(
                event_id=pending["outbox_id"],
                session_id=revision.session_id,
                event_type=pending["event_type"],
                created_at=pending["created_at"],
                payload=payload,
                actor_ref=revision.publisher_agent_id,
            )
        )
        self.repositories.published_revisions.mark_event_delivered(
            outbox_id=pending["outbox_id"],
            delivered_at=_utc_now_iso(),
        )

    def _terminal_execution(
        self,
        intent: WorkspacePublicationIntent,
        execution: ControlledOperationExecution,
        *,
        outcome: ControlledOperationExecutionTerminalOutcome,
        effect_certainty: ExternalEffectCertainty,
        error_code: str,
        summary: str,
    ) -> ControlledOperationExecution:
        now = _utc_now_iso()
        terminal = replace(
            execution,
            lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
            terminal_outcome=outcome,
            effect_certainty=effect_certainty,
            retry_eligibility=RetryEligibility.TERMINAL,
            state_version=execution.state_version + 1,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=error_code,
            safe_error_summary=summary,
            updated_at=now,
            terminal_at=now,
        )
        self._persist_transition(
            execution,
            terminal,
            phase=ControlledOperationExecutionPhase.TERMINAL,
            summary=summary,
        )
        return terminal

    def _persist_transition(
        self,
        current: ControlledOperationExecution,
        updated: ControlledOperationExecution,
        *,
        phase: ControlledOperationExecutionPhase,
        summary: str,
        safe_receipt_digest: str | None = None,
    ) -> None:
        event = self._event(
            updated,
            phase=phase,
            previous=current.lifecycle_state,
            summary=summary,
            safe_receipt_digest=safe_receipt_digest,
        )
        try:
            validate_controlled_operation_execution_transition(
                current=current,
                updated=updated,
                event=event,
                expected_state_version=current.state_version,
            )
        except InvalidExecutionTransitionError as exc:
            raise WorkspacePublicationIdentityError(str(exc)) from exc
        self.repositories.workspace_publication_executions.replace_if_version(
            updated,
            expected_state_version=current.state_version,
            expected_lease_token=(
                current.lease_token if current.lease_owner is not None else None
            ),
            expected_fencing_token=(
                current.fencing_token if current.lease_owner is not None else None
            ),
        )
        self.repositories.workspace_publication_execution_events.append(event)

    def _state(self, intent: WorkspacePublicationIntent) -> WorkspacePublicationState:
        execution = self.repositories.workspace_publication_executions.get_by_intent(
            intent.intent_id
        )
        if execution is None:
            raise WorkspacePublicationIdentityError(
                "frozen publication intent has no controlled execution"
            )
        return WorkspacePublicationState(
            intent=intent,
            execution=execution,
            revision=self.repositories.published_revisions.get(intent.publication_id),
        )

    def _require_binding(self, binding_id: str) -> ProjectRepositoryBinding:
        binding = self.repositories.project_repository_bindings.get(binding_id)
        if binding is None:
            raise WorkspacePublicationError("repository binding does not exist")
        return binding

    def _require_session_binding(
        self,
        *,
        session_id: str,
        binding_id: str,
    ) -> ProjectRepositoryBinding:
        binding = self._require_binding(binding_id)
        pin = self.repositories.session_repository_binding_pins.require(session_id)
        if (
            pin.binding_id != binding.binding_id
            or pin.binding_version != binding.binding_version
            or pin.repository_id != binding.repository_id
            or pin.resolved_base_commit != binding.default_base_commit
            or pin.binding_canonical_digest != binding.canonical_digest
        ):
            raise WorkspacePublicationError(
                "session repository pin differs from the publication binding"
            )
        if (
            self.repositories.project_repository_bindings.lifecycle_status(
                binding.binding_id
            )
            is RepositoryBindingLifecycleStatus.RETIRED
        ):
            raise WorkspacePublicationError("publication binding is retired")
        return binding

    def _require_intent_binding(
        self,
        intent: WorkspacePublicationIntent,
    ) -> ProjectRepositoryBinding:
        binding = self._require_session_binding(
            session_id=intent.session_id,
            binding_id=intent.repository_binding_id,
        )
        if (
            binding.binding_version != intent.repository_binding_version
            or binding.repository_id != intent.repository_id
            or binding.repository_policy_version
            != intent.repository_policy_version
            or binding.repository_policy_digest
            != intent.repository_policy_digest
            or intent.publication_ref
            != (
                f"{binding.ref_namespace_policy.publication_prefix}/"
                f"{intent.publication_id}"
            )
        ):
            raise WorkspacePublicationError(
                "frozen publication intent differs from the pinned binding"
            )
        return binding

    def _require_publication_relationships(
        self,
        *,
        session_id: str,
        binding: ProjectRepositoryBinding,
        command: WorkspacePublishCommand,
    ) -> None:
        for publication_id, field_name in (
            (command.parent_publication_id, "parent publication"),
            (command.supersedes_publication_id, "superseded publication"),
        ):
            if publication_id is None:
                continue
            revision = self.repositories.published_revisions.get(publication_id)
            if (
                revision is None
                or revision.session_id != session_id
                or revision.repository_binding_id != binding.binding_id
                or revision.repository_binding_version != binding.binding_version
            ):
                raise WorkspacePublicationError(
                    f"{field_name} does not match the exact repository binding"
                )

    @staticmethod
    def _require_replay_matches(
        intent: WorkspacePublicationIntent,
        *,
        agent_id: str,
        command: WorkspacePublishCommand,
    ) -> None:
        if (
            intent.agent_id != agent_id
            or intent.workspace_id != command.workspace_id
            or intent.workspace_generation != command.workspace_generation
            or intent.expected_head_commit != command.expected_head_commit
            or intent.expected_tree != command.expected_tree
            or intent.declared_base_commit != command.declared_base_commit
            or intent.checkpoint_id != command.checkpoint_id
            or intent.repository_binding_version
            != command.repository_binding_version
            or intent.parent_publication_id != command.parent_publication_id
            or intent.supersedes_publication_id
            != command.supersedes_publication_id
            or not command.whole_repository
        ):
            raise WorkspacePublicationIdentityError(
                "publication idempotency replay changes frozen identity"
            )

    @staticmethod
    def _initial_execution(
        intent: WorkspacePublicationIntent,
        *,
        command: WorkspacePublishCommand,
        created_at: str,
    ) -> ControlledOperationExecution:
        return ControlledOperationExecution(
            execution_id=_stable_id("publication_execution", intent.intent_id),
            operation_id=f"workspace_publication:{intent.intent_id}",
            session_id=intent.session_id,
            task_id=command.task_id,
            lane_id=command.lane_id,
            approval_id=None,
            owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
            operation_digest=intent.canonical_digest,
            approval_digest=None,
            route_policy_id=PUBLICATION_ROUTE_POLICY_ID,
            selected_backend="internal_git_publication",
            adapter_policy_id=PUBLICATION_ADAPTER_POLICY_ID,
            input_identity_digest=intent.manifest.manifest_digest,
            expected_output_contract_digest=canonical_publication_digest(
                {
                    "publication_id": intent.publication_id,
                    "publication_ref": intent.publication_ref,
                    "commit": intent.expected_head_commit,
                    "tree": intent.expected_tree,
                }
            ),
            runtime_identity_digest=canonical_publication_digest(
                {"runtime_identity": PUBLICATION_RUNTIME_IDENTITY}
            ),
            lifecycle_state=ControlledOperationExecutionLifecycle.READY,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            dispatch_generation=0,
            state_version=1,
            fencing_token=0,
            created_at=created_at,
            updated_at=created_at,
        )

    @staticmethod
    def _event(
        execution: ControlledOperationExecution,
        *,
        phase: ControlledOperationExecutionPhase,
        previous: ControlledOperationExecutionLifecycle | None,
        summary: str,
        safe_receipt_digest: str | None = None,
    ) -> ControlledOperationExecutionEvent:
        return ControlledOperationExecutionEvent(
            event_id=_stable_id(
                "publication_execution_event",
                execution.execution_id,
                str(execution.state_version),
            ),
            execution_id=execution.execution_id,
            operation_id=execution.operation_id,
            session_id=execution.session_id,
            state_version=execution.state_version,
            dispatch_generation=execution.dispatch_generation,
            phase=phase,
            previous_lifecycle_state=previous,
            lifecycle_state=execution.lifecycle_state,
            terminal_outcome=execution.terminal_outcome,
            effect_certainty=execution.effect_certainty,
            retry_eligibility=execution.retry_eligibility,
            fencing_token=execution.fencing_token,
            safe_receipt_digest=safe_receipt_digest,
            safe_summary=summary,
            created_at=execution.updated_at,
        )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


__all__ = [
    "CurrentPublicationManifestPolicyValidator",
    "PublicationManifestPolicyValidator",
    "WorkspacePublicationError",
    "WorkspacePublicationGitReader",
    "WorkspacePublicationIdentityError",
    "WorkspacePublicationRemoteRoute",
    "WorkspacePublicationService",
    "WorkspacePublicationState",
    "WorkspacePublishCommand",
]
