from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from importlib import resources
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceFilesystemMutationKind
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceObservationKind
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_process_podman import MappingPodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanWorkspaceFilesystemAdapter
from openzyme_process_podman import PodmanWorkspaceMount
from openzyme_process_podman import SupervisedProcessRequest
from openzyme_process_podman import SupervisedProcessResult
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedger
from openzyme_store_sqlite import install_store_schema_for_offline_migration


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-22T12:00:00+00:00"


def _ledger(
    connection: sqlite3.Connection | None = None,
) -> SQLiteWorkspaceOperationLedger:
    selected = connection or sqlite3.connect(":memory:")
    if selected.execute("PRAGMA user_version").fetchone()[0] == 0:
        install_store_schema_for_offline_migration(selected)
    return SQLiteWorkspaceOperationLedger(selected, _Clock())


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _helper_source() -> str:
    return (
        resources.files("openzyme_process_podman")
        .joinpath("assets/workspace_fs_helper.py")
        .read_text(encoding="utf-8")
    )


def _run_helper(root: Path, request: dict[str, object]) -> dict[str, object]:
    completed = subprocess.run(
        ("/usr/bin/python3", "-c", _helper_source()),
        cwd=root,
        input=json.dumps(request).encode(),
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    response = json.loads(completed.stdout)
    assert isinstance(response, dict)
    return response


def _request(
    *,
    mode: str,
    operation: str,
    path: str,
    **values: object,
) -> dict[str, object]:
    return {
        "schema_version": "openzyme_workspace_fs_helper@1",
        "mode": mode,
        "operation": operation,
        "path": path,
        **values,
    }


def test_helper_supports_closed_crud_patch_and_git_status(tmp_path: Path) -> None:
    created = _run_helper(
        tmp_path,
        _request(
            mode="mutation",
            operation="write",
            path="note.txt",
            content_base64=base64.b64encode(b"old\n").decode(),
            expected_content_digest=None,
            recursive=False,
        ),
    )
    assert created["ok"] is True
    old_digest = _digest_bytes(b"old\n")

    patched = _run_helper(
        tmp_path,
        _request(
            mode="mutation",
            operation="apply_patch",
            path="note.txt",
            content_base64=base64.b64encode(
                b"--- a/note.txt\n+++ b/note.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n"
            ).decode(),
            expected_content_digest=old_digest,
            recursive=False,
        ),
    )
    assert patched["ok"] is True
    assert (tmp_path / "note.txt").read_bytes() == b"new\n"

    new_digest = _digest_bytes(b"new\n")
    copied = _run_helper(
        tmp_path,
        _request(
            mode="mutation",
            operation="copy",
            path="note.txt",
            destination_path="copy.txt",
            expected_content_digest=new_digest,
            content_base64=None,
            recursive=False,
        ),
    )
    assert copied["ok"] is True
    moved = _run_helper(
        tmp_path,
        _request(
            mode="mutation",
            operation="move",
            path="copy.txt",
            destination_path="moved.txt",
            expected_content_digest=new_digest,
            content_base64=None,
            recursive=False,
        ),
    )
    assert moved["ok"] is True
    removed = _run_helper(
        tmp_path,
        _request(
            mode="mutation",
            operation="remove",
            path="moved.txt",
            expected_content_digest=new_digest,
            content_base64=None,
            recursive=False,
        ),
    )
    assert removed["result"] == {"path": "moved.txt", "removed": True}

    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "config", "user.email", "test@example.invalid"),
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "OpenZyme Test"),
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(("git", "add", "note.txt"), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "-qm", "seed"), cwd=tmp_path, check=True)
    (tmp_path / "note.txt").write_text("dirty\n", encoding="utf-8")
    status = _run_helper(
        tmp_path,
        _request(
            mode="observation",
            operation="status",
            path=".",
            max_bytes=4_096,
        ),
    )
    assert status["result"]["dirty"] is True
    assert status["result"]["head_commit"]
    assert status["mutation_applied"] is False


