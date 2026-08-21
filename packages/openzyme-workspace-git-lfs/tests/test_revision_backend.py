from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_contracts import PrivateRefAdvanceKind
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublishedRevision
from openzyme_contracts import RemotePrivateRefObservation
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathReadRequest
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import WorkspaceCheckpointProofInput
from openzyme_contracts import WorkspaceFormalBoundary
from openzyme_contracts import WorkspacePublicationDispatchIdentity
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationIntentState
from openzyme_contracts import canonical_sha256_digest
from openzyme_workspace_git_lfs import GitLfsPointer
from openzyme_workspace_git_lfs import GitRepositoryLocation
from openzyme_workspace_git_lfs import GitRepositoryLocator
from openzyme_workspace_git_lfs import GitRevisionBackendError
from openzyme_workspace_git_lfs import GitlessComputeTreeRequest
from openzyme_workspace_git_lfs import LocalGitRevisionBackend
from openzyme_workspace_git_lfs import LocalGitlessComputeTreePreparer


NOW = "2026-08-20T12:00:00+00:00"


def _run(cwd: Path, *argv: str) -> bytes:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


@dataclass(frozen=True)
class _Repository:
    bare: Path
    lfs: Path
    base: str
    commit: str
    tree: str
    private_ref: str
    pointer: GitLfsPointer


def _repository(tmp_path: Path) -> _Repository:
    bare = tmp_path / "repository.git"
    work = tmp_path / "work"
    lfs = tmp_path / "lfs"
    _run(tmp_path, "git", "init", "--bare", str(bare))
    _run(tmp_path, "git", "init", str(work))
    _run(work, "git", "config", "user.name", "OpenZyme Test")
    _run(work, "git", "config", "user.email", "openzyme@example.invalid")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _run(work, "git", "add", "README.md")
    _run(work, "git", "commit", "-m", "base")
    base = _run(work, "git", "rev-parse", "HEAD").decode().strip()

    content = b"verified-large-content\n"
    oid = hashlib.sha256(content).hexdigest()
    pointer = GitLfsPointer(oid=oid, size=len(content))
    (work / "models").mkdir()
    (work / "models" / "model.bin").write_bytes(pointer.to_bytes())
    (work / "results.txt").write_text("result\n", encoding="utf-8")
    _run(work, "git", "add", "models/model.bin", "results.txt")
    _run(work, "git", "commit", "-m", "result")
    commit = _run(work, "git", "rev-parse", "HEAD").decode().strip()
    tree = _run(work, "git", "rev-parse", "HEAD^{tree}").decode().strip()
    private_ref = "refs/openzyme/private/session-1/agent-1"
    _run(work, "git", "push", str(bare), f"HEAD:{private_ref}")

    object_path = lfs / "objects" / oid[:2] / oid[2:4] / oid
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(content)
    return _Repository(bare, lfs, base, commit, tree, private_ref, pointer)


def _binding(repo: _Repository) -> ProjectRepositoryBinding:
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
        default_base_commit=repo.base,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="policy-1",
        repository_policy_digest=canonical_sha256_digest({"policy": 1}),
        created_at=NOW,
        created_by="operator-1",
    )


def _backend(repo: _Repository) -> LocalGitRevisionBackend:
    return LocalGitRevisionBackend(
        locator=GitRepositoryLocator(
            (
                GitRepositoryLocation(
                    repository_id="repository-1",
                    bare_repository_root=repo.bare,
                    lfs_object_root=repo.lfs,
                ),
            )
        ),
        now=lambda: NOW,
    )


def _intent(repo: _Repository, backend: LocalGitRevisionBackend) -> WorkspacePublicationIntent:
    binding = _binding(repo)
    manifest = backend.observe_manifest(binding, commit=repo.commit).manifest
    return WorkspacePublicationIntent.create(
        intent_id="intent-1",
        publication_id="publication-1",
        idempotency_key="publication-1",
        project_id="project-1",
        session_id="session-1",
        agent_member_id="agent-1",
        agent_id="agent-identity-1",
        workspace_id="workspace-1",
        workspace_generation=1,
        capability_lease_id="lease-1",
        repository_binding_id=binding.binding_id,
        repository_binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        expected_head_commit=repo.commit,
        expected_tree=repo.tree,
        git_parent_commits=(repo.base,),
        declared_base_commit=repo.base,
        parent_publication_id=None,
        supersedes_publication_id=None,
        publication_ref="refs/openzyme/publications/publication-1",
        manifest=manifest,
        repository_policy_version=binding.repository_policy_version,
        repository_policy_digest=binding.repository_policy_digest,
        checkpoint_id="checkpoint-1",
        state=WorkspacePublicationIntentState.FROZEN,
        created_at=NOW,
    )


