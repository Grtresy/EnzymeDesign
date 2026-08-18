from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from openzyme_core.device_fresh_reset import DeviceFreshResetError
from openzyme_core.device_fresh_reset import build_reset_receipt
from openzyme_core.device_fresh_reset import canonical_digest
from openzyme_core.device_fresh_reset import execute_inventory
from openzyme_core.device_fresh_reset import freeze_inventory
from openzyme_core.device_fresh_reset import load_occurrences
from openzyme_core.device_fresh_reset import load_permission_adjustments
from openzyme_core.device_fresh_reset import verify_inventory
from openzyme_core.device_fresh_reset import verify_reset_receipt


DIGEST = "sha256:" + "1" * 64


def _plan(target: Path, exclusion: Path) -> dict[str, object]:
    return {
        "targets": [
            {
                "path": str(target),
                "target_kind": "old_openzyme_state",
                "owner_evidence": "fixture deployment locator",
                "preserve_root": True,
                "recoverable": False,
            }
        ],
        "exclusions": [
            {
                "path": str(exclusion),
                "exclusion_kind": "current_git_truth",
                "reason": "must survive the device reset",
            }
        ],
    }


def _authorization(inventory: dict[str, object]) -> str:
    return canonical_digest(
        {
            "inventory_digest": inventory["inventory_digest"],
            "recoverable": False,
            "authorized_scope": "all_resolved_openzyme_old_records_and_storage",
        }
    )


def test_freeze_execute_resume_and_receipt_are_exact(tmp_path: Path) -> None:
    target = tmp_path / "state" / "openzyme"
    target.mkdir(parents=True)
    (target / "old.sqlite3").write_bytes(b"old-state")
    nested = target / "backups"
    nested.mkdir()
    (nested / "receipt.json").write_text("{}", encoding="utf-8")
    nested.chmod(0o555)
    exclusion = tmp_path / "share" / "openzyme" / "repository-service" / "git"
    exclusion.mkdir(parents=True)
    (exclusion / "truth").write_text("preserve", encoding="utf-8")

    inventory = freeze_inventory(
        _plan(target, exclusion),
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
    )
    verify_inventory(inventory)
    log_path = tmp_path / "private" / "occurrences.jsonl"
    occurrences = execute_inventory(
        inventory,
        occurrence_log_path=log_path,
        permission_log_path=tmp_path / "private" / "permissions.jsonl",
        authorization_digest=_authorization(inventory),
    )
    permission_adjustments = tuple(
        load_permission_adjustments(
            tmp_path / "private" / "permissions.jsonl"
        ).values()
    )

    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert (exclusion / "truth").read_text(encoding="utf-8") == "preserve"
    assert len(occurrences) == inventory["deletion_occurrence_count"]
    assert execute_inventory(
        inventory,
        occurrence_log_path=log_path,
        permission_log_path=tmp_path / "private" / "permissions.jsonl",
        authorization_digest=_authorization(inventory),
    ) == occurrences

    receipt = build_reset_receipt(
        inventory=inventory,
        occurrences=occurrences,
        permission_adjustments=permission_adjustments,
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
        zero_scan_digest=DIGEST,
        fresh_bootstrap_receipt_digest=DIGEST,
        fresh_database_identity_digest=DIGEST,
    )
    verify_reset_receipt(receipt)


def test_identity_drift_fails_before_mutation_with_diagnostics(tmp_path: Path) -> None:
    target = tmp_path / "state" / "openzyme"
    target.mkdir(parents=True)
    old_file = target / "old.sqlite3"
    old_file.write_bytes(b"old-state")
    exclusion = tmp_path / "repository" / "git"
    exclusion.mkdir(parents=True)
    inventory = freeze_inventory(
        _plan(target, exclusion),
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
    )
    old_file.write_bytes(b"changed-after-freeze")

    with pytest.raises(DeviceFreshResetError) as caught:
        execute_inventory(
            inventory,
            occurrence_log_path=tmp_path / "occurrences.jsonl",
            permission_log_path=tmp_path / "permissions.jsonl",
            authorization_digest=_authorization(inventory),
        )

    assert caught.value.error_code == "reset_target_identity_drift"
    assert caught.value.mutation_applied is False
    assert caught.value.fallback_performed is False
    assert caught.value.diagnostic_id.startswith("sha256:")
    assert old_file.exists()


def test_unrecorded_absence_and_exclusion_overlap_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "state" / "openzyme"
    target.mkdir(parents=True)
    old_file = target / "old.sqlite3"
    old_file.write_bytes(b"old-state")
    exclusion = tmp_path / "repository" / "git"
    exclusion.mkdir(parents=True)
    inventory = freeze_inventory(
        _plan(target, exclusion),
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
    )
    old_file.unlink()
    with pytest.raises(DeviceFreshResetError, match="reset_unrecorded_path_absent"):
        verify_inventory(inventory)

    with pytest.raises(DeviceFreshResetError, match="reset_exclusion_overlap"):
        freeze_inventory(
            _plan(target, target / "protected"),
            source_identity=DIGEST,
            quiescence_digest=DIGEST,
        )


def test_occurrence_log_is_bound_and_receipt_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "openzyme"
    target.mkdir(parents=True)
    (target / "old").write_text("old", encoding="utf-8")
    exclusion = tmp_path / "repository" / "git"
    exclusion.mkdir(parents=True)
    inventory = freeze_inventory(
        _plan(target, exclusion),
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
    )
    log_path = tmp_path / "occurrences.jsonl"
    occurrences = execute_inventory(
        inventory,
        occurrence_log_path=log_path,
        permission_log_path=tmp_path / "permissions.jsonl",
        authorization_digest=_authorization(inventory),
    )
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    rows[0]["item_digest"] = "sha256:" + "2" * 64
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(DeviceFreshResetError, match="reset_occurrence_log_invalid"):
        verify_inventory(inventory, occurrences=load_occurrences(log_path))

    receipt = build_reset_receipt(
        inventory=inventory,
        occurrences=occurrences,
        permission_adjustments=(),
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
        zero_scan_digest=DIGEST,
        fresh_bootstrap_receipt_digest=DIGEST,
        fresh_database_identity_digest=DIGEST,
    )
    receipt["product_authority"] = True
    with pytest.raises(DeviceFreshResetError, match="reset_receipt_invalid"):
        verify_reset_receipt(receipt)


def test_only_exact_new_inode_replacement_is_allowed_after_fresh_init(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "openzyme"
    target.mkdir(parents=True)
    database = target / "control-plane.sqlite3"
    database.write_bytes(b"old-database")
    exclusion = tmp_path / "repository" / "git"
    exclusion.mkdir(parents=True)
    inventory = freeze_inventory(
        _plan(target, exclusion),
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
    )
    log_path = tmp_path / "occurrences.jsonl"
    execute_inventory(
        inventory,
        occurrence_log_path=log_path,
        permission_log_path=tmp_path / "permissions.jsonl",
        authorization_digest=_authorization(inventory),
    )
    database.write_bytes(b"fresh-database")
    occurrences = load_occurrences(log_path)

    with pytest.raises(DeviceFreshResetError, match="recorded_path_reappeared"):
        verify_inventory(inventory, occurrences=occurrences)

    observed = database.lstat()
    verify_inventory(
        inventory,
        occurrences=occurrences,
        allowed_replacements={
            str(database): {
                "device": observed.st_dev,
                "inode": observed.st_ino,
                "content_digest": "sha256:"
                + hashlib.sha256(database.read_bytes()).hexdigest(),
            }
        },
    )
