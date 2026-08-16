"""Pure contract for the future receipt-gated offline removal executable.

This module deliberately lives with the OpenSpec operator artifacts.  It is not
an application entry point, package export, migration asset, or runtime fallback.
It performs no database, filesystem, Git, LFS, provider, runner, or network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable
from typing import Mapping


REMOVAL_MANIFEST_SCHEMA_ID = "artifact_subsystem_removal_manifest@1"
REMOVAL_DRY_RUN_SCHEMA_ID = "artifact_subsystem_removal_dry_run@1"
FINAL_SCHEMA_GENERATION = "openzyme_file_workspace_final@1"
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

PREREQUISITE_CHANGE_IDS = (
    "supersede-aox-hmm-artifact-cutover",
    "establish-project-repository-bindings",
    "establish-agent-capability-leases",
    "provision-independent-agent-git-workspaces",
    "publish-and-sync-workspace-revisions",
    "support-git-lfs-work-products",
    "migrate-research-report-and-task-handoffs-to-files",
    "provision-isolated-executor-hpc-workspaces",
    "execute-hpc-jobs-from-workspace-revisions",
    "migrate-scientific-deliverables-to-files",
    "replace-sandbox-artifact-boundaries-with-files",
    "cut-over-workspace-public-interfaces",
    "migrate-historical-artifacts-to-git-lfs",
)


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class RemovalAdmissionError(RuntimeError):
    error_code = "artifact_subsystem_removal_not_admitted"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.details = {
            "schema_id": "artifact_subsystem_removal_rejection@1",
            "reason": reason,
            "migration_authority_issued": False,
            "database_mutated": False,
            "storage_mutated": False,
        }


def _require_digest(value: str, field_name: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise RemovalAdmissionError(f"{field_name} is not an exact sha256 digest")


@dataclass(frozen=True, slots=True)
class PrerequisiteCompletionReceipt:
    change_id: str
    receipt_schema_id: str
    source_revision: str
    schema_identity_digest: str
    contract_identity_digest: str
    activation_epoch: int
    accepted: bool
    superseded: bool
    transitive_receipt_digest: str
    receipt_digest: str

    def validate(self) -> None:
        if not self.receipt_schema_id or not self.source_revision:
            raise RemovalAdmissionError(
                f"{self.change_id} receipt identity is incomplete"
            )
        if self.activation_epoch < 1 or not self.accepted or self.superseded:
            raise RemovalAdmissionError(
                f"{self.change_id} is not accepted in an active epoch"
            )
        for field_name in (
            "schema_identity_digest",
            "contract_identity_digest",
            "transitive_receipt_digest",
            "receipt_digest",
        ):
            _require_digest(str(getattr(self, field_name)), field_name)


@dataclass(frozen=True, slots=True)
class HistoricalMigrationProof:
    receipt_schema_id: str
    receipt_digest: str
    inventory_generation: int
    inventory_digest: str
    database_snapshot_digest: str
    storage_snapshot_digest: str
    expected_identity_set_digest: str
    migrated_identity_set_digest: str
    unit_receipt_set_digest: str
    target_readback_set_digest: str
    reference_rewrite_set_digest: str
    expected_row_count: int
    migrated_row_count: int
    expected_object_count: int
    migrated_object_count: int
    expected_byte_count: int
    migrated_byte_count: int
    unresolved_reference_count: int
    post_freeze_write_count: int
    aox_non_adoption_proven: bool
    source_preserved: bool

    def validate(self) -> None:
        if self.receipt_schema_id != "historical_artifact_migration_receipt@1":
            raise RemovalAdmissionError("historical receipt schema is unsupported")
        if self.inventory_generation < 1:
            raise RemovalAdmissionError("historical inventory generation is invalid")
        for field_name in (
            "receipt_digest",
            "inventory_digest",
            "database_snapshot_digest",
            "storage_snapshot_digest",
            "expected_identity_set_digest",
            "migrated_identity_set_digest",
            "unit_receipt_set_digest",
            "target_readback_set_digest",
            "reference_rewrite_set_digest",
        ):
            _require_digest(str(getattr(self, field_name)), field_name)
        exact_pairs = (
            (self.expected_identity_set_digest, self.migrated_identity_set_digest),
            (self.expected_row_count, self.migrated_row_count),
            (self.expected_object_count, self.migrated_object_count),
            (self.expected_byte_count, self.migrated_byte_count),
        )
        if any(expected != actual for expected, actual in exact_pairs):
            raise RemovalAdmissionError("historical exact-set proof drifted")
        if min(
            self.expected_row_count,
            self.expected_object_count,
            self.expected_byte_count,
        ) < 0:
            raise RemovalAdmissionError("historical inventory count is invalid")
        if self.unresolved_reference_count or self.post_freeze_write_count:
            raise RemovalAdmissionError("historical source is not frozen and closed")
        if not self.aox_non_adoption_proven or not self.source_preserved:
            raise RemovalAdmissionError(
                "historical non-adoption or source preservation is unproven"
            )


@dataclass(frozen=True, slots=True)
class QuiescenceAndBackupProof:
    maintenance_mode: bool
    host_stopped: bool
    mutation_consumers_stopped: bool
    sandbox_and_execution_stopped: bool
    runner_callbacks_stopped: bool
    ui_writes_stopped: bool
    unsettled_external_effect_count: int
    active_writer_count: int
    writer_fence_high_watermark: int
    quiescence_receipt_digest: str
    database_backup_digest: str
    storage_backup_digest: str
    isolated_recovery_only: bool

    def validate(self) -> None:
        stopped = (
            self.maintenance_mode,
            self.host_stopped,
            self.mutation_consumers_stopped,
            self.sandbox_and_execution_stopped,
            self.runner_callbacks_stopped,
            self.ui_writes_stopped,
            self.isolated_recovery_only,
        )
        if not all(stopped):
            raise RemovalAdmissionError("deployment is not quiescent")
        if (
            self.unsettled_external_effect_count != 0
            or self.active_writer_count != 0
            or self.writer_fence_high_watermark < 0
        ):
            raise RemovalAdmissionError("writer or external-effect closure is incomplete")
        for field_name in (
            "quiescence_receipt_digest",
            "database_backup_digest",
            "storage_backup_digest",
        ):
            _require_digest(str(getattr(self, field_name)), field_name)


@dataclass(frozen=True, slots=True)
class SchemaRebuildEntry:
    source_table: str
    final_table: str
    source_schema_digest: str
    final_schema_digest: str
    typed_replacement_set_digest: str
    expected_row_identity_set_digest: str


@dataclass(frozen=True, slots=True)
class LegacyStorageDeletionTarget:
    object_identity: str
    allowlisted_root_identity: str
    relative_path: str
    content_digest: str
    size_bytes: int
    non_symlink: bool

    def validate(self) -> None:
        if (
            not self.object_identity
            or not self.allowlisted_root_identity
            or not self.relative_path
            or self.relative_path.startswith("/")
            or ".." in self.relative_path.split("/")
            or self.size_bytes < 0
            or not self.non_symlink
        ):
            raise RemovalAdmissionError("legacy storage target is not exactly bounded")
        _require_digest(self.content_digest, "legacy storage content_digest")


@dataclass(frozen=True, slots=True)
class RemovalManifest:
    prerequisite_receipt_digests: tuple[str, ...]
    historical_receipt_digest: str
    current_inventory_digest: str
    final_schema_manifest_digest: str
    rebuild_plan_digest: str
    drop_set_digest: str
    storage_deletion_set_digest: str
    expected_storage_bytes: int
    writer_fence_high_watermark: int
    manifest_digest: str
    schema_id: str = REMOVAL_MANIFEST_SCHEMA_ID


@dataclass(frozen=True, slots=True)
class RemovalDryRun:
    manifest: RemovalManifest
    rebuild_entries: tuple[SchemaRebuildEntry, ...]
    drop_structures: tuple[str, ...]
    storage_targets: tuple[LegacyStorageDeletionTarget, ...]
    migration_authority_issued: bool = False
    database_mutated: bool = False
    storage_mutated: bool = False
    schema_id: str = REMOVAL_DRY_RUN_SCHEMA_ID


def build_removal_dry_run(
    *,
    prerequisite_receipts: Iterable[PrerequisiteCompletionReceipt],
    historical_proof: HistoricalMigrationProof,
    quiescence_and_backup: QuiescenceAndBackupProof,
    current_inventory_digest: str,
    final_schema_manifest_digest: str,
    rebuild_entries: Iterable[SchemaRebuildEntry],
    drop_structures: Iterable[str],
    storage_targets: Iterable[LegacyStorageDeletionTarget],
) -> RemovalDryRun:
    receipts_by_id: Mapping[str, PrerequisiteCompletionReceipt] = {
        receipt.change_id: receipt for receipt in prerequisite_receipts
    }
    if tuple(receipts_by_id) != PREREQUISITE_CHANGE_IDS:
        raise RemovalAdmissionError(
            "prerequisite receipts are missing, duplicated, extra, or out of order"
        )
    for receipt in receipts_by_id.values():
        receipt.validate()
    historical_proof.validate()
    quiescence_and_backup.validate()
    _require_digest(current_inventory_digest, "current_inventory_digest")
    _require_digest(final_schema_manifest_digest, "final_schema_manifest_digest")

    rebuild = tuple(rebuild_entries)
    drops = tuple(drop_structures)
    targets = tuple(storage_targets)
    if len(drops) != len(set(drops)) or len(targets) != len(
        {target.object_identity for target in targets}
    ):
        raise RemovalAdmissionError("removal plan contains duplicate identities")
    for entry in rebuild:
        if not entry.source_table or not entry.final_table:
            raise RemovalAdmissionError("schema rebuild identity is incomplete")
        for value in (
            entry.source_schema_digest,
            entry.final_schema_digest,
            entry.typed_replacement_set_digest,
            entry.expected_row_identity_set_digest,
        ):
            _require_digest(value, "schema rebuild digest")
    for target in targets:
        target.validate()

    prerequisite_digests = tuple(
        receipts_by_id[change_id].receipt_digest
        for change_id in PREREQUISITE_CHANGE_IDS
    )
    rebuild_digest = canonical_digest(
        [
            {
                "source_table": entry.source_table,
                "final_table": entry.final_table,
                "source_schema_digest": entry.source_schema_digest,
                "final_schema_digest": entry.final_schema_digest,
                "typed_replacement_set_digest": entry.typed_replacement_set_digest,
                "expected_row_identity_set_digest": (
                    entry.expected_row_identity_set_digest
                ),
            }
            for entry in rebuild
        ]
    )
    drop_set_digest = canonical_digest(list(drops))
    deletion_set_digest = canonical_digest(
        [
            {
                "object_identity": target.object_identity,
                "allowlisted_root_identity": target.allowlisted_root_identity,
                "relative_path": target.relative_path,
                "content_digest": target.content_digest,
                "size_bytes": target.size_bytes,
            }
            for target in targets
        ]
    )
    payload = {
        "schema_id": REMOVAL_MANIFEST_SCHEMA_ID,
        "prerequisite_receipt_digests": prerequisite_digests,
        "historical_receipt_digest": historical_proof.receipt_digest,
        "current_inventory_digest": current_inventory_digest,
        "final_schema_manifest_digest": final_schema_manifest_digest,
        "rebuild_plan_digest": rebuild_digest,
        "drop_set_digest": drop_set_digest,
        "storage_deletion_set_digest": deletion_set_digest,
        "expected_storage_bytes": sum(target.size_bytes for target in targets),
        "writer_fence_high_watermark": (
            quiescence_and_backup.writer_fence_high_watermark
        ),
    }
    manifest = RemovalManifest(**payload, manifest_digest=canonical_digest(payload))
    return RemovalDryRun(
        manifest=manifest,
        rebuild_entries=rebuild,
        drop_structures=drops,
        storage_targets=targets,
    )


__all__ = [
    "FINAL_SCHEMA_GENERATION",
    "PREREQUISITE_CHANGE_IDS",
    "HistoricalMigrationProof",
    "LegacyStorageDeletionTarget",
    "PrerequisiteCompletionReceipt",
    "QuiescenceAndBackupProof",
    "RemovalAdmissionError",
    "RemovalDryRun",
    "RemovalManifest",
    "SchemaRebuildEntry",
    "build_removal_dry_run",
    "canonical_digest",
]
