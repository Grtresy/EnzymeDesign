from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import PrivateRefAdvanceKind
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublicationManifestEntry
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import PublishedRevision
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import RevisionCommitObservation
from openzyme_contracts import RevisionManifestObservation
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import VerifiedWorkspaceCheckpoint
from openzyme_contracts import WorkspaceFormalBoundary
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationIntentState
from openzyme_contracts import WorkspacePublicationManifest
from openzyme_contracts import WorkspacePublicationRemoteReceipt
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import AgentAuthorityLeaseSQLiteKernelEntityCodec
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import ControlledOperationSQLiteKernelEntityCodec
from openzyme_store_sqlite import KernelCommandReceiptSQLiteKernelEntityCodec
from openzyme_store_sqlite import ProjectRepositoryBindingSQLiteKernelEntityCodec
from openzyme_store_sqlite import PublishedRevisionSQLiteKernelEntityCodec
from openzyme_store_sqlite import RevisionPathVerificationSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionRepositoryBindingPinSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteControlStoreError
from openzyme_store_sqlite import SQLiteRevisionPathVerificationQuery
from openzyme_store_sqlite import TaskEvidenceSQLiteKernelEntityCodec
from openzyme_store_sqlite import VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec
from openzyme_store_sqlite import WorkspacePublicationIntentSQLiteKernelEntityCodec
from openzyme_store_sqlite import WorkspaceGenerationSQLiteKernelEntityCodec
from openzyme_store_sqlite import WorkspaceRuntimeBindingSQLiteKernelEntityCodec
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import AuthorityKernelApplicationService
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import PublicationCoordinationState
from openzyme_kernel import PublicationKernelApplicationService
from openzyme_kernel import WorkspacePublicationCoordinator
from openzyme_kernel import WorkspacePublicationRequest
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator


NOW = "2026-08-21T00:00:00+00:00"
COMMIT = "a" * 40
TREE = "b" * 40
BASE = "c" * 40
OBJECT = "d" * 40


def _digest(label: str) -> str:
    return canonical_sha256_digest({"label": label})


def _database() -> sqlite3.Connection:
    # Mapping tests deliberately leave foreign-key enforcement disabled. The
    # owner-schema suite separately proves the exact FK closure; this fixture
    # isolates each codec's closed payload, CAS ledger and mutation guard.
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection


def _request(command: str) -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command}",
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="agent-1",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key=f"idempotency-{command}",
        command_digest=_digest(command),
    )


def _commit(
    store: SQLiteControlStore,
    *,
    command: str,
    mutation: KernelStateMutation,
) -> None:
    unit = store.begin(_request(command))
    unit.stage(mutation)
    next_version = (
        1
        if mutation.expected_state_version is None
        else mutation.expected_state_version + 1
    )
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"{mutation.entity_type}.{command}",
        source_entity_type=mutation.entity_type,
        source_entity_id=mutation.entity_id,
        source_state_version=next_version,
        command_id=f"command-{command}",
        payload={"entity_id": mutation.entity_id},
    )
    unit.append_event(event)
    outbox_payload = {"event_id": event.event_id}
    unit.append_outbox(
        OutboxRecord(
            outbox_id=f"outbox-{command}",
            session_id="session-1",
            topic="openzyme.kernel.evidence-publication-qualification",
            occurrence_id=event.event_id,
            payload=outbox_payload,
            payload_digest=canonical_sha256_digest(outbox_payload),
            created_at=NOW,
        )
    )
    unit.commit()


