from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import ProjectRepositoryBindingHeadSQLiteKernelEntityCodec
from openzyme_store_sqlite import ProjectRepositoryBindingSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionRepositoryBindingPinSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


NOW = "2026-08-21T00:00:00+00:00"
COMMIT_1 = "1" * 40
COMMIT_2 = "2" * 40


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection


def _request(command: str) -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command}",
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="operator-1",
        authority_lease_id="authority-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key=f"idempotency-{command}",
        command_digest=canonical_sha256_digest({"command": command}),
    )


def _commit(
    store: SQLiteControlStore,
    *,
    command: str,
    mutations: tuple[KernelStateMutation, ...],
) -> None:
    unit = store.begin(_request(command))
    for mutation in mutations:
        unit.stage(mutation)
    source = mutations[-1]
    version = 1 if source.expected_state_version is None else source.expected_state_version + 1
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"{source.entity_type}.{command}",
        source_entity_type=source.entity_type,
        source_entity_id=source.entity_id,
        source_state_version=version,
        command_id=f"command-{command}",
        payload={"entity_id": source.entity_id},
    )
    unit.append_event(event)
    outbox_payload = {"event_id": event.event_id}
    unit.append_outbox(
        OutboxRecord(
            outbox_id=f"outbox-{command}",
            session_id="session-1",
            topic="openzyme.kernel.repository-binding-qualification",
            occurrence_id=event.event_id,
            payload=outbox_payload,
            payload_digest=canonical_sha256_digest(outbox_payload),
            created_at=NOW,
        )
    )
    unit.commit()


def _binding(*, version: int, commit: str) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id=f"binding-{version}",
        project_id="project-1",
        binding_version=version,
        repository_id="repository-1",
        internal_git_service_id="git-internal-1",
        internal_git_endpoint="https://git.internal.example/repository-1",
        lfs_service_id="lfs-internal-1",
        lfs_endpoint="https://lfs.internal.example/repository-1",
        upstream_identity="upstream-1",
        upstream_url="https://git.example/repository-1",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit=commit,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="repository-policy@1",
        repository_policy_digest=canonical_sha256_digest(
            {"policy": "repository", "version": version}
        ),
        created_at=NOW,
        created_by="operator-1",
    )


def _head(binding: ProjectRepositoryBinding) -> dict[str, object]:
    return {
        "project_id": binding.project_id,
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "binding_canonical_digest": binding.canonical_digest,
        "updated_at": NOW,
    }


def test_repository_binding_codecs_round_trip_binding_head_and_session_pin() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(
            ProjectRepositoryBindingHeadSQLiteKernelEntityCodec(),
            ProjectRepositoryBindingSQLiteKernelEntityCodec(),
            SessionRepositoryBindingPinSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
        ),
    )
    session_payload = {
        "session_id": "session-1",
        "project_id": "project-1",
        "title": "Repository binding qualification",
        "objective": "prove repository binding owner codecs",
        "status": "active",
        "created_at": NOW,
        "updated_at": NOW,
    }
    _commit(
        store,
        command="session-create",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-session-create",
                kind=KernelMutationKind.CREATE,
                entity_type="session",
                entity_id="session-1",
                expected_state_version=None,
                payload=session_payload,
            ),
        ),
    )

    binding_1 = _binding(version=1, commit=COMMIT_1)
    head_1 = _head(binding_1)
    _commit(
        store,
        command="binding-1-register",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-binding-1",
                kind=KernelMutationKind.CREATE,
                entity_type="project_repository_binding",
                entity_id=binding_1.binding_id,
                expected_state_version=None,
                payload=binding_1.to_dict(),
            ),
            KernelStateMutation.create(
                mutation_id="mutation-binding-head-1",
                kind=KernelMutationKind.CREATE,
                entity_type="project_repository_binding_head",
                entity_id="project-1",
                expected_state_version=None,
                payload=head_1,
            ),
        ),
    )
    assert store.read(
        entity_type="project_repository_binding", entity_id=binding_1.binding_id
    ) == KernelRecordSnapshot.create(
        entity_type="project_repository_binding",
        entity_id=binding_1.binding_id,
        state_version=1,
        payload=binding_1.to_dict(),
    )
    assert store.read(
        entity_type="project_repository_binding_head", entity_id="project-1"
    ) == KernelRecordSnapshot.create(
        entity_type="project_repository_binding_head",
        entity_id="project-1",
        state_version=1,
        payload=head_1,
    )

    pin = SessionRepositoryBindingPin(
        session_id="session-1",
        project_id="project-1",
        binding_id=binding_1.binding_id,
        binding_version=binding_1.binding_version,
        repository_id=binding_1.repository_id,
        resolved_base_commit=binding_1.default_base_commit,
        binding_canonical_digest=binding_1.canonical_digest,
        pinned_at=NOW,
    )
    _commit(
        store,
        command="session-pin",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-session-pin",
                kind=KernelMutationKind.CREATE,
                entity_type="session_repository_binding_pin",
                entity_id="session-1",
                expected_state_version=None,
                payload=pin.to_dict(),
            ),
        ),
    )
    assert store.read(
        entity_type="session_repository_binding_pin", entity_id="session-1"
    ) == KernelRecordSnapshot.create(
        entity_type="session_repository_binding_pin",
        entity_id="session-1",
        state_version=1,
        payload=pin.to_dict(),
    )

    binding_2 = _binding(version=2, commit=COMMIT_2)
    head_2 = _head(binding_2)
    _commit(
        store,
        command="binding-2-register",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-binding-2",
                kind=KernelMutationKind.CREATE,
                entity_type="project_repository_binding",
                entity_id=binding_2.binding_id,
                expected_state_version=None,
                payload=binding_2.to_dict(),
            ),
            KernelStateMutation.create(
                mutation_id="mutation-binding-head-2",
                kind=KernelMutationKind.REPLACE,
                entity_type="project_repository_binding_head",
                entity_id="project-1",
                expected_state_version=1,
                payload=head_2,
            ),
        ),
    )
    assert store.read(
        entity_type="project_repository_binding_head", entity_id="project-1"
    ) == KernelRecordSnapshot.create(
        entity_type="project_repository_binding_head",
        entity_id="project-1",
        state_version=2,
        payload=head_2,
    )
    assert connection.execute(
        "SELECT binding_id, binding_version FROM project_repository_binding_heads"
    ).fetchone() == ("binding-2", 2)
    assert connection.execute(
        "SELECT COUNT(*) FROM project_repository_active_bindings"
    ).fetchone() == (0,)

    with pytest.raises(sqlite3.IntegrityError, match="mutation write authority rejected"):
        connection.execute(
            "UPDATE project_repository_binding_heads SET updated_at = ? WHERE project_id = ?",
            ("2026-08-21T00:01:00+00:00", "project-1"),
        )