def test_helper_rejects_cas_symlink_hardlink_and_root_escape(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("value", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(source)

    wrong_cas = _run_helper(
        tmp_path,
        _request(
            mode="mutation",
            operation="write",
            path="source.txt",
            content_base64=base64.b64encode(b"changed").decode(),
            expected_content_digest=_digest("wrong"),
            recursive=False,
        ),
    )
    (tmp_path / "hard.txt").hardlink_to(source)
    symlink = _run_helper(
        tmp_path,
        _request(
            mode="observation",
            operation="read",
            path="link.txt",
            max_bytes=1_024,
        ),
    )
    hardlink = _run_helper(
        tmp_path,
        _request(
            mode="observation",
            operation="read",
            path="hard.txt",
            max_bytes=1_024,
        ),
    )
    escape = _run_helper(
        tmp_path,
        _request(
            mode="observation",
            operation="read",
            path="../outside",
            max_bytes=1_024,
        ),
    )

    assert wrong_cas["error_code"] == "workspace_content_precondition_failed"
    assert symlink["error_code"] == "workspace_symlink_forbidden"
    assert hardlink["error_code"] == "workspace_hardlink_forbidden"
    assert escape["error_code"] == "workspace_path_escape"
    assert source.read_text(encoding="utf-8") == "value"


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


def _mount() -> PodmanWorkspaceMount:
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


@dataclass
class LocalHelperExecutor:
    root: Path
    calls: list[SupervisedProcessRequest]

    def run(self, request: SupervisedProcessRequest) -> SupervisedProcessResult:
        self.calls.append(request)
        completed = subprocess.run(
            ("/usr/bin/python3", "-c", request.argv[-1]),
            cwd=self.root,
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
        raise AssertionError("bounded filesystem helper is never retired externally")


def _adapter(tmp_path: Path) -> tuple[PodmanWorkspaceFilesystemAdapter, LocalHelperExecutor]:
    executor = LocalHelperExecutor(tmp_path, [])
    connection = sqlite3.connect(tmp_path / "workspace-operation-ledger.sqlite3")
    adapter = PodmanWorkspaceFilesystemAdapter(
        mount_resolver=MappingPodmanWorkspaceMountResolver(
            {"workspace-1": _mount()}
        ),
        operation_ledger=_ledger(connection),
        executor=executor,
    )
    return adapter, executor


def _mutation(
    *,
    operation_id: str,
    content: bytes,
    expected: str | None,
) -> WorkspaceFilesystemMutation:
    return WorkspaceFilesystemMutation(
        operation_id=operation_id,
        binding=_binding(),
        operation=WorkspaceFilesystemMutationKind.WRITE,
        path="data.txt",
        content=content,
        expected_content_digest=expected,
        idempotency_key=operation_id,
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
    )


def test_filesystem_adapter_executes_and_replays_exact_mutation(tmp_path: Path) -> None:
    adapter, executor = _adapter(tmp_path)
    request = _mutation(operation_id="write-1", content=b"hello", expected=None)

    receipt = adapter.mutate(request)
    replay = adapter.mutate(request)
    observation = adapter.observe(
        WorkspaceObservationRequest(
            binding=_binding(),
            operation=WorkspaceObservationKind.READ,
            path="data.txt",
            max_bytes=1_024,
        )
    )
    payload = json.loads(observation.bounded_payload)

    assert receipt == replay
    assert len(executor.calls) == 2
    assert (tmp_path / "data.txt").read_bytes() == b"hello"
    assert base64.b64decode(payload["content_base64"]) == b"hello"
    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert "--network none" in " ".join(executor.calls[0].argv)


def test_filesystem_reconciliation_never_redispatches_mutation(
    tmp_path: Path,
) -> None:
    adapter, executor = _adapter(tmp_path)
    request = _mutation(operation_id="write-1", content=b"hello", expected=None)
    receipt = adapter.mutate(request)

    reconciled = adapter.reconcile(request)
    restarted, restarted_executor = _adapter(tmp_path)
    pending = restarted.reconcile(request)

    assert reconciled == receipt
    assert len(executor.calls) == 1
    assert restarted_executor.calls == []
    assert pending == receipt
    assert (tmp_path / "data.txt").read_bytes() == b"hello"


def test_filesystem_adapter_preserves_cas_failure_as_no_effect(tmp_path: Path) -> None:
    adapter, _ = _adapter(tmp_path)
    adapter.mutate(_mutation(operation_id="write-1", content=b"hello", expected=None))

    with pytest.raises(WorkspacePortError) as captured:
        adapter.mutate(
            _mutation(
                operation_id="write-2",
                content=b"changed",
                expected=_digest("wrong"),
            )
        )

    assert captured.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert captured.value.mutation_applied is False
    assert (tmp_path / "data.txt").read_bytes() == b"hello"


def test_filesystem_adapter_rejects_operation_identity_collision(
    tmp_path: Path,
) -> None:
    adapter, executor = _adapter(tmp_path)
    adapter.mutate(_mutation(operation_id="write-1", content=b"hello", expected=None))

    with pytest.raises(WorkspacePortError, match="another intent") as captured:
        adapter.mutate(
            _mutation(operation_id="write-1", content=b"different", expected=None)
        )

    assert captured.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert len(executor.calls) == 1