def _store(connection: sqlite3.Connection) -> SQLiteControlStore:
    store = SQLiteControlStore(
        connection,
        codecs=(
            AgentAuthorityLeaseSQLiteKernelEntityCodec(),
            AgentMemberSQLiteKernelEntityCodec(),
            ControlledOperationSQLiteKernelEntityCodec(),
            KernelCommandReceiptSQLiteKernelEntityCodec(),
            ProjectRepositoryBindingSQLiteKernelEntityCodec(),
            PublishedRevisionSQLiteKernelEntityCodec(),
            RevisionPathVerificationSQLiteKernelEntityCodec(),
            SessionRepositoryBindingPinSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
            TaskEvidenceSQLiteKernelEntityCodec(),
            VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec(),
            WorkspaceGenerationSQLiteKernelEntityCodec(),
            WorkspacePublicationIntentSQLiteKernelEntityCodec(),
            WorkspaceRuntimeBindingSQLiteKernelEntityCodec(),
        ),
    )
    _commit(
        store,
        command="session-create",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-session-create",
            kind=KernelMutationKind.CREATE,
            entity_type="session",
            entity_id="session-1",
            expected_state_version=None,
            payload={
                "session_id": "session-1",
                "project_id": "project-1",
                "title": "Evidence and publication codec qualification",
                "objective": "prove immutable Kernel owner mappings",
                "status": "active",
                "created_at": NOW,
                "updated_at": NOW,
            },
        ),
    )
    _commit(
        store,
        command="member-create",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-member-create",
            kind=KernelMutationKind.CREATE,
            entity_type="agent_member",
            entity_id="member-1",
            expected_state_version=None,
            payload={
                "agent_member_id": "member-1",
                "agent_id": "agent-1",
                "session_id": "session-1",
                "parent_agent_id": None,
                "lane_id": None,
                "name": "Master",
                "role": "master",
                "status": "active",
                "process_epoch": 1,
                "active_authority_lease_id": None,
                "workspace_generation": 1,
                "owned_task_ids": [],
                "retirement_reason": None,
                "terminal_proof_digest": None,
                "retirement_settled": False,
                "retired_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ),
    )
    binding = ProjectRepositoryBinding.create(
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
        repository_policy_version="repository-policy-1",
        repository_policy_digest=_digest("repository-policy"),
        created_at=NOW,
        created_by="operator-1",
    )
    _commit(
        store,
        command="binding-create",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-binding-create",
            kind=KernelMutationKind.CREATE,
            entity_type="project_repository_binding",
            entity_id=binding.binding_id,
            expected_state_version=None,
            payload=binding.to_dict(),
        ),
    )
    pin = SessionRepositoryBindingPin(
        session_id="session-1",
        project_id="project-1",
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=binding.default_base_commit,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at=NOW,
    )
    _commit(
        store,
        command="binding-pin",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-binding-pin",
            kind=KernelMutationKind.CREATE,
            entity_type="session_repository_binding_pin",
            entity_id="session-1",
            expected_state_version=None,
            payload=pin.to_dict(),
        ),
    )
    generation = WorkspaceGeneration(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=1,
        state_version=1,
        status=WorkspaceGenerationStatus.READY,
        provider_id="openzyme.workspace.git.lfs",
        target_id="local:host",
        created_at=NOW,
        updated_at=NOW,
        root_identity_digest=_digest("workspace-root"),
        transition_receipt_digest=_digest("workspace-ready"),
        controlled_operation_id="workspace-operation-1",
    )
    _commit(
        store,
        command="workspace-ready",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-workspace-ready",
            kind=KernelMutationKind.CREATE,
            entity_type="workspace_generation",
            entity_id=generation.workspace_id,
            expected_state_version=None,
            payload=generation.to_dict(),
        ),
    )
    runtime = generation.runtime_binding()
    _commit(
        store,
        command="workspace-bind",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-workspace-bind",
            kind=KernelMutationKind.CREATE,
            entity_type="workspace_runtime_binding",
            entity_id=runtime.workspace_id,
            expected_state_version=None,
            payload=runtime.to_dict(),
        ),
    )
    grant = AuthorityGrant.create(
        grant_id="grant-1",
        scope_id="workspace-1",
        operations=(
            "workspace.checkpoint.verify",
            "workspace.publish",
            "workspace.revision.verify",
        ),
        generation=1,
        fence=1,
    )
    lease = AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="member-1",
        grants=(grant,),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=NOW,
        expires_at="2026-08-22T00:00:00+00:00",
        agent_id="agent-1",
        workspace_generation=1,
        parent_lease_id=None,
        policy_digest=_digest("authority-policy"),
        idempotency_key="lease-1",
        updated_at=NOW,
    )
    _commit(
        store,
        command="lease-create",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-lease-create",
            kind=KernelMutationKind.CREATE,
            entity_type="agent_authority_lease",
            entity_id=lease.lease_id,
            expected_state_version=None,
            payload=lease.to_dict(),
        ),
    )
    return store


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


