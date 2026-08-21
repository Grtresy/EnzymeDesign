from __future__ import annotations

from datetime import UTC
from datetime import datetime
from dataclasses import dataclass

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import PrivateRefAdvanceKind
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublicationManifestEntry
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import RemotePrivateRefObservation
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import RevisionCommitObservation
from openzyme_contracts import RevisionManifestObservation
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import WorkspaceCheckpointProofInput
from openzyme_contracts import WorkspaceFormalBoundary
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationIntentState
from openzyme_contracts import WorkspacePublicationManifest
from openzyme_contracts import WorkspacePublicationRemoteReceipt
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import PublicationApplicationCommand
from openzyme_extension_spi import PublicationCommandKind
from openzyme_kernel import KernelContractError
from openzyme_kernel import AuthorityKernelApplicationService
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import PublicationCoordinationState
from openzyme_kernel import PublicationCoordinationError
from openzyme_kernel import PublicationKernelApplicationService
from openzyme_kernel import WorkspacePublicationCoordinator
from openzyme_kernel import WorkspacePublicationRequest
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


COMMIT = "a" * 40
TREE = "b" * 40
OBJECT = "c" * 40
BASE = "d" * 40
PARENT = "e" * 40


def _digest(label: str) -> str:
    return canonical_sha256_digest({"label": label})


def _binding() -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="binding-1",
        project_id="project-1",
        binding_version=1,
        repository_id="repository-1",
        internal_git_service_id="git-service-1",
        internal_git_endpoint="https://git.internal.example/repository-1",
        lfs_service_id="lfs-service-1",
        lfs_endpoint="https://lfs.internal.example/repository-1",
        upstream_identity="upstream-1",
        upstream_url="https://example.org/project/repository.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit=BASE,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="policy-1",
        repository_policy_digest=_digest("policy"),
        created_at="2026-08-20T09:00:00+00:00",
        created_by="operator-1",
    )


def _workspace() -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="agent-1",
        generation=2,
        state_version=1,
        root_identity_digest=_digest("root"),
        provider_id="fake.git-workspace",
        target_id="local:host",
    )


def _pin(binding: ProjectRepositoryBinding) -> SessionRepositoryBindingPin:
    return SessionRepositoryBindingPin(
        session_id="session-1",
        project_id="project-1",
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=BASE,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at="2026-08-20T09:00:00+00:00",
    )


def _remote_observation() -> RemotePrivateRefObservation:
    return RemotePrivateRefObservation(
        service_id="git-service-1",
        repository_id="repository-1",
        private_ref="refs/openzyme/private/session-1/agent-1",
        prior_commit=BASE,
        observed_commit=COMMIT,
        advance_kind=PrivateRefAdvanceKind.FAST_FORWARD,
        observed_at="2026-08-20T09:59:00+00:00",
    )


def _proof() -> WorkspaceCheckpointProofInput:
    return WorkspaceCheckpointProofInput(
        boundary=WorkspaceFormalBoundary.PUBLICATION,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_member_id="agent-1",
        agent_id="agent-identity-1",
        workspace_generation=2,
        repository_binding_id="binding-1",
        repository_binding_version=1,
        commit=COMMIT,
        tree=TREE,
        private_ref="refs/openzyme/private/session-1/agent-1",
        remote_observation=_remote_observation(),
    )


def _manifest() -> WorkspacePublicationManifest:
    return WorkspacePublicationManifest.create(
        (
            PublicationManifestEntry(
                path="results/model.hmm",
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id=OBJECT,
                size_bytes=3,
            ),
        )
    )


def _intent() -> WorkspacePublicationIntent:
    return WorkspacePublicationIntent.create(
        intent_id="intent-1",
        publication_id="publication-1",
        idempotency_key="publish-intent-1",
        project_id="project-1",
        session_id="session-1",
        agent_member_id="agent-1",
        agent_id="agent-identity-1",
        workspace_id="workspace-1",
        workspace_generation=2,
        capability_lease_id="lease-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        expected_head_commit=COMMIT,
        expected_tree=TREE,
        git_parent_commits=(PARENT,),
        declared_base_commit=BASE,
        parent_publication_id=None,
        supersedes_publication_id=None,
        publication_ref="refs/openzyme/publications/publication-1",
        manifest=_manifest(),
        repository_policy_version="policy-1",
        repository_policy_digest=_digest("policy"),
        checkpoint_id="checkpoint-1",
        state=WorkspacePublicationIntentState.FROZEN,
        created_at="2026-08-20T10:00:00+00:00",
    )


