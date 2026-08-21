from __future__ import annotations

import base64
from collections.abc import Iterable
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
import json
import sqlite3
from time import monotonic
from typing import Iterator

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import ExtensionStateMutation
from openzyme_extension_spi import ExtensionStateMutationKind
from openzyme_extension_spi import ExtensionStateRecord
from openzyme_extension_spi import ExtensionTransactionBudget


_STATE_TABLE = "openzyme_store_extension_state_records"
_READ_ACTIONS = frozenset({sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT})
_WRITE_ACTIONS = frozenset(
    {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
)
_DENIED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_REINDEX,
    }
)


class ExtensionStateStoreError(RuntimeError):
    error_code = "extension_state_store_rejected"

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        namespace: str,
        observed: object = None,
    ) -> None:
        self.phase = phase
        self.namespace = namespace
        self.observed = observed
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; namespace={namespace}; "
            f"observed={observed!r}; mutation_applied=false; "
            "fallback_performed=false"
        )


class _BudgetCounter:
    def __init__(self, budget: ExtensionTransactionBudget) -> None:
        self.budget = budget
        self.started = monotonic()
        self.reads = 0
        self.mutations = 0
        self.payload_bytes = 0

    def check_time(self, *, namespace: str) -> None:
        elapsed_ms = int((monotonic() - self.started) * 1_000)
        if elapsed_ms > self.budget.max_duration_ms:
            raise ExtensionStateStoreError(
                "extension transaction exceeded its duration budget",
                phase="transaction_budget",
                namespace=namespace,
                observed={
                    "elapsed_ms": elapsed_ms,
                    "max_duration_ms": self.budget.max_duration_ms,
                },
            )

    def consume_read(self, *, namespace: str) -> None:
        self.check_time(namespace=namespace)
        self.reads += 1
        if self.reads > self.budget.max_reads:
            raise ExtensionStateStoreError(
                "extension transaction exceeded its read budget",
                phase="transaction_budget",
                namespace=namespace,
                observed={"reads": self.reads, "max_reads": self.budget.max_reads},
            )

    def consume_mutation(self, payload: str, *, namespace: str) -> None:
        self.check_time(namespace=namespace)
        self.mutations += 1
        self.payload_bytes += len(payload.encode("utf-8"))
        if self.mutations > self.budget.max_mutations:
            raise ExtensionStateStoreError(
                "extension transaction exceeded its mutation budget",
                phase="transaction_budget",
                namespace=namespace,
                observed={
                    "mutations": self.mutations,
                    "max_mutations": self.budget.max_mutations,
                },
            )
        if self.payload_bytes > self.budget.max_payload_bytes:
            raise ExtensionStateStoreError(
                "extension transaction exceeded its payload budget",
                phase="transaction_budget",
                namespace=namespace,
                observed={
                    "payload_bytes": self.payload_bytes,
                    "max_payload_bytes": self.budget.max_payload_bytes,
                },
            )