def _dispatch() -> WorkspacePublicationDispatchIdentity:
    return WorkspacePublicationDispatchIdentity(
        receipt_id="receipt-1",
        execution_id="operation-1",
        dispatch_generation=1,
        fencing_token=7,
    )


def _published(repo: _Repository, intent: WorkspacePublicationIntent, receipt_id: str) -> PublishedRevision:
    return PublishedRevision.create(
        publication_id=intent.publication_id,
        intent_id=intent.intent_id,
        project_id=intent.project_id,
        session_id=intent.session_id,
        repository_binding_id=intent.repository_binding_id,
        repository_binding_version=intent.repository_binding_version,
        repository_id=intent.repository_id,
        commit=repo.commit,
        tree=repo.tree,
        git_parent_commits=(repo.base,),
        declared_base_commit=repo.base,
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
        remote_receipt_id=receipt_id,
        supersedes_publication_id=None,
        created_at=NOW,
    )


def test_observes_checkpoint_commit_and_lfs_closed_manifest(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    backend = _backend(repo)
    binding = _binding(repo)
    supplied = RemotePrivateRefObservation(
        service_id=binding.internal_git_service_id,
        repository_id=binding.repository_id,
        private_ref=repo.private_ref,
        prior_commit=repo.base,
        observed_commit=repo.commit,
        advance_kind=PrivateRefAdvanceKind.FAST_FORWARD,
        observed_at=NOW,
    )
    proof = WorkspaceCheckpointProofInput(
        boundary=WorkspaceFormalBoundary.PUBLICATION,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_member_id="agent-1",
        agent_id="agent-identity-1",
        workspace_generation=1,
        repository_binding_id=binding.binding_id,
        repository_binding_version=binding.binding_version,
        commit=repo.commit,
        tree=repo.tree,
        private_ref=repo.private_ref,
        remote_observation=supplied,
    )

    observed = backend.observe_private_ref(binding, proof)
    commit = backend.observe_commit(binding, commit=repo.commit)
    manifest = backend.observe_manifest(binding, commit=repo.commit)

    assert observed.observed_commit == repo.commit
    assert commit.tree == repo.tree
    lfs_entry = next(item for item in manifest.manifest.entries if item.path.endswith("model.bin"))
    assert lfs_entry.lfs_oid == f"sha256:{repo.pointer.oid}"
    assert lfs_entry.lfs_size_bytes == repo.pointer.size


def test_publication_is_create_only_and_restart_observation_returns_exact_receipt(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    backend = _backend(repo)
    binding = _binding(repo)
    intent = _intent(repo, backend)

    receipt = backend.dispatch_publication(binding, intent, _dispatch())
    restarted = _backend(repo)

    assert restarted.observe_publication(binding, intent, receipt) == receipt
    assert receipt.server_observed_commit == repo.commit
    with pytest.raises(GitRevisionBackendError) as exc_info:
        restarted.dispatch_publication(binding, intent, _dispatch())
    assert exc_info.value.code == "publication_ref_integrity_conflict"
    assert exc_info.value.fallback_performed is False


def test_publication_reconcile_and_namespace_observation_never_redispatch(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    backend = _backend(repo)
    binding = _binding(repo)
    intent = _intent(repo, backend)
    dispatch = _dispatch()

    assert backend.reconcile_publication(binding, intent, dispatch) is None
    receipt = backend.dispatch_publication(binding, intent, dispatch)
    restarted = _backend(repo)

    reconciled = restarted.reconcile_publication(binding, intent, dispatch)
    namespace = restarted.observe_publication_namespace(binding)

    assert reconciled is not None
    assert reconciled.receipt_id == receipt.receipt_id
    assert reconciled.execution_id == receipt.execution_id
    assert reconciled.execution_dispatch_generation == dispatch.dispatch_generation
    assert reconciled.execution_fencing_token == dispatch.fencing_token
    assert namespace.repository_binding_id == binding.binding_id
    assert namespace.refs == ((intent.publication_ref, repo.commit),)
    assert namespace.observation_digest.startswith("sha256:")


def test_revision_path_reads_actual_lfs_bytes_and_detects_tamper(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    backend = _backend(repo)
    binding = _binding(repo)
    intent = _intent(repo, backend)
    receipt = backend.dispatch_publication(binding, intent, _dispatch())
    revision = _published(repo, intent, receipt.receipt_id)
    entry = next(item for item in intent.manifest.entries if item.path.endswith("model.bin"))
    ref = RevisionPathRef.create(
        ref_id="ref-1",
        publication_id=intent.publication_id,
        project_id=intent.project_id,
        session_id=intent.session_id,
        repository_binding_id=binding.binding_id,
        repository_binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        commit=repo.commit,
        tree=repo.tree,
        path=entry.path,
        entry_kind=RevisionPathEntryKind.LFS_FILE,
        object_id=entry.object_id,
        size_bytes=entry.size_bytes,
        lfs_oid=entry.lfs_oid,
        lfs_size_bytes=entry.lfs_size_bytes,
        path_manifest_digest=None,
        created_at=NOW,
    )

    verified = backend.verify_revision_path(binding, revision, ref)
    read = backend.read_revision_path(binding, RevisionPathReadRequest(ref=ref, max_bytes=8))

    assert verified.lfs_oid == f"sha256:{repo.pointer.oid}"
    assert read.truncated is True
    assert read.returned_bytes == b"verified"

    object_path = repo.lfs / "objects" / repo.pointer.oid[:2] / repo.pointer.oid[2:4] / repo.pointer.oid
    object_path.write_bytes(b"tampered")
    with pytest.raises(GitRevisionBackendError) as exc_info:
        backend.verify_revision_path(binding, revision, ref)
    assert exc_info.value.code == "git_lfs_object_integrity_mismatch"
    assert exc_info.value.effect_certainty.value == "no_effect"


def test_missing_lfs_object_fails_closed_without_locator_disclosure(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    object_path = repo.lfs / "objects" / repo.pointer.oid[:2] / repo.pointer.oid[2:4] / repo.pointer.oid
    object_path.unlink()
    backend = _backend(repo)

    with pytest.raises(GitRevisionBackendError) as exc_info:
        backend.observe_manifest(_binding(repo), commit=repo.commit)
    assert exc_info.value.code == "git_lfs_object_missing"
    assert str(repo.lfs) not in str(exc_info.value)


def test_gitless_compute_tree_materializes_exact_revision_and_lfs_bytes(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    backend = _backend(repo)
    binding = _binding(repo)
    intent = _intent(repo, backend)
    remote = backend.dispatch_publication(binding, intent, _dispatch())
    revision = _published(repo, intent, remote.receipt_id)
    destination = tmp_path / "compute-tree"
    request = GitlessComputeTreeRequest(
        preparation_id="preparation-1",
        binding=binding,
        revision=revision,
        destination_root=destination,
        max_total_bytes=1_048_576,
    )
    preparer = LocalGitlessComputeTreePreparer(backend)

    receipt = preparer.prepare(request)

    assert (destination / "README.md").read_text() == "base\n"
    assert (destination / "results.txt").read_text() == "result\n"
    assert (destination / "models" / "model.bin").read_bytes() == (
        b"verified-large-content\n"
    )
    assert (destination / ".git").exists() is False
    assert receipt.lfs_oids == (f"sha256:{repo.pointer.oid}",)
    assert "destination" not in receipt.to_safe_dict()
    assert preparer.observe(request, receipt) == receipt


def test_gitless_compute_tree_reconcile_detects_tamper_without_rematerializing(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    backend = _backend(repo)
    binding = _binding(repo)
    intent = _intent(repo, backend)
    remote = backend.dispatch_publication(binding, intent, _dispatch())
    revision = _published(repo, intent, remote.receipt_id)
    destination = tmp_path / "compute-tree"
    request = GitlessComputeTreeRequest(
        preparation_id="preparation-1",
        binding=binding,
        revision=revision,
        destination_root=destination,
        max_total_bytes=1_048_576,
    )
    preparer = LocalGitlessComputeTreePreparer(backend)
    receipt = preparer.prepare(request)
    (destination / "results.txt").write_text("tampered\n")

    with pytest.raises(GitRevisionBackendError) as error:
        preparer.observe(request, receipt)
    assert error.value.code == "gitless_compute_tree_integrity_mismatch"

    with pytest.raises(GitRevisionBackendError) as exists:
        preparer.prepare(request)
    assert exists.value.code == "gitless_compute_destination_exists"
