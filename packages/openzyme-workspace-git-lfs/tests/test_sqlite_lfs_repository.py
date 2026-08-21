from __future__ import annotations

import sqlite3

import pytest

from openzyme_workspace_git_lfs import GitLfsBindingPolicy
from openzyme_workspace_git_lfs import GitLfsPathRepresentation
from openzyme_workspace_git_lfs import GitLfsPathRule
from openzyme_workspace_git_lfs import GitLfsPolicyError
from openzyme_workspace_git_lfs import GitLfsRepository
from openzyme_workspace_git_lfs import GitLfsRetentionClass


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE git_lfs_binding_policies (
            binding_id TEXT NOT NULL,
            binding_version INTEGER NOT NULL,
            repository_id TEXT NOT NULL,
            lfs_service_id TEXT NOT NULL,
            lfs_endpoint TEXT NOT NULL,
            object_format TEXT NOT NULL,
            path_rules_json TEXT NOT NULL,
            ordinary_blob_threshold_bytes INTEGER NOT NULL,
            max_object_bytes INTEGER NOT NULL,
            max_workspace_bytes INTEGER NOT NULL,
            max_repository_bytes INTEGER NOT NULL,
            published_retention_class TEXT NOT NULL,
            private_retention_class TEXT NOT NULL,
            private_retention_seconds INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            policy_digest TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            PRIMARY KEY (binding_id, binding_version)
        )
        """
    )
    connection.commit()
    return connection


def _policy(*, repository_id: str = "repository-1") -> GitLfsBindingPolicy:
    return GitLfsBindingPolicy.create(
        binding_id="binding-1",
        binding_version=1,
        repository_id=repository_id,
        lfs_service_id="lfs-1",
        lfs_endpoint="https://git.example/repositories/repository-1.git/info/lfs",
        object_format="sha256",
        path_rules=(
            GitLfsPathRule(
                rule_id="models",
                pattern="models/**",
                representation=GitLfsPathRepresentation.LFS_REQUIRED,
            ),
        ),
        ordinary_blob_threshold_bytes=1024,
        max_object_bytes=2048,
        max_workspace_bytes=4096,
        max_repository_bytes=8192,
        published_retention_class=GitLfsRetentionClass.PUBLISHED,
        private_retention_class=GitLfsRetentionClass.PRIVATE,
        private_retention_seconds=3600,
        policy_version="policy-1",
        created_at="2026-08-20T00:00:00+00:00",
        created_by="operator-1",
    )


def test_repository_delegates_commit_to_injected_uow_callback() -> None:
    connection = _connection()
    committed: list[sqlite3.Connection] = []

    repository = GitLfsRepository(
        connection,
        commit=lambda current: committed.append(current),
    )
    policy = repository.add_policy(_policy())

    assert committed == [connection]
    assert repository.get_policy(binding_id="binding-1", binding_version=1) == policy


def test_repository_rejects_conflicting_immutable_policy() -> None:
    connection = _connection()
    repository = GitLfsRepository(connection, commit=lambda current: current.commit())
    repository.add_policy(_policy())

    with pytest.raises(GitLfsPolicyError, match="immutable binding"):
        repository.add_policy(_policy(repository_id="repository-2"))