def _checkpoint() -> VerifiedWorkspaceCheckpoint:
    return VerifiedWorkspaceCheckpoint.create(
        checkpoint_id="checkpoint-1",
        boundary=WorkspaceFormalBoundary.PUBLICATION,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_member_id="member-1",
        agent_id="agent-1",
        workspace_generation=1,
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        commit=COMMIT,
        tree=TREE,
        private_ref="refs/openzyme/private/session-1/agent-1",
        prior_commit=BASE,
        advance_kind=PrivateRefAdvanceKind.FAST_FORWARD,
        remote_observed_at=NOW,
        verified_at=NOW,
    )


def _intent() -> WorkspacePublicationIntent:
    return WorkspacePublicationIntent.create(
        intent_id="intent-1",
        publication_id="publication-1",
        idempotency_key="publish-1",
        project_id="project-1",
        session_id="session-1",
        agent_member_id="member-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        workspace_generation=1,
        capability_lease_id="lease-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        expected_head_commit=COMMIT,
        expected_tree=TREE,
        git_parent_commits=(BASE,),
        declared_base_commit=BASE,
        parent_publication_id=None,
        supersedes_publication_id=None,
        publication_ref="refs/openzyme/publications/publication-1",
        manifest=_manifest(),
        repository_policy_version="repository-policy-1",
        repository_policy_digest=_digest("repository-policy"),
        checkpoint_id="checkpoint-1",
        state=WorkspacePublicationIntentState.FROZEN,
        created_at=NOW,
    )


def _revision(intent: WorkspacePublicationIntent) -> PublishedRevision:
    return PublishedRevision.create(
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
        parent_publication_id=None,
        publisher_agent_member_id=intent.agent_member_id,
        publisher_agent_id=intent.agent_id,
        publisher_workspace_id=intent.workspace_id,
        publisher_workspace_generation=intent.workspace_generation,
        publication_ref=intent.publication_ref,
        manifest=intent.manifest,
        repository_policy_version=intent.repository_policy_version,
        repository_policy_digest=intent.repository_policy_digest,
        controlled_execution_id="operation-1",
        remote_receipt_id="remote-receipt-1",
        supersedes_publication_id=None,
        created_at=NOW,
    )


@dataclass(frozen=True)
class _ManifestValidation:
    manifest: WorkspacePublicationManifest


class _ManifestPolicy:
    def validate(self, **values):  # noqa: ANN003, ANN201
        return _ManifestValidation(values["manifest"])


class _RevisionBackend:
    def __init__(self) -> None:
        self.dispatch_calls = 0
        self.receipt: WorkspacePublicationRemoteReceipt | None = None

    def observe_commit(self, binding, *, commit):  # noqa: ANN001
        return RevisionCommitObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=TREE,
            parent_commits=(BASE,),
            observed_at=NOW,
        )

    def observe_manifest(self, binding, *, commit):  # noqa: ANN001
        return RevisionManifestObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=TREE,
            manifest=_manifest(),
            observed_at=NOW,
        )

    def dispatch_publication(self, binding, intent, dispatch):  # noqa: ANN001
        self.dispatch_calls += 1
        self.receipt = WorkspacePublicationRemoteReceipt.create(
            receipt_id=dispatch.receipt_id,
            intent_id=intent.intent_id,
            publication_id=intent.publication_id,
            execution_id=dispatch.execution_id,
            execution_dispatch_generation=dispatch.dispatch_generation,
            execution_fencing_token=dispatch.fencing_token,
            internal_git_service_id=binding.internal_git_service_id,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            publication_ref=intent.publication_ref,
            expected_previous_commit=None,
            new_commit=intent.expected_head_commit,
            new_tree=intent.expected_tree,
            server_observed_commit=intent.expected_head_commit,
            observed_at=NOW,
        )
        return self.receipt

    def reconcile_publication(self, binding, intent, dispatch):  # noqa: ANN001, ARG002
        return self.receipt

    def observe_publication(self, binding, intent, receipt):  # noqa: ANN001, ARG002
        return receipt


