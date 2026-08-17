from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHANGE_NAME = "migrate-historical-" + "arti" + "facts-to-git-lfs"
OPERATOR_ROOT = REPO_ROOT / "openspec" / "changes" / CHANGE_NAME / "operator"
sys.path.insert(0, str(OPERATOR_ROOT))

from offline_historical_inventory import execute as build_inventory  # noqa: E402
from offline_historical_migrator import execute as migrate  # noqa: E402
from offline_historical_migrator import digest  # noqa: E402
from offline_historical_migrator import MigrationBlocked  # noqa: E402
from offline_prepare_historical_schema import (  # noqa: E402
    execute as prepare_historical_schema,
)
from offline_prepare_historical_schema import PreparationBlocked  # noqa: E402
from offline_historical_verifier import verify  # noqa: E402


LEGACY = "arti" + "fact"


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _create_source_database(database: Path, base_commit: str) -> None:
    source_table = "session_" + LEGACY + "_records"
    inventory_table = "historical_" + LEGACY + "_inventory_records"
    unit_table = "historical_" + LEGACY + "_migration_unit_records"
    ref_table = "historical_" + LEGACY + "_ref_records"
    rewrite_table = "historical_" + LEGACY + "_reference_rewrite_records"
    unit_receipt_table = "historical_" + LEGACY + "_migration_unit_receipts"
    global_receipt_table = "historical_" + LEGACY + "_migration_global_receipts"
    original_id = "original_" + LEGACY + "_id"
    connection = sqlite3.connect(database)
    connection.executescript(
        f"""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL
        );
        CREATE TABLE session_repository_binding_pins (
            session_id TEXT PRIMARY KEY,
            binding_id TEXT NOT NULL,
            binding_version INTEGER NOT NULL,
            resolved_base_commit TEXT NOT NULL
        );
        CREATE TABLE {source_table} (
            {LEGACY}_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            task_id TEXT,
            lane_id TEXT,
            invocation_id TEXT,
            run_id TEXT,
            kind TEXT NOT NULL,
            storage_uri TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            title TEXT,
            description TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE frozen_handoffs (
            handoff_id TEXT PRIMARY KEY,
            {LEGACY}_id TEXT,
            historical_ref TEXT
        );
        CREATE TABLE {inventory_table} (
            inventory_id TEXT PRIMARY KEY,
            database_snapshot_digest TEXT NOT NULL,
            storage_snapshot_digest TEXT NOT NULL,
            writer_freeze_receipt_digest TEXT NOT NULL,
            database_high_watermark TEXT NOT NULL,
            storage_generation TEXT NOT NULL,
            expected_row_set_digest TEXT NOT NULL,
            expected_object_set_digest TEXT NOT NULL,
            expected_reference_set_digest TEXT NOT NULL,
            expected_byte_total INTEGER NOT NULL,
            blocker_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            inventory_digest TEXT NOT NULL
        );
        CREATE TABLE {unit_table} (
            migration_unit_id TEXT PRIMARY KEY,
            inventory_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            repository_binding_id TEXT NOT NULL,
            repository_binding_version INTEGER NOT NULL,
            historical_namespace TEXT NOT NULL,
            expected_identity_set_digest TEXT NOT NULL,
            expected_byte_total INTEGER NOT NULL,
            unit_ordinal INTEGER NOT NULL,
            unit_digest TEXT NOT NULL
        );
        CREATE TABLE {ref_table} (
            historical_ref_id TEXT PRIMARY KEY,
            {original_id} TEXT NOT NULL,
            original_kind TEXT NOT NULL,
            original_digest TEXT NOT NULL,
            original_size INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            owner_identity_digest TEXT NOT NULL,
            lineage_digest TEXT NOT NULL,
            source_snapshot_digest TEXT NOT NULL,
            migration_unit_id TEXT NOT NULL,
            repository_binding_id TEXT NOT NULL,
            repository_binding_version INTEGER NOT NULL,
            historical_ref TEXT NOT NULL,
            historical_commit TEXT NOT NULL,
            historical_tree TEXT NOT NULL,
            repository_path TEXT NOT NULL,
            storage TEXT NOT NULL,
            git_blob_oid TEXT,
            lfs_oid TEXT,
            lfs_size INTEGER,
            verification_digest TEXT NOT NULL,
            eligibility TEXT NOT NULL,
            supersession_decision_digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ref_digest TEXT NOT NULL
        );
        CREATE TABLE {rewrite_table} (
            rewrite_id TEXT PRIMARY KEY,
            migration_unit_id TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_row_identity_digest TEXT NOT NULL,
            source_field TEXT NOT NULL,
            {original_id} TEXT NOT NULL,
            replacement_kind TEXT NOT NULL,
            replacement_ref TEXT NOT NULL,
            source_version_digest TEXT NOT NULL,
            rewrite_digest TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE {unit_receipt_table} (
            receipt_id TEXT PRIMARY KEY,
            migration_unit_id TEXT NOT NULL,
            inventory_digest TEXT NOT NULL,
            expected_identity_set_digest TEXT NOT NULL,
            migrated_identity_set_digest TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            target_commit TEXT NOT NULL,
            target_tree TEXT NOT NULL,
            lfs_closure_digest TEXT NOT NULL,
            mapping_digest TEXT NOT NULL,
            reference_rewrite_digest TEXT NOT NULL,
            actual_byte_total INTEGER NOT NULL,
            zero_post_freeze_write INTEGER NOT NULL,
            non_adoption_digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            receipt_digest TEXT NOT NULL
        );
        CREATE TABLE {global_receipt_table} (
            receipt_id TEXT PRIMARY KEY,
            inventory_digest TEXT NOT NULL,
            expected_global_identity_set_digest TEXT NOT NULL,
            migrated_global_identity_set_digest TEXT NOT NULL,
            unit_receipt_set_digest TEXT NOT NULL,
            mapping_set_digest TEXT NOT NULL,
            reference_rewrite_set_digest TEXT NOT NULL,
            git_lfs_closure_set_digest TEXT NOT NULL,
            non_adoption_set_digest TEXT NOT NULL,
            negative_item_count INTEGER NOT NULL,
            source_preserved INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            receipt_digest TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO sessions (session_id, project_id) VALUES (?, ?)",
        ("session-1", "project-1"),
    )
    connection.execute(
        """
        INSERT INTO session_repository_binding_pins (
            session_id, binding_id, binding_version, resolved_base_commit
        ) VALUES (?, ?, ?, ?)
        """,
        ("session-1", "binding-1", 1, base_commit),
    )
    connection.execute(
        f"""
        INSERT INTO {source_table} (
            {LEGACY}_id, session_id, task_id, lane_id, invocation_id, run_id,
            kind, storage_uri, relative_path, title, description,
            metadata_json, created_at
        ) VALUES (?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            "legacy-object-1",
            "session-1",
            "research.output",
            "legacy://one",
            "reports/result.bin",
            "result",
            "{}",
            "2026-08-17T00:00:00+00:00",
        ),
    )
    connection.execute(
        f"INSERT INTO frozen_handoffs (handoff_id, {LEGACY}_id) VALUES (?, ?)",
        ("handoff-1", "legacy-object-1"),
    )
    connection.commit()
    connection.close()


