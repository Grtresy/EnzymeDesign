from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from openzyme_core import DurableRepositoryRootManager
from openzyme_core import RepositoryRootBoundary
from openzyme_core import SQLiteRepositoryProvider
from openzyme_runtime import RepositoryServiceSettings

from .repository_service_preflight import preflight_repository_service


REPOSITORY_RESTORE_REHEARSAL_SCHEMA_VERSION = "repository_restore_rehearsal@1"


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _path_digest(path: Path) -> str:
    return _digest_bytes(str(path.resolve(strict=True)).encode("utf-8"))


def _rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query).fetchall()]


def capture_repository_service_state(
    *,
    provider: SQLiteRepositoryProvider,
    roots: DurableRepositoryRootManager,
) -> dict[str, Any]:
    roots.preflight_roots()
    with provider.read() as scope:
        connection = scope.connection
        binding_ids = tuple(
            row["binding_id"]
            for row in connection.execute(
                """
                SELECT binding_id
                FROM project_repository_binding_versions
                ORDER BY project_id, binding_version
                """
            ).fetchall()
        )
        bindings = tuple(
            scope.repositories.project_repository_bindings.get(binding_id)
            for binding_id in binding_ids
        )
        if any(binding is None for binding in bindings):
            raise RuntimeError("repository binding disappeared during state capture")
        binding_records = [
            {
                "project_id": binding.project_id,
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "repository_id": binding.repository_id,
                "default_base_commit": binding.default_base_commit,
                "canonical_digest": binding.canonical_digest,
            }
            for binding in bindings
            if binding is not None
        ]
        active_bindings = _rows(
            connection,
            """
            SELECT project_id, binding_id, binding_version,
                   activation_generation
            FROM project_repository_active_bindings
            ORDER BY project_id
            """,
        )
        session_pins = _rows(
            connection,
            """
            SELECT session_id, project_id, binding_id, binding_version,
                   repository_id, resolved_base_commit,
                   binding_canonical_digest, mapping_receipt_id
            FROM session_repository_binding_pins
            ORDER BY session_id
            """,
        )
        credential_records = _rows(
            connection,
            """
            SELECT credential_id, binding_id, binding_version, repository_id,
                   session_id, agent_member_id, workspace_generation,
                   capability_lease_id, protocols_json, ref_classes_json,
                   claims_digest, issued_at, expires_at, revoked_at
            FROM repository_credential_issuance_records
            ORDER BY credential_id
            """,
        )
        private_namespaces = _rows(
            connection,
            """
            SELECT namespace_id, binding_id, binding_version, session_id,
                   agent_member_id, workspace_generation, namespace_prefix,
                   status, retention_deadline, opened_at, closed_at, retired_at
            FROM repository_private_namespace_records
            ORDER BY namespace_id
            """,
        )
        private_namespace_holds = _rows(
            connection,
            """
            SELECT hold_id, namespace_id, hold_kind, owner_ref,
                   created_at, released_at
            FROM repository_private_namespace_holds
            ORDER BY hold_id
            """,
        )
        namespace_retirements = _rows(
            connection,
            """
            SELECT receipt_id, namespace_id, binding_id, binding_version,
                   namespace_prefix, terminal_refs_json,
                   terminal_commits_json, receipt_digest
            FROM repository_private_namespace_retirement_receipts
            ORDER BY receipt_id
            """,
        )
        binding_retirements = _rows(
            connection,
            """
            SELECT receipt_id, binding_id, binding_version, project_id,
                   reference_audit_digest, receipt_digest
            FROM project_repository_binding_retirement_receipts
            ORDER BY receipt_id
            """,
        )

    repository_states: list[dict[str, Any]] = []
    seen_repository_ids: set[str] = set()
    for binding in bindings:
        if binding is None:
            raise RuntimeError("repository binding disappeared during state capture")
        roots.verify_pinned_commit(binding)
        if binding.repository_id in seen_repository_ids:
            continue
        seen_repository_ids.add(binding.repository_id)
        refs = roots.list_refs(binding, prefix="refs/")
        for _, commit in refs:
            roots.require_commit_object(binding, commit)
        repository_states.append(
            {
                "repository_id": binding.repository_id,
                "object_format": binding.object_format.value,
                "pre_receive_hook_digest": roots.verify_pre_receive_hook(binding),
                "refs": [
                    {"ref": ref_name, "commit": commit} for ref_name, commit in refs
                ],
            }
        )

    lfs_objects: list[dict[str, Any]] = []
    lfs_root = roots.settings.lfs_object_root.resolve(strict=True)
    for path in sorted(lfs_root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("repository LFS state contains a symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(lfs_root)
        if "incoming" in relative.parts:
            raise RuntimeError("repository LFS incoming area is not quiescent")
        if len(relative.parts) != 5 or relative.parts[1] != "objects":
            raise RuntimeError("repository LFS object layout is invalid")
        repository_id, _, first, second, oid = relative.parts
        if first != oid[:2] or second != oid[2:4]:
            raise RuntimeError("repository LFS object path does not match oid")
        content_digest = _digest_bytes(path.read_bytes())
        if content_digest != f"sha256:{oid}":
            raise RuntimeError("repository LFS object content does not match oid")
        lfs_objects.append(
            {
                "repository_id": repository_id,
                "oid": oid,
                "size": path.stat().st_size,
            }
        )

    payload = {
        "schema_version": "repository_service_state@1",
        "bindings": binding_records,
        "active_bindings": active_bindings,
        "session_pins": session_pins,
        "credential_records": credential_records,
        "private_namespaces": private_namespaces,
        "private_namespace_holds": private_namespace_holds,
        "namespace_retirements": namespace_retirements,
        "binding_retirements": binding_retirements,
        "repositories": repository_states,
        "lfs_objects": lfs_objects,
    }
    return {**payload, "state_digest": _digest_bytes(_canonical_json(payload))}


def _assert_regular_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"backup source contains symlink: {path.name}")
        if not path.is_dir() and not path.is_file():
            raise RuntimeError(f"backup source contains special file: {path.name}")


def _copy_sqlite_snapshot(source: Path, destination: Path) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    os.close(descriptor)
    with closing(
        sqlite3.connect(
            f"file:{source.resolve(strict=True).as_posix()}?mode=ro", uri=True
        )
    ) as source_connection:
        source_connection.execute("PRAGMA query_only = ON")
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.commit()
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())


