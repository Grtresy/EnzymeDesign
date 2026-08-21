from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from openzyme_store_sqlite.device_fresh_reset import DeviceFreshResetError
from openzyme_store_sqlite.device_fresh_reset import build_reset_receipt
from openzyme_store_sqlite.device_fresh_reset import canonical_digest
from openzyme_store_sqlite.device_fresh_reset import execute_inventory
from openzyme_store_sqlite.device_fresh_reset import freeze_inventory
from openzyme_store_sqlite.device_fresh_reset import load_occurrences
from openzyme_store_sqlite.device_fresh_reset import load_permission_adjustments
from openzyme_store_sqlite.device_fresh_reset import verify_inventory
from openzyme_store_sqlite.device_fresh_reset import verify_reset_receipt


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
                "component_kind": "control_store",
                "component_owner": "openzyme.store.sqlite",
                "distribution_id": "enzymedesign",
                "distribution_manifest_digest": DIGEST,
                "ownership_scope": "exact_tree",
            }
        ],
        "exclusions": [
            {
                "path": str(exclusion),
                "exclusion_kind": "current_repository_git_lfs_truth",
                "reason": "must survive the device reset",
            },
            {
                "path": str(exclusion.parent / "source"),
                "exclusion_kind": "source_tree",
                "reason": "source is not deployment state",
            },
            {
                "path": str(exclusion.parent / "git-history"),
                "exclusion_kind": "git_history",
                "reason": "Git history is protected",
            },
            {
                "path": str(exclusion.parent / "openspec-history"),
                "exclusion_kind": "openspec_history",
                "reason": "OpenSpec history is protected",
            },
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
        built_wheel_set_digest=DIGEST,
        documentation_set_digest=DIGEST,
        target_distribution_id="enzymedesign",
        target_distribution_version="0.1.0",
        target_distribution_manifest_digest=DIGEST,
        target_composition_bundle_digest=DIGEST,
    )
    verify_reset_receipt(receipt)
    assert receipt["schema_version"] == "device_fresh_install_reset_receipt@2"
    assert receipt["built_wheel_set_digest"] == DIGEST
    assert receipt["target_distribution_id"] == "enzymedesign"


def test_at2_inventory_requires_component_identity_and_all_exclusions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "openzyme"
    target.mkdir(parents=True)
    (target / "old").write_text("old", encoding="utf-8")
    exclusion = tmp_path / "protected" / "repository"
    exclusion.mkdir(parents=True)
    plan = _plan(target, exclusion)
    del plan["targets"][0]["component_owner"]
    with pytest.raises(DeviceFreshResetError, match="reset_target_owner_missing"):
        freeze_inventory(plan, source_identity=DIGEST, quiescence_digest=DIGEST)

    plan = _plan(target, exclusion)
    plan["exclusions"] = plan["exclusions"][:-1]
    with pytest.raises(
        DeviceFreshResetError, match="reset_required_exclusion_missing"
    ):
        freeze_inventory(plan, source_identity=DIGEST, quiescence_digest=DIGEST)


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
        built_wheel_set_digest=DIGEST,
        documentation_set_digest=DIGEST,
        target_distribution_id="enzymedesign",
        target_distribution_version="0.1.0",
        target_distribution_manifest_digest=DIGEST,
        target_composition_bundle_digest=DIGEST,
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
                "fresh_bootstrap_receipt_digest": DIGEST,
            }
        },
    )


def test_fresh_replacement_allows_inode_reuse_only_with_bootstrap_proof(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state"
    target.mkdir()
    database = target / "control-plane.sqlite3"
    database.write_bytes(b"old")
    exclusion = tmp_path / "protected"
    exclusion.mkdir()
    inventory = freeze_inventory(
        {
            **_plan(database, exclusion),
            "targets": [
                {
                    **_plan(database, exclusion)["targets"][0],
                    "preserve_root": False,
                }
            ],
        },
        source_identity=DIGEST,
        quiescence_digest=DIGEST,
    )
    occurrences = execute_inventory(
        inventory,
        occurrence_log_path=tmp_path / "occurrences.jsonl",
        permission_log_path=tmp_path / "permissions.jsonl",
        authorization_digest=_authorization(inventory),
    )
    database.write_bytes(b"fresh")
    observed = database.stat()
    replacement = {
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "content_digest": "sha256:"
        + hashlib.sha256(database.read_bytes()).hexdigest(),
    }
    with pytest.raises(DeviceFreshResetError, match="recorded_path_reappeared"):
        verify_inventory(
            inventory,
            occurrences={row["path"]: row for row in occurrences},
            allowed_replacements={str(database): replacement},
        )
    replacement["fresh_bootstrap_receipt_digest"] = DIGEST
    verify_inventory(
        inventory,
        occurrences={row["path"]: row for row in occurrences},
        allowed_replacements={str(database): replacement},
    )
