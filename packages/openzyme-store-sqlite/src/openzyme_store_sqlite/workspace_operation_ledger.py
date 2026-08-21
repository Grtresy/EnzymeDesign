from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import sqlite3
import threading

from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceOperationIdentity
from openzyme_contracts import WorkspaceOperationLedgerError
from openzyme_contracts import WorkspaceOperationLedgerRecord
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import json_compatible


_TABLE = "openzyme_store_workspace_operation_receipts"


class SQLiteWorkspaceOperationLedgerError(WorkspaceOperationLedgerError):
    error_code = "sqlite_workspace_operation_ledger_rejected"


@dataclass(slots=True)
class SQLiteWorkspaceOperationLedger:
    """Durable reserve/settle ledger for selected Workspace Adapters.

    The Store owns the SQLite mechanism, while occurrence semantics remain in
    Contracts and the invoking Adapter.  The ledger uses a Store-private namespace;
    it is never part of Plugin projection or Core canonical tables.
    """

    connection: sqlite3.Connection
    clock: ClockPort
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (_TABLE,),
        ).fetchone()
        if row is None:
            raise SQLiteWorkspaceOperationLedgerError(
                "workspace operation ledger requires the selected Store schema",
                phase="schema_admission",
            )

    def read(
        self,
        identity: WorkspaceOperationIdentity,
    ) -> WorkspaceOperationLedgerRecord | None:
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
        payload = json.loads(str(row[1]))
        if not isinstance(payload, dict):
            raise SQLiteWorkspaceOperationLedgerError(
                "workspace operation ledger payload is not closed",
                phase="decode",
            )
        record = WorkspaceOperationLedgerRecord.from_dict(payload)
        if (
            record.identity != identity
            or record.ledger_version != int(row[0])
            or row[2] != record.record_digest
        ):
            raise SQLiteWorkspaceOperationLedgerError(
                "workspace operation ledger identity or digest drifted",
                phase="identity",
            )
        return record

    def reserve(self, identity: WorkspaceOperationIdentity) -> bool:
        record = WorkspaceOperationLedgerRecord(
            identity=identity,
            receipt=None,
            ledger_version=1,
        )
        payload = record.to_dict()
        with self._lock:
            self._require_standalone()
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                cursor = self.connection.execute(
                    f"""
                    INSERT OR IGNORE INTO {_TABLE} (
                        provider_id, operation_id, session_id, workspace_id,
                        workspace_generation, workspace_state_version,
                        operation_kind, intent_digest, ledger_version,
                        record_digest, record_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identity.provider_id,
                        identity.operation_id,
                        identity.session_id,
                        identity.workspace_id,
                        identity.generation,
                        identity.state_version,
                        identity.operation_kind,
                        identity.intent_digest,
                        1,
                        record.record_digest,
                        _json(payload),
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
            raise SQLiteWorkspaceOperationLedgerError(
                "workspace operation reservation disappeared",
                phase="reserve",
            )
        return False

    def settle(
        self,
        identity: WorkspaceOperationIdentity,
        receipt: WorkspaceOperationReceipt,
    ) -> WorkspaceOperationLedgerRecord:
        _require_receipt_identity(identity, receipt)
        with self._lock:
            current = self.read(identity)
            if current is None:
                raise SQLiteWorkspaceOperationLedgerError(
                    "workspace operation must be reserved before settlement",
                    phase="settle_admission",
                )
            if current.receipt == receipt:
                return current
            if current.receipt is not None and (
                current.receipt.effect_certainty
                is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ):
                raise SQLiteWorkspaceOperationLedgerError(
                    "terminal workspace operation receipt cannot be replaced",
                    phase="settle_terminal",
                )
            if (
                current.receipt is not None
                and receipt.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ):
                raise SQLiteWorkspaceOperationLedgerError(
                    "uncertain workspace receipt cannot be replaced by another uncertainty",
                    phase="settle_progress",
                )
            updated = WorkspaceOperationLedgerRecord(
                identity=identity,
                receipt=receipt,
                ledger_version=current.ledger_version + 1,
            )
            payload = updated.to_dict()
            self._require_standalone()
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                cursor = self.connection.execute(
                    f"""
                    UPDATE {_TABLE}
                    SET ledger_version = ?, record_json = ?, record_digest = ?,
                        updated_at = ?
                    WHERE provider_id = ? AND operation_id = ?
                      AND ledger_version = ?
                    """,
                    (
                        updated.ledger_version,
                        _json(payload),
                        updated.record_digest,
                        self.clock.now_iso(),
                        identity.provider_id,
                        identity.operation_id,
                        current.ledger_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise SQLiteWorkspaceOperationLedgerError(
                        "workspace operation ledger CAS drifted",
                        phase="settle_cas",
                    )
                self.connection.commit()
            except Exception:
                if self.connection.in_transaction:
                    self.connection.rollback()
                raise
        return updated

    def _require_standalone(self) -> None:
        if self.connection.in_transaction:
            raise SQLiteWorkspaceOperationLedgerError(
                "workspace Adapter ledger cannot join an unrelated transaction",
                phase="transaction_admission",
            )


def _require_receipt_identity(
    identity: WorkspaceOperationIdentity,
    receipt: WorkspaceOperationReceipt,
) -> None:
    if (
        receipt.operation_id != identity.operation_id
        or receipt.workspace_id != identity.workspace_id
        or receipt.generation != identity.generation
        or receipt.state_version != identity.state_version
    ):
        raise SQLiteWorkspaceOperationLedgerError(
            "workspace receipt crossed its reserved identity",
            phase="receipt_identity",
        )


def _json(value: object) -> str:
    return json.dumps(
        json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
__all__ = [
    "SQLiteWorkspaceOperationLedger",
    "SQLiteWorkspaceOperationLedgerError",
]
