from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from openzyme_hpc_ssh.workspace_runtime import WorkspaceBinding
from openzyme_hpc_ssh.workspace_runtime import WorkspaceRuntimeError
from openzyme_hpc_ssh.workspace_runtime import cleanup
from openzyme_hpc_ssh.workspace_runtime import helper_build_digest
from openzyme_hpc_ssh.workspace_runtime import principal_identity
from openzyme_hpc_ssh.workspace_runtime import provision
from openzyme_hpc_ssh.workspace_runtime import root_policy_digest
from openzyme_hpc_ssh.workspace_runtime import verify


DIGEST = "sha256:" + "a" * 64
HANDLE = "hpcws_" + "1" * 32
POLICY_ID = "diannan-executor-workspace-v1"


def _binding(parent: Path) -> WorkspaceBinding:
    parent.mkdir(mode=0o700)
    return WorkspaceBinding.create(
        policy_id=POLICY_ID,
        root_policy_digest_value=root_policy_digest(
            policy_id=POLICY_ID,
            workspace_parent=parent,
        ),
        workspace_root=str(parent / HANDLE),
        owner_identity_digest=DIGEST,
        runner_handle=HANDLE,
    )


def test_helper_provisions_verifies_and_idempotently_cleans_one_exact_root(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path / "workspaces")

    provision(binding)
    provision(binding)
    verify(binding)

    marker = binding.workspace_root / ".openzyme-workspace-runtime.json"
    assert stat.S_IMODE(binding.workspace_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert json.loads(marker.read_text(encoding="utf-8"))["runner_handle"] == HANDLE

    cleanup(binding, settlement_proof_digest=DIGEST)
    cleanup(binding, settlement_proof_digest=DIGEST)

    assert not binding.workspace_root.exists()
    state = json.loads(
        (
            binding.workspace_root.parent
            / ".openzyme-workspace-runtime-state"
            / f"{HANDLE}.json"
        ).read_text(encoding="utf-8")
    )
    assert state["phase"] == "deleted"


def test_helper_rejects_root_policy_drift_before_mutation(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir(mode=0o700)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    policy_digest = root_policy_digest(
        policy_id=POLICY_ID,
        workspace_parent=approved,
    )

    with pytest.raises(WorkspaceRuntimeError) as captured:
        WorkspaceBinding.create(
            policy_id=POLICY_ID,
            root_policy_digest_value=policy_digest,
            workspace_root=str(other / HANDLE),
            owner_identity_digest=DIGEST,
            runner_handle=HANDLE,
        )

    assert captured.value.error_code == "workspace_runtime_policy_drift"
    assert tuple(other.iterdir()) == ()


def test_helper_rejects_symlink_workspace_without_following_it(tmp_path: Path) -> None:
    parent = tmp_path / "workspaces"
    binding = _binding(parent)
    target = tmp_path / "outside"
    target.mkdir()
    binding.workspace_root.symlink_to(target, target_is_directory=True)

    with pytest.raises(WorkspaceRuntimeError) as captured:
        provision(binding)

    assert captured.value.error_code == "workspace_runtime_root_unsafe"
    assert tuple(target.iterdir()) == ()


def test_helper_cleanup_resumes_exact_deleting_intent_after_response_loss(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path / "workspaces")
    provision(binding)
    state_path = (
        binding.workspace_root.parent
        / ".openzyme-workspace-runtime-state"
        / f"{HANDLE}.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tombstone = binding.workspace_root.parent / f".{HANDLE}.deleting"
    os.replace(binding.workspace_root, tombstone)
    state.update(
        {
            "phase": "deleting",
            "settlement_proof_digest": DIGEST,
            "cleanup_receipt_digest": "sha256:" + "0" * 64,
        }
    )
    state_path.write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state_path.chmod(0o600)

    cleanup(binding, settlement_proof_digest=DIGEST)

    assert not tombstone.exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))["phase"] == "deleted"


def test_helper_identity_is_exact_and_source_digest_bound() -> None:
    principal = principal_identity()

    assert principal["uid"] == os.geteuid()
    assert principal["gid"] == os.getegid()
    assert str(principal["principal_digest"]).startswith("sha256:")
    assert helper_build_digest().startswith("sha256:")
