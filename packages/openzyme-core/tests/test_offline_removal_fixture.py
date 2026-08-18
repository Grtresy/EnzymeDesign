from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from openzyme_core import connect_sqlite
from openzyme_core.migration_assets import apply_sqlite_migrations
from openzyme_core.migration_assets import FINAL_SCHEMA_MANIFEST_DIGEST
from openzyme_core.migration_assets import get_migration_sql


REPO_ROOT = Path(__file__).resolve().parents[3]
CHANGE_NAME = "remove-" + "arti" + "fact-control-plane-and-storage"
OPERATOR_ROOT = REPO_ROOT / "openspec" / "changes" / CHANGE_NAME / "operator"
sys.path.insert(0, str(OPERATOR_ROOT))

from offline_removal_contract import HistoricalMigrationProof  # noqa: E402
from offline_removal_contract import LegacyStorageDeletionTarget  # noqa: E402
from offline_removal_contract import PREREQUISITE_CHANGE_IDS  # noqa: E402
from offline_removal_contract import PrerequisiteCompletionReceipt  # noqa: E402
from offline_removal_contract import QuiescenceAndBackupProof  # noqa: E402
from offline_removal_contract import SchemaRebuildEntry  # noqa: E402
from offline_removal_contract import build_removal_dry_run  # noqa: E402
from offline_removal_contract import canonical_digest  # noqa: E402
from offline_removal_contract import RemovalAdmissionError  # noqa: E402
from offline_remover import execute  # noqa: E402
from offline_remover import file_digest  # noqa: E402
from offline_remover import observe_removal_inventory  # noqa: E402
from offline_remover import prepare_final_copy  # noqa: E402
from offline_remover import remove_storage  # noqa: E402
from offline_remover import removal_root_identity_set_digest  # noqa: E402
from offline_remover import schema_manifest  # noqa: E402

HISTORICAL_OPERATOR_ROOT = (
    REPO_ROOT
    / "openspec"
    / "changes"
    / ("migrate-historical-" + "arti" + "facts-to-git-lfs")
    / "operator"
)
sys.path.insert(0, str(HISTORICAL_OPERATOR_ROOT))
from offline_historical_migrator import fresh_readback  # noqa: E402
from offline_historical_migrator import operator_source_digests  # noqa: E402


DIGEST = "sha256:" + "a" * 64


def test_final_copy_allows_new_required_columns_only_for_exact_zero_rows_and_defers_triggers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source.sqlite"
    source = sqlite3.connect(database)
    source.executescript(
        """
        CREATE TABLE empty_survivor (id TEXT PRIMARY KEY);
        CREATE TABLE audited (id TEXT PRIMARY KEY, lease_id TEXT NOT NULL);
        INSERT INTO audited VALUES ('old', 'legacy');
        """
    )
    source.commit()
    final_sql = """
        CREATE TABLE empty_survivor (
            id TEXT PRIMARY KEY,
            required_generation INTEGER NOT NULL
        );
        CREATE TABLE audited (id TEXT PRIMARY KEY, lease_id TEXT NOT NULL);
        CREATE TRIGGER audited_requires_current_lease
        BEFORE INSERT ON audited
        WHEN NEW.lease_id = 'legacy'
        BEGIN SELECT RAISE(ABORT, 'legacy lease rejected'); END;
        PRAGMA user_version = 1;
    """
    target = sqlite3.connect(":memory:")
    target.executescript(final_sql)
    _, expected_manifest = schema_manifest(target)
    source_sql = str(
        source.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='empty_survivor'"
        ).fetchone()[0]
    )
    target_sql = str(
        target.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='empty_survivor'"
        ).fetchone()[0]
    )
    target.close()
    empty_rows_digest = canonical_digest([])
    final_copy, _ = prepare_final_copy(
        source=source,
        final_sql=final_sql,
        expected_manifest_digest=expected_manifest,
        rebuild_entries=(
            SchemaRebuildEntry(
                source_table="empty_survivor",
                final_table="empty_survivor",
                source_schema_digest=canonical_digest(source_sql),
                final_schema_digest=canonical_digest(target_sql),
                typed_replacement_set_digest=empty_rows_digest,
                expected_row_identity_set_digest=empty_rows_digest,
            ),
        ),
        drop_structures=(),
        working_root=tmp_path,
    )
    source.close()

    copied = sqlite3.connect(final_copy)
    assert copied.execute("SELECT * FROM audited").fetchall() == [("old", "legacy")]
    assert copied.execute("SELECT count(*) FROM empty_survivor").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="legacy lease rejected"):
        copied.execute("INSERT INTO audited VALUES ('new', 'legacy')")
    copied.close()


