from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Mapping
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

    def restore_safe_receipts_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> tuple[ExternalQualificationSafeReceipt, ...]: ...

    def record_occurrence_scope(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        source_identity_digest: str,
        unit_digests: tuple[str, ...],
    ) -> None: ...

    def restore_occurrence_scope(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[str, tuple[str, ...]] | None: ...

    def restore_occurrence_scopes_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> Mapping[str, tuple[str, tuple[str, ...]]]: ...

    def record_preparation_result(
        self, result: ExternalIdentityPreparationResult
    ) -> None: ...

    def restore_preparation_results_by_safe_identity(
        self,
        *,
        owner_component_id: str,
        safe_identity_fields: Mapping[str, str],
    ) -> tuple[ExternalIdentityPreparationResult, ...]: ...

    def record_probe_outcome(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        unit_digest: str,
        outcome: ExternalQualificationProbeOutcome,
    ) -> None: ...

    def record_occurrence_evidence(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        cleanup_receipt_digest: str,
        cleanup_resources: Mapping[str, dict[str, object]],
        budget_settlements: Mapping[str, dict[str, object]],
    ) -> None: ...

    def restore_occurrence_evidence_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> Mapping[str, dict[str, object]]: ...


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
                CREATE TABLE IF NOT EXISTS external_qualification_occurrence_evidence (
                    dry_plan_digest TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    cleanup_receipt_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (dry_plan_digest, authorization_digest)
                );
                CREATE TABLE IF NOT EXISTS external_qualification_occurrence_scopes (
                    dry_plan_digest TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    source_identity_digest TEXT NOT NULL,
                    unit_digests_json TEXT NOT NULL,
                    PRIMARY KEY (dry_plan_digest, authorization_digest)
                );
                """
            )
            scope_columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(external_qualification_occurrence_scopes)"
                ).fetchall()
            }
            if "source_identity_digest" not in scope_columns:
                connection.execute(
                    "ALTER TABLE external_qualification_occurrence_scopes "
                    "ADD COLUMN source_identity_digest TEXT"
                )
                connection.execute(
                    "UPDATE external_qualification_occurrence_scopes "
                    "SET source_identity_digest = ? "
                    "WHERE source_identity_digest IS NULL",
                    ("sha256:" + "0" * 64,),
                )

    def record_occurrence_scope(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        source_identity_digest: str,
        unit_digests: tuple[str, ...],
    ) -> None:
        for field_name, value in (
            ("dry_plan_digest", dry_plan_digest),
            ("authorization_digest", authorization_digest),
            ("source_identity_digest", source_identity_digest),
        ):
            require_digest(value, field_name=field_name)
        canonical_units = tuple(sorted(unit_digests))
        if not canonical_units or len(set(canonical_units)) != len(canonical_units):
            raise ValueError("qualification occurrence scope must be non-empty and unique")
        for unit_digest in canonical_units:
            require_digest(unit_digest, field_name="unit_digest")
        payload = json.dumps(canonical_units, separators=(",", ":"))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT source_identity_digest, unit_digests_json "
                "FROM external_qualification_occurrence_scopes "
                "WHERE dry_plan_digest = ? AND authorization_digest = ?",
                (dry_plan_digest, authorization_digest),
            ).fetchone()
            if existing is not None:
                if existing != (source_identity_digest, payload):
                    raise ValueError("qualification occurrence scope cannot drift")
                return
            connection.execute(
                "INSERT INTO external_qualification_occurrence_scopes "
                "(dry_plan_digest, authorization_digest, source_identity_digest, "
                "unit_digests_json) VALUES (?, ?, ?, ?)",
                (
                    dry_plan_digest,
                    authorization_digest,
                    source_identity_digest,
                    payload,
                ),
            )

    def restore_occurrence_scope(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[str, tuple[str, ...]] | None:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        require_digest(authorization_digest, field_name="authorization_digest")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT source_identity_digest, unit_digests_json "
                "FROM external_qualification_occurrence_scopes "
                "WHERE dry_plan_digest = ? AND authorization_digest = ?",
                (dry_plan_digest, authorization_digest),
            ).fetchone()
        if row is None:
            return None
        values = json.loads(row[1])
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError("qualification occurrence scope payload is invalid")
        return str(row[0]), tuple(values)

    def restore_occurrence_scopes_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> dict[str, tuple[str, tuple[str, ...]]]:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT authorization_digest, source_identity_digest, "
                "unit_digests_json "
                "FROM external_qualification_occurrence_scopes "
                "WHERE dry_plan_digest = ? ORDER BY authorization_digest",
                (dry_plan_digest,),
            ).fetchall()
        scopes: dict[str, tuple[str, tuple[str, ...]]] = {}
        for authorization_digest, source_identity_digest, payload_json in rows:
            values = json.loads(payload_json)
            if not isinstance(values, list) or not all(
                isinstance(item, str) for item in values
            ):
                raise ValueError("qualification occurrence scope payload is invalid")
            scopes[str(authorization_digest)] = (
                str(source_identity_digest),
                tuple(values),
            )
        return scopes

    def record_occurrence_evidence(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        cleanup_receipt_digest: str,
        cleanup_resources: Mapping[str, dict[str, object]],
        budget_settlements: Mapping[str, dict[str, object]],
    ) -> None:
        for field_name, value in (
            ("dry_plan_digest", dry_plan_digest),
            ("authorization_digest", authorization_digest),
            ("cleanup_receipt_digest", cleanup_receipt_digest),
        ):
            require_digest(value, field_name=field_name)
        payload = {
            "schema_version": "external_qualification_occurrence_evidence@1",
            "dry_plan_digest": dry_plan_digest,
            "authorization_digest": authorization_digest,
            "cleanup_receipt_digest": cleanup_receipt_digest,
            "cleanup_resources": cleanup_resources,
            "budget_settlements": budget_settlements,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM external_qualification_occurrence_evidence "
                "WHERE dry_plan_digest = ? AND authorization_digest = ?",
                (dry_plan_digest, authorization_digest),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload_json:
                    raise ValueError(
                        "qualification occurrence evidence cannot be overwritten"
                    )
                return
            connection.execute(
                "INSERT INTO external_qualification_occurrence_evidence "
                "(dry_plan_digest, authorization_digest, cleanup_receipt_digest, "
                "payload_json) VALUES (?, ?, ?, ?)",
                (
                    dry_plan_digest,
                    authorization_digest,
                    cleanup_receipt_digest,
                    payload_json,
                ),
            )

    def restore_occurrence_evidence(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> dict[str, object] | None:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        require_digest(authorization_digest, field_name="authorization_digest")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM external_qualification_occurrence_evidence "
                "WHERE dry_plan_digest = ? AND authorization_digest = ?",
                (dry_plan_digest, authorization_digest),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def restore_occurrence_evidence_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> dict[str, dict[str, object]]:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT authorization_digest, payload_json "
                "FROM external_qualification_occurrence_evidence "
                "WHERE dry_plan_digest = ? ORDER BY authorization_digest",
                (dry_plan_digest,),
            ).fetchall()
        return {str(item[0]): json.loads(item[1]) for item in rows}

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

    def restore_safe_receipts_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> tuple[ExternalQualificationSafeReceipt, ...]:
        require_digest(dry_plan_digest, field_name="dry_plan_digest")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM external_qualification_safe_receipts "
                "ORDER BY unit_digest, receipt_digest"
            ).fetchall()
        return tuple(
            receipt
            for (payload_json,) in rows
            for receipt in (
                ExternalQualificationSafeReceipt.from_dict(json.loads(payload_json)),
            )
            if receipt.dry_plan_digest == dry_plan_digest
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

    def restore_preparation_results_by_safe_identity(
        self,
        *,
        owner_component_id: str,
        safe_identity_fields: Mapping[str, str],
    ) -> tuple[ExternalIdentityPreparationResult, ...]:
        if not owner_component_id or not safe_identity_fields:
            raise ValueError("preparation identity lookup must be exact and non-empty")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM external_identity_preparation_results "
                "ORDER BY occurrence_id"
            ).fetchall()
        expected = dict(safe_identity_fields)
        matches = []
        for (payload_json,) in rows:
            result = ExternalIdentityPreparationResult.from_dict(
                json.loads(payload_json)
            )
            fields = {
                item.field_id: item.value for item in result.safe_identity_fields
            }
            if result.owner_component_id == owner_component_id and all(
                fields.get(field_id) == value
                for field_id, value in expected.items()
            ):
                matches.append(result)
        return tuple(matches)

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
