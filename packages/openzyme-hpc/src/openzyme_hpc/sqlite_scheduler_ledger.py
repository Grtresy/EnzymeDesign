from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import sqlite3
import threading

from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import json_compatible
from openzyme_contracts import require_identifier

from .scheduler import PrivateSchedulerHandleRecord
from .scheduler import SchedulerDispatchReceipt
from .scheduler import SchedulerOccurrenceIdentity
from .scheduler import SchedulerOccurrenceKind
from .scheduler import SchedulerOccurrenceRecord


_TABLE = "openzyme_hpc_scheduler_occurrences"


class SQLiteSchedulerOccurrenceLedgerError(RuntimeError):
    error_code = "sqlite_scheduler_occurrence_ledger_rejected"

    def __init__(self, message: str, *, phase: str) -> None:
        self.phase = require_identifier(phase, field_name="phase")
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; mutation_applied=false; "
            "fallback_performed=false"
        )


@dataclass(slots=True)
class SQLiteSchedulerOccurrenceLedger:
    """HPC-owned durable scheduler occurrence and private-handle ledger."""

    connection: sqlite3.Connection
    clock: ClockPort
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (_TABLE,),
        ).fetchone()
        if row is None:
            raise SQLiteSchedulerOccurrenceLedgerError(
                "scheduler ledger requires the mounted HPC migration",
                phase="schema_admission",
            )

    def read(
        self,
        identity: SchedulerOccurrenceIdentity,
    ) -> SchedulerOccurrenceRecord | None:
        with self._lock:
            row = self.connection.execute(
                f"""
                SELECT ledger_version, record_json, record_digest
                FROM {_TABLE}
                WHERE provider_id = ? AND operation_id = ?
                """,
                (identity.provider_id, identity.operation_id),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row[1]))
            record = SchedulerOccurrenceRecord.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SQLiteSchedulerOccurrenceLedgerError(
                "scheduler occurrence payload is not closed",
                phase="decode",
            ) from exc
        if (
            record.identity != identity
            or record.ledger_version != int(row[0])
            or record.record_digest != row[2]
        ):
            raise SQLiteSchedulerOccurrenceLedgerError(
                "scheduler occurrence identity or digest drifted",
                phase="identity",
            )
        return record

    def reserve(self, identity: SchedulerOccurrenceIdentity) -> bool:
        record = SchedulerOccurrenceRecord(identity=identity, receipt=None)
        with self._lock:
            self._require_standalone()
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                cursor = self.connection.execute(
                    f"""
                    INSERT OR IGNORE INTO {_TABLE} (
                        provider_id, operation_kind, operation_id, request_digest,
                        ledger_version, opaque_handle_id, raw_scheduler_id,
                        record_digest, record_json, updated_at
                    ) VALUES (?, ?, ?, ?, 1, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        identity.provider_id,
                        identity.operation_kind.value,
                        identity.operation_id,
                        identity.request_digest,
                        record.record_digest,
                        _json(record.to_dict()),
                        self.clock.now_iso(),
                    ),
                )
                self.connection.commit()
            except Exception:
                if self.connection.in_transaction:
                    self.connection.rollback()
                raise
        if cursor.rowcount == 1:
            return True
        existing = self.read(identity)
        if existing is None:
            raise SQLiteSchedulerOccurrenceLedgerError(
                "scheduler occurrence reservation disappeared",
                phase="reserve",
            )
        return False

    def settle(
        self,
        identity: SchedulerOccurrenceIdentity,
        receipt: SchedulerDispatchReceipt,
        *,
        raw_scheduler_id: str | None = None,
    ) -> SchedulerOccurrenceRecord:
        if (
            receipt.operation_id != identity.operation_id
            or receipt.request_digest != identity.request_digest
        ):
            raise SQLiteSchedulerOccurrenceLedgerError(
                "scheduler receipt crossed its reserved identity",
                phase="receipt_identity",
            )
        if raw_scheduler_id is not None:
            require_identifier(raw_scheduler_id, field_name="raw_scheduler_id")
        with self._lock:
            current = self.read(identity)
            if current is None:
                raise SQLiteSchedulerOccurrenceLedgerError(
                    "scheduler occurrence must be reserved before settlement",
                    phase="settle_admission",
                )
            if current.receipt == receipt and current.raw_scheduler_id == raw_scheduler_id:
                return current
            if current.receipt is not None and (
                current.receipt.effect_certainty
                is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ):
                raise SQLiteSchedulerOccurrenceLedgerError(
                    "terminal scheduler occurrence cannot be replaced",
                    phase="settle_terminal",
                )
            if (
                current.receipt is not None
                and receipt.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ):
                raise SQLiteSchedulerOccurrenceLedgerError(
                    "uncertain scheduler occurrence cannot regress",
                    phase="settle_progress",
                )
            updated = SchedulerOccurrenceRecord(
                identity=identity,
                receipt=receipt,
                raw_scheduler_id=raw_scheduler_id,
                ledger_version=current.ledger_version + 1,
            )
            handle = updated.private_handle()
            self._require_standalone()
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                cursor = self.connection.execute(
                    f"""
                    UPDATE {_TABLE}
                    SET ledger_version = ?, opaque_handle_id = ?, raw_scheduler_id = ?,
                        record_digest = ?, record_json = ?, updated_at = ?
                    WHERE provider_id = ? AND operation_id = ? AND ledger_version = ?
                    """,
                    (
                        updated.ledger_version,
                        None if handle is None else handle.opaque_handle_id,
                        updated.raw_scheduler_id,
                        updated.record_digest,
                        _json(updated.to_dict()),
                        self.clock.now_iso(),
                        identity.provider_id,
                        identity.operation_id,
                        current.ledger_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise SQLiteSchedulerOccurrenceLedgerError(
                        "scheduler occurrence ledger CAS drifted",
                        phase="settle_cas",
                    )
                self.connection.commit()
            except Exception:
                if self.connection.in_transaction:
                    self.connection.rollback()
                raise
        return updated

    def get_handle(
        self,
        provider_id: str,
        opaque_handle_id: str,
    ) -> PrivateSchedulerHandleRecord | None:
        require_identifier(provider_id, field_name="provider_id")
        require_identifier(opaque_handle_id, field_name="opaque_handle_id")
        with self._lock:
            row = self.connection.execute(
                f"""
                SELECT operation_id, request_digest, raw_scheduler_id
                FROM {_TABLE}
                WHERE provider_id = ? AND operation_kind = ?
                  AND opaque_handle_id = ?
                """,
                (
                    provider_id,
                    SchedulerOccurrenceKind.SUBMIT.value,
                    opaque_handle_id,
                ),
            ).fetchone()
        if row is None:
            return None
        if row[2] is None:
            raise SQLiteSchedulerOccurrenceLedgerError(
                "accepted scheduler handle lost its private mapping",
                phase="handle_decode",
            )
        return PrivateSchedulerHandleRecord(
            opaque_handle_id=opaque_handle_id,
            operation_id=str(row[0]),
            request_digest=str(row[1]),
            raw_scheduler_id=str(row[2]),
        )

    def _require_standalone(self) -> None:
        if self.connection.in_transaction:
            raise SQLiteSchedulerOccurrenceLedgerError(
                "scheduler ledger cannot join an unrelated transaction",
                phase="transaction_admission",
            )


def _json(value: object) -> str:
    return json.dumps(
        json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "SQLiteSchedulerOccurrenceLedger",
    "SQLiteSchedulerOccurrenceLedgerError",
]
