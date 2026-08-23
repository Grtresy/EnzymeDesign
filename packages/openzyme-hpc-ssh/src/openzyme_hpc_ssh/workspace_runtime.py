#!/usr/bin/env python3
"""Target-native executor workspace isolation helper.

This module deliberately uses only the Python standard library so the exact
source file can be deployed as one digest-pinned executable on an HPC login
target.  It owns no scheduler authority and accepts no arbitrary command.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import sys

WORKSPACE_RUNTIME_VERSION = "1.0.0"
WORKSPACE_RUNTIME_SCHEMA = "openzyme_workspace_runtime@1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HANDLE = re.compile(r"hpcws_[0-9a-f]{32}")
_MARKER_NAME = ".openzyme-workspace-runtime.json"
_STATE_NAME = ".openzyme-workspace-runtime-state"


class WorkspaceRuntimeError(RuntimeError):
    """Stable target helper failure without a fallback."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(payload: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def helper_build_digest(path: Path | None = None) -> str:
    source = Path(__file__) if path is None else path
    return "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()


def principal_identity() -> dict[str, object]:
    uid = os.geteuid()
    gid = os.getegid()
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError as exc:
        raise WorkspaceRuntimeError(
            "workspace_runtime_principal_unknown",
            "effective uid has no passwd identity",
        ) from exc
    payload: dict[str, object] = {
        "schema_version": "openzyme_workspace_runtime_principal@1",
        "uid": uid,
        "gid": gid,
        "username": username,
    }
    return {**payload, "principal_digest": _digest(payload)}


def root_policy_digest(*, policy_id: str, workspace_parent: Path) -> str:
    principal = principal_identity()
    return _digest(
        {
            "schema_version": "openzyme_workspace_root_policy@1",
            "helper_version": WORKSPACE_RUNTIME_VERSION,
            "policy_id": policy_id,
            "workspace_parent": str(workspace_parent),
            "principal_digest": principal["principal_digest"],
        }
    )