class _RevisionBackend:
    def __init__(self, intent: WorkspacePublicationIntent) -> None:
        self.private_observation = _remote_observation()
        self.publication_receipt = WorkspacePublicationRemoteReceipt.create(
            receipt_id="remote-receipt-1",
            intent_id=intent.intent_id,
            publication_id=intent.publication_id,
            execution_id="operation-1",
            execution_dispatch_generation=1,
            execution_fencing_token=8,
            internal_git_service_id="git-service-1",
            repository_binding_id=intent.repository_binding_id,
            repository_binding_version=intent.repository_binding_version,
            repository_id=intent.repository_id,
            publication_ref=intent.publication_ref,
            expected_previous_commit=None,
            new_commit=intent.expected_head_commit,
            new_tree=intent.expected_tree,
            server_observed_commit=intent.expected_head_commit,
            observed_at="2026-08-20T10:00:01+00:00",
        )
        self.dispatch_calls = 0
        self.observe_calls = 0
        self.source_observe_calls = 0

    def observe_private_ref(self, binding, proof):  # noqa: ANN001
        return self.private_observation

    def observe_commit(self, binding, *, commit):  # noqa: ANN001
        self.source_observe_calls += 1
        return RevisionCommitObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=TREE,
            parent_commits=(PARENT,),
            observed_at="2026-08-20T10:00:00+00:00",
        )

    def observe_manifest(self, binding, *, commit):  # noqa: ANN001
        self.source_observe_calls += 1
        return RevisionManifestObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=TREE,
            manifest=_manifest(),
            observed_at="2026-08-20T10:00:00+00:00",
        )

    def dispatch_publication(self, binding, intent, dispatch):  # noqa: ANN001
        self.dispatch_calls += 1
        raise AssertionError("Kernel publication owner must never dispatch Git")

    def observe_publication(self, binding, intent, receipt):  # noqa: ANN001
        self.observe_calls += 1
        assert receipt == self.publication_receipt
        return self.publication_receipt

    def verify_revision_path(self, binding, revision, ref):  # noqa: ANN001
        return RevisionPathVerificationReceipt.create(
            ref_id=ref.ref_id,
            publication_id=ref.publication_id,
            repository_binding_id=ref.repository_binding_id,
            repository_binding_version=ref.repository_binding_version,
            commit=ref.commit,
            tree=ref.tree,
            path=ref.path,
            object_id=ref.object_id,
            actual_size_bytes=ref.size_bytes,
            actual_content_digest=_digest("content"),
            lfs_oid=ref.lfs_oid,
            lfs_size_bytes=ref.lfs_size_bytes,
            verified_at="2026-08-20T10:00:02+00:00",
        )


class _CoordinatingRevisionBackend(_RevisionBackend):
    def __init__(
        self,
        intent: WorkspacePublicationIntent,
        *,
        lose_dispatch_response: bool = False,
        reconciliation_visible: bool = True,
    ) -> None:
        super().__init__(intent)
        self._lose_dispatch_response = lose_dispatch_response
        self._reconciliation_visible = reconciliation_visible
        self._accepted = False
        self.reconcile_calls = 0

    def dispatch_publication(self, binding, intent, dispatch):  # noqa: ANN001
        self.dispatch_calls += 1
        assert binding.binding_id == intent.repository_binding_id
        self.publication_receipt = WorkspacePublicationRemoteReceipt.create(
            receipt_id=dispatch.receipt_id,
            intent_id=intent.intent_id,
            publication_id=intent.publication_id,
            execution_id=dispatch.execution_id,
            execution_dispatch_generation=dispatch.dispatch_generation,
            execution_fencing_token=dispatch.fencing_token,
            internal_git_service_id=binding.internal_git_service_id,
            repository_binding_id=intent.repository_binding_id,
            repository_binding_version=intent.repository_binding_version,
            repository_id=intent.repository_id,
            publication_ref=intent.publication_ref,
            expected_previous_commit=None,
            new_commit=intent.expected_head_commit,
            new_tree=intent.expected_tree,
            server_observed_commit=intent.expected_head_commit,
            observed_at="2026-08-20T10:00:01+00:00",
        )
        self._accepted = True
        if self._lose_dispatch_response:
            raise TimeoutError("publication response lost after create-only dispatch")
        return self.publication_receipt

    def reconcile_publication(self, binding, intent, dispatch):  # noqa: ANN001
        self.reconcile_calls += 1
        assert binding.binding_id == intent.repository_binding_id
        assert dispatch.execution_id == self.publication_receipt.execution_id
        if not self._accepted or not self._reconciliation_visible:
            return None
        return self.publication_receipt


