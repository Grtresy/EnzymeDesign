from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OPERATOR_ROOT = (
    REPOSITORY_ROOT
    / "openspec/changes/cut-over-workspace-public-interfaces/operator"
)
sys.path.insert(0, str(OPERATOR_ROOT))

from offline_activate_release import activate  # noqa: E402
from offline_activate_release import canonical_digest  # noqa: E402


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_proofs(tmp_path: Path) -> tuple[Path, Path]:
    quiescence_payload = {
        "schema_id": "file_workspace_release_quiescence@1",
        "maintenance_mode": True,
        "host_stopped": True,
        "runtime_consumers_stopped": True,
        "continuations_stopped": True,
        "execution_workers_stopped": True,
        "runner_callbacks_stopped": True,
        "ui_writes_stopped": True,
        "active_writer_count": 0,
        "unsettled_external_effect_count": 0,
        "active_openzyme_process_count": 0,
        "writer_fence_high_watermark": 7,
    }
    quiescence = tmp_path / "quiescence.json"
    quiescence.write_text(
        json.dumps(
            {
                **quiescence_payload,
                "receipt_digest": canonical_digest(quiescence_payload),
            }
        ),
        encoding="utf-8",
    )
    storage_payload = {
        "schema_id": "legacy_storage_backup_manifest@1",
        "storage_snapshot_digest": canonical_digest([]),
        "verified": True,
        "isolated_recovery_only": True,
        "objects": [],
    }
    storage = tmp_path / "storage-backup.json"
    storage.write_text(
        json.dumps(
            {
                **storage_payload,
                "manifest_digest": canonical_digest(storage_payload),
            }
        ),
        encoding="utf-8",
    )
    return quiescence, storage


def _database(path: Path, *, task_count: int = 0) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE tasks (task_id TEXT PRIMARY KEY);
        """
    )
    connection.execute(
        "INSERT INTO sessions VALUES ('legacy-session', 'active', 'before')"
    )
    if task_count:
        connection.execute("INSERT INTO tasks VALUES ('unsettled-task')")
    connection.commit()
    connection.close()


def test_offline_release_activation_archives_exact_legacy_session(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.sqlite"
    _database(database)
    backup = tmp_path / "legacy.sqlite.backup"
    shutil.copyfile(database, backup)
    quiescence, storage = _write_proofs(tmp_path)
    output = tmp_path / "activation.json"

    activate(
        database=database,
        database_backup=backup,
        storage_backup_manifest=storage,
        quiescence_receipt=quiescence,
        historical_session_ids=("legacy-session",),
        activated_at="2026-08-17T00:00:00+00:00",
        output=output,
    )

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT status FROM sessions").fetchone()[0] == "archived"
    connection.close()
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["file_workspace_public_contract_active"] is True
    assert evidence["active_artifact_era_session_count"] == 0
    assert evidence["database_snapshot_digest"] == _file_digest(database)
    assert evidence["evidence_digest"] == canonical_digest(
        {key: value for key, value in evidence.items() if key != "evidence_digest"}
    )


def test_offline_release_activation_rejects_unsettled_task_without_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.sqlite"
    _database(database, task_count=1)
    backup = tmp_path / "legacy.sqlite.backup"
    shutil.copyfile(database, backup)
    quiescence, storage = _write_proofs(tmp_path)

    with pytest.raises(ValueError, match="unsettled mutation state"):
        activate(
            database=database,
            database_backup=backup,
            storage_backup_manifest=storage,
            quiescence_receipt=quiescence,
            historical_session_ids=("legacy-session",),
            activated_at="2026-08-17T00:00:00+00:00",
            output=tmp_path / "activation.json",
        )

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT status FROM sessions").fetchone()[0] == "active"
    connection.close()