@contextmanager
def _extension_authorizer(
    connection: sqlite3.Connection,
    *,
    writable: bool,
    namespace: str,
) -> Iterator[None]:
    """Temporarily deny every SQLite surface outside the fixed state table."""

    def authorize(
        action: int,
        argument_one: str | None,
        _argument_two: str | None,
        _database_name: str | None,
        _trigger_name: str | None,
    ) -> int:
        if action in _DENIED_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action in _READ_ACTIONS:
            return (
                sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_SELECT or argument_one == _STATE_TABLE
                else sqlite3.SQLITE_DENY
            )
        if action in _WRITE_ACTIONS:
            return (
                sqlite3.SQLITE_OK
                if writable and argument_one == _STATE_TABLE
                else sqlite3.SQLITE_DENY
            )
        if action in {sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    connection.set_authorizer(authorize)
    try:
        yield
    except sqlite3.DatabaseError as exc:
        raise ExtensionStateStoreError(
            "SQLite authorizer rejected extension state access",
            phase="sqlite_authorizer",
            namespace=namespace,
            observed=exc.__class__.__qualname__,
        ) from exc
    finally:
        connection.set_authorizer(None)


def _json(value: object) -> str:
    return json.dumps(
        json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _projection_cursor(*, entity_kind: str, entity_id: str) -> str:
    encoded = _json({"entity_kind": entity_kind, "entity_id": entity_id}).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _parse_projection_cursor(value: str) -> tuple[str, str]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("extension projection cursor is invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"entity_kind", "entity_id"}
        or not isinstance(payload["entity_kind"], str)
        or not payload["entity_kind"]
        or not isinstance(payload["entity_id"], str)
        or not payload["entity_id"]
    ):
        raise ValueError("extension projection cursor is invalid")
    return payload["entity_kind"], payload["entity_id"]


@dataclass(frozen=True, slots=True)
class SQLiteExtensionStateProjectionQuery:
    """Read one composition-authorized namespace without exposing SQLite."""

    connection: sqlite3.Connection
    allowed_namespaces: frozenset[str]

    @classmethod
    def create(
        cls,
        connection: sqlite3.Connection,
        *,
        allowed_namespaces: Iterable[str],
    ) -> SQLiteExtensionStateProjectionQuery:
        normalized = frozenset(allowed_namespaces)
        if not normalized or any(
            not isinstance(item, str) or not item for item in normalized
        ):
            raise ValueError("extension projection namespaces are invalid")
        return cls(connection=connection, allowed_namespaces=normalized)

    def list_session_records(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kinds: tuple[str, ...],
        after_cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ExtensionStateRecord, ...], str | None]:
        if namespace not in self.allowed_namespaces:
            raise ExtensionStateStoreError(
                "extension projection crossed its activated namespace",
                phase="projection_namespace",
                namespace=namespace,
            )
        if not session_id:
            raise ValueError("extension projection Session is required")
        kinds = tuple(sorted(set(entity_kinds)))
        if not kinds or len(kinds) != len(entity_kinds):
            raise ValueError("extension projection entity kinds are invalid")
        if any(not isinstance(kind, str) or not kind for kind in kinds):
            raise ValueError("extension projection entity kinds are invalid")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("extension projection limit must be between 1 and 200")
        cursor_kind, cursor_id = (
            ("", "")
            if after_cursor is None
            else _parse_projection_cursor(after_cursor)
        )
        if after_cursor is not None and cursor_kind not in kinds:
            raise ValueError("extension projection cursor crossed its entity kinds")
        placeholders = ", ".join("?" for _ in kinds)
        rows = self.connection.execute(
            f"""
            SELECT entity_kind, entity_id, state_version, payload_json, record_digest
            FROM {_STATE_TABLE}
            WHERE namespace = ?
              AND entity_kind IN ({placeholders})
              AND json_extract(payload_json, '$.session_id') = ?
              AND (entity_kind > ? OR (entity_kind = ? AND entity_id > ?))
            ORDER BY entity_kind, entity_id
            LIMIT ?
            """,
            (
                namespace,
                *kinds,
                session_id,
                cursor_kind,
                cursor_kind,
                cursor_id,
                limit + 1,
            ),
        ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        records = tuple(
            ExtensionStateRecord(
                namespace=namespace,
                entity_kind=str(row[0]),
                entity_id=str(row[1]),
                state_version=int(row[2]),
                payload=json.loads(str(row[3])),
                record_digest=str(row[4]),
            )
            for row in selected
        )
        next_cursor = (
            _projection_cursor(
                entity_kind=records[-1].entity_kind,
                entity_id=records[-1].entity_id,
            )
            if has_more and records
            else None
        )
        return records, next_cursor

    def get_session_record(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord | None:
        if namespace not in self.allowed_namespaces:
            raise ExtensionStateStoreError(
                "extension query crossed its activated namespace",
                phase="projection_namespace",
                namespace=namespace,
            )
        if not session_id or not entity_kind or not entity_id:
            raise ValueError("extension query requires exact Session and entity identity")
        row = self.connection.execute(
            f"""
            SELECT state_version, payload_json, record_digest
            FROM {_STATE_TABLE}
            WHERE namespace = ?
              AND entity_kind = ?
              AND entity_id = ?
              AND json_extract(payload_json, '$.session_id') = ?
            """,
            (namespace, entity_kind, entity_id, session_id),
        ).fetchone()
        if row is None:
            return None
        return ExtensionStateRecord(
            namespace=namespace,
            entity_kind=entity_kind,
            entity_id=entity_id,
            state_version=int(row[0]),
            payload=json.loads(str(row[1])),
            record_digest=str(row[2]),
        )


class ExtensionStateStore:
    """Structured namespace-confined state; never exposes a raw connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        namespace: str,
        budget: ExtensionTransactionBudget,
        writable: bool,
        timestamp: str,
        counter: _BudgetCounter | None = None,
        authorizer_managed_externally: bool = False,
    ) -> None:
        if not connection.in_transaction:
            raise ExtensionStateStoreError(
                "extension state is available only inside a Kernel-owned transaction",
                phase="transaction_admission",
                namespace=namespace,
            )
        self.__connection = connection
        self.namespace = namespace
        self.writable = writable
        self.timestamp = timestamp
        self._counter = counter or _BudgetCounter(budget)
        self._authorizer_managed_externally = authorizer_managed_externally
        self._changed_records: list[ExtensionStateRecord] = []
        self._deleted_keys: list[tuple[str, str]] = []

    def _authorization(self, *, writable: bool):
        if self._authorizer_managed_externally:
            return nullcontext()
        return _extension_authorizer(
            self.__connection,
            writable=writable,
            namespace=self.namespace,
        )

    @property
    def counter(self) -> _BudgetCounter:
        return self._counter

    @property
    def changed_records(self) -> tuple[ExtensionStateRecord, ...]:
        return tuple(self._changed_records)

    @property
    def deleted_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._deleted_keys)

    def _require_namespace(self, namespace: str) -> None:
        if namespace != self.namespace:
            raise ExtensionStateStoreError(
                "extension state request crossed its declared namespace",
                phase="namespace_authority",
                namespace=self.namespace,
                observed=namespace,
            )

    def get(
        self,
        *,
        namespace: str,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord | None:
        self._require_namespace(namespace)
        self._counter.consume_read(namespace=self.namespace)
        with self._authorization(writable=False):
            row = self.__connection.execute(
                f"""
                SELECT state_version, payload_json, record_digest
                FROM {_STATE_TABLE}
                WHERE namespace = ? AND entity_kind = ? AND entity_id = ?
                """,
                (namespace, entity_kind, entity_id),
            ).fetchone()
        if row is None:
            return None
        return ExtensionStateRecord(
            namespace=namespace,
            entity_kind=entity_kind,
            entity_id=entity_id,
            state_version=int(row[0]),
            payload=json.loads(str(row[1])),
            record_digest=str(row[2]),
        )

    def list(
        self,
        *,
        namespace: str,
        entity_kind: str,
        after_entity_id: str | None,
        limit: int,
    ) -> tuple[ExtensionStateRecord, ...]:
        self._require_namespace(namespace)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ExtensionStateStoreError(
                "extension state list limit must be between 1 and 200",
                phase="read_admission",
                namespace=self.namespace,
                observed=limit,
            )
        self._counter.consume_read(namespace=self.namespace)
        cursor = "" if after_entity_id is None else after_entity_id
        with self._authorization(writable=False):
            rows = self.__connection.execute(
                f"""
                SELECT entity_id, state_version, payload_json, record_digest
                FROM {_STATE_TABLE}
                WHERE namespace = ? AND entity_kind = ? AND entity_id > ?
                ORDER BY entity_id
                LIMIT ?
                """,
                (namespace, entity_kind, cursor, limit),
            ).fetchall()
        return tuple(
            ExtensionStateRecord(
                namespace=namespace,
                entity_kind=entity_kind,
                entity_id=str(row[0]),
                state_version=int(row[1]),
                payload=json.loads(str(row[2])),
                record_digest=str(row[3]),
            )
            for row in rows
        )

    def upsert(self, mutation: ExtensionStateMutation) -> ExtensionStateRecord:
        self._require_namespace(mutation.namespace)
        if not self.writable:
            raise ExtensionStateStoreError(
                "read-only extension state cannot mutate",
                phase="write_admission",
                namespace=self.namespace,
            )
        if mutation.mutation_kind is not ExtensionStateMutationKind.UPSERT:
            raise ExtensionStateStoreError(
                "upsert received a non-upsert mutation",
                phase="write_admission",
                namespace=self.namespace,
            )
        payload_json = _json(mutation.payload)
        self._counter.consume_mutation(payload_json, namespace=self.namespace)
        existing = self.get(
            namespace=mutation.namespace,
            entity_kind=mutation.entity_kind,
            entity_id=mutation.entity_id,
        )
        observed_version = None if existing is None else existing.state_version
        if observed_version != mutation.expected_state_version:
            raise ExtensionStateStoreError(
                "extension state compare-and-swap version drifted",
                phase="state_version",
                namespace=self.namespace,
                observed={
                    "expected": mutation.expected_state_version,
                    "observed": observed_version,
                },
            )
        state_version = 1 if existing is None else existing.state_version + 1
        record_digest = canonical_sha256_digest(
            {
                "namespace": mutation.namespace,
                "entity_kind": mutation.entity_kind,
                "entity_id": mutation.entity_id,
                "state_version": state_version,
                "payload": json.loads(payload_json),
            }
        )
        with self._authorization(writable=True):
            self.__connection.execute(
                f"""
                INSERT INTO {_STATE_TABLE} (
                    namespace, entity_kind, entity_id, state_version,
                    payload_json, record_digest, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, entity_kind, entity_id) DO UPDATE SET
                    state_version = excluded.state_version,
                    payload_json = excluded.payload_json,
                    record_digest = excluded.record_digest,
                    updated_at = excluded.updated_at
                """,
                (
                    mutation.namespace,
                    mutation.entity_kind,
                    mutation.entity_id,
                    state_version,
                    payload_json,
                    record_digest,
                    self.timestamp,
                ),
            )
        record = ExtensionStateRecord(
            namespace=mutation.namespace,
            entity_kind=mutation.entity_kind,
            entity_id=mutation.entity_id,
            state_version=state_version,
            payload={} if mutation.payload is None else mutation.payload,
            record_digest=record_digest,
        )
        self._changed_records.append(record)
        return record

    def delete(self, mutation: ExtensionStateMutation) -> None:
        self._require_namespace(mutation.namespace)
        if not self.writable:
            raise ExtensionStateStoreError(
                "read-only extension state cannot mutate",
                phase="write_admission",
                namespace=self.namespace,
            )
        if mutation.mutation_kind is not ExtensionStateMutationKind.DELETE:
            raise ExtensionStateStoreError(
                "delete received a non-delete mutation",
                phase="write_admission",
                namespace=self.namespace,
            )
        self._counter.consume_mutation("", namespace=self.namespace)
        existing = self.get(
            namespace=mutation.namespace,
            entity_kind=mutation.entity_kind,
            entity_id=mutation.entity_id,
        )
        observed_version = None if existing is None else existing.state_version
        if observed_version != mutation.expected_state_version:
            raise ExtensionStateStoreError(
                "extension state delete compare-and-swap version drifted",
                phase="state_version",
                namespace=self.namespace,
                observed={
                    "expected": mutation.expected_state_version,
                    "observed": observed_version,
                },
            )
        with self._authorization(writable=True):
            self.__connection.execute(
                f"""
                DELETE FROM {_STATE_TABLE}
                WHERE namespace = ? AND entity_kind = ? AND entity_id = ?
                """,
                (mutation.namespace, mutation.entity_kind, mutation.entity_id),
            )
        self._deleted_keys.append((mutation.entity_kind, mutation.entity_id))


__all__ = [
    "ExtensionStateStore",
    "ExtensionStateStoreError",
    "SQLiteExtensionStateProjectionQuery",
]