def test_task_evidence_codec_round_trips_wrapper_without_finishing_task() -> None:
    connection = _database()
    store = _store(connection)
    evidence = EvidenceRef(
        evidence_id="evidence-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id="science-closure-1",
        owner_component_id="openzyme.science",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        subject_ref="closure-1",
        subject_digest=_digest("closure"),
        attributes={},
    )
    payload = {
        "session_id": "session-1",
        "task_id": "task-1",
        "registered_by_actor_id": "agent-1",
        "evidence_digest": evidence.evidence_digest,
        "evidence_ref": evidence.to_dict(),
        "created_at": NOW,
        "task_transition_performed": False,
    }

    _commit(
        store,
        command="evidence-register",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-evidence",
            kind=KernelMutationKind.CREATE,
            entity_type="task_evidence",
            entity_id=evidence.evidence_id,
            expected_state_version=None,
            payload=payload,
        ),
    )

    assert store.read(
        entity_type="task_evidence", entity_id=evidence.evidence_id
    ) == KernelRecordSnapshot.create(
        entity_type="task_evidence",
        entity_id=evidence.evidence_id,
        state_version=1,
        payload=payload,
    )
    assert connection.execute(
        "SELECT task_transition_performed FROM task_evidence_records"
    ).fetchone()[0] == 0