def _copy_tree(source: Path, destination: Path) -> None:
    _assert_regular_tree(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)


def _tree_inventory(root: Path) -> dict[str, Any]:
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "digest": _digest_bytes(path.read_bytes()),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    payload = {"schema_version": "repository_backup_inventory@1", "files": files}
    return {**payload, "inventory_digest": _digest_bytes(_canonical_json(payload))}


def rehearse_repository_service_restore(
    *,
    settings: RepositoryServiceSettings,
    database_path: Path,
    boundary: RepositoryRootBoundary,
    receipt_id: str,
    created_at: str,
    created_by: str,
) -> dict[str, Any]:
    if not receipt_id:
        raise ValueError("receipt_id must not be empty")
    source_database = database_path.resolve(strict=True)
    source_provider = SQLiteRepositoryProvider(str(source_database))
    source_roots = DurableRepositoryRootManager(settings, boundary)
    source_preflight = preflight_repository_service(
        settings=settings,
        provider=source_provider,
        roots=source_roots,
    )
    before_restart = capture_repository_service_state(
        provider=source_provider,
        roots=source_roots,
    )

    restarted_provider = SQLiteRepositoryProvider(str(source_database))
    restarted_roots = DurableRepositoryRootManager(settings, boundary)
    restarted_preflight = preflight_repository_service(
        settings=settings,
        provider=restarted_provider,
        roots=restarted_roots,
    )
    after_restart = capture_repository_service_state(
        provider=restarted_provider,
        roots=restarted_roots,
    )
    if before_restart != after_restart:
        raise RuntimeError("repository state changed across provider reconstruction")

    rehearsal_parent = settings.backup_root / "repository-rehearsals"
    rehearsal_parent.mkdir(mode=0o700, exist_ok=True)
    rehearsal_root = rehearsal_parent / receipt_id
    rehearsal_root.mkdir(mode=0o700)
    snapshot_root = rehearsal_root / "snapshot"
    restored_root = rehearsal_root / "restored"
    snapshot_root.mkdir(mode=0o700)
    restored_root.mkdir(mode=0o700)

    snapshot_database = snapshot_root / "control-plane.sqlite3"
    _copy_sqlite_snapshot(source_database, snapshot_database)
    shutil.copy2(settings.binding_inventory_file, snapshot_root / "bindings.json")
    _copy_tree(settings.bare_repository_root, snapshot_root / "git")
    _copy_tree(settings.lfs_object_root, snapshot_root / "lfs")
    snapshot_inventory = _tree_inventory(snapshot_root)

    shutil.copy2(snapshot_database, restored_root / "control-plane.sqlite3")
    shutil.copy2(snapshot_root / "bindings.json", restored_root / "bindings.json")
    _copy_tree(snapshot_root / "git", restored_root / "git")
    _copy_tree(snapshot_root / "lfs", restored_root / "lfs")
    restored_backup_root = restored_root / "backup"
    restored_backup_root.mkdir(mode=0o700)

    restored_settings = replace(
        settings,
        bare_repository_root=restored_root / "git",
        lfs_object_root=restored_root / "lfs",
        backup_root=restored_backup_root,
        binding_inventory_file=restored_root / "bindings.json",
    )
    restored_provider = SQLiteRepositoryProvider(
        str(restored_root / "control-plane.sqlite3")
    )
    restored_roots = DurableRepositoryRootManager(restored_settings, boundary)
    restored_preflight = preflight_repository_service(
        settings=restored_settings,
        provider=restored_provider,
        roots=restored_roots,
    )
    restored_state = capture_repository_service_state(
        provider=restored_provider,
        roots=restored_roots,
    )
    if before_restart != restored_state:
        raise RuntimeError("restored repository state differs from source state")

    devices = {
        "bare_git": settings.bare_repository_root.stat().st_dev,
        "lfs_objects": settings.lfs_object_root.stat().st_dev,
        "backup": settings.backup_root.stat().st_dev,
    }
    failure_domain_separated = devices["backup"] not in {
        devices["bare_git"],
        devices["lfs_objects"],
    }
    payload = {
        "schema_version": REPOSITORY_RESTORE_REHEARSAL_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "acceptance_profile": "local_development",
        "rehearsal_class": (
            "separate_filesystem_logical_restore"
            if failure_domain_separated
            else "local_same_filesystem_logical_restore"
        ),
        "created_at": created_at,
        "created_by": created_by,
        "database_identity_digest": _path_digest(source_database),
        "rehearsal_root_digest": _path_digest(rehearsal_root),
        "source_state_digest": before_restart["state_digest"],
        "restarted_state_digest": after_restart["state_digest"],
        "restored_state_digest": restored_state["state_digest"],
        "source_preflight_inventory_digest": source_preflight.inventory_digest,
        "restarted_preflight_inventory_digest": (restarted_preflight.inventory_digest),
        "restored_preflight_inventory_digest": restored_preflight.inventory_digest,
        "backup_inventory_digest": snapshot_inventory["inventory_digest"],
        "failure_domain_devices": devices,
        "failure_domain_separated": failure_domain_separated,
        "verified_properties": [
            "provider_reconstruction_persistence",
            "logical_backup_restore_mechanics",
            "binding_ref_lfs_session_pin_acl_identity_stability",
        ],
        "not_verified": [
            "filesystem_loss_survival",
            "host_loss_survival",
            "offsite_disaster_recovery",
            "production_rpo_rto",
        ],
        "production_disaster_recovery_proven": False,
        "status": "passed_for_local_development",
    }
    return {**payload, "receipt_digest": _digest_bytes(_canonical_json(payload))}


__all__ = [
    "REPOSITORY_RESTORE_REHEARSAL_SCHEMA_VERSION",
    "capture_repository_service_state",
    "rehearse_repository_service_restore",
]
