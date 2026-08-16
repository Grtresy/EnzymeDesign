from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_domain import HistoricalArtifactEligibility
from openzyme_domain import HistoricalArtifactMigrationReceipt
from openzyme_domain import HistoricalArtifactRef
from openzyme_domain import HistoricalArtifactStorage

from .repositories import _commit


class HistoricalArtifactRepositoryError(RuntimeError):
    error_code = "historical_artifact_repository_conflict"


@dataclass(slots=True)
class HistoricalArtifactRepository:
    connection: sqlite3.Connection

    def add_ref(self, record: HistoricalArtifactRef) -> HistoricalArtifactRef:
        existing = self.get_ref(record.historical_ref_id)
        if existing is not None:
            if existing == record:
                return existing
            raise HistoricalArtifactRepositoryError(
                "historical artifact ref identity conflicts"
            )
        self.connection.execute(
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
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record.historical_ref_id,
                record.original_artifact_id,
                record.original_kind,
                record.original_digest,
                record.original_size,
                record.project_id,
                record.session_id,
                record.owner_identity_digest,
                record.lineage_digest,
                record.source_snapshot_digest,
                record.migration_unit_id,
                record.repository_binding_id,
                record.repository_binding_version,
                record.historical_ref,
                record.historical_commit,
                record.historical_tree,
                record.path,
                record.storage.value,
                record.git_blob_oid,
                record.lfs_oid,
                record.lfs_size,
                record.verification_digest,
                record.eligibility.value,
                record.supersession_decision_digest,
                record.created_at,
                record.ref_digest,
            ),
        )
        _commit(self.connection)
        return record

    def get_ref(self, historical_ref_id: str) -> HistoricalArtifactRef | None:
        row = self.connection.execute(
            """
            SELECT * FROM historical_artifact_ref_records
            WHERE historical_ref_id = ?
            """,
            (historical_ref_id,),
        ).fetchone()
        return None if row is None else self._ref(row)

    def get_ref_by_original_id(
        self,
        original_artifact_id: str,
    ) -> HistoricalArtifactRef | None:
        row = self.connection.execute(
            """
            SELECT * FROM historical_artifact_ref_records
            WHERE original_artifact_id = ?
            """,
            (original_artifact_id,),
        ).fetchone()
        return None if row is None else self._ref(row)

    def add_global_receipt(
        self,
        receipt: HistoricalArtifactMigrationReceipt,
    ) -> HistoricalArtifactMigrationReceipt:
        existing = self.get_global_receipt(receipt.receipt_id)
        if existing is not None:
            if existing == receipt:
                return existing
            raise HistoricalArtifactRepositoryError(
                "historical global receipt identity conflicts"
            )
        self.connection.execute(
            """
            INSERT INTO historical_artifact_migration_global_receipts (
                receipt_id, inventory_digest,
                expected_global_identity_set_digest,
                migrated_global_identity_set_digest, unit_receipt_set_digest,
                mapping_set_digest, reference_rewrite_set_digest,
                git_lfs_closure_set_digest, non_adoption_set_digest,
                negative_item_count, source_preserved, created_at,
                receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.inventory_digest,
                receipt.expected_global_identity_set_digest,
                receipt.migrated_global_identity_set_digest,
                receipt.unit_receipt_set_digest,
                receipt.mapping_set_digest,
                receipt.reference_rewrite_set_digest,
                receipt.git_lfs_closure_set_digest,
                receipt.non_adoption_set_digest,
                receipt.negative_item_count,
                int(receipt.source_preserved),
                receipt.created_at,
                receipt.receipt_digest,
            ),
        )
        _commit(self.connection)
        return receipt

    def get_global_receipt(
        self,
        receipt_id: str,
    ) -> HistoricalArtifactMigrationReceipt | None:
        row = self.connection.execute(
            """
            SELECT * FROM historical_artifact_migration_global_receipts
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if row is None:
            return None
        return HistoricalArtifactMigrationReceipt(
            receipt_id=row["receipt_id"],
            inventory_digest=row["inventory_digest"],
            expected_global_identity_set_digest=(
                row["expected_global_identity_set_digest"]
            ),
            migrated_global_identity_set_digest=(
                row["migrated_global_identity_set_digest"]
            ),
            unit_receipt_set_digest=row["unit_receipt_set_digest"],
            mapping_set_digest=row["mapping_set_digest"],
            reference_rewrite_set_digest=row["reference_rewrite_set_digest"],
            git_lfs_closure_set_digest=row["git_lfs_closure_set_digest"],
            non_adoption_set_digest=row["non_adoption_set_digest"],
            negative_item_count=int(row["negative_item_count"]),
            source_preserved=bool(row["source_preserved"]),
            created_at=row["created_at"],
            receipt_digest=row["receipt_digest"],
        )

    @staticmethod
    def _ref(row: sqlite3.Row) -> HistoricalArtifactRef:
        return HistoricalArtifactRef(
            historical_ref_id=row["historical_ref_id"],
            original_artifact_id=row["original_artifact_id"],
            original_kind=row["original_kind"],
            original_digest=row["original_digest"],
            original_size=int(row["original_size"]),
            project_id=row["project_id"],
            session_id=row["session_id"],
            owner_identity_digest=row["owner_identity_digest"],
            lineage_digest=row["lineage_digest"],
            source_snapshot_digest=row["source_snapshot_digest"],
            migration_unit_id=row["migration_unit_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            historical_ref=row["historical_ref"],
            historical_commit=row["historical_commit"],
            historical_tree=row["historical_tree"],
            path=row["repository_path"],
            storage=HistoricalArtifactStorage(row["storage"]),
            git_blob_oid=row["git_blob_oid"],
            lfs_oid=row["lfs_oid"],
            lfs_size=None if row["lfs_size"] is None else int(row["lfs_size"]),
            verification_digest=row["verification_digest"],
            eligibility=HistoricalArtifactEligibility(row["eligibility"]),
            supersession_decision_digest=row["supersession_decision_digest"],
            created_at=row["created_at"],
            ref_digest=row["ref_digest"],
        )


__all__ = ["HistoricalArtifactRepository", "HistoricalArtifactRepositoryError"]
