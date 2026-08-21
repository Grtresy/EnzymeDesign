from __future__ import annotations

import sqlite3

from openzyme_contracts import RevisionPathVerificationReceipt


class SQLiteRevisionPathVerificationQuery:
    """Read immutable path receipts by their canonical PublishedRevision owner.

    ``RevisionPathVerificationReceipt`` deliberately has no denormalized Session
    field, so it cannot participate in the generic Session-slice query.  This
    Adapter-owned query follows the explicit publication foreign key and returns
    only closed, digest-verified contracts.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_for_publication(
        self,
        publication_id: str,
        *,
        max_items: int = 1_000,
    ) -> tuple[RevisionPathVerificationReceipt, ...]:
        if not publication_id:
            raise ValueError("publication_id must be non-empty")
        if not 1 <= max_items <= 1_000:
            raise ValueError("max_items must be between 1 and 1000")
        rows = self.connection.execute(
            """
            SELECT ref_id, publication_id, repository_binding_id,
                   repository_binding_version, commit_oid, tree_oid,
                   repository_path, object_id, actual_size_bytes,
                   actual_content_digest, lfs_oid, lfs_size_bytes,
                   verified_at, verification_digest
            FROM revision_path_verification_records
            WHERE publication_id = ?
            ORDER BY repository_path, ref_id
            LIMIT ?
            """,
            (publication_id, max_items + 1),
        ).fetchall()
        if len(rows) > max_items:
            raise ValueError("publication path verification query exceeded its budget")
        return tuple(
            RevisionPathVerificationReceipt(
                ref_id=str(row[0]),
                publication_id=str(row[1]),
                repository_binding_id=str(row[2]),
                repository_binding_version=int(row[3]),
                commit=str(row[4]),
                tree=str(row[5]),
                path=str(row[6]),
                object_id=str(row[7]),
                actual_size_bytes=None if row[8] is None else int(row[8]),
                actual_content_digest=None if row[9] is None else str(row[9]),
                lfs_oid=None if row[10] is None else str(row[10]),
                lfs_size_bytes=None if row[11] is None else int(row[11]),
                verified_at=str(row[12]),
                verification_digest=str(row[13]),
            )
            for row in rows
        )


__all__ = ["SQLiteRevisionPathVerificationQuery"]
