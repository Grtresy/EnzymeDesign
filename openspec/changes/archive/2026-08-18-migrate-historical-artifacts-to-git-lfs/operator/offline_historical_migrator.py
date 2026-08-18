#!/usr/bin/env python3
"""Receipt-gated offline migration of frozen legacy bytes to immutable Git/LFS.

This executable is intentionally outside every runtime package and entry-point
manifest.  It must be invoked in a maintenance window with explicit paths and
an exact admission document.  It has no environment-derived defaults, force
mode, current-workspace adoption, or source deletion operation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Iterable
import unicodedata


SCHEMA = "historical_artifact_offline_migrator@1"
INVENTORY_SCHEMA = "historical_artifact_inventory_manifest@1"
RECEIPT_SCHEMA = "historical_artifact_migration_receipt@1"
PUBLIC_CONTRACT = "file_workspace_public@1"
HISTORICAL_PREFIX = "refs/openzyme/history/"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def operator_source_digests() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    names = (
        "offline_prepare_historical_schema.py",
        "offline_historical_inventory.py",
        "offline_historical_migrator.py",
        "offline_historical_verifier.py",
    )
    return {name: file_digest(root / name) for name in names}


def require_digest(value: object, name: str) -> str:
    text = str(value)
    if _DIGEST.fullmatch(text) is None:
        raise MigrationBlocked(f"{name} is not an exact SHA-256 digest")
    return text


class MigrationBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FrozenObject:
    object_id: str
    project_id: str
    session_id: str
    kind: str
    source_scheme: str
    source_root_id: str
    source_relative_path: str
    source_identity_digest: str
    expected_content_digest: str
    expected_size: int
    relative_path: str
    owner_identity_digest: str
    lineage_digest: str
    source_row_version_digest: str
    repository_binding_id: str
    repository_binding_version: int
    repository_base_commit: str
    byte_range_start: int = 0
    byte_range_length: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "FrozenObject":
        item = cls(**value)
        if (
            not item.object_id
            or not item.project_id
            or not item.session_id
            or item.source_scheme not in {"file", "canonical_tree", "engine_document"}
            or item.expected_size < 0
            or item.repository_binding_version < 1
            or _OID.fullmatch(item.repository_base_commit) is None
            or item.byte_range_start < 0
            or (item.byte_range_length is not None and item.byte_range_length < 0)
        ):
            raise MigrationBlocked("frozen source object is malformed")
        for name in (
            "source_identity_digest",
            "expected_content_digest",
            "owner_identity_digest",
            "lineage_digest",
            "source_row_version_digest",
        ):
            require_digest(getattr(item, name), name)
        normalize_target_path(item)
        return item

    @property
    def identity(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "kind": self.kind,
            "source_scheme": self.source_scheme,
            "source_root_id": self.source_root_id,
            "source_relative_path": self.source_relative_path,
            "source_identity_digest": self.source_identity_digest,
            "expected_content_digest": self.expected_content_digest,
            "expected_size": self.expected_size,
            "relative_path": self.relative_path,
            "owner_identity_digest": self.owner_identity_digest,
            "lineage_digest": self.lineage_digest,
            "source_row_version_digest": self.source_row_version_digest,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_base_commit": self.repository_base_commit,
            "byte_range_start": self.byte_range_start,
            "byte_range_length": self.byte_range_length,
        }


@dataclass(frozen=True, slots=True)
class FrozenReference:
    reference_id: str
    source_table: str
    source_primary_key: dict[str, object]
    source_field: str
    replacement_field: str
    object_id: str
    replacement_kind: str
    expected_replacement_ref: str | None
    source_row_payload: dict[str, object]
    source_row_version_digest: str

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "FrozenReference":
        item = cls(**value)
        if item.replacement_kind not in {
            "historical_ref",
            "revision_path_ref",
            "controlled_result",
            "scientific_deliverable_ref",
        }:
            raise MigrationBlocked("reference replacement kind is not typed")
        require_digest(item.source_row_version_digest, "source_row_version_digest")
        if digest(item.source_row_payload) != item.source_row_version_digest:
            raise MigrationBlocked("reference source row payload digest differs")
        if not item.source_primary_key or not item.replacement_field:
            raise MigrationBlocked("reference rewrite target is incomplete")
        if any(
            item.source_row_payload.get(key) != value
            for key, value in item.source_primary_key.items()
        ) or item.source_row_payload.get(item.source_field) != item.object_id:
            raise MigrationBlocked("reference source row identity differs")
        if item.replacement_kind == "historical_ref":
            if item.expected_replacement_ref is not None:
                raise MigrationBlocked(
                    "historical reference target must be created by the exact mapping"
                )
        elif not item.expected_replacement_ref:
            raise MigrationBlocked(
                "non-historical typed replacement must already name an exact target"
            )
        return item


def normalize_relative_path(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or "\\" in normalized
        or any(part in {"", ".", "..", ".git"} for part in path.parts)
    ):
        raise MigrationBlocked("path is not a safe normalized repository path")
    return path.as_posix()


def normalize_target_path(item: FrozenObject) -> str:
    session_hash = hashlib.sha256(item.session_id.encode()).hexdigest()[:16]
    object_hash = hashlib.sha256(item.object_id.encode()).hexdigest()[:24]
    return (
        f"legacy/{session_hash}/{object_hash}/"
        f"{normalize_relative_path(item.relative_path)}"
    )


class AllowlistedStorageReader:
    def __init__(self, roots: dict[str, Path]) -> None:
        if any(not path.is_absolute() or path.is_symlink() for path in roots.values()):
            raise MigrationBlocked("source roots must not be symlinks")
        self.roots = {name: path.resolve(strict=True) for name, path in roots.items()}
        if len(set(self.roots.values())) != len(self.roots):
            raise MigrationBlocked("multiple source identities resolve to one root")
        if any(
            not path.is_dir()
            or path == Path(path.anchor)
            or len(path.parts) < 3
            for path in self.roots.values()
        ):
            raise MigrationBlocked("source root is not an exact bounded directory")

    def read(self, item: FrozenObject) -> bytes:
        root = self.roots.get(item.source_root_id)
        if root is None:
            raise MigrationBlocked(f"source root {item.source_root_id!r} is not allowlisted")
        relative = normalize_relative_path(item.source_relative_path)
        candidate = root.joinpath(*PurePosixPath(relative).parts)
        if candidate.is_symlink():
            raise MigrationBlocked(f"source object {item.object_id!r} is a symlink")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise MigrationBlocked(f"source object {item.object_id!r} escaped its root")
        raw = resolved.read_bytes()
        start = item.byte_range_start
        end = None if item.byte_range_length is None else start + item.byte_range_length
        content = raw[start:end]
        if len(content) != item.expected_size or byte_digest(content) != item.expected_content_digest:
            raise MigrationBlocked(f"source bytes differ for {item.object_id!r}")
        identity = {
            "source_scheme": item.source_scheme,
            "root_id": item.source_root_id,
            "relative_path": relative,
            "file_size": len(raw),
            "slice_start": start,
            "slice_size": len(content),
            "slice_digest": byte_digest(content),
        }
        if digest(identity) != item.source_identity_digest:
            raise MigrationBlocked(f"source identity differs for {item.object_id!r}")
        return content


def observe_storage_snapshot(
    *,
    reader: AllowlistedStorageReader,
    objects: tuple[FrozenObject, ...],
) -> dict[str, object]:
    expected_paths = {
        (
            item.source_root_id,
            normalize_relative_path(item.source_relative_path),
        )
        for item in objects
    }
    observed_paths: set[tuple[str, str]] = set()
    physical_files = []
    for root_id, root in sorted(reader.roots.items()):
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise MigrationBlocked("legacy storage snapshot contains a symlink")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            observed_paths.add((root_id, relative))
            physical_files.append(
                {
                    "root_id": root_id,
                    "relative_path": relative,
                    "content_digest": file_digest(path),
                    "size": path.stat().st_size,
                }
            )
    if observed_paths != expected_paths:
        raise MigrationBlocked("legacy storage snapshot identity set drifted")
    for item in objects:
        reader.read(item)
    return {
        "schema": "historical_storage_snapshot_observation@1",
        "physical_files": physical_files,
        "object_source_identity_digests": sorted(
            item.source_identity_digest for item in objects
        ),
    }


def verify_frozen_source_snapshot(
    *,
    database: Path,
    inventory: dict[str, object],
    reader: AllowlistedStorageReader,
    objects: tuple[FrozenObject, ...],
) -> None:
    wal = database.with_name(database.name + "-wal")
    if wal.exists() and wal.stat().st_size != 0:
        raise MigrationBlocked("database WAL contains writes after writer freeze")
    if file_digest(database) != inventory.get("database_snapshot_digest"):
        raise MigrationBlocked("database snapshot drifted after writer freeze")
    observation = observe_storage_snapshot(reader=reader, objects=objects)
    if (
        observation != inventory.get("storage_snapshot_observation")
        or digest(observation) != inventory.get("storage_snapshot_digest")
    ):
        raise MigrationBlocked("storage snapshot drifted after writer freeze")


def sqlite_schema_inventory(connection: sqlite3.Connection) -> dict[str, object]:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    structures = [
        {
            "type": row[0],
            "name": row[1],
            "table": row[2],
            "sql_digest": digest(row[3] or ""),
        }
        for row in rows
    ]
    legacy_structures = [
        item
        for item in structures
        if any(
            token in str(item["name"]).lower() or token in str(item["table"]).lower()
            for token in ("artifact", "materialization", "staging")
        )
    ]
    return {
        "schema": "historical_schema_inventory@1",
        "structures": structures,
        "legacy_structures": legacy_structures,
        "structure_set_digest": digest(structures),
    }


def verify_admission(admission: dict[str, object], inventory: dict[str, object]) -> None:
    if admission.get("schema") != "historical_artifact_migration_admission@1":
        raise MigrationBlocked("migration admission schema is unsupported")
    required_true = (
        "maintenance_mode",
        "host_stopped",
        "runtime_consumers_stopped",
        "continuations_stopped",
        "execution_workers_stopped",
        "runner_callbacks_stopped",
        "backup_verified",
        "zero_legacy_public_surface",
        "aox_non_adoption_required",
    )
    if not all(admission.get(name) is True for name in required_true):
        raise MigrationBlocked("maintenance, backup, writer, or non-adoption gate is open")
    if admission.get("active_public_contract") != PUBLIC_CONTRACT:
        raise MigrationBlocked("file-workspace public epoch is not active")
    if any(
        int(admission.get(name, -1)) != 0
        for name in (
            "active_writer_count",
            "unsettled_external_effect_count",
            "post_freeze_write_count",
            "legacy_public_writer_count",
        )
    ):
        raise MigrationBlocked("writer or external-effect closure is incomplete")
    for name in (
        "public_cutover_completion_receipt_digest",
        "public_release_bundle_digest",
        "historical_schema_preparation_receipt_digest",
        "quiescence_receipt_digest",
        "writer_freeze_receipt_digest",
        "database_backup_digest",
        "storage_backup_digest",
        "database_snapshot_digest",
        "storage_snapshot_digest",
        "database_high_watermark_digest",
        "storage_generation_digest",
        "lfs_policy_digest",
        "operator_source_set_digest",
    ):
        require_digest(admission.get(name), name)
    if inventory.get("database_snapshot_digest") != admission["database_snapshot_digest"]:
        raise MigrationBlocked("inventory does not bind the admitted database snapshot")
    if inventory.get("storage_snapshot_digest") != admission["storage_snapshot_digest"]:
        raise MigrationBlocked("inventory does not bind the admitted storage snapshot")
    for name in (
        "writer_freeze_receipt_digest",
        "database_high_watermark_digest",
        "storage_generation_digest",
    ):
        if inventory.get(name) != admission.get(name):
            raise MigrationBlocked(f"inventory does not bind admitted {name}")
    if inventory.get("lfs_policy_digest") != admission.get("lfs_policy_digest"):
        raise MigrationBlocked("inventory does not bind the admitted Git LFS policy")
    if inventory.get("operator_source_set_digest") != admission.get(
        "operator_source_set_digest"
    ):
        raise MigrationBlocked("inventory does not bind the admitted operator source")


def load_inventory(path: Path) -> tuple[dict[str, object], tuple[FrozenObject, ...], tuple[FrozenReference, ...]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != INVENTORY_SCHEMA:
        raise MigrationBlocked("inventory manifest schema is unsupported")
    declared = value.get("inventory_digest")
    payload = {key: item for key, item in value.items() if key != "inventory_digest"}
    if declared != digest(payload):
        raise MigrationBlocked("inventory manifest digest mismatch")
    if value.get("blockers") != []:
        raise MigrationBlocked("inventory contains unresolved blockers")
    for name in (
        "database_snapshot_digest",
        "storage_snapshot_digest",
        "writer_freeze_receipt_digest",
        "database_high_watermark_digest",
        "storage_generation_digest",
        "schema_inventory_digest",
        "lfs_policy_digest",
        "operator_source_set_digest",
    ):
        require_digest(value.get(name), name)
    lfs_policy = value.get("lfs_policy")
    if (
        not isinstance(lfs_policy, dict)
        or lfs_policy.get("schema") != "git_lfs_content_policy@1"
        or digest(lfs_policy) != value.get("lfs_policy_digest")
    ):
        raise MigrationBlocked("inventory Git LFS policy identity differs")
    root_digests = value.get("source_root_path_digests")
    if not isinstance(root_digests, dict):
        raise MigrationBlocked("inventory source root identities are invalid")
    for root_id, root_digest in root_digests.items():
        if not root_id:
            raise MigrationBlocked("inventory source root identity is empty")
        require_digest(root_digest, "source_root_path_digest")
    sources = value.get("operator_source_digests")
    if (
        not isinstance(sources, dict)
        or sources != operator_source_digests()
        or digest(sources) != value.get("operator_source_set_digest")
    ):
        raise MigrationBlocked("inventory operator source identity differs")
    objects = tuple(FrozenObject.from_dict(item) for item in value.get("objects", []))
    references = tuple(
        FrozenReference.from_dict(item) for item in value.get("references", [])
    )
    if objects and not root_digests:
        raise MigrationBlocked("inventory source root identities are absent")
    if len({item.object_id for item in objects}) != len(objects):
        raise MigrationBlocked("inventory contains duplicate object identities")
    if len({item.reference_id for item in references}) != len(references):
        raise MigrationBlocked("inventory contains duplicate reference identities")
    object_ids = {item.object_id for item in objects}
    if {item.object_id for item in references} - object_ids:
        raise MigrationBlocked("inventory contains a reference to an unknown object")
    target_paths = [normalize_target_path(item).casefold() for item in objects]
    if len(target_paths) != len(set(target_paths)):
        raise MigrationBlocked("normalized target paths collide")
    expected_object_set = digest(sorted(digest(item.identity) for item in objects))
    expected_reference_set = digest(
        sorted(digest(asdict(item)) for item in references)
    )
    if (
        value.get("expected_object_set_digest") != expected_object_set
        or value.get("expected_reference_set_digest") != expected_reference_set
        or value.get("expected_byte_total") != sum(item.expected_size for item in objects)
    ):
        raise MigrationBlocked("inventory identity sets or byte total differ")
    return value, objects, references


def run_git(
    args: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> str:
    environment = {
        "PATH": os.environ["PATH"],
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        **(extra_env or {}),
    }
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed.returncode != 0:
        raise MigrationBlocked(
            f"Git command failed: git {' '.join(args)}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def exact_work_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise MigrationBlocked("working root must not be a symlink")
    resolved = path.resolve(strict=True)
    if (
        not resolved.is_dir()
        or resolved == Path(resolved.anchor)
        or len(resolved.parts) < 3
    ):
        raise MigrationBlocked("working root is not an exact bounded directory")
    return resolved


def make_work_directory(*, working_root: Path, prefix: str) -> Path:
    root = exact_work_root(working_root)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))


def migrate_unit(
    *,
    repository: Path,
    remote_name: str,
    inventory_digest: str,
    objects: tuple[FrozenObject, ...],
    reader: AllowlistedStorageReader,
    lfs_threshold: int,
    lfs_policy_digest: str,
    commit_timestamp: str,
    working_root: Path,
) -> dict[str, object]:
    if not objects:
        raise MigrationBlocked("migration unit cannot be empty")
    project_ids = {item.project_id for item in objects}
    session_ids = {item.session_id for item in objects}
    if len(project_ids) != 1 or len(session_ids) != 1:
        raise MigrationBlocked("migration unit crosses an owner boundary")
    identity_set_digest = digest(sorted(digest(item.identity) for item in objects))
    unit_id = "historical_unit_" + identity_set_digest[-32:]
    historical_ref = HISTORICAL_PREFIX + unit_id
    content_by_id = {item.object_id: reader.read(item) for item in objects}
    base_commits = {item.repository_base_commit for item in objects}
    if len(base_commits) != 1:
        raise MigrationBlocked("migration unit base commit is ambiguous")
    base_commit = base_commits.pop()
    if run_git(["rev-parse", f"{base_commit}^{{commit}}"], cwd=repository) != base_commit:
        raise MigrationBlocked("pinned historical base commit is unavailable")
    require_digest(lfs_policy_digest, "lfs_policy_digest")
    if lfs_threshold < 0:
        raise MigrationBlocked("Git LFS threshold is invalid")
    worktree = make_work_directory(
        working_root=working_root,
        prefix="openzyme-historical-unit-",
    )
    worktree_added = False
    try:
        run_git(["worktree", "add", "--detach", str(worktree), base_commit], cwd=repository)
        worktree_added = True
        for item in objects:
            target = worktree / normalize_target_path(item)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content_by_id[item.object_id])
        lfs_paths = tuple(
            normalize_target_path(item)
            for item in objects
            if item.expected_size >= lfs_threshold
        )
        if lfs_paths:
            run_git(["lfs", "install", "--local"], cwd=worktree)
        for path in lfs_paths:
            run_git(["lfs", "track", "--", path], cwd=worktree)
        manifest_payload = {
            "schema": "historical_migration_unit_manifest@1",
            "unit_id": unit_id,
            "inventory_digest": inventory_digest,
            "lfs_policy_digest": lfs_policy_digest,
            "identity_set_digest": identity_set_digest,
            "objects": [
                {
                    "object_id": item.object_id,
                    "path": normalize_target_path(item),
                    "content_digest": item.expected_content_digest,
                    "size": item.expected_size,
                    "owner_identity_digest": item.owner_identity_digest,
                    "lineage_digest": item.lineage_digest,
                    "storage": (
                        "git_lfs" if normalize_target_path(item) in lfs_paths else "git_blob"
                    ),
                    "eligibility": "historical_import_non_adoptable",
                }
                for item in objects
            ],
        }
        manifest = worktree / ".openzyme" / "historical" / f"{unit_id}.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(canonical_bytes({
            **manifest_payload,
            "manifest_digest": digest(manifest_payload),
        }))
        run_git(["add", "--all"], cwd=worktree)
        run_git(
            [
                "-c", "user.name=OpenZyme Historical Migrator",
                "-c", "user.email=openzyme-historical@invalid",
                "commit", "-m", f"archive: migrate frozen historical unit {unit_id}",
            ],
            cwd=worktree,
            extra_env={
                "GIT_AUTHOR_DATE": commit_timestamp,
                "GIT_COMMITTER_DATE": commit_timestamp,
            },
        )
        commit = run_git(["rev-parse", "HEAD"], cwd=worktree)
        tree = run_git(["rev-parse", "HEAD^{tree}"], cwd=worktree)
        manifest_path = manifest.relative_to(worktree).as_posix()
        manifest_blob_oid = run_git(
            ["rev-parse", f"HEAD:{manifest_path}"],
            cwd=worktree,
        )
        manifest_content_digest = byte_digest(manifest.read_bytes())
        target_objects = []
        for item in objects:
            path = normalize_target_path(item)
            storage = "git_lfs" if path in lfs_paths else "git_blob"
            if storage == "git_lfs":
                pointer = run_git(
                    ["cat-file", "blob", f"HEAD:{path}"],
                    cwd=worktree,
                )
                oid_line = next(
                    (line for line in pointer.splitlines() if line.startswith("oid sha256:")),
                    None,
                )
                size_line = next(
                    (line for line in pointer.splitlines() if line.startswith("size ")),
                    None,
                )
                if oid_line is None or size_line is None:
                    raise MigrationBlocked("Git LFS pointer is malformed")
                lfs_oid = "sha256:" + oid_line.removeprefix("oid sha256:")
                lfs_size = int(size_line.removeprefix("size "))
                if lfs_size != item.expected_size or lfs_oid != item.expected_content_digest:
                    raise MigrationBlocked("Git LFS pointer identity differs")
                git_blob_oid = None
            else:
                git_blob_oid = run_git(["rev-parse", f"HEAD:{path}"], cwd=worktree)
                lfs_oid = None
                lfs_size = None
            target_objects.append(
                {
                    "object_id": item.object_id,
                    "path": path,
                    "content_digest": item.expected_content_digest,
                    "size": item.expected_size,
                    "owner_identity_digest": item.owner_identity_digest,
                    "lineage_digest": item.lineage_digest,
                    "storage": storage,
                    "git_blob_oid": git_blob_oid,
                    "lfs_oid": lfs_oid,
                    "lfs_size": lfs_size,
                    "repository_binding_id": item.repository_binding_id,
                    "repository_binding_version": item.repository_binding_version,
                }
            )
        remote_matches = run_git(
            ["ls-remote", "--refs", remote_name, historical_ref],
            cwd=worktree,
        )
        if remote_matches:
            fields = remote_matches.split()
            if len(fields) != 2 or fields[0] != commit or fields[1] != historical_ref:
                raise MigrationBlocked("immutable historical ref already has another target")
        else:
            run_git(["push", remote_name, f"{commit}:{historical_ref}"], cwd=worktree)
    finally:
        if worktree_added:
            run_git(["worktree", "remove", "--force", str(worktree)], cwd=repository)
        if worktree.exists():
            shutil.rmtree(worktree)
    return {
        "schema": "historical_migration_unit_target@1",
        "unit_id": unit_id,
        "historical_ref": historical_ref,
        "commit": commit,
        "tree": tree,
        "lfs_policy_digest": lfs_policy_digest,
        "unit_manifest_path": manifest_path,
        "unit_manifest_blob_oid": manifest_blob_oid,
        "unit_manifest_content_digest": manifest_content_digest,
        "identity_set_digest": identity_set_digest,
        "byte_total": sum(item.expected_size for item in objects),
        "objects": target_objects,
    }


def fresh_readback(
    *,
    remote_url: str,
    target: dict[str, object],
    working_root: Path,
) -> dict[str, object]:
    clone = make_work_directory(
        working_root=working_root,
        prefix="openzyme-historical-readback-",
    )
    try:
        run_git(["init"], cwd=clone)
        run_git(["lfs", "install", "--local"], cwd=clone)
        run_git(["remote", "add", "origin", remote_url], cwd=clone)
        run_git(["fetch", "--no-tags", "origin", str(target["historical_ref"])], cwd=clone)
        fetched = run_git(["rev-parse", "FETCH_HEAD"], cwd=clone)
        if fetched != target["commit"]:
            raise MigrationBlocked("fresh fetch returned a different historical commit")
        run_git(["checkout", "--detach", fetched], cwd=clone)
        run_git(["lfs", "pull", "origin"], cwd=clone)
        manifest_path = normalize_relative_path(str(target["unit_manifest_path"]))
        manifest_bytes = (clone / manifest_path).read_bytes()
        if (
            byte_digest(manifest_bytes) != target.get("unit_manifest_content_digest")
            or run_git(["rev-parse", f"HEAD:{manifest_path}"], cwd=clone)
            != target.get("unit_manifest_blob_oid")
        ):
            raise MigrationBlocked("fresh readback unit manifest differs")
        manifest = json.loads(manifest_bytes)
        manifest_declared = manifest.get("manifest_digest")
        manifest_payload = {
            key: value for key, value in manifest.items() if key != "manifest_digest"
        }
        if (
            manifest_declared != digest(manifest_payload)
            or manifest_payload.get("unit_id") != target.get("unit_id")
            or manifest_payload.get("identity_set_digest")
            != target.get("identity_set_digest")
            or manifest_payload.get("lfs_policy_digest")
            != target.get("lfs_policy_digest")
        ):
            raise MigrationBlocked("fresh readback unit manifest identity differs")
        observations = []
        for item in target["objects"]:
            if not isinstance(item, dict):
                raise MigrationBlocked("target object manifest is malformed")
            content = (clone / str(item["path"])).read_bytes()
            observation = {
                "object_id": item["object_id"],
                "path": item["path"],
                "content_digest": byte_digest(content),
                "size": len(content),
            }
            if (
                observation["content_digest"] != item["content_digest"]
                or observation["size"] != item["size"]
            ):
                raise MigrationBlocked("fresh readback bytes differ")
            if item.get("storage") == "git_blob":
                observed_oid = run_git(
                    ["rev-parse", f"HEAD:{item['path']}"],
                    cwd=clone,
                )
                if observed_oid != item.get("git_blob_oid"):
                    raise MigrationBlocked("fresh readback Git blob OID differs")
            elif (
                item.get("storage") != "git_lfs"
                or item.get("lfs_oid") != item.get("content_digest")
                or item.get("lfs_size") != item.get("size")
            ):
                raise MigrationBlocked("fresh readback Git LFS identity differs")
            observations.append(observation)
        payload = {
            "schema": "historical_target_fresh_readback@1",
            "historical_ref": target["historical_ref"],
            "commit": fetched,
            "tree": run_git(["rev-parse", "HEAD^{tree}"], cwd=clone),
            "unit_manifest_content_digest": byte_digest(manifest_bytes),
            "observations": observations,
        }
        if payload["tree"] != target["tree"]:
            raise MigrationBlocked("fresh readback tree differs")
        return {**payload, "readback_digest": digest(payload)}
    finally:
        shutil.rmtree(clone)


def verify_source_rows(
    connection: sqlite3.Connection,
    objects: Iterable[FrozenObject],
) -> None:
    for item in objects:
        row = connection.execute(
            "SELECT * FROM session_artifact_records WHERE artifact_id = ?",
            (item.object_id,),
        ).fetchone()
        if row is None:
            raise MigrationBlocked(f"source row {item.object_id!r} disappeared")
        row_payload = {key: row[key] for key in row.keys()}
        if digest(row_payload) != item.source_row_version_digest:
            raise MigrationBlocked(f"source row {item.object_id!r} changed after freeze")


def persist_mappings_and_rewrites(
    *,
    connection: sqlite3.Connection,
    inventory: dict[str, object],
    objects: tuple[FrozenObject, ...],
    references: tuple[FrozenReference, ...],
    targets: tuple[dict[str, object], ...],
    readbacks: tuple[dict[str, object], ...],
    pending_receipt_path: Path,
) -> dict[str, object]:
    verify_source_rows(connection, objects)
    target_by_object = {
        str(item["object_id"]): (target, item)
        for target in targets
        for item in target["objects"]
        if isinstance(item, dict)
    }
    if set(target_by_object) != {item.object_id for item in objects}:
        raise MigrationBlocked("target mapping identity set differs")
    mapping_rows = []
    for source in objects:
        target, target_item = target_by_object[source.object_id]
        payload = {
            "historical_ref_id": "historical_ref_" + digest(source.identity)[-32:],
            "original_id": source.object_id,
            "project_id": source.project_id,
            "session_id": source.session_id,
            "kind": source.kind,
            "content_digest": source.expected_content_digest,
            "size": source.expected_size,
            "owner_identity_digest": source.owner_identity_digest,
            "lineage_digest": source.lineage_digest,
            "source_identity_digest": source.source_identity_digest,
            "unit_id": target["unit_id"],
            "historical_ref": target["historical_ref"],
            "commit": target["commit"],
            "tree": target["tree"],
            "path": target_item["path"],
            "storage": target_item["storage"],
            "git_blob_oid": target_item["git_blob_oid"],
            "lfs_oid": target_item["lfs_oid"],
            "lfs_size": target_item["lfs_size"],
            "repository_binding_id": source.repository_binding_id,
            "repository_binding_version": source.repository_binding_version,
            "eligibility": "historical_import_non_adoptable",
        }
        supersession_payload = {
            "original_id": source.object_id,
            "decision": "historical_import_non_adoptable",
            "current_adoption_authorized": False,
        }
        payload["supersession_decision_digest"] = digest(supersession_payload)
        mapping_rows.append({**payload, "mapping_digest": digest(payload)})
    rewrite_rows = []
    mapping_by_original = {item["original_id"]: item for item in mapping_rows}
    for reference in references:
        mapping = mapping_by_original[reference.object_id]
        replacement_ref = (
            mapping["historical_ref_id"]
            if reference.replacement_kind == "historical_ref"
            else reference.expected_replacement_ref
        )
        if not replacement_ref:
            raise MigrationBlocked("typed replacement identity is absent")
        payload = {
            "reference_id": reference.reference_id,
            "source_table": reference.source_table,
            "source_primary_key": reference.source_primary_key,
            "source_field": reference.source_field,
            "replacement_field": reference.replacement_field,
            "original_id": reference.object_id,
            "replacement_kind": reference.replacement_kind,
            "replacement_ref": replacement_ref,
            "replacement_identity_digest": digest(
                {
                    "kind": reference.replacement_kind,
                    "ref": replacement_ref,
                }
            ),
            "source_row_version_digest": reference.source_row_version_digest,
        }
        rewrite_rows.append({**payload, "rewrite_digest": digest(payload)})
    readback_by_ref = {item["historical_ref"]: item for item in readbacks}
    unit_receipts = []
    for target in targets:
        unit_mappings = [
            item for item in mapping_rows if item["unit_id"] == target["unit_id"]
        ]
        unit_rewrites = [
            item
            for item in rewrite_rows
            if mapping_by_original[item["original_id"]]["unit_id"]
            == target["unit_id"]
        ]
        readback = readback_by_ref[target["historical_ref"]]
        unit_payload = {
            "migration_unit_id": target["unit_id"],
            "inventory_digest": inventory["inventory_digest"],
            "expected_identity_set_digest": target["identity_set_digest"],
            "migrated_identity_set_digest": target["identity_set_digest"],
            "target_ref": target["historical_ref"],
            "target_commit": target["commit"],
            "target_tree": target["tree"],
            "lfs_closure_digest": readback["readback_digest"],
            "mapping_digest": digest(unit_mappings),
            "reference_rewrite_digest": digest(unit_rewrites),
            "actual_byte_total": target["byte_total"],
            "zero_post_freeze_write": True,
            "non_adoption_digest": digest(
                sorted(
                    str(item["supersession_decision_digest"])
                    for item in unit_mappings
                )
            ),
        }
        unit_digest = digest(unit_payload)
        unit_receipts.append(
            {
                **unit_payload,
                "receipt_id": "historical_unit_receipt_" + unit_digest[-32:],
                "receipt_digest": unit_digest,
            }
        )
    receipt_payload = {
        "schema": RECEIPT_SCHEMA,
        "inventory_digest": inventory["inventory_digest"],
        "database_snapshot_digest": inventory["database_snapshot_digest"],
        "storage_snapshot_digest": inventory["storage_snapshot_digest"],
        "expected_identity_set_digest": inventory["expected_object_set_digest"],
        "migrated_identity_set_digest": digest(
            sorted(digest(item.identity) for item in objects)
        ),
        "expected_reference_set_digest": inventory["expected_reference_set_digest"],
        "migrated_reference_set_digest": digest(
            sorted(digest(asdict(item)) for item in references)
        ),
        "rewritten_reference_set_digest": digest(
            sorted(item["rewrite_digest"] for item in rewrite_rows)
        ),
        "target_set_digest": digest(targets),
        "readback_set_digest": digest(readbacks),
        "mapping_set_digest": digest(
            sorted(item["mapping_digest"] for item in mapping_rows)
        ),
        "unit_receipt_set_digest": digest(
            sorted(item["receipt_digest"] for item in unit_receipts)
        ),
        "expected_byte_total": inventory["expected_byte_total"],
        "migrated_byte_total": sum(item.expected_size for item in objects),
        "unresolved_reference_count": 0,
        "post_freeze_write_count": 0,
        "negative_item_count": 0,
        "aox_non_adoption_proven": True,
        "non_adoption_set_digest": digest(
            sorted(
                str(item["supersession_decision_digest"])
                for item in mapping_rows
            )
        ),
        "lfs_policy_digest": inventory["lfs_policy_digest"],
        "operator_source_digests": inventory["operator_source_digests"],
        "operator_source_set_digest": inventory["operator_source_set_digest"],
        "source_preserved": True,
        "storage_snapshot_observation": inventory[
            "storage_snapshot_observation"
        ],
        "source_root_path_digests": inventory["source_root_path_digests"],
        "frozen_objects": [asdict(item) for item in objects],
        "frozen_references": [asdict(item) for item in references],
        "objects": mapping_rows,
        "reference_rewrites": rewrite_rows,
        "targets": list(targets),
        "readbacks": list(readbacks),
        "unit_receipts": unit_receipts,
    }
    if (
        receipt_payload["expected_identity_set_digest"]
        != receipt_payload["migrated_identity_set_digest"]
        or receipt_payload["expected_byte_total"]
        != receipt_payload["migrated_byte_total"]
        or receipt_payload["expected_reference_set_digest"]
        != receipt_payload["migrated_reference_set_digest"]
    ):
        raise MigrationBlocked("global identity or byte set differs")
    receipt = {**receipt_payload, "receipt_digest": digest(receipt_payload)}
    receipt_bytes = canonical_bytes(receipt)
    if pending_receipt_path.exists():
        if pending_receipt_path.read_bytes() != receipt_bytes:
            raise MigrationBlocked("pending external receipt identity differs")
    else:
        with pending_receipt_path.open("xb") as handle:
            handle.write(receipt_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    connection.execute("BEGIN IMMEDIATE")
    try:
        verify_source_rows(connection, objects)
        inventory_id = "historical_inventory_" + str(inventory["inventory_digest"])[-32:]
        connection.execute(
            """
            INSERT INTO historical_artifact_inventory_records (
                inventory_id, database_snapshot_digest, storage_snapshot_digest,
                writer_freeze_receipt_digest, database_high_watermark,
                storage_generation, expected_row_set_digest,
                expected_object_set_digest, expected_reference_set_digest,
                expected_byte_total, blocker_count, created_at, inventory_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, datetime('now'), ?)
            """,
            (
                inventory_id,
                inventory["database_snapshot_digest"],
                inventory["storage_snapshot_digest"],
                inventory["writer_freeze_receipt_digest"],
                inventory["database_high_watermark_digest"],
                inventory["storage_generation_digest"],
                inventory["expected_object_set_digest"],
                inventory["expected_object_set_digest"],
                inventory["expected_reference_set_digest"],
                inventory["expected_byte_total"],
                inventory["inventory_digest"],
            ),
        )
        for ordinal, target in enumerate(targets, start=1):
            unit_objects = [
                item for item in objects if item.object_id in {
                    str(value["object_id"])
                    for value in target["objects"]
                    if isinstance(value, dict)
                }
            ]
            binding_ids = {
                (item.repository_binding_id, item.repository_binding_version)
                for item in unit_objects
            }
            if len(binding_ids) != 1:
                raise MigrationBlocked("migration unit repository binding is ambiguous")
            binding_id, binding_version = binding_ids.pop()
            connection.execute(
                """
                INSERT INTO historical_artifact_migration_unit_records (
                    migration_unit_id, inventory_id, project_id, session_id,
                    repository_binding_id, repository_binding_version,
                    historical_namespace, expected_identity_set_digest,
                    expected_byte_total, unit_ordinal, unit_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target["unit_id"], inventory_id, unit_objects[0].project_id,
                    unit_objects[0].session_id, binding_id, binding_version,
                    target["historical_ref"], target["identity_set_digest"],
                    target["byte_total"], ordinal, digest(target),
                ),
            )
        for mapping in mapping_rows:
            verification_digest = readback_by_ref[mapping["historical_ref"]][
                "readback_digest"
            ]
            ref_payload = {
                "schema_version": "historical_artifact_ref@1",
                "historical_ref_id": mapping["historical_ref_id"],
                "original_artifact_id": mapping["original_id"],
                "original_kind": mapping["kind"],
                "original_digest": mapping["content_digest"],
                "original_size": mapping["size"],
                "project_id": mapping["project_id"],
                "session_id": mapping["session_id"],
                "owner_identity_digest": mapping["owner_identity_digest"],
                "lineage_digest": mapping["lineage_digest"],
                "source_snapshot_digest": mapping["source_identity_digest"],
                "migration_unit_id": mapping["unit_id"],
                "repository_binding_id": mapping["repository_binding_id"],
                "repository_binding_version": mapping["repository_binding_version"],
                "historical_ref": mapping["historical_ref"],
                "historical_commit": mapping["commit"],
                "historical_tree": mapping["tree"],
                "path": mapping["path"],
                "storage": mapping["storage"],
                "git_blob_oid": mapping["git_blob_oid"],
                "lfs_oid": mapping["lfs_oid"],
                "lfs_size": mapping["lfs_size"],
                "verification_digest": verification_digest,
                "eligibility": "historical_import_non_adoptable",
                "supersession_decision_digest": mapping[
                    "supersession_decision_digest"
                ],
                "created_at": inventory["created_at"],
            }
            connection.execute(
                """
                INSERT INTO historical_artifact_ref_records (
                    historical_ref_id, original_artifact_id, original_kind,
                    original_digest, original_size, project_id, session_id,
                    owner_identity_digest, lineage_digest, source_snapshot_digest,
                    migration_unit_id, repository_binding_id,
                    repository_binding_version, historical_ref, historical_commit,
                    historical_tree, repository_path, storage, git_blob_oid,
                    lfs_oid, lfs_size, verification_digest, eligibility,
                    supersession_decision_digest, created_at, ref_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mapping["historical_ref_id"], mapping["original_id"], mapping["kind"],
                    mapping["content_digest"], mapping["size"], mapping["project_id"],
                    mapping["session_id"], mapping["owner_identity_digest"],
                    mapping["lineage_digest"], mapping["source_identity_digest"],
                    mapping["unit_id"], mapping["repository_binding_id"],
                    mapping["repository_binding_version"], mapping["historical_ref"],
                    mapping["commit"], mapping["tree"], mapping["path"],
                    mapping["storage"], mapping["git_blob_oid"], mapping["lfs_oid"],
                    mapping["lfs_size"], verification_digest,
                    "historical_import_non_adoptable",
                    ref_payload["supersession_decision_digest"], inventory["created_at"],
                    digest(ref_payload),
                ),
            )
        for rewrite in rewrite_rows:
            reference = next(
                item for item in references if item.reference_id == rewrite["reference_id"]
            )
            where = " AND ".join(
                f'"{key.replace(chr(34), chr(34) * 2)}" = ?'
                for key in reference.source_primary_key
            )
            current = connection.execute(
                f'SELECT * FROM "{reference.source_table.replace(chr(34), chr(34) * 2)}" WHERE {where}',
                tuple(reference.source_primary_key.values()),
            ).fetchone()
            if current is None or digest({key: current[key] for key in current.keys()}) != reference.source_row_version_digest:
                raise MigrationBlocked("reference row changed after freeze")
            connection.execute(
                f'UPDATE "{reference.source_table.replace(chr(34), chr(34) * 2)}" '
                f'SET "{reference.replacement_field.replace(chr(34), chr(34) * 2)}" = ? WHERE {where}',
                (rewrite["replacement_ref"], *reference.source_primary_key.values()),
            )
            connection.execute(
                """
                INSERT INTO historical_artifact_reference_rewrite_records (
                    rewrite_id, migration_unit_id, source_table,
                    source_row_identity_digest, source_field, original_artifact_id,
                    replacement_kind, replacement_ref, source_version_digest,
                    rewrite_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    rewrite["reference_id"], mapping_by_original[rewrite["original_id"]]["unit_id"],
                    rewrite["source_table"], digest(rewrite["source_primary_key"]),
                    rewrite["source_field"], rewrite["original_id"],
                    rewrite["replacement_kind"], rewrite["replacement_ref"],
                    rewrite["source_row_version_digest"], rewrite["rewrite_digest"],
                ),
            )
        for unit_receipt in unit_receipts:
            connection.execute(
                """
                INSERT INTO historical_artifact_migration_unit_receipts (
                    receipt_id, migration_unit_id, inventory_digest,
                    expected_identity_set_digest, migrated_identity_set_digest,
                    target_ref, target_commit, target_tree, lfs_closure_digest,
                    mapping_digest, reference_rewrite_digest, actual_byte_total,
                    zero_post_freeze_write, non_adoption_digest, created_at,
                    receipt_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'), ?)
                """,
                (
                    unit_receipt["receipt_id"],
                    unit_receipt["migration_unit_id"],
                    unit_receipt["inventory_digest"],
                    unit_receipt["expected_identity_set_digest"],
                    unit_receipt["migrated_identity_set_digest"],
                    unit_receipt["target_ref"],
                    unit_receipt["target_commit"],
                    unit_receipt["target_tree"],
                    unit_receipt["lfs_closure_digest"],
                    unit_receipt["mapping_digest"],
                    unit_receipt["reference_rewrite_digest"],
                    unit_receipt["actual_byte_total"],
                    unit_receipt["non_adoption_digest"],
                    unit_receipt["receipt_digest"],
                ),
            )
        connection.execute(
            """
            INSERT INTO historical_artifact_migration_global_receipts (
                receipt_id, inventory_digest, expected_global_identity_set_digest,
                migrated_global_identity_set_digest, unit_receipt_set_digest,
                mapping_set_digest, reference_rewrite_set_digest,
                git_lfs_closure_set_digest, non_adoption_set_digest,
                negative_item_count, source_preserved, created_at, receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, datetime('now'), ?)
            """,
            (
                "historical_global_" + receipt["receipt_digest"][-32:],
                inventory["inventory_digest"],
                receipt_payload["expected_identity_set_digest"],
                receipt_payload["migrated_identity_set_digest"],
                receipt_payload["unit_receipt_set_digest"],
                receipt_payload["mapping_set_digest"],
                receipt_payload["rewritten_reference_set_digest"],
                receipt_payload["readback_set_digest"],
                receipt_payload["non_adoption_set_digest"],
                receipt["receipt_digest"],
            ),
        )
        connection.commit()
    except (sqlite3.Error, MigrationBlocked):
        connection.rollback()
        raise
    return receipt