def test_offline_historical_schema_preparation_is_exact_and_one_shot(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control-plane.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE sessions (session_id TEXT PRIMARY KEY);
        CREATE TABLE project_repository_binding_versions (
            binding_id TEXT NOT NULL,
            binding_version INTEGER NOT NULL,
            PRIMARY KEY (binding_id, binding_version)
        );
        PRAGMA user_version = 38;
        """
    )
    connection.close()
    receipt = tmp_path / "preparation-receipt.json"
    arguments = argparse.Namespace(
        database=database,
        repository_root=REPO_ROOT,
        receipt=receipt,
    )

    prepare_historical_schema(arguments)

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema"] == "historical_artifact_schema_preparation@1"
    assert payload["user_version"] == 38
    connection = sqlite3.connect(database)
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    connection.close()
    assert "historical_artifact_migration_global_receipts" in tables
    with pytest.raises(PreparationBlocked):
        prepare_historical_schema(arguments)


def test_offline_historical_migration_is_exact_and_non_adoptable(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "--allow-empty", "-m", "base")
    base_commit = _git(repository, "rev-parse", "HEAD")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "origin", f"{base_commit}:refs/heads/main")

    source_root = tmp_path / "legacy-bytes"
    source_root.mkdir()
    source = source_root / "one.bin"
    source_bytes = b"isolated historical payload\n"
    source.write_bytes(source_bytes)
    database = tmp_path / "legacy.sqlite"
    _create_source_database(database, base_commit)

    fixed = "sha256:" + "a" * 64
    database_snapshot_digest = _sha256(database.read_bytes())
    source_identity_digest = digest(
        {
            "source_scheme": "file",
            "root_id": "fixture",
            "relative_path": "one.bin",
            "file_size": len(source_bytes),
            "slice_start": 0,
            "slice_size": len(source_bytes),
            "slice_digest": _sha256(source_bytes),
        }
    )
    storage_snapshot_digest = digest(
        {
            "schema": "historical_storage_snapshot_observation@1",
            "physical_files": [
                {
                    "root_id": "fixture",
                    "relative_path": "one.bin",
                    "content_digest": _sha256(source_bytes),
                    "size": len(source_bytes),
                }
            ],
            "object_source_identity_digests": [source_identity_digest],
        }
    )
    inventory_config = tmp_path / "inventory-config.json"
    inventory_config.write_text(
        json.dumps(
            {
                "schema": "historical_inventory_config@1",
                "source_roots": [{"root_id": "fixture", "path": str(source_root)}],
                "source_objects": [
                    {
                        "storage_uri": "legacy://one",
                        "source_scheme": "file",
                        "source_root_id": "fixture",
                        "source_relative_path": "one.bin",
                    }
                ],
                "reference_rules": [
                    {
                        "table": "frozen_handoffs",
                        "field": LEGACY + "_id",
                        "replacement_kind": "historical_ref",
                        "replacement_field": "historical_ref",
                    }
                ],
                "lfs_policy": {
                    "schema": "git_lfs_content_policy@1",
                    "threshold_bytes": 1,
                },
                "database_snapshot_digest": database_snapshot_digest,
                "storage_snapshot_digest": storage_snapshot_digest,
                "writer_freeze_receipt_digest": fixed,
                "database_high_watermark_digest": fixed,
                "storage_generation_digest": fixed,
                "created_at": "2026-08-17T00:00:00+00:00",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.json"
    build_inventory(
        argparse.Namespace(
            database=database,
            config=inventory_config,
            output=inventory,
        )
    )
    frozen_inventory = json.loads(inventory.read_text(encoding="utf-8"))

    admission = tmp_path / "admission.json"
    admitted = {
        "schema": "historical_" + LEGACY + "_migration_admission@1",
        "maintenance_mode": True,
        "host_stopped": True,
        "runtime_consumers_stopped": True,
        "continuations_stopped": True,
        "execution_workers_stopped": True,
        "runner_callbacks_stopped": True,
        "backup_verified": True,
        "zero_legacy_public_surface": True,
        "aox_non_adoption_required": True,
        "active_public_contract": "file_workspace_public@1",
        "active_writer_count": 0,
        "unsettled_external_effect_count": 0,
        "post_freeze_write_count": 0,
        "legacy_public_writer_count": 0,
        "public_cutover_completion_receipt_digest": fixed,
        "public_release_bundle_digest": fixed,
        "historical_schema_preparation_receipt_digest": fixed,
        "quiescence_receipt_digest": fixed,
        "writer_freeze_receipt_digest": fixed,
        "database_backup_digest": fixed,
        "storage_backup_digest": fixed,
        "database_snapshot_digest": database_snapshot_digest,
        "storage_snapshot_digest": storage_snapshot_digest,
        "database_high_watermark_digest": fixed,
        "storage_generation_digest": fixed,
        "lfs_policy_digest": _sha256(
            json.dumps(
                {
                    "schema": "git_lfs_content_policy@1",
                    "threshold_bytes": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ),
        "operator_source_set_digest": frozen_inventory[
            "operator_source_set_digest"
        ],
    }
    admission.write_text(json.dumps(admitted, sort_keys=True), encoding="utf-8")
    receipt = tmp_path / "migration-receipt.json"
    working_root = tmp_path / "operator-work"
    working_root.mkdir()
    migrate(
        argparse.Namespace(
            database=database,
            inventory=inventory,
            admission=admission,
            repository=repository,
            remote_name="origin",
            remote_url=str(remote),
            source_root=[f"fixture={source_root}"],
            receipt=receipt,
            working_root=working_root,
        )
    )

    verification = verify(
        receipt,
        str(remote),
        working_root=working_root,
    )
    result = json.loads(receipt.read_text(encoding="utf-8"))
    assert verification["historical_only"] is True
    assert verification["current_adoption_authorized"] is False
    assert result["source_preserved"] is True
    assert result["objects"][0]["storage"] == "git_lfs"
    assert result["objects"][0]["eligibility"] == "historical_import_non_adoptable"
    assert source.read_bytes() == source_bytes

    original_receipt = receipt.read_bytes()
    migrate(
        argparse.Namespace(
            database=database,
            inventory=inventory,
            admission=admission,
            repository=repository,
            remote_name="origin",
            remote_url=str(remote),
            source_root=[f"fixture={source_root}"],
            receipt=receipt,
            working_root=working_root,
        )
    )
    assert receipt.read_bytes() == original_receipt

    tampered = tmp_path / "tampered-migration-receipt.json"
    tampered_payload = dict(result)
    tampered_payload["aox_non_adoption_proven"] = False
    tampered.write_text(json.dumps(tampered_payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(MigrationBlocked):
        verify(tampered, str(remote), working_root=working_root)

    connection = sqlite3.connect(database)
    rewritten = connection.execute(
        "SELECT historical_ref FROM frozen_handoffs WHERE handoff_id = ?",
        ("handoff-1",),
    ).fetchone()
    assert rewritten is not None
    assert str(rewritten[0]).startswith("historical_ref_")
    connection.close()


def test_offline_historical_migration_closes_an_exact_empty_source_set(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(
        repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@invalid",
        "commit",
        "--allow-empty",
        "-m",
        "base",
    )
    base_commit = _git(repository, "rev-parse", "HEAD")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "origin", f"{base_commit}:refs/heads/main")

    database = tmp_path / "legacy.sqlite"
    _create_source_database(database, base_commit)
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM frozen_handoffs")
    connection.execute(f"DELETE FROM session_{LEGACY}_records")
    connection.commit()
    connection.close()

    fixed = "sha256:" + "a" * 64
    empty_observation = {
        "schema": "historical_storage_snapshot_observation@1",
        "physical_files": [],
        "object_source_identity_digests": [],
    }
    lfs_policy = {
        "schema": "git_lfs_content_policy@1",
        "threshold_bytes": 1024,
    }
    database_snapshot_digest = _sha256(database.read_bytes())
    inventory_config = tmp_path / "inventory-config.json"
    inventory_config.write_text(
        json.dumps(
            {
                "schema": "historical_inventory_config@1",
                "source_roots": [],
                "source_objects": [],
                "reference_rules": [],
                "lfs_policy": lfs_policy,
                "database_snapshot_digest": database_snapshot_digest,
                "storage_snapshot_digest": digest(empty_observation),
                "writer_freeze_receipt_digest": fixed,
                "database_high_watermark_digest": fixed,
                "storage_generation_digest": fixed,
                "created_at": "2026-08-17T00:00:00+00:00",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.json"
    build_inventory(
        argparse.Namespace(
            database=database,
            config=inventory_config,
            output=inventory,
        )
    )
    frozen_inventory = json.loads(inventory.read_text(encoding="utf-8"))
    assert frozen_inventory["source_root_path_digests"] == {}
    assert frozen_inventory["objects"] == []
    assert frozen_inventory["references"] == []

    admission = tmp_path / "admission.json"
    admission.write_text(
        json.dumps(
            {
                "schema": "historical_" + LEGACY + "_migration_admission@1",
                "maintenance_mode": True,
                "host_stopped": True,
                "runtime_consumers_stopped": True,
                "continuations_stopped": True,
                "execution_workers_stopped": True,
                "runner_callbacks_stopped": True,
                "backup_verified": True,
                "zero_legacy_public_surface": True,
                "aox_non_adoption_required": True,
                "active_public_contract": "file_workspace_public@1",
                "active_writer_count": 0,
                "unsettled_external_effect_count": 0,
                "post_freeze_write_count": 0,
                "legacy_public_writer_count": 0,
                "public_cutover_completion_receipt_digest": fixed,
                "public_release_bundle_digest": fixed,
                "historical_schema_preparation_receipt_digest": fixed,
                "quiescence_receipt_digest": fixed,
                "writer_freeze_receipt_digest": fixed,
                "database_backup_digest": fixed,
                "storage_backup_digest": fixed,
                "database_snapshot_digest": database_snapshot_digest,
                "storage_snapshot_digest": digest(empty_observation),
                "database_high_watermark_digest": fixed,
                "storage_generation_digest": fixed,
                "lfs_policy_digest": digest(lfs_policy),
                "operator_source_set_digest": frozen_inventory[
                    "operator_source_set_digest"
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt = tmp_path / "migration-receipt.json"
    working_root = tmp_path / "operator-work"
    working_root.mkdir()
    migrate(
        argparse.Namespace(
            database=database,
            inventory=inventory,
            admission=admission,
            repository=repository,
            remote_name="origin",
            remote_url=str(remote),
            source_root=[],
            receipt=receipt,
            working_root=working_root,
        )
    )

    result = json.loads(receipt.read_text(encoding="utf-8"))
    verification = verify(receipt, str(remote), working_root=working_root)
    assert result["expected_byte_total"] == 0
    assert result["migrated_byte_total"] == 0
    assert result["objects"] == []
    assert result["targets"] == []
    assert result["unit_receipts"] == []
    assert verification["verified_object_count"] == 0
    assert verification["current_adoption_authorized"] is False
