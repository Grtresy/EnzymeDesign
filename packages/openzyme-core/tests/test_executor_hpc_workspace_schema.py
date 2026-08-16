from __future__ import annotations

import sqlite3

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import ExecutorHpcNativeQualificationEvidence
from openzyme_core import ExecutorHpcTargetQualificationError
from openzyme_core import ExecutorHpcTargetQualificationService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import ExecutorHpcTargetQualification


DIGEST = "sha256:" + "a" * 64
NOW = "2026-08-17T01:00:00+00:00"


def _connection() -> sqlite3.Connection:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return connection


def _qualification() -> ExecutorHpcTargetQualification:
    return ExecutorHpcTargetQualification(
        target_profile_id="target_1",
        target_profile_digest=DIGEST,
        root_policy_digest=DIGEST,
        os_principal_policy_id="principal-policy-v1",
        credential_provider_id="provider_1",
        authenticator_id="authenticator_1",
        login_alias="target-login",
        workspace_root="/srv/openzyme/workspaces",
        sidecar_root_digest=DIGEST,
        toolchain_digest=DIGEST,
        native_positive_proof_digest=DIGEST,
        native_negative_proof_digest=DIGEST,
        activated=True,
        qualified_at=NOW,
    )


def _evidence() -> ExecutorHpcNativeQualificationEvidence:
    return ExecutorHpcNativeQualificationEvidence.create(
        target_profile_id="target_1",
        target_profile_digest=DIGEST,
        credential_provider_id="provider_1",
        authenticator_id="authenticator_1",
        os_principal_policy_id="principal-policy-v1",
        root_policy_digest=DIGEST,
        login_alias="target-login",
        workspace_root="/srv/openzyme/workspaces",
        sidecar_root_digest=DIGEST,
        toolchain_digest=DIGEST,
        positive_receipt_digest=DIGEST,
        negative_receipt_digest=DIGEST,
        positive_scenarios=(
            "ssh_login",
            "git",
            "git_lfs",
            "rsync",
            "scp",
            "file_create",
            "file_read",
            "file_update",
            "file_delete",
            "private_ref_push_fetch",
            "published_ref_fetch",
            "git_lfs_actual_bytes",
        ),
        negative_scenarios=(
            "cross_executor",
            "cross_generation",
            "cross_target_replay",
            "parent_traversal",
            "absolute_path_substitution",
            "symlink_escape",
            "hardlink_escape",
            "rsync_destination_escape",
            "scp_destination_escape",
            "runner_sidecar_access",
            "revoked_credential",
            "scheduler_submit_absent",
            "private_ref_cross_owner_denied",
            "published_ref_force_update_denied",
            "published_ref_delete_denied",
        ),
        execution_mode="native_target_ssh",
        mocked=False,
        verified_at=NOW,
    )


def test_migration_installs_closed_workspace_and_cleanup_state_machine() -> None:
    connection = _connection()
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(executor_hpc_workspace_records)"
        ).fetchall()
    }
    triggers = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }

    assert {
        "os_principal_identity_digest",
        "isolation_receipt_digest",
        "remote_workspace_generation",
        "state_version",
    } <= columns
    assert {
        "executor_hpc_workspace_identity_immutable",
        "executor_hpc_workspace_transition_guard",
        "executor_hpc_workspace_retire_on_lease_inactive",
        "executor_hpc_cleanup_intent_scope_matches",
        "executor_hpc_cleanup_receipt_matches",
    } <= triggers


def test_target_activation_rejects_unverified_native_evidence() -> None:
    repositories = CoreRepositories.from_connection(_connection())
    service = ExecutorHpcTargetQualificationService(repositories)

    with pytest.raises(
        ExecutorHpcTargetQualificationError,
        match="verifier is unavailable",
    ):
        service.record_native_qualification(
            _qualification(),
            evidence=_evidence(),
        )


def test_verified_target_qualification_is_persisted_immutable() -> None:
    repositories = CoreRepositories.from_connection(_connection())
    evidence = _evidence()

    class _Verifier:
        def verify(self, value: ExecutorHpcNativeQualificationEvidence) -> str:
            assert value == evidence
            return value.evidence_digest

    service = ExecutorHpcTargetQualificationService(
        repositories,
        evidence_verifier=_Verifier(),
    )

    assert service.record_native_qualification(
        _qualification(),
        evidence=evidence,
    ) == _qualification()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        repositories.connection.execute(
            "UPDATE executor_hpc_target_qualifications SET login_alias = ?",
            ("other-login",),
        )