def verify_completed_replay(
    *,
    connection: sqlite3.Connection,
    receipt_path: Path,
    inventory: dict[str, object],
    objects: tuple[FrozenObject, ...],
    references: tuple[FrozenReference, ...],
    reader: AllowlistedStorageReader,
    remote_url: str,
    working_root: Path,
) -> dict[str, object] | None:
    pending_receipt_path = receipt_path.with_name(receipt_path.name + ".pending")
    try:
        stored = connection.execute(
            """
            SELECT * FROM historical_artifact_migration_global_receipts
            WHERE inventory_digest = ?
            """,
            (inventory["inventory_digest"],),
        ).fetchall()
    except sqlite3.OperationalError:
        stored = []
    candidate_path = (
        receipt_path
        if receipt_path.exists()
        else pending_receipt_path
        if pending_receipt_path.exists()
        else None
    )
    if candidate_path is None:
        if stored:
            raise MigrationBlocked(
                "completed migration state exists but its exact external receipt is unavailable"
            )
        return None
    receipt = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not stored:
        return None
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise MigrationBlocked("existing migration receipt schema is unsupported")
    declared = receipt.get("receipt_digest")
    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if (
        declared != digest(payload)
        or receipt.get("inventory_digest") != inventory["inventory_digest"]
        or len(stored) != 1
        or stored[0]["receipt_digest"] != declared
        or stored[0]["unit_receipt_set_digest"]
        != receipt.get("unit_receipt_set_digest")
        or stored[0]["mapping_set_digest"] != receipt.get("mapping_set_digest")
        or stored[0]["reference_rewrite_set_digest"]
        != receipt.get("rewritten_reference_set_digest")
        or stored[0]["git_lfs_closure_set_digest"]
        != receipt.get("readback_set_digest")
    ):
        raise MigrationBlocked("completed migration replay identity differs")
    verify_source_rows(connection, objects)
    for item in objects:
        reader.read(item)
    rewrites = {
        str(item["reference_id"]): item
        for item in receipt.get("reference_rewrites", [])
        if isinstance(item, dict)
    }
    if set(rewrites) != {item.reference_id for item in references}:
        raise MigrationBlocked("completed migration rewrite identity set differs")
    for reference in references:
        where = " AND ".join(
            f'"{key.replace(chr(34), chr(34) * 2)}" = ?'
            for key in reference.source_primary_key
        )
        row = connection.execute(
            f'SELECT * FROM "{reference.source_table.replace(chr(34), chr(34) * 2)}" '
            f"WHERE {where}",
            tuple(reference.source_primary_key.values()),
        ).fetchone()
        expected_row = dict(reference.source_row_payload)
        expected_row[reference.replacement_field] = rewrites[reference.reference_id][
            "replacement_ref"
        ]
        if row is None or {key: row[key] for key in row.keys()} != expected_row:
            raise MigrationBlocked("completed migration typed rewrite drifted")
    targets = receipt.get("targets")
    if not isinstance(targets, list) or any(
        not isinstance(target, dict) for target in targets
    ):
        raise MigrationBlocked("completed migration target set is malformed")
    readbacks = tuple(
        fresh_readback(
            remote_url=remote_url,
            target=target,
            working_root=working_root,
        )
        for target in targets
        if isinstance(target, dict)
    )
    if digest(readbacks) != receipt.get("readback_set_digest"):
        raise MigrationBlocked("completed migration empty-cache readback drifted")
    if candidate_path == pending_receipt_path:
        os.replace(pending_receipt_path, receipt_path)
    return receipt