def test_publication_application_materializes_through_target_sqlite_store() -> None:
    connection = _database()
    store = _store(connection)
    checkpoint = _checkpoint()
    _commit(
        store,
        command="application-checkpoint",
        mutation=KernelStateMutation.create(
            mutation_id="mutation-application-checkpoint",
            kind=KernelMutationKind.CREATE,
            entity_type="verified_workspace_checkpoint",
            entity_id=checkpoint.checkpoint_id,
            expected_state_version=None,
            payload=checkpoint.to_dict(),
        ),
    )
    clock = DeterministicClock(datetime(2026, 8, 21, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    backend = _RevisionBackend()
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
    coordinator = WorkspacePublicationCoordinator(
        reader=store,
        authority=AuthorityKernelApplicationService(reader=store, clock=clock),
        publications=publications,
        controlled_operations=controlled_operations,
        revision_backend=backend,
        manifest_policy=_ManifestPolicy(),
    )
    context = KernelCommandContext(
        command_id="command-application-publication",
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        extension_bundle_digest=_digest("extension-bundle"),
        capability_binding_digest=_digest("capability-binding"),
        idempotency_key="application-publication",
        correlation_id="correlation-application-publication",
        workspace_generation=1,
        route_id="git-publication-route-1",
    )

    intent, outcome = coordinator.prepare_and_publish(
        context=context,
        request=WorkspacePublicationRequest(
            idempotency_key="application-publication",
            workspace_id="workspace-1",
            workspace_generation=1,
            expected_head_commit=COMMIT,
            expected_tree=TREE,
            declared_base_commit=BASE,
            checkpoint_id="checkpoint-1",
            repository_binding_version=1,
        ),
        created_at=NOW,
    )

    assert outcome.state is PublicationCoordinationState.MATERIALIZED
    assert backend.dispatch_calls == 1
    assert store.read(
        entity_type="workspace_publication_intent",
        entity_id=intent.publication_id,
    ) is not None
    assert store.read(
        entity_type="published_revision",
        entity_id=intent.publication_id,
    ) is not None
    assert connection.execute(
        "SELECT COUNT(*) FROM command_receipt_records"
    ).fetchone()[0] >= 1
    publication_snapshot = store.read(
        entity_type="published_revision",
        entity_id=intent.publication_id,
    )
    assert publication_snapshot is not None
    read_identity = PublishedRevision.from_dict(publication_snapshot.payload)
    assert read_identity.commit == intent.expected_head_commit
    assert read_identity.tree == intent.expected_tree


def test_checkpoint_publication_and_path_receipt_codecs_form_immutable_chain() -> None:
    connection = _database()
    store = _store(connection)
    checkpoint = _checkpoint()
    intent = _intent()
    revision = _revision(intent)
    verification = RevisionPathVerificationReceipt.create(
        ref_id="path-ref-1",
        publication_id=revision.publication_id,
        repository_binding_id=revision.repository_binding_id,
        repository_binding_version=revision.repository_binding_version,
        commit=revision.commit,
        tree=revision.tree,
        path="results/model.hmm",
        object_id=OBJECT,
        actual_size_bytes=3,
        actual_content_digest=_digest("model-bytes"),
        lfs_oid=None,
        lfs_size_bytes=None,
        verified_at=NOW,
    )
    verification_payload = {
        **verification.identity_payload,
        "verification_digest": verification.verification_digest,
    }
    operation_payload = {
        "session_id": "session-1",
        "actor_id": "member-1",
        "owner_plugin_id": "openzyme.kernel",
        "operation_id": "operation-1",
        "intent_digest": intent.canonical_digest,
        "route_id": "git-publication-route-1",
        "authority_lease_id": "lease-1",
        "authority_generation": 1,
        "authority_fence": 1,
        "authority_operation": "workspace.publish",
        "scope_id": "workspace-1",
        "dispatch_generation": 1,
        "state": "settled",
        "effect_certainty": "terminal_known",
        "mutation_applied": True,
        "deadline": "2026-08-21T00:05:00+00:00",
        "approval_required": False,
        "approval_id": None,
        "cancel_intent_digest": None,
        "result_handle": "publication:publication-1",
        "terminal_receipt_digest": _digest("remote-receipt-1"),
        "last_observation_digest": _digest("publication-observation"),
        "error_code": None,
        "diagnostic_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "safe_intent": {"publication_id": "publication-1"},
        "fallback_performed": False,
    }
    records = (
        ("checkpoint", "verified_workspace_checkpoint", checkpoint.checkpoint_id, checkpoint.to_dict()),
        ("publication-intent", "workspace_publication_intent", intent.publication_id, intent.to_dict()),
        ("controlled-operation", "controlled_operation", "operation-1", operation_payload),
        ("published-revision", "published_revision", revision.publication_id, revision.to_dict()),
        ("path-verification", "revision_path_verification", verification.ref_id, verification_payload),
    )
    for command, entity_type, entity_id, payload in records:
        _commit(
            store,
            command=command,
            mutation=KernelStateMutation.create(
                mutation_id=f"mutation-{command}",
                kind=KernelMutationKind.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_state_version=None,
                payload=payload,
            ),
        )
        assert store.read(entity_type=entity_type, entity_id=entity_id) == (
            KernelRecordSnapshot.create(
                entity_type=entity_type,
                entity_id=entity_id,
                state_version=1,
                payload=payload,
            )
        )

    assert store.list_for_session(
        entity_type="revision_path_verification",
        session_id="session-1",
        max_items=16,
    ) == ()
    assert SQLiteRevisionPathVerificationQuery(connection).list_for_publication(
        revision.publication_id
    ) == (verification,)

    with pytest.raises(SQLiteControlStoreError) as error:
        _commit(
            store,
            command="published-revision-replace",
            mutation=KernelStateMutation.create(
                mutation_id="mutation-published-revision-replace",
                kind=KernelMutationKind.REPLACE,
                entity_type="published_revision",
                entity_id=revision.publication_id,
                expected_state_version=1,
                payload=revision.to_dict(),
            ),
        )
    assert error.value.code == "sqlite_published_revision_immutable"

    with pytest.raises(sqlite3.IntegrityError, match="publication intents are immutable"):
        connection.execute(
            "UPDATE workspace_publication_intents SET state = 'frozen' WHERE publication_id = ?",
            (intent.publication_id,),
        )