@dataclass(frozen=True)
class _ManifestValidation:
    manifest: WorkspacePublicationManifest


class _ManifestPolicy:
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, **values):  # noqa: ANN003, ANN201
        self.calls += 1
        return _ManifestValidation(values["manifest"])


class _FailingManifestPolicy:
    def validate(self, **values):  # noqa: ANN003, ANN201, ARG002
        raise OSError("adapter policy backend unavailable")

def _store(binding: ProjectRepositoryBinding) -> InMemoryControlStore:
    workspace = _workspace()
    pin = _pin(binding)
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=4,
                payload={"project_id": "project-1", "status": "active"},
            ),
            KernelRecordSnapshot.create(
                entity_type="workspace_runtime_binding",
                entity_id=workspace.workspace_id,
                state_version=1,
                payload=workspace.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="session_repository_binding_pin",
                entity_id="session-1",
                state_version=1,
                payload=pin.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="project_repository_binding",
                entity_id=binding.binding_id,
                state_version=1,
                payload=binding.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id="lease-1",
                state_version=1,
                payload={
                    "session_id": "session-1",
                    "agent_member_id": "agent-1",
                    "state": "active",
                    "generation": 3,
                    "fence": 8,
                    "expires_at": "2026-08-20T11:00:00+00:00",
                    "grants": [
                        {
                            "scope_id": "workspace-1",
                            "operations": [
                                "workspace.checkpoint.verify",
                                "workspace.publish",
                                "workspace.revision.verify",
                            ],
                        }
                    ],
                },
            ),
        )
    )


def _context(phase: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-{phase}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=4,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("capability-binding"),
        idempotency_key=f"idempotency-{phase}",
        correlation_id="correlation-1",
        workspace_generation=2,
        route_id="git-route-1",
    )


def _publication_request(
    *,
    idempotency_key: str = "publish-request-1",
    expected_tree: str = TREE,
) -> WorkspacePublicationRequest:
    return WorkspacePublicationRequest(
        idempotency_key=idempotency_key,
        workspace_id="workspace-1",
        workspace_generation=2,
        expected_head_commit=COMMIT,
        expected_tree=expected_tree,
        declared_base_commit=BASE,
        checkpoint_id="checkpoint-1",
        repository_binding_version=1,
    )


def _command(
    operation: PublicationCommandKind,
    phase: str,
    *,
    resource_id: str,
    payload: dict,
) -> PublicationApplicationCommand:
    return PublicationApplicationCommand(
        context=_context(phase),
        operation=operation,
        resource_id=resource_id,
        workspace_id="workspace-1",
        expected_workspace_generation=2,
        payload=payload,
    )


def _service(store, backend):  # noqa: ANN001
    return PublicationKernelApplicationService(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 20, 10, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
        revision_backend=backend,
    )


