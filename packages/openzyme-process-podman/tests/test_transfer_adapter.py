from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import subprocess

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceTransferDirection
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_process_podman import MappingPodmanTransferMountResolver
from openzyme_process_podman import MappingPodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanRevisionTransferIdentity
from openzyme_process_podman import PodmanTransferObjectKind
from openzyme_process_podman import PodmanTransferObjectMount
from openzyme_process_podman import PodmanWorkspaceMount
from openzyme_process_podman import PodmanWorkspaceTransferAdapter
from openzyme_process_podman import SupervisedProcessRequest
from openzyme_process_podman import SupervisedProcessResult


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _bytes_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _tree_identity(root: Path) -> tuple[str, int]:
    entries: list[dict[str, object]] = []
    size = 0
    for current_root, directory_names, file_names in os.walk(root):
        directory_names.sort()
        file_names.sort()
        current = Path(current_root)
        for name in directory_names:
            entries.append(
                {
                    "path": (current / name).relative_to(root).as_posix(),
                    "kind": "directory",
                }
            )
        for name in file_names:
            content = (current / name).read_bytes()
            size += len(content)
            entries.append(
                {
                    "path": (current / name).relative_to(root).as_posix(),
                    "kind": "file",
                    "size_bytes": len(content),
                    "content_digest": _bytes_digest(content),
                }
            )
    entries.sort(key=lambda item: (str(item["path"]), str(item["kind"])))
    return (
        _bytes_digest(
            _json_bytes(
                {
                    "schema_version": "openzyme_workspace_transfer_tree@1",
                    "entries": entries,
                }
            )
        ),
        size,
    )


def _binding() -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=3,
        state_version=2,
        root_identity_digest=_digest("root"),
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
    )


def _workspace_mount() -> PodmanWorkspaceMount:
    return PodmanWorkspaceMount.create(
        workspace_id="workspace-1",
        session_id="session-1",
        owner_member_id="member-1",
        generation=3,
        state_version=2,
        root_identity_digest=_digest("root"),
        target_id="local:host",
        volume_id="workspace-volume-1",
        clone_logical_root="/workspace/repository",
        image_identity="registry.invalid/openzyme/agent@sha256:" + "a" * 64,
    )


def _revision_identity() -> PodmanRevisionTransferIdentity:
    return PodmanRevisionTransferIdentity(
        source_kind="published_revision",
        source_id="publication-1",
        repository_binding_id="binding-1",
        repository_binding_version=2,
        repository_id="repository-1",
        source_ref="refs/openzyme/publications/publication-1",
        commit="a" * 40,
        tree="b" * 40,
        source_digest=_digest("published-revision"),
        lfs_closure_manifest_digest=_digest("lfs-closure"),
    )


def _mount(
    *,
    direction: WorkspaceTransferDirection,
    object_kind: PodmanTransferObjectKind,
    transfer_ref: str,
    transfer_path: str,
    expected_digest: str | None,
    expected_size: int | None,
    max_bytes: int = 1_048_576,
) -> PodmanTransferObjectMount:
    return PodmanTransferObjectMount.create(
        transfer_ref=transfer_ref,
        session_id="session-1",
        owner_member_id="member-1",
        workspace_id="workspace-1",
        workspace_generation=3,
        workspace_state_version=2,
        direction=direction,
        object_kind=object_kind,
        max_bytes=max_bytes,
        expected_content_digest=expected_digest,
        expected_size_bytes=expected_size,
        revision_identity=(
            _revision_identity()
            if direction is WorkspaceTransferDirection.SYNC_REVISION
            else None
        ),
        volume_id="transfer-volume-1",
        object_relative_path=transfer_path,
        read_only=direction is not WorkspaceTransferDirection.UPLOAD,
    )


def _request(
    mount: PodmanTransferObjectMount,
    *,
    operation_id: str,
    workspace_path: str,
) -> WorkspaceTransferRequest:
    return WorkspaceTransferRequest(
        operation_id=operation_id,
        binding=_binding(),
        direction=mount.direction,
        path=workspace_path,
        transfer_ref=mount.transfer_ref,
        transfer_manifest_digest=mount.transfer_manifest_digest,
        max_bytes=mount.max_bytes,
        timeout_seconds=120,
        idempotency_key=operation_id,
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
    )


@dataclass
class LocalTransferExecutor:
    workspace_root: Path
    transfer_root: Path
    calls: list[SupervisedProcessRequest]

    def run(self, request: SupervisedProcessRequest) -> SupervisedProcessResult:
        self.calls.append(request)
        completed = subprocess.run(
            (
                "/usr/bin/python3",
                "-c",
                request.argv[-2],
                str(self.transfer_root),
            ),
            cwd=self.workspace_root,
            input=request.stdin,
            check=False,
            capture_output=True,
            timeout=10,
        )
        return SupervisedProcessResult(
            process_identity=request.process_identity,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            retired=False,
            started_at="2026-08-19T00:00:00+00:00",
            ended_at="2026-08-19T00:00:01+00:00",
            duration_ms=1_000,
        )

    def retire(self, **_values: object) -> SupervisedProcessResult:
        raise AssertionError("bounded transfer helper is never retired externally")