def _seed_incomplete_removal_ledger(
    database: Path,
    *,
    manifest_digest: str,
    targets: tuple[LegacyStorageDeletionTarget, ...],
) -> str:
    connection = sqlite3.connect(database)
    connection.executescript(get_migration_sql("001_file_workspace_final"))
    receipt_id = "legacy_removal_" + manifest_digest[-32:]
    incomplete_digest = canonical_digest(
        {"receipt_id": receipt_id, "state": "incomplete"}
    )
    expected = canonical_digest(sorted(item.object_identity for item in targets))
    connection.execute(
        "UPDATE deployment_schema_state SET removal_state='offline_removal_incomplete', removal_receipt_digest=?",
        (incomplete_digest,),
    )
    connection.execute(
        """
        INSERT INTO legacy_removal_ledger (
            receipt_id, schema_generation, manifest_digest,
            historical_receipt_digest, database_backup_digest,
            storage_backup_digest, quiescence_receipt_digest,
            expected_object_set_digest, removed_object_set_digest,
            already_absent_set_digest, root_identity_set_digest,
            error_object_set_digest, expected_byte_total, removed_byte_total,
            state, created_at, completed_at, receipt_digest
        ) VALUES (?, 'openzyme_file_workspace_final@2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'incomplete', ?, NULL, ?)
        """,
        (
            receipt_id,
            manifest_digest,
            DIGEST,
            DIGEST,
            DIGEST,
            DIGEST,
            expected,
            canonical_digest([]),
            canonical_digest([]),
            removal_root_identity_set_digest(targets),
            canonical_digest([]),
            sum(item.size_bytes for item in targets),
            "7",
            incomplete_digest,
        ),
    )
    connection.executemany(
        """
        INSERT INTO legacy_removal_items (
            receipt_id, object_identity, root_identity, root_path_digest,
            relative_path, content_digest, size_bytes, state, error_digest,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'expected', NULL, '7')
        """,
        [
            (
                receipt_id,
                item.object_identity,
                item.allowlisted_root_identity,
                item.allowlisted_root_path_digest,
                item.relative_path,
                item.content_digest,
                item.size_bytes,
            )
            for item in targets
        ],
    )
    connection.commit()
    connection.close()
    return receipt_id


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_current_product_sources_do_not_restore_the_retired_subsystem() -> None:
    retired = "arti" + "fact"
    forbidden = (
        retired + ".",
        retired + "_",
        retired + "s.",
        "/" + retired + "s",
        "session_" + retired + "_records",
        "sandbox_" + retired,
        "result_" + retired,
        "historical_" + retired,
    )
    roots = (
        *(REPO_ROOT / "apps").glob("*/src"),
        *(REPO_ROOT / "packages").glob("*/src"),
    )
    candidates = [
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".json"}
    ]
    candidates.extend(REPO_ROOT.glob("apps/*/pyproject.toml"))
    candidates.extend(REPO_ROOT.glob("packages/*/pyproject.toml"))
    violations = {
        str(path.relative_to(REPO_ROOT)): token
        for path in sorted(set(candidates))
        for token in forbidden
        if token.casefold() in path.read_text(encoding="utf-8").casefold()
    }
    assert violations == {}


def _prerequisites() -> tuple[PrerequisiteCompletionReceipt, ...]:
    receipts = []
    for change_id in PREREQUISITE_CHANGE_IDS:
        payload = {
            "change_id": change_id,
            "receipt_schema_id": "change_completion_receipt@1",
            "source_revision": "1" * 40,
            "schema_identity_digest": DIGEST,
            "contract_identity_digest": DIGEST,
            "activation_epoch": 1,
            "accepted": True,
            "superseded": False,
            "transitive_receipt_digest": DIGEST,
        }
        receipts.append(
            PrerequisiteCompletionReceipt(
                **payload,
                receipt_digest=canonical_digest(payload),
            )
        )
    return tuple(receipts)


