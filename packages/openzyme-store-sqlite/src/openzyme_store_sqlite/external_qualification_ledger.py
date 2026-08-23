from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Protocol

from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationSafeReceipt
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import require_digest


class ProtectedQualificationLedgerPort(Protocol):
    def record_dry_plan(self, plan: ExternalQualificationDryPlan) -> None: ...

    def record_safe_receipt(self, receipt: ExternalQualificationSafeReceipt) -> None: ...

    def record_safe_receipts(
        self, receipts: tuple[ExternalQualificationSafeReceipt, ...]
    ) -> None: ...

    def restore_safe_receipts(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[ExternalQualificationSafeReceipt, ...]: ...

    def record_preparation_result(
        self, result: ExternalIdentityPreparationResult
    ) -> None: ...

    def record_probe_outcome(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        unit_digest: str,
        outcome: ExternalQualificationProbeOutcome,
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
                CREATE TABLE IF NOT EXISTS external_qualification_probe_outcomes (
                    attempt_id TEXT PRIMARY KEY,
                    dry_plan_digest TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    unit_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (dry_plan_digest, authorization_digest, unit_digest)
                );
                """
            )

    def record_probe_outcome(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        unit_digest: str,
        outcome: ExternalQualificationProbeOutcome,
    ) -> None:
        for field_name, value in (
            ("dry_plan_digest", dry_plan_digest),
            ("authorization_digest", authorization_digest),
            ("unit_digest", unit_digest),
        ):
            require_digest(value, field_name=field_name)
        payload = json.dumps(outcome.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT dry_plan_digest, authorization_digest, unit_digest, "
                "request_digest, disposition, payload_json "
                "FROM external_qualification_probe_outcomes "
                "WHERE attempt_id = ? OR "
                "(dry_plan_digest = ? AND authorization_digest = ? AND unit_digest = ?)",
                (
                    outcome.attempt_id,
                    dry_plan_digest,
                    authorization_digest,
                    unit_digest,
                ),
            ).fetchone()
            expected = (
                dry_plan_digest,
                authorization_digest,
                unit_digest,
                outcome.request_digest,
            )
            if existing is not None:
                identity = tuple(existing[:4])
                prior_disposition = str(existing[4])
                prior_payload = str(existing[5])
                if identity != expected:
                    raise ValueError(
                        "qualification occurrence already binds a different probe identity"
                    )
                if prior_payload == payload:
                    return
                if prior_disposition != "reconcile_required":
                    raise ValueError(
                        "terminal qualification outcome cannot be overwritten"
                    )
                if outcome.disposition.value == "reconcile_required":
                    raise ValueError(
                        "in-doubt qualification outcome cannot be replaced by another"
                    )
                connection.execute(
                    "UPDATE external_qualification_probe_outcomes "
                    "SET disposition = ?, payload_json = ? WHERE attempt_id = ?",
                    (outcome.disposition.value, payload, outcome.attempt_id),
                )
                return
            connection.execute(
                "INSERT OR IGNORE INTO external_qualification_probe_outcomes "
                "(attempt_id, dry_plan_digest, authorization_digest, unit_digest, "
                "request_digest, disposition, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome.attempt_id,
                    dry_plan_digest,
                    authorization_digest,
                    unit_digest,
                    outcome.request_digest,
                    outcome.disposition.value,
                    payload,
                ),
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
        self.record_safe_receipts((receipt,))

    def record_safe_receipts(
        self,
        receipts: tuple[ExternalQualificationSafeReceipt, ...],
    ) -> None:
        if len({item.unit_digest for item in receipts}) != len(receipts):
            raise ValueError("qualification safe receipt batch units must be unique")
        with self._connect() as connection:
            for receipt in receipts:
                payload = json.dumps(
                    receipt.to_dict(), sort_keys=True, separators=(",", ":")
                )
                connection.execute(
                    "INSERT OR IGNORE INTO external_qualification_safe_receipts "
                    "(receipt_digest, unit_digest, payload_json) VALUES (?, ?, ?)",
                    (receipt.receipt_digest, receipt.unit_digest, payload),
                )

    def restore_safe_receipts(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[ExternalQualificationSafeReceipt, ...]:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        require_digest(authorization_digest, field_name="authorization_digest")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM external_qualification_safe_receipts "
                "ORDER BY unit_digest"
            ).fetchall()
        return tuple(
            receipt
            for (payload_json,) in rows
            for receipt in (
                ExternalQualificationSafeReceipt.from_dict(json.loads(payload_json)),
            )
            if receipt.dry_plan_digest == dry_plan_digest
            and receipt.authorization_digest == authorization_digest
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
        self,
        preparation_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[ExternalIdentityPreparationResult, ...]:
        require_digest(authorization_digest, field_name="authorization_digest")
        return tuple(
            ExternalIdentityPreparationResult.from_dict(payload)
            for payload in self.read_preparation_results(preparation_plan_digest)
            if payload.get("authorization_digest") == authorization_digest
        )

    def restore_probe_outcomes(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[tuple[str, ExternalQualificationProbeOutcome], ...]:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        require_digest(authorization_digest, field_name="authorization_digest")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unit_digest, payload_json "
                "FROM external_qualification_probe_outcomes "
                "WHERE dry_plan_digest = ? AND authorization_digest = ? "
                "ORDER BY unit_digest",
                (dry_plan_digest, authorization_digest),
            ).fetchall()
        return tuple(
            (str(unit_digest), ExternalQualificationProbeOutcome.from_dict(json.loads(payload)))
            for unit_digest, payload in rows
        )


__all__ = [
    "ProtectedQualificationLedgerPort",
    "SQLiteProtectedQualificationLedger",
]
