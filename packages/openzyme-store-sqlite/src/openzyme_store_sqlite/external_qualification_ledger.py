from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Protocol

from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationSafeReceipt
from openzyme_contracts import ExternalIdentityPreparationResult


class ProtectedQualificationLedgerPort(Protocol):
    def record_dry_plan(self, plan: ExternalQualificationDryPlan) -> None: ...

    def record_safe_receipt(self, receipt: ExternalQualificationSafeReceipt) -> None: ...

    def record_preparation_result(
        self, result: ExternalIdentityPreparationResult
    ) -> None: ...


class SQLiteProtectedQualificationLedger:
    """Adapter-owned protected ledger; public values are contract-safe JSON only."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_qualification_dry_plans (
                    dry_plan_digest TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS external_qualification_safe_receipts (
                    receipt_digest TEXT PRIMARY KEY,
                    unit_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS external_identity_preparation_results (
                    result_digest TEXT PRIMARY KEY,
                    occurrence_id TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL,
                    preparation_plan_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def record_dry_plan(self, plan: ExternalQualificationDryPlan) -> None:
        payload = json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO external_qualification_dry_plans "
                "(dry_plan_digest, batch_id, payload_json) VALUES (?, ?, ?)",
                (plan.dry_plan_digest, plan.batch_id, payload),
            )

    def record_safe_receipt(self, receipt: ExternalQualificationSafeReceipt) -> None:
        payload = json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO external_qualification_safe_receipts "
                "(receipt_digest, unit_digest, payload_json) VALUES (?, ?, ?)",
                (receipt.receipt_digest, receipt.unit_digest, payload),
            )

    def record_preparation_result(
        self, result: ExternalIdentityPreparationResult
    ) -> None:
        payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT result_digest FROM external_identity_preparation_results "
                "WHERE occurrence_id = ?",
                (result.occurrence_id,),
            ).fetchone()
            if existing is not None and existing[0] != result.result_digest:
                raise ValueError(
                    "preparation occurrence already binds a different result digest"
                )
            connection.execute(
                "INSERT OR IGNORE INTO external_identity_preparation_results "
                "(result_digest, occurrence_id, action_id, preparation_plan_digest, "
                "payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    result.result_digest,
                    result.occurrence_id,
                    result.action_id,
                    result.preparation_plan_digest,
                    payload,
                ),
            )

    def read_dry_plan(self, dry_plan_digest: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM external_qualification_dry_plans "
                "WHERE dry_plan_digest = ?",
                (dry_plan_digest,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def read_preparation_results(
        self, preparation_plan_digest: str
    ) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM external_identity_preparation_results "
                "WHERE preparation_plan_digest = ? ORDER BY action_id",
                (preparation_plan_digest,),
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def restore_preparation_results(
        self, preparation_plan_digest: str
    ) -> tuple[ExternalIdentityPreparationResult, ...]:
        return tuple(
            ExternalIdentityPreparationResult.from_dict(payload)
            for payload in self.read_preparation_results(preparation_plan_digest)
        )


__all__ = [
    "ProtectedQualificationLedgerPort",
    "SQLiteProtectedQualificationLedger",
]