def test_exact_offline_removal_executes_only_against_an_isolated_fixture(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(get_migration_sql("001_file_workspace_final"))
    retired_table = "session_" + "arti" + "facts"
    connection.execute(f'CREATE TABLE "{retired_table}" (id TEXT PRIMARY KEY)')
    connection.commit()
    connection.close()

    database_backup = tmp_path / "fixture.sqlite.backup"
    shutil.copyfile(database, database_backup)
    storage_root = tmp_path / "legacy-bytes"
    storage_root.mkdir()
    stored = storage_root / "one.bin"
    stored.write_bytes(b"legacy fixture bytes")
    remote = tmp_path / "historical.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    historical_repository = tmp_path / "historical-repository"
    historical_repository.mkdir()
    _git(historical_repository, "init")
    _git(
        historical_repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@invalid",
        "commit",
        "--allow-empty",
        "-m",
        "base",
    )
    historical_base_commit = _git(historical_repository, "rev-parse", "HEAD")
    historical_path = historical_repository / "legacy" / "one.bin"
    historical_path.parent.mkdir()
    shutil.copyfile(stored, historical_path)
    frozen_object = {
        "object_id": "legacy-object-1",
        "project_id": "project-1",
        "session_id": "session-1",
        "kind": "research.output",
        "source_scheme": "file",
        "source_root_id": "fixture-root",
        "source_relative_path": "one.bin",
        "source_identity_digest": DIGEST,
        "expected_content_digest": file_digest(stored),
        "expected_size": stored.stat().st_size,
        "relative_path": "legacy/one.bin",
        "owner_identity_digest": DIGEST,
        "lineage_digest": DIGEST,
        "source_row_version_digest": DIGEST,
        "repository_binding_id": "binding-1",
        "repository_binding_version": 1,
        "repository_base_commit": historical_base_commit,
        "byte_range_start": 0,
        "byte_range_length": None,
    }
    identity_set = canonical_digest([canonical_digest(frozen_object)])
    unit_manifest_payload = {
        "schema": "historical_migration_unit_manifest@1",
        "unit_id": "unit-1",
        "inventory_digest": DIGEST,
        "lfs_policy_digest": DIGEST,
        "identity_set_digest": identity_set,
        "objects": [
            {
                "object_id": "legacy-object-1",
                "path": "legacy/one.bin",
                "content_digest": file_digest(stored),
                "size": stored.stat().st_size,
                "owner_identity_digest": DIGEST,
                "lineage_digest": DIGEST,
                "storage": "git_blob",
                "eligibility": "historical_import_non_adoptable",
            }
        ],
    }
    unit_manifest = historical_repository / ".openzyme" / "historical" / "unit-1.json"
    unit_manifest.parent.mkdir(parents=True)
    unit_manifest.write_text(
        json.dumps(
            {
                **unit_manifest_payload,
                "manifest_digest": canonical_digest(unit_manifest_payload),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    _git(historical_repository, "add", "--all")
    _git(
        historical_repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@invalid",
        "commit",
        "-m",
        "historical fixture",
    )
    historical_commit = _git(historical_repository, "rev-parse", "HEAD")
    historical_tree = _git(historical_repository, "rev-parse", "HEAD^{tree}")
    historical_blob = _git(
        historical_repository,
        "rev-parse",
        "HEAD:legacy/one.bin",
    )
    unit_manifest_blob = _git(
        historical_repository,
        "rev-parse",
        "HEAD:.openzyme/historical/unit-1.json",
    )
    historical_ref = "refs/openzyme/history/unit-1"
    _git(historical_repository, "remote", "add", "origin", str(remote))
    _git(
        historical_repository,
        "push",
        "origin",
        f"{historical_commit}:{historical_ref}",
    )
    storage_backup_manifest = tmp_path / "storage-backup.json"
    storage_backup_manifest.write_text('{"verified":true}\n', encoding="utf-8")
    quiescence_receipt = tmp_path / "quiescence.json"
    quiescence_receipt.write_text('{"writers":0}\n', encoding="utf-8")
    storage_root_path_digest = canonical_digest(str(storage_root.resolve()))
    storage_item_identity_payload = {
        "root_identity": "fixture-root",
        "relative_path": "one.bin",
        "content_digest": file_digest(stored),
        "size_bytes": stored.stat().st_size,
    }
    storage_object_identity = (
        "legacy_storage_"
        + canonical_digest(storage_item_identity_payload)[-32:]
    )
    storage_snapshot_observation = {
        "schema": "historical_storage_snapshot_observation@1",
        "physical_files": [
            {
                "root_id": "fixture-root",
                "relative_path": "one.bin",
                "content_digest": file_digest(stored),
                "size": stored.stat().st_size,
            }
        ],
        "object_source_identity_digests": [DIGEST],
    }
    storage_snapshot_digest = canonical_digest(storage_snapshot_observation)

    target_object = {
        "original_id": "legacy-object-1",
        "object_id": "legacy-object-1",
        "path": "legacy/one.bin",
        "content_digest": file_digest(stored),
        "size": stored.stat().st_size,
        "owner_identity_digest": DIGEST,
        "lineage_digest": DIGEST,
        "storage": "git_blob",
        "git_blob_oid": historical_blob,
        "lfs_oid": None,
        "lfs_size": None,
        "repository_binding_id": "binding-1",
        "repository_binding_version": 1,
    }
    target_object.pop("original_id")
    target = {
        "schema": "historical_migration_unit_target@1",
        "unit_id": "unit-1",
        "historical_ref": historical_ref,
        "commit": historical_commit,
        "tree": historical_tree,
        "lfs_policy_digest": DIGEST,
        "unit_manifest_path": ".openzyme/historical/unit-1.json",
        "unit_manifest_blob_oid": unit_manifest_blob,
        "unit_manifest_content_digest": file_digest(unit_manifest),
        "identity_set_digest": identity_set,
        "byte_total": stored.stat().st_size,
        "objects": [target_object],
    }
    working_root = tmp_path / "operator-work"
    working_root.mkdir()
    readback = fresh_readback(
        remote_url=str(remote),
        target=target,
        working_root=working_root,
    )
    supersession_decision_digest = canonical_digest(
        {
            "original_id": "legacy-object-1",
            "decision": "historical_import_non_adoptable",
            "current_adoption_authorized": False,
        }
    )
    mapping_payload = {
        "historical_ref_id": "historical-ref-1",
        "original_id": "legacy-object-1",
        "project_id": "project-1",
        "session_id": "session-1",
        "kind": "research.output",
        "eligibility": "historical_import_non_adoptable",
        "historical_ref": historical_ref,
        "commit": historical_commit,
        "tree": historical_tree,
        "path": "legacy/one.bin",
        "content_digest": file_digest(stored),
        "size": stored.stat().st_size,
        "owner_identity_digest": DIGEST,
        "lineage_digest": DIGEST,
        "source_identity_digest": DIGEST,
        "unit_id": "unit-1",
        "storage": "git_blob",
        "git_blob_oid": historical_blob,
        "lfs_oid": None,
        "lfs_size": None,
        "repository_binding_id": "binding-1",
        "repository_binding_version": 1,
        "supersession_decision_digest": supersession_decision_digest,
    }
    mapping = {
        **mapping_payload,
        "mapping_digest": canonical_digest(mapping_payload),
    }
    unit_payload = {
        "migration_unit_id": "unit-1",
        "inventory_digest": DIGEST,
        "expected_identity_set_digest": identity_set,
        "migrated_identity_set_digest": identity_set,
        "target_ref": historical_ref,
        "target_commit": historical_commit,
        "target_tree": historical_tree,
        "lfs_closure_digest": readback["readback_digest"],
        "mapping_digest": canonical_digest([mapping]),
        "reference_rewrite_digest": canonical_digest([]),
        "actual_byte_total": stored.stat().st_size,
        "zero_post_freeze_write": True,
        "non_adoption_digest": canonical_digest([supersession_decision_digest]),
    }
    unit_receipt = {
        **unit_payload,
        "receipt_id": "unit-receipt-1",
        "receipt_digest": canonical_digest(unit_payload),
    }
    unit_set_digest = canonical_digest([unit_receipt["receipt_digest"]])
    rewrite_set_digest = canonical_digest([])
    historical_payload = {
        "schema": "historical_" + "arti" + "fact_migration_receipt@1",
        "inventory_digest": DIGEST,
        "database_snapshot_digest": DIGEST,
        "storage_snapshot_digest": storage_snapshot_digest,
        "expected_identity_set_digest": identity_set,
        "migrated_identity_set_digest": identity_set,
        "expected_reference_set_digest": rewrite_set_digest,
        "migrated_reference_set_digest": rewrite_set_digest,
        "rewritten_reference_set_digest": rewrite_set_digest,
        "target_set_digest": canonical_digest([target]),
        "readback_set_digest": canonical_digest([readback]),
        "mapping_set_digest": canonical_digest([mapping["mapping_digest"]]),
        "unit_receipt_set_digest": unit_set_digest,
        "expected_byte_total": stored.stat().st_size,
        "migrated_byte_total": stored.stat().st_size,
        "unresolved_reference_count": 0,
        "post_freeze_write_count": 0,
        "negative_item_count": 0,
        "aox_non_adoption_proven": True,
        "non_adoption_set_digest": canonical_digest(
            [supersession_decision_digest]
        ),
        "lfs_policy_digest": DIGEST,
        "operator_source_digests": operator_source_digests(),
        "operator_source_set_digest": canonical_digest(
            operator_source_digests()
        ),
        "source_preserved": True,
        "storage_snapshot_observation": storage_snapshot_observation,
        "source_root_path_digests": {
            "fixture-root": storage_root_path_digest,
        },
        "frozen_objects": [frozen_object],
        "frozen_references": [],
        "objects": [mapping],
        "reference_rewrites": [],
        "targets": [target],
        "readbacks": [readback],
        "unit_receipts": [unit_receipt],
    }
    historical_payload["receipt_digest"] = canonical_digest(historical_payload)
    historical_receipt = tmp_path / "historical-receipt.json"
    historical_receipt.write_text(
        json.dumps(historical_payload, sort_keys=True), encoding="utf-8"
    )
    historical = HistoricalMigrationProof(
        receipt_schema_id=str(historical_payload["schema"]),
        receipt_digest=str(historical_payload["receipt_digest"]),
        inventory_generation=1,
        inventory_digest=DIGEST,
        database_snapshot_digest=DIGEST,
        storage_snapshot_digest=storage_snapshot_digest,
        expected_identity_set_digest=identity_set,
        migrated_identity_set_digest=identity_set,
        unit_receipt_set_digest=unit_set_digest,
        target_readback_set_digest=canonical_digest([readback]),
        reference_rewrite_set_digest=rewrite_set_digest,
        expected_row_count=0,
        migrated_row_count=0,
        expected_object_count=1,
        migrated_object_count=1,
        expected_byte_count=stored.stat().st_size,
        migrated_byte_count=stored.stat().st_size,
        unresolved_reference_count=0,
        post_freeze_write_count=0,
        aox_non_adoption_proven=True,
        source_preserved=True,
    )
    closure = QuiescenceAndBackupProof(
        maintenance_mode=True,
        host_stopped=True,
        mutation_consumers_stopped=True,
        sandbox_and_execution_stopped=True,
        runner_callbacks_stopped=True,
        ui_writes_stopped=True,
        unsettled_external_effect_count=0,
        active_writer_count=0,
        writer_fence_high_watermark=7,
        quiescence_receipt_digest=file_digest(quiescence_receipt),
        database_backup_digest=file_digest(database_backup),
        storage_backup_digest=file_digest(storage_backup_manifest),
        isolated_recovery_only=True,
    )
    target = LegacyStorageDeletionTarget(
        object_identity=storage_object_identity,
        allowlisted_root_identity="fixture-root",
        allowlisted_root_path_digest=storage_root_path_digest,
        relative_path="one.bin",
        content_digest=file_digest(stored),
        size_bytes=stored.stat().st_size,
        non_symlink=True,
    )
    current_inventory_digest = observe_removal_inventory(
        database=database,
        targets=(target,),
        roots={"fixture-root": storage_root},
    )
    dry_run = build_removal_dry_run(
        prerequisite_receipts=_prerequisites(),
        historical_proof=historical,
        quiescence_and_backup=closure,
        current_inventory_digest=current_inventory_digest,
        final_schema_manifest_digest=FINAL_SCHEMA_MANIFEST_DIGEST,
        rebuild_entries=(),
        drop_structures=(retired_table,),
        storage_targets=(target,),
    )
    admission = tmp_path / "admission.json"
    admission.write_text(
        json.dumps(
            {
                "schema": "offline_removal_admission@1",
                "prerequisite_receipts": [
                    asdict(item) for item in _prerequisites()
                ],
                "historical_proof": asdict(historical),
                "quiescence_and_backup": asdict(closure),
                "current_inventory_digest": current_inventory_digest,
                "final_schema_manifest_digest": FINAL_SCHEMA_MANIFEST_DIGEST,
                "rebuild_entries": [],
                "drop_structures": [retired_table],
                "storage_targets": [asdict(target)],
                "manifest_digest": dry_run.manifest.manifest_digest,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt = tmp_path / "removal-receipt.json"
    prerequisite_receipt_arguments = []
    for item in _prerequisites():
        path = tmp_path / f"{item.change_id}.receipt.json"
        path.write_text(json.dumps(asdict(item), sort_keys=True), encoding="utf-8")
        prerequisite_receipt_arguments.append(f"{item.change_id}={path}")

    execution_args = argparse.Namespace(
        database=database,
        database_backup=database_backup,
        storage_backup_manifest=storage_backup_manifest,
        quiescence_receipt=quiescence_receipt,
        historical_receipt=historical_receipt,
        historical_remote_url=str(remote),
        prerequisite_receipt=prerequisite_receipt_arguments,
        admission=admission,
        final_schema=(
            REPO_ROOT
            / "packages/openzyme-core/src/openzyme_core/migrations"
            / "001_file_workspace_final.sql"
        ),
        legacy_root=[f"fixture-root={storage_root}"],
        working_root=working_root,
        receipt=receipt,
    )
    execute(execution_args)

    assert not stored.exists()
    result = json.loads(receipt.read_text(encoding="utf-8"))
    assert result["state"] == "complete"
    current = connect_sqlite(str(database))
    apply_sqlite_migrations(current)
    assert current.execute(
        "SELECT state FROM legacy_removal_ledger"
    ).fetchone()[0] == "complete"
    assert current.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (retired_table,),
    ).fetchone() is None
    current.close()

    completed_receipt = receipt.read_bytes()
    execute(execution_args)
    assert receipt.read_bytes() == completed_receipt


def test_partial_storage_removal_resumes_only_the_same_ledger(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-root"
    root.mkdir()
    first = root / "first.bin"
    second = root / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    root_digest = canonical_digest(str(root.resolve()))
    targets = (
        LegacyStorageDeletionTarget(
            object_identity="legacy-storage-first",
            allowlisted_root_identity="fixture-root",
            allowlisted_root_path_digest=root_digest,
            relative_path="first.bin",
            content_digest=file_digest(first),
            size_bytes=first.stat().st_size,
            non_symlink=True,
        ),
        LegacyStorageDeletionTarget(
            object_identity="legacy-storage-second",
            allowlisted_root_identity="fixture-root",
            allowlisted_root_path_digest=root_digest,
            relative_path="second.bin",
            content_digest=file_digest(second),
            size_bytes=second.stat().st_size,
            non_symlink=True,
        ),
    )
    second.write_bytes(b"drifted")
    database = tmp_path / "partial.sqlite"
    manifest_digest = canonical_digest({"fixture": "partial"})
    receipt_id = _seed_incomplete_removal_ledger(
        database,
        manifest_digest=manifest_digest,
        targets=targets,
    )

    with pytest.raises(RemovalAdmissionError, match="identity differs"):
        remove_storage(
            database=database,
            receipt_id=receipt_id,
            manifest_digest=manifest_digest,
            targets=targets,
            roots={"fixture-root": root},
        )
    assert not first.exists()
    connection = sqlite3.connect(database)
    state = connection.execute(
        "SELECT removal_state FROM deployment_schema_state"
    ).fetchone()[0]
    connection.close()
    assert state == "offline_removal_incomplete"

    second.write_bytes(b"second")
    result = remove_storage(
        database=database,
        receipt_id=receipt_id,
        manifest_digest=manifest_digest,
        targets=targets,
        roots={"fixture-root": root},
    )
    assert result["removed_object_set_digest"] == canonical_digest(
        ["legacy-storage-first", "legacy-storage-second"]
    )
    assert result["already_absent_set_digest"] == canonical_digest([])
    assert result["error_object_set_digest"] == canonical_digest([])


def test_unknown_storage_absence_is_not_reinterpreted_as_success(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-root"
    root.mkdir()
    root_digest = canonical_digest(str(root.resolve()))
    target = LegacyStorageDeletionTarget(
        object_identity="legacy-storage-missing",
        allowlisted_root_identity="fixture-root",
        allowlisted_root_path_digest=root_digest,
        relative_path="missing.bin",
        content_digest=DIGEST,
        size_bytes=1,
        non_symlink=True,
    )
    database = tmp_path / "missing.sqlite"
    manifest_digest = canonical_digest({"fixture": "missing"})
    receipt_id = _seed_incomplete_removal_ledger(
        database,
        manifest_digest=manifest_digest,
        targets=(target,),
    )

    with pytest.raises(RemovalAdmissionError, match="absent without"):
        remove_storage(
            database=database,
            receipt_id=receipt_id,
            manifest_digest=manifest_digest,
            targets=(target,),
            roots={"fixture-root": root},
        )
    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT state FROM legacy_removal_items WHERE object_identity=?",
        (target.object_identity,),
    ).fetchone()[0] == "error"
    assert connection.execute(
        "SELECT removal_state FROM deployment_schema_state"
    ).fetchone()[0] == "offline_removal_incomplete"
    connection.close()