def _adapter(
    workspace_root: Path,
    transfer_root: Path,
    mount: PodmanTransferObjectMount,
) -> tuple[PodmanWorkspaceTransferAdapter, LocalTransferExecutor]:
    executor = LocalTransferExecutor(workspace_root, transfer_root, [])
    adapter = PodmanWorkspaceTransferAdapter(
        workspace_mount_resolver=MappingPodmanWorkspaceMountResolver(
            {"workspace-1": _workspace_mount()}
        ),
        transfer_mount_resolver=MappingPodmanTransferMountResolver(
            {mount.transfer_ref: mount}
        ),
        executor=executor,
    )
    return adapter, executor


def test_download_is_content_verified_create_only_and_restart_replayable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    transfer = tmp_path / "transfer"
    workspace.joinpath("imports").mkdir(parents=True)
    transfer.joinpath("objects").mkdir(parents=True)
    content = b"model-bytes" * 4096
    transfer.joinpath("objects/model.bin").write_bytes(content)
    mount = _mount(
        direction=WorkspaceTransferDirection.DOWNLOAD,
        object_kind=PodmanTransferObjectKind.FILE,
        transfer_ref="transfer:model-1",
        transfer_path="objects/model.bin",
        expected_digest=_bytes_digest(content),
        expected_size=len(content),
    )
    request = _request(
        mount,
        operation_id="download-1",
        workspace_path="imports/model.bin",
    )
    adapter, executor = _adapter(workspace, transfer, mount)

    receipt = adapter.transfer(request)
    cached = adapter.transfer(request)
    restarted, restarted_executor = _adapter(workspace, transfer, mount)
    replay = restarted.transfer(request)

    assert receipt is cached
    assert workspace.joinpath("imports/model.bin").read_bytes() == content
    assert len(executor.calls) == 1
    assert len(restarted_executor.calls) == 1
    assert "src=transfer-volume-1,dst=/openzyme-transfer,ro" in " ".join(
        executor.calls[0].argv
    )
    assert str(tmp_path) not in " ".join(executor.calls[0].argv)
    assert "transfer:model-1" not in " ".join(executor.calls[0].argv)
    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert json.loads(replay.result_payload)["replayed"] is True