def _require_digest(value: str, *, field: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise WorkspaceRuntimeError(
            "workspace_runtime_argument_invalid",
            f"{field} is not a canonical sha256 digest",
        )
    return value


def _require_identifier(value: str, *, field: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None:
        raise WorkspaceRuntimeError(
            "workspace_runtime_argument_invalid",
            f"{field} is not a safe identifier",
        )
    return value


def _require_owned_directory(path: Path, *, mode: int) -> None:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise WorkspaceRuntimeError(
            "workspace_runtime_root_unsafe",
            "workspace runtime directory ownership or mode is unsafe",
        )


def _ensure_owned_directory(path: Path, *, mode: int) -> None:
    if path.exists() or path.is_symlink():
        _require_owned_directory(path, mode=mode)
        return
    path.mkdir(mode=mode, parents=False)
    _require_owned_directory(path, mode=mode)


def _write_once(path: Path, payload: dict[str, object]) -> None:
    encoded = _canonical_bytes(payload) + b"\n"
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or path.read_bytes() != encoded
        ):
            raise WorkspaceRuntimeError(
                "workspace_runtime_state_conflict",
                "workspace runtime state conflicts with the exact occurrence",
            )
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_private_json(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise WorkspaceRuntimeError(
            "workspace_runtime_state_unsafe",
            "workspace runtime state ownership or mode is unsafe",
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WorkspaceRuntimeError(
            "workspace_runtime_state_invalid",
            "workspace runtime state is not one JSON object",
        )
    return payload


def _replace_json(path: Path, payload: dict[str, object]) -> None:
    encoded = _canonical_bytes(payload) + b"\n"
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    policy_id: str
    root_policy_digest: str
    workspace_root: Path
    owner_identity_digest: str
    runner_handle: str

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        root_policy_digest_value: str,
        workspace_root: str,
        owner_identity_digest: str,
        runner_handle: str,
    ) -> "WorkspaceBinding":
        _require_identifier(policy_id, field="policy_id")
        _require_digest(root_policy_digest_value, field="root_policy_digest")
        _require_digest(owner_identity_digest, field="owner_identity_digest")
        if _HANDLE.fullmatch(runner_handle) is None:
            raise WorkspaceRuntimeError(
                "workspace_runtime_handle_invalid",
                "runner handle is not an exact workspace handle",
            )
        root = Path(workspace_root)
        if (
            not root.is_absolute()
            or root == Path("/")
            or root.name != runner_handle
            or any(part in {"", ".", ".."} for part in root.parts[1:])
        ):
            raise WorkspaceRuntimeError(
                "workspace_runtime_path_invalid",
                "workspace root is not the exact handle child of an absolute root",
            )
        expected = root_policy_digest(policy_id=policy_id, workspace_parent=root.parent)
        if expected != root_policy_digest_value:
            raise WorkspaceRuntimeError(
                "workspace_runtime_policy_drift",
                "workspace parent or principal differs from the bound root policy",
            )
        return cls(
            policy_id=policy_id,
            root_policy_digest=root_policy_digest_value,
            workspace_root=root,
            owner_identity_digest=owner_identity_digest,
            runner_handle=runner_handle,
        )

    @property
    def marker_payload(self) -> dict[str, object]:
        principal = principal_identity()
        return {
            "schema_version": WORKSPACE_RUNTIME_SCHEMA,
            "helper_version": WORKSPACE_RUNTIME_VERSION,
            "policy_id": self.policy_id,
            "root_policy_digest": self.root_policy_digest,
            "workspace_root": str(self.workspace_root),
            "owner_identity_digest": self.owner_identity_digest,
            "runner_handle": self.runner_handle,
            "principal_digest": principal["principal_digest"],
        }

    @property
    def receipt_payload(self) -> dict[str, object]:
        marker_digest = _digest(self.marker_payload)
        return {
            "schema_version": "openzyme_workspace_isolation_receipt@1",
            "marker_digest": marker_digest,
            "root_policy_digest": self.root_policy_digest,
            "owner_identity_digest": self.owner_identity_digest,
            "runner_handle": self.runner_handle,
            "principal_digest": principal_identity()["principal_digest"],
        }


def _state_root(binding: WorkspaceBinding) -> Path:
    return binding.workspace_root.parent / _STATE_NAME


def _state_path(binding: WorkspaceBinding) -> Path:
    return _state_root(binding) / f"{binding.runner_handle}.json"


def _verify_marker(binding: WorkspaceBinding) -> None:
    _require_owned_directory(binding.workspace_root, mode=0o700)
    marker = binding.workspace_root / _MARKER_NAME
    metadata = marker.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or marker.read_bytes() != _canonical_bytes(binding.marker_payload) + b"\n"
    ):
        raise WorkspaceRuntimeError(
            "workspace_runtime_marker_drift",
            "workspace marker differs from the exact owner binding",
        )


def _emit_isolation(binding: WorkspaceBinding) -> None:
    print(
        "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST="
        + str(principal_identity()["principal_digest"])
    )
    print("OPENZYME_ISOLATION_RECEIPT_DIGEST=" + _digest(binding.receipt_payload))


def provision(binding: WorkspaceBinding) -> None:
    parent = binding.workspace_root.parent
    _ensure_owned_directory(parent, mode=0o700)
    state_root = _state_root(binding)
    _ensure_owned_directory(state_root, mode=0o700)
    if binding.workspace_root.exists() or binding.workspace_root.is_symlink():
        _verify_marker(binding)
    else:
        binding.workspace_root.mkdir(mode=0o700)
        _write_once(binding.workspace_root / _MARKER_NAME, binding.marker_payload)
        _verify_marker(binding)
    _write_once(
        _state_path(binding),
        {
            "schema_version": "openzyme_workspace_runtime_state@1",
            "phase": "provisioned",
            "binding": binding.marker_payload,
            "isolation_receipt_digest": _digest(binding.receipt_payload),
        },
    )
    _emit_isolation(binding)


def verify(binding: WorkspaceBinding) -> None:
    _require_owned_directory(binding.workspace_root.parent, mode=0o700)
    _require_owned_directory(_state_root(binding), mode=0o700)
    _verify_marker(binding)
    state = _read_private_json(_state_path(binding))
    if state.get("binding") != binding.marker_payload or state.get("phase") != "provisioned":
        raise WorkspaceRuntimeError(
            "workspace_runtime_state_drift",
            "workspace state differs from the exact provision occurrence",
        )
    _emit_isolation(binding)


def cleanup(binding: WorkspaceBinding, *, settlement_proof_digest: str) -> None:
    _require_digest(settlement_proof_digest, field="settlement_proof_digest")
    parent = binding.workspace_root.parent
    _require_owned_directory(parent, mode=0o700)
    state_root = _state_root(binding)
    _require_owned_directory(state_root, mode=0o700)
    state_path = _state_path(binding)
    if not state_path.exists() and not state_path.is_symlink():
        raise WorkspaceRuntimeError(
            "workspace_runtime_cleanup_state_missing",
            "cleanup requires the exact persisted provision state",
        )
    state = _read_private_json(state_path)
    cleanup_payload = {
        "schema_version": "openzyme_workspace_isolation_cleanup_receipt@1",
        "binding_digest": _digest(binding.marker_payload),
        "settlement_proof_digest": settlement_proof_digest,
        "disposition": "deleted",
    }
    cleanup_digest = _digest(cleanup_payload)
    if state.get("phase") == "deleted":
        if state.get("cleanup_receipt_digest") != cleanup_digest:
            raise WorkspaceRuntimeError(
                "workspace_runtime_cleanup_settlement_drift",
                "cleanup was already settled by a different proof",
            )
    else:
        if state.get("binding") != binding.marker_payload:
            raise WorkspaceRuntimeError(
                "workspace_runtime_state_drift",
                "cleanup state differs from the exact provision occurrence",
            )
        tombstone = parent / f".{binding.runner_handle}.deleting"
        if binding.workspace_root.exists() or binding.workspace_root.is_symlink():
            _verify_marker(binding)
            if tombstone.exists() or tombstone.is_symlink():
                raise WorkspaceRuntimeError(
                    "workspace_runtime_cleanup_tombstone_conflict",
                    "cleanup tombstone already exists",
                )
            os.replace(binding.workspace_root, tombstone)
            _replace_json(
                state_path,
                {
                    **state,
                    "phase": "deleting",
                    "settlement_proof_digest": settlement_proof_digest,
                    "cleanup_receipt_digest": cleanup_digest,
                },
            )
        elif state.get("phase") != "deleting":
            raise WorkspaceRuntimeError(
                "workspace_runtime_cleanup_effect_unknown",
                "workspace disappeared without a helper-owned cleanup intent",
            )
        if tombstone.exists() or tombstone.is_symlink():
            metadata = tombstone.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise WorkspaceRuntimeError(
                    "workspace_runtime_cleanup_tombstone_unsafe",
                    "cleanup tombstone is not an exact directory",
                )
            shutil.rmtree(tombstone)
        _replace_json(
            state_path,
            {
                "schema_version": "openzyme_workspace_runtime_state@1",
                "phase": "deleted",
                "binding": binding.marker_payload,
                "settlement_proof_digest": settlement_proof_digest,
                "cleanup_receipt_digest": cleanup_digest,
            },
        )
    print("OPENZYME_CLEANUP_DISPOSITION=deleted")
    print("OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST=" + cleanup_digest)


def _binding_from_args(args: argparse.Namespace) -> WorkspaceBinding:
    return WorkspaceBinding.create(
        policy_id=args.policy_id,
        root_policy_digest_value=args.root_policy_digest,
        workspace_root=args.workspace_root,
        owner_identity_digest=args.owner_identity_digest,
        runner_handle=args.runner_handle,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openzyme-workspace-runtime")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("version")
    policy = subparsers.add_parser("policy-digest")
    policy.add_argument("--policy-id", required=True)
    policy.add_argument("--workspace-parent", required=True)
    for operation in ("provision", "verify", "cleanup"):
        command = subparsers.add_parser(operation)
        command.add_argument("--policy-id", required=True)
        command.add_argument("--root-policy-digest", required=True)
        command.add_argument("--workspace-root", required=True)
        command.add_argument("--owner-identity-digest", required=True)
        command.add_argument("--runner-handle", required=True)
        if operation == "cleanup":
            command.add_argument("--settlement-proof-digest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "version":
            print("OPENZYME_WORKSPACE_RUNTIME_VERSION=" + WORKSPACE_RUNTIME_VERSION)
            print("OPENZYME_WORKSPACE_RUNTIME_BUILD_DIGEST=" + helper_build_digest())
        elif args.operation == "policy-digest":
            policy_id = _require_identifier(args.policy_id, field="policy_id")
            parent = Path(args.workspace_parent)
            if not parent.is_absolute() or parent == Path("/"):
                raise WorkspaceRuntimeError(
                    "workspace_runtime_path_invalid",
                    "workspace parent must be a protected absolute path",
                )
            print(
                "OPENZYME_ROOT_POLICY_DIGEST="
                + root_policy_digest(policy_id=policy_id, workspace_parent=parent)
            )
            print(
                "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST="
                + str(principal_identity()["principal_digest"])
            )
        elif args.operation == "provision":
            provision(_binding_from_args(args))
        elif args.operation == "verify":
            verify(_binding_from_args(args))
        else:
            cleanup(
                _binding_from_args(args),
                settlement_proof_digest=args.settlement_proof_digest,
            )
    except (OSError, ValueError, json.JSONDecodeError, WorkspaceRuntimeError) as exc:
        error_code = getattr(exc, "error_code", "workspace_runtime_failed")
        print(f"OPENZYME_WORKSPACE_RUNTIME_ERROR={error_code}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