def execute(args: argparse.Namespace) -> None:
    for name in (
        "database",
        "inventory",
        "admission",
        "repository",
        "receipt",
        "working_root",
    ):
        path = Path(getattr(args, name))
        if not path.is_absolute():
            raise MigrationBlocked(f"{name} must be an explicit absolute path")
    if not args.receipt.parent.resolve(strict=True).is_dir():
        raise MigrationBlocked("receipt parent is unavailable")
    inventory, objects, references = load_inventory(args.inventory)
    admission = json.loads(args.admission.read_text(encoding="utf-8"))
    verify_admission(admission, inventory)
    connection = sqlite3.connect(f"file:{args.database}?mode=rw", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        schema_inventory = sqlite_schema_inventory(connection)
        if schema_inventory["structure_set_digest"] != inventory["schema_inventory_digest"]:
            raise MigrationBlocked("database schema differs from frozen inventory")
        roots = {}
        for value in args.source_root:
            root_id, separator, path = value.partition("=")
            if not separator or not root_id or not path:
                raise MigrationBlocked("source roots must use ROOT_ID=/absolute/path")
            if root_id in roots:
                raise MigrationBlocked("source root mapping is duplicated")
            roots[root_id] = Path(path)
        reader = AllowlistedStorageReader(roots)
        if {
            root_id: digest(str(path))
            for root_id, path in sorted(reader.roots.items())
        } != inventory["source_root_path_digests"]:
            raise MigrationBlocked("source root path identity set differs")
        working_root = exact_work_root(args.working_root)
        if run_git(["remote", "get-url", args.remote_name], cwd=args.repository) != str(
            args.remote_url
        ):
            raise MigrationBlocked("repository remote identity differs from remote_url")
        lfs_policy = inventory.get("lfs_policy")
        if not isinstance(lfs_policy, dict):
            raise MigrationBlocked("frozen Git LFS policy is absent")
        lfs_threshold = lfs_policy.get("threshold_bytes")
        if not isinstance(lfs_threshold, int) or lfs_threshold < 0:
            raise MigrationBlocked("frozen Git LFS threshold is invalid")
        replay = verify_completed_replay(
            connection=connection,
            receipt_path=args.receipt,
            inventory=inventory,
            objects=objects,
            references=references,
            reader=reader,
            remote_url=args.remote_url,
            working_root=working_root,
        )
        if replay is not None:
            return
        verify_frozen_source_snapshot(
            database=args.database,
            inventory=inventory,
            reader=reader,
            objects=objects,
        )
        by_owner: dict[tuple[str, str], list[FrozenObject]] = {}
        for item in objects:
            by_owner.setdefault((item.project_id, item.session_id), []).append(item)
        targets_list = []
        for _, unit in sorted(by_owner.items()):
            verify_frozen_source_snapshot(
                database=args.database,
                inventory=inventory,
                reader=reader,
                objects=objects,
            )
            targets_list.append(
                migrate_unit(
                repository=args.repository,
                remote_name=args.remote_name,
                inventory_digest=str(inventory["inventory_digest"]),
                objects=tuple(sorted(unit, key=lambda item: item.object_id)),
                reader=reader,
                lfs_threshold=lfs_threshold,
                lfs_policy_digest=str(inventory["lfs_policy_digest"]),
                commit_timestamp=str(inventory["created_at"]),
                working_root=working_root,
                )
            )
        targets = tuple(targets_list)
        readbacks = tuple(
            fresh_readback(
                remote_url=args.remote_url,
                target=target,
                working_root=working_root,
            )
            for target in targets
        )
        verify_frozen_source_snapshot(
            database=args.database,
            inventory=inventory,
            reader=reader,
            objects=objects,
        )
        pending_receipt_path = args.receipt.with_name(args.receipt.name + ".pending")
        persist_mappings_and_rewrites(
            connection=connection,
            inventory=inventory,
            objects=objects,
            references=references,
            targets=targets,
            readbacks=readbacks,
            pending_receipt_path=pending_receipt_path,
        )
    finally:
        connection.close()
    os.replace(pending_receipt_path, args.receipt)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--database", required=True, type=Path)
    value.add_argument("--inventory", required=True, type=Path)
    value.add_argument("--admission", required=True, type=Path)
    value.add_argument("--repository", required=True, type=Path)
    value.add_argument("--remote-name", required=True)
    value.add_argument("--remote-url", required=True)
    value.add_argument("--source-root", action="append", default=[])
    value.add_argument("--receipt", required=True, type=Path)
    value.add_argument("--working-root", required=True, type=Path)
    return value


if __name__ == "__main__":
    execute(parser().parse_args())