def test_transfer_reconciliation_observes_receipt_without_copy_replay(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    transfer = tmp_path / "transfer"
    workspace.joinpath("imports").mkdir(parents=True)
    transfer.joinpath("objects").mkdir(parents=True)
    content = b"model-bytes"
    transfer.joinpath("objects/model.bin").write_bytes(content)
    mount = _mount(
        direction=WorkspaceTransferDirection.DOWNLOAD,
        object_kind=PodmanTransferObjectKind.FILE,
        transfer_ref="transfer:model-reconcile",
        transfer_path="objects/model.bin",
        expected_digest=_bytes_digest(content),
        expected_size=len(content),
    )
    request = _request(
        mount,
        operation_id="download-reconcile-1",
        workspace_path="imports/model.bin",
    )
    adapter, executor = _adapter(workspace, transfer, mount)
    receipt = adapter.transfer(request)

    reconciled = adapter.reconcile(request)
    restarted, restarted_executor = _adapter(workspace, transfer, mount)
    pending = restarted.reconcile(request)

    assert reconciled is receipt
    assert len(executor.calls) == 1
    assert restarted_executor.calls == []
    assert pending.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert pending.mutation_applied is None
    assert workspace.joinpath("imports/model.bin").read_bytes() == content


def test_upload_writes_reserved_transfer_volume_without_publication(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    transfer = tmp_path / "transfer"
    workspace.joinpath("exports").mkdir(parents=True)
    transfer.joinpath("uploads").mkdir(parents=True)
    content = b"private-result"
    workspace.joinpath("exports/result.bin").write_bytes(content)
    mount = _mount(
        direction=WorkspaceTransferDirection.UPLOAD,
        object_kind=PodmanTransferObjectKind.FILE,
        transfer_ref="transfer:upload-1",
        transfer_path="uploads/result.bin",
        expected_digest=None,
        expected_size=None,
    )
    request = _request(
        mount,
        operation_id="upload-1",
        workspace_path="exports/result.bin",
    )
    adapter, executor = _adapter(workspace, transfer, mount)

    receipt = adapter.transfer(request)
    result = json.loads(receipt.result_payload)

    assert transfer.joinpath("uploads/result.bin").read_bytes() == content
    assert "src=transfer-volume-1,dst=/openzyme-transfer,rw" in " ".join(
        executor.calls[0].argv
    )
    assert result["content_digest"] == _bytes_digest(content)
    assert result["publication_performed"] is False
    assert result["workspace_cleanup_performed"] is False
    assert result["task_transition_performed"] is False


def test_revision_sync_materializes_exact_tree_without_checkout_or_publish(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    transfer = tmp_path / "transfer"
    workspace.joinpath("imports").mkdir(parents=True)
    revision = transfer / "revisions/revision-1"
    revision.joinpath("nested").mkdir(parents=True)
    revision.joinpath("README.md").write_text("revision\n", encoding="utf-8")
    revision.joinpath("nested/data.bin").write_bytes(b"data")
    content_digest, size = _tree_identity(revision)
    mount = _mount(
        direction=WorkspaceTransferDirection.SYNC_REVISION,
        object_kind=PodmanTransferObjectKind.REVISION_TREE,
        transfer_ref="transfer:revision-1",
        transfer_path="revisions/revision-1",
        expected_digest=content_digest,
        expected_size=size,
    )
    request = _request(
        mount,
        operation_id="sync-revision-1",
        workspace_path="imports/revision-1",
    )
    adapter, _ = _adapter(workspace, transfer, mount)

    receipt = adapter.transfer(request)
    result = json.loads(receipt.result_payload)

    assert workspace.joinpath("imports/revision-1/README.md").read_text() == (
        "revision\n"
    )
    assert result["revision_identity"]["commit"] == "a" * 40
    assert result["revision_identity"]["tree"] == "b" * 40
    assert result["checkpoint_performed"] is False
    assert result["publication_performed"] is False


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_upload_rejects_links_without_creating_transfer_object(
    tmp_path: Path,
    link_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    transfer = tmp_path / "transfer"
    workspace.joinpath("exports").mkdir(parents=True)
    transfer.joinpath("uploads").mkdir(parents=True)
    source = workspace / "exports/source.bin"
    source.write_bytes(b"private")
    link = workspace / "exports/link.bin"
    if link_kind == "symlink":
        link.symlink_to(source)
    else:
        link.hardlink_to(source)
    mount = _mount(
        direction=WorkspaceTransferDirection.UPLOAD,
        object_kind=PodmanTransferObjectKind.FILE,
        transfer_ref=f"transfer:{link_kind}-1",
        transfer_path=f"uploads/{link_kind}.bin",
        expected_digest=None,
        expected_size=None,
    )
    request = _request(
        mount,
        operation_id=f"upload-{link_kind}-1",
        workspace_path="exports/link.bin",
    )
    adapter, _ = _adapter(workspace, transfer, mount)

    with pytest.raises(WorkspacePortError) as caught:
        adapter.transfer(request)

    assert caught.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert caught.value.mutation_applied is False
    assert not transfer.joinpath(f"uploads/{link_kind}.bin").exists()


def test_manifest_drift_is_rejected_before_podman_dispatch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    transfer = tmp_path / "transfer"
    workspace.mkdir()
    transfer.mkdir()
    content = b"data"
    transfer.joinpath("source.bin").write_bytes(content)
    mount = _mount(
        direction=WorkspaceTransferDirection.DOWNLOAD,
        object_kind=PodmanTransferObjectKind.FILE,
        transfer_ref="transfer:source-1",
        transfer_path="source.bin",
        expected_digest=_bytes_digest(content),
        expected_size=len(content),
    )
    request = _request(
        mount,
        operation_id="download-source-1",
        workspace_path="source.bin",
    )
    request = WorkspaceTransferRequest(
        operation_id=request.operation_id,
        binding=request.binding,
        direction=request.direction,
        path=request.path,
        transfer_ref=request.transfer_ref,
        transfer_manifest_digest=_digest("wrong-transfer-manifest"),
        max_bytes=request.max_bytes,
        timeout_seconds=request.timeout_seconds,
        idempotency_key=request.idempotency_key,
        authority_lease_id=request.authority_lease_id,
        authority_generation=request.authority_generation,
        authority_fence=request.authority_fence,
    )
    adapter, executor = _adapter(workspace, transfer, mount)

    with pytest.raises(WorkspacePortError) as caught:
        adapter.transfer(request)

    assert caught.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert executor.calls == []


def test_transfer_helper_is_packaged_with_pinned_source_digest() -> None:
    source = (
        resources.files("openzyme_process_podman")
        .joinpath("assets/workspace_transfer_helper.py")
        .read_bytes()
    )
    from openzyme_process_podman import PODMAN_TRANSFER_HELPER_DIGEST

    assert _bytes_digest(source) == PODMAN_TRANSFER_HELPER_DIGEST
