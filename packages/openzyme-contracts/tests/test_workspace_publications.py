from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import PublicationFetchIdentity
from openzyme_contracts import PublicationManifestEntry
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import PublishedRevision
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationIntentState
from openzyme_contracts import WorkspacePublicationManifest


COMMIT = "a" * 40
TREE = "b" * 40
BASE = "c" * 40
POLICY_DIGEST = f"sha256:{'d' * 64}"


def _manifest() -> WorkspacePublicationManifest:
    return WorkspacePublicationManifest.create(
        (
            PublicationManifestEntry(
                path="src/openzyme/__init__.py",
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id="e" * 40,
                size_bytes=17,
            ),
            PublicationManifestEntry(
                path="tests/test_openzyme.py",
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id="f" * 40,
                size_bytes=29,
            ),
        )
    )


def _intent() -> WorkspacePublicationIntent:
    return WorkspacePublicationIntent.create(
        intent_id="intent_1",
        publication_id="publication_1",
        idempotency_key="publish-clean-head-1",
        project_id="project_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:researcher",
        workspace_id="workspace_1",
        workspace_generation=1,
        capability_lease_id="lease_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        expected_head_commit=COMMIT,
        expected_tree=TREE,
        git_parent_commits=(BASE,),
        declared_base_commit=BASE,
        parent_publication_id=None,
        supersedes_publication_id=None,
        publication_ref="refs/openzyme/publications/publication_1",
        manifest=_manifest(),
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=POLICY_DIGEST,
        checkpoint_id="checkpoint_1",
        state=WorkspacePublicationIntentState.FROZEN,
        created_at="2026-08-16T04:00:00+00:00",
    )


def test_manifest_is_canonical_whole_tree_identity() -> None:
    manifest = _manifest()

    assert [entry.path for entry in manifest.entries] == [
        "src/openzyme/__init__.py",
        "tests/test_openzyme.py",
    ]
    assert manifest.manifest_digest.startswith("sha256:")
    assert WorkspacePublicationManifest.create(tuple(reversed(manifest.entries))) == (
        manifest
    )


def test_manifest_rejects_duplicate_or_noncanonical_path() -> None:
    entry = _manifest().entries[0]

    with pytest.raises(ValueError, match="unique and sorted"):
        WorkspacePublicationManifest(
            entries=(entry, entry),
            manifest_digest=_manifest().manifest_digest,
        )
    with pytest.raises(ValueError, match="canonical repository-relative"):
        replace(entry, path="../outside")


def test_frozen_intent_digest_detects_identity_drift() -> None:
    intent = _intent()

    with pytest.raises(ValueError, match="canonical digest mismatch"):
        replace(intent, workspace_generation=2)
    with pytest.raises(ValueError, match="canonical digest mismatch"):
        replace(intent, repository_policy_digest=f"sha256:{'0' * 64}")


def test_published_revision_keeps_supersedes_and_manifest_path_identity() -> None:
    intent = _intent()
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
        controlled_execution_id="execution_1",
        remote_receipt_id="receipt_1",
        supersedes_publication_id="publication_0",
        created_at="2026-08-16T04:01:00+00:00",
    )

    assert revision.supersedes_publication_id == "publication_0"
    assert revision.contains_path("src/openzyme/__init__.py")
    assert not revision.contains_path("README.md")


def test_fetch_identity_rejects_mutable_branch_name() -> None:
    with pytest.raises(ValueError, match="immutable publication ref"):
        PublicationFetchIdentity(
            publication_id="publication_1",
            repository_binding_id="binding_1",
            repository_binding_version=1,
            repository_id="repository_1",
            publication_ref="refs/heads/dev",
            commit=COMMIT,
            tree=TREE,
            manifest_digest=_manifest().manifest_digest,
        )