def _coordination_stack(
    *,
    lose_dispatch_response: bool = False,
    reconciliation_visible: bool = True,
):
    binding = _binding()
    intent = _intent()
    store = _store(binding)
    clock = DeterministicClock(datetime(2026, 8, 20, 10, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    backend = _CoordinatingRevisionBackend(
        intent,
        lose_dispatch_response=lose_dispatch_response,
        reconciliation_visible=reconciliation_visible,
    )
    publications = PublicationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
        revision_backend=backend,
    )
    controlled_operations = ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    manifest_policy = _ManifestPolicy()
    coordinator = WorkspacePublicationCoordinator(
        reader=store,
        authority=AuthorityKernelApplicationService(reader=store, clock=clock),
        publications=publications,
        controlled_operations=controlled_operations,
        revision_backend=backend,
        manifest_policy=manifest_policy,
    )
    publications.execute(
        _command(
            PublicationCommandKind.VERIFY_CHECKPOINT,
            "coordination-checkpoint",
            resource_id="checkpoint-1",
            payload={"proof": _proof().to_dict()},
        )
    )
    return coordinator, store, backend, intent, manifest_policy


def _replace_authority_state(store: InMemoryControlStore, state: str) -> None:
    lease = store.read(entity_type="agent_authority_lease", entity_id="lease-1")
    assert lease is not None
    replacement = KernelRecordSnapshot.create(
        entity_type=lease.entity_type,
        entity_id=lease.entity_id,
        state_version=lease.state_version + 1,
        payload={**lease.payload, "state": state},
    )
    store._records[(lease.entity_type, lease.entity_id)] = replacement  # noqa: SLF001


def test_checkpoint_publication_and_path_verification_are_immutable_kernel_facts() -> None:
    binding = _binding()
    intent = _intent()
    backend = _RevisionBackend(intent)
    store = _store(binding)
    service = _service(store, backend)

    checkpoint = service.execute(
        _command(
            PublicationCommandKind.VERIFY_CHECKPOINT,
            "checkpoint",
            resource_id="checkpoint-1",
            payload={"proof": _proof().to_dict()},
        )
    )
    admitted = service.execute(
        _command(
            PublicationCommandKind.PUBLISH,
            "admit",
            resource_id="publication-1",
            payload={"phase": "admit", "intent": intent.to_dict()},
        )
    )
    store.seed(
        KernelRecordSnapshot.create(
            entity_type="controlled_operation",
            entity_id="operation-1",
            state_version=2,
            payload={
                "session_id": "session-1",
                "actor_id": "agent-1",
                "authority_lease_id": "lease-1",
                "authority_generation": 3,
                "authority_fence": 8,
                "dispatch_generation": 1,
                "state": "settled",
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "intent_digest": intent.canonical_digest,
                "scope_id": "workspace-1",
                "result_handle": "publication:publication-1",
                "terminal_receipt_digest": backend.publication_receipt.receipt_digest,
            },
        )
    )
    materialized = service.execute(
        _command(
            PublicationCommandKind.PUBLISH,
            "materialize",
            resource_id="publication-1",
            payload={
                "phase": "materialize",
                "controlled_operation_id": "operation-1",
                "remote_receipt": backend.publication_receipt.to_dict(),
            },
        )
    )
    ref = RevisionPathRef.create(
        ref_id="path-ref-1",
        publication_id="publication-1",
        project_id="project-1",
        session_id="session-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        commit=COMMIT,
        tree=TREE,
        path="results/model.hmm",
        entry_kind=RevisionPathEntryKind.FILE,
        object_id=OBJECT,
        size_bytes=3,
        lfs_oid=None,
        lfs_size_bytes=None,
        path_manifest_digest=None,
        created_at="2026-08-20T10:00:02+00:00",
    )
    verified = service.execute(
        _command(
            PublicationCommandKind.VERIFY_REVISION_PATH,
            "verify-path",
            resource_id=ref.ref_id,
            payload={"ref": ref.to_dict()},
        )
    )

    assert checkpoint.result["checkpoint_id"] == "checkpoint-1"
    assert admitted.result["dispatch_performed"] is False
    assert materialized.result["publication_id"] == "publication-1"
    assert verified.result["ref_id"] == "path-ref-1"
    assert backend.dispatch_calls == 0
    assert backend.observe_calls == 1
    assert store.read(
        entity_type="published_revision", entity_id="publication-1"
    ) is not None


def test_materialization_rejects_missing_terminal_operation_without_observing_git() -> None:
    binding = _binding()
    intent = _intent()
    backend = _RevisionBackend(intent)
    store = _store(binding)
    service = _service(store, backend)
    service.execute(
        _command(
            PublicationCommandKind.VERIFY_CHECKPOINT,
            "checkpoint",
            resource_id="checkpoint-1",
            payload={"proof": _proof().to_dict()},
        )
    )
    service.execute(
        _command(
            PublicationCommandKind.PUBLISH,
            "admit",
            resource_id="publication-1",
            payload={"phase": "admit", "intent": intent.to_dict()},
        )
    )

    with pytest.raises(KernelContractError) as exc_info:
        service.execute(
            _command(
                PublicationCommandKind.PUBLISH,
                "materialize",
                resource_id="publication-1",
                payload={
                    "phase": "materialize",
                    "controlled_operation_id": "operation-1",
                    "remote_receipt": backend.publication_receipt.to_dict(),
                },
            )
        )
    assert exc_info.value.code == "publication_controlled_operation_unsettled"
    assert backend.observe_calls == 0


def test_checkpoint_rejects_stale_workspace_generation_before_adapter_call() -> None:
    with pytest.raises(ValueError, match="workspace generation differs"):
        PublicationApplicationCommand(
            context=_context("stale"),
            operation=PublicationCommandKind.VERIFY_CHECKPOINT,
            resource_id="checkpoint-1",
            workspace_id="workspace-1",
            expected_workspace_generation=3,
            payload={"proof": _proof().to_dict()},
        )


def test_publication_coordinator_dispatches_once_and_replays_materialized_truth() -> None:
    coordinator, store, backend, intent, _ = _coordination_stack()

    first = coordinator.publish(
        context=_context("coordinated-publish"),
        intent=intent,
        operation_id="operation-1",
    )
    replay = coordinator.publish(
        context=_context("coordinated-publish"),
        intent=intent,
        operation_id="operation-1",
    )

    assert first.state is PublicationCoordinationState.MATERIALIZED
    assert first.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert replay.state is PublicationCoordinationState.MATERIALIZED
    assert backend.dispatch_calls == 1
    assert backend.reconcile_calls == 0
    assert backend.observe_calls == 1
    operation = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert operation is not None
    assert operation.payload["state"] == "settled"
    assert operation.payload["dispatch_generation"] == 1
    assert store.read(
        entity_type="published_revision", entity_id="publication-1"
    ) is not None


def test_publication_coordinator_prepares_exact_intent_and_replays_without_reobserving() -> None:
    coordinator, store, backend, _, policy = _coordination_stack()
    context = _context("prepared-publication")

    intent, first = coordinator.prepare_and_publish(
        context=context,
        request=_publication_request(),
        created_at="2026-08-20T10:00:00+00:00",
    )
    replay_intent, replay = coordinator.prepare_and_publish(
        context=context,
        request=_publication_request(),
        created_at="2026-08-20T10:00:01+00:00",
    )

    assert first.state is PublicationCoordinationState.MATERIALIZED
    assert replay.state is PublicationCoordinationState.MATERIALIZED
    assert replay_intent == intent
    assert intent.publication_ref.endswith("/" + intent.publication_id)
    assert intent.git_parent_commits == (PARENT,)
    assert backend.source_observe_calls == 2
    assert backend.dispatch_calls == 1
    assert policy.calls == 1
    assert store.read(
        entity_type="workspace_publication_intent",
        entity_id=intent.publication_id,
    ) is not None


def test_publication_preparation_rejects_idempotency_drift_without_adapter_call() -> None:
    coordinator, _, backend, _, _ = _coordination_stack()
    context = _context("preparation-drift")
    coordinator.prepare_and_publish(
        context=context,
        request=_publication_request(),
        created_at="2026-08-20T10:00:00+00:00",
    )
    observed_calls = backend.source_observe_calls

    with pytest.raises(KernelContractError) as rejected:
        coordinator.prepare_intent(
            context=context,
            request=_publication_request(expected_tree="f" * 40),
            created_at="2026-08-20T10:00:02+00:00",
        )

    assert rejected.value.code == "publication_idempotency_conflict"
    assert backend.source_observe_calls == observed_calls


def test_publication_preparation_rejects_revoked_authority_before_source_observation() -> None:
    coordinator, store, backend, _, policy = _coordination_stack()
    _replace_authority_state(store, "revoked")

    with pytest.raises(KernelContractError) as rejected:
        coordinator.prepare_intent(
            context=_context("preparation-revoked"),
            request=_publication_request(),
            created_at="2026-08-20T10:00:00+00:00",
        )

    assert rejected.value.code == "authority_lease_inactive"
    assert backend.source_observe_calls == 0
    assert backend.dispatch_calls == 0
    assert policy.calls == 0


def test_publication_request_rejects_noncanonical_uppercase_git_object_id() -> None:
    with pytest.raises(ValueError, match="lowercase exact Git object id"):
        _publication_request(expected_tree="F" * 40)


def test_publication_manifest_policy_failure_is_no_effect_and_preserves_cause() -> None:
    coordinator, _, backend, _, _ = _coordination_stack()
    coordinator._manifest_policy = _FailingManifestPolicy()  # noqa: SLF001

    with pytest.raises(PublicationCoordinationError) as rejected:
        coordinator.prepare_intent(
            context=_context("policy-failure"),
            request=_publication_request(),
            created_at="2026-08-20T10:00:00+00:00",
        )

    assert rejected.value.code == "publication_manifest_policy_failed"
    assert rejected.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert rejected.value.mutation_applied is False
    assert isinstance(rejected.value.__cause__, OSError)
    assert backend.dispatch_calls == 0


def test_publication_response_loss_reconciles_without_redispatch() -> None:
    coordinator, store, backend, intent, _ = _coordination_stack(
        lose_dispatch_response=True
    )

    uncertain = coordinator.publish(
        context=_context("response-loss"),
        intent=intent,
        operation_id="operation-1",
    )
    settled = coordinator.reconcile(
        context=_context("response-loss"),
        intent=intent,
        operation_id="operation-1",
    )

    assert uncertain.state is PublicationCoordinationState.RECONCILE_REQUIRED
    assert uncertain.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert uncertain.mutation_applied is None
    assert settled.state is PublicationCoordinationState.MATERIALIZED
    assert backend.dispatch_calls == 1
    assert backend.reconcile_calls == 1
    assert backend.observe_calls == 1
    assert store.read(
        entity_type="published_revision", entity_id="publication-1"
    ) is not None


def test_pending_publication_reconciliation_never_redispatches() -> None:
    coordinator, store, backend, intent, _ = _coordination_stack(
        lose_dispatch_response=True,
        reconciliation_visible=False,
    )
    coordinator.publish(
        context=_context("pending-reconciliation"),
        intent=intent,
        operation_id="operation-1",
    )

    first = coordinator.reconcile(
        context=_context("pending-reconciliation"),
        intent=intent,
        operation_id="operation-1",
    )
    second = coordinator.reconcile(
        context=_context("pending-reconciliation"),
        intent=intent,
        operation_id="operation-1",
    )

    assert first.state is PublicationCoordinationState.RECONCILE_REQUIRED
    assert second.state is PublicationCoordinationState.RECONCILE_REQUIRED
    assert first.error_code == second.error_code == "publication_observation_pending"
    assert backend.dispatch_calls == 1
    assert backend.reconcile_calls == 2
    assert backend.observe_calls == 0
    operation = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert operation is not None
    assert operation.payload["state"] == "reconcile_required"
    assert operation.payload["dispatch_generation"] == 1
    assert store.read(
        entity_type="published_revision", entity_id="publication-1"
    ) is None


def test_publication_rejects_revoked_authority_before_adapter_dispatch() -> None:
    coordinator, store, backend, intent, _ = _coordination_stack()
    _replace_authority_state(store, "revoked")

    with pytest.raises(KernelContractError) as rejected:
        coordinator.publish(
            context=_context("revoked-before-dispatch"),
            intent=intent,
            operation_id="operation-1",
        )

    assert rejected.value.code == "authority_lease_inactive"
    assert backend.dispatch_calls == 0
    assert store.read(
        entity_type="workspace_publication_intent", entity_id="publication-1"
    ) is None
    assert store.read(
        entity_type="controlled_operation", entity_id="operation-1"
    ) is None


def test_publication_reconciles_original_uncertain_effect_after_revoke() -> None:
    coordinator, store, backend, intent, _ = _coordination_stack(
        lose_dispatch_response=True
    )
    uncertain = coordinator.publish(
        context=_context("reconcile-after-revoke"),
        intent=intent,
        operation_id="operation-1",
    )
    assert uncertain.state is PublicationCoordinationState.RECONCILE_REQUIRED
    _replace_authority_state(store, "revoked")

    settled = coordinator.reconcile(
        context=_context("reconcile-after-revoke"),
        intent=intent,
        operation_id="operation-1",
    )

    assert settled.state is PublicationCoordinationState.MATERIALIZED
    assert backend.dispatch_calls == 1
    assert backend.reconcile_calls == 1
    assert store.read(
        entity_type="published_revision", entity_id="publication-1"
    ) is not None
