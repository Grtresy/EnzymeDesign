"""SQLite implementation of the generic Kernel ControlStore Port.

Entity codecs map canonical Kernel records onto existing owner tables.  This module
intentionally provides no generic JSON state table and no Plugin/raw-SQL escape hatch.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import sqlite3
from threading import RLock
from time import monotonic
from typing import Protocol

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkReceipt
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import json_compatible
from openzyme_contracts import require_identifier


class SQLiteControlStoreError(RuntimeError):
    def __init__(self, code: str, message: str, *, phase: str) -> None:
        super().__init__(f"{message}; phase={phase}; mutation_applied=false; fallback_performed=false")
        self.code = code
        self.phase = phase
        self.mutation_applied = False
        self.effect_certainty = "no_effect"
        self.fallback_performed = False


class SQLiteKernelEntityCodec(Protocol):
    """Closed mapper for one Kernel entity type and its existing owner table."""

    entity_type: str
    owner_id: str
    table_names: tuple[str, ...]

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None: ...

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None: ...


class SQLiteControlStore:
    provider_id = "openzyme.store.sqlite"
    provider_contract_digest = canonical_sha256_digest(
        {
            "contract": "openzyme.control-store-port@1",
            "provider": provider_id,
            "entity_mapping": "explicit-existing-owner-table-codecs",
            "generic_state_table": False,
            "transaction": "begin-immediate",
        }
    )

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        codecs: tuple[SQLiteKernelEntityCodec, ...],
        max_duration_ms: int = 5_000,
    ) -> None:
        if not 1 <= max_duration_ms <= 5_000:
            raise ValueError("max_duration_ms must be between 1 and 5000")
        identities = [codec.entity_type for codec in codecs]
        if len(identities) != len(set(identities)):
            raise ValueError("Kernel entity codec identities must be unique")
        if any(not codec.table_names for codec in codecs):
            raise ValueError("Kernel entity codec must name its existing owner tables")
        self.connection = connection
        self.codecs = {codec.entity_type: codec for codec in codecs}
        self.max_duration_ms = max_duration_ms
        # One verified writer is shared by request and bounded worker threads.
        # Hold this lock for the complete Unit-of-Work lifetime so no reader can
        # observe uncommitted state and no second writer can enter the same
        # sqlite3.Connection transaction.
        self._connection_lock = RLock()
        self._active_write_session_id: str | None = None
        self._active_write_channels: frozenset[str] = frozenset()
        self.connection.create_function(
            "openzyme_mutation_write_allowed",
            2,
            self._mutation_write_allowed,
            deterministic=False,
        )
        # Retained @1 triggers remain readable during the offline transition but
        # their mutation authorities are not part of the target Control Store.
        # Register deny-only sentinels so SQLite can compile statements against a
        # shared physical table without importing legacy Core callbacks. Target
        # record-kind triggers use direct structured facts instead.
        self.connection.create_function(
            "openzyme_runtime_signal_capability_admission_allowed",
            4,
            lambda *_args: 0,
            deterministic=False,
        )
        self.connection.create_function(
            "openzyme_runtime_signal_write_fence_allowed",
            3,
            lambda *_args: 0,
            deterministic=False,
        )

    def read(
        self, *, entity_type: str, entity_id: str
    ) -> KernelRecordSnapshot | None:
        with self._connection_lock:
            return self._codec(entity_type).read(
                self.connection,
                entity_id=entity_id,
            )

    def list_for_session(
        self,
        *,
        entity_type: str,
        session_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]:
        """Read one bounded Session slice through the canonical entity codec.

        The version ledger is used only as the closed identity index.  Payloads
        are reconstructed and digest-verified by the selected owner-table codec;
        legacy rows without target CAS ownership never enter this read model.
        """

        with self._connection_lock:
            codec = self._codec(entity_type)
            if not session_id:
                raise ValueError("session_id must be non-empty")
            if not 1 <= max_items <= 1_000:
                raise ValueError("max_items must be between 1 and 1000")
            rows = self.connection.execute(
                """
                SELECT entity_id
                FROM openzyme_store_kernel_entity_versions
                WHERE entity_type = ? AND owner_component_id = ? AND session_id = ?
                ORDER BY entity_id
                LIMIT ?
                """,
                (entity_type, codec.owner_id, session_id, max_items + 1),
            ).fetchall()
            if len(rows) > max_items:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_session_query_budget_exceeded",
                    "Kernel Session query exceeded its explicit item budget",
                    phase="entity_query",
                )
            snapshots: list[KernelRecordSnapshot] = []
            for row in rows:
                entity_id = str(row[0])
                snapshot = codec.read(self.connection, entity_id=entity_id)
                if snapshot is None:
                    raise SQLiteControlStoreError(
                        "sqlite_kernel_entity_index_drift",
                        "Kernel version ledger references a missing owner row",
                        phase="entity_query",
                    )
                session_indexer = getattr(codec, "session_id_for_ledger", None)
                if session_indexer is not None:
                    observed_session_id = session_indexer(snapshot.payload)
                else:
                    observed_session_id = (
                        entity_id
                        if entity_type == "session"
                        else snapshot.payload.get("session_id")
                    )
                if observed_session_id != session_id:
                    raise SQLiteControlStoreError(
                        "sqlite_kernel_entity_session_index_drift",
                        "Kernel Session index differs from the canonical owner payload",
                        phase="entity_query",
                    )
                snapshots.append(snapshot)
            return tuple(snapshots)

    def list_session_ids(
        self,
        *,
        after_session_id: str | None,
        max_items: int,
    ) -> tuple[str, ...]:
        """Discover one bounded lexical page through the canonical Session owner.

        The version ledger is only the identity index.  Every returned identity
        is re-read through the closed Session codec so a stale or foreign index
        row fails closed before a scheduler can act on it.
        """

        if after_session_id is not None:
            require_identifier(after_session_id, field_name="after_session_id")
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or not 1 <= max_items <= 1_024
        ):
            raise ValueError("max_items must be between 1 and 1024")
        with self._connection_lock:
            codec = self._codec("session")
            if after_session_id is None:
                rows = self.connection.execute(
                    """
                    SELECT entity_id
                    FROM openzyme_store_kernel_entity_versions
                    WHERE entity_type = 'session' AND owner_component_id = ?
                    ORDER BY entity_id
                    LIMIT ?
                    """,
                    (codec.owner_id, max_items),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    """
                    SELECT entity_id
                    FROM openzyme_store_kernel_entity_versions
                    WHERE entity_type = 'session' AND owner_component_id = ?
                      AND entity_id > ?
                    ORDER BY entity_id
                    LIMIT ?
                    """,
                    (codec.owner_id, after_session_id, max_items),
                ).fetchall()
            session_ids: list[str] = []
            for row in rows:
                session_id = str(row[0])
                snapshot = codec.read(self.connection, entity_id=session_id)
                if snapshot is None:
                    raise SQLiteControlStoreError(
                        "sqlite_kernel_session_index_drift",
                        "Kernel Session index references a missing owner row",
                        phase="session_discovery",
                    )
                payload_session_id = snapshot.payload.get("session_id")
                if (
                    snapshot.entity_id != session_id
                    or payload_session_id not in {None, session_id}
                ):
                    raise SQLiteControlStoreError(
                        "sqlite_kernel_session_index_drift",
                        "Kernel Session identity index differs from its owner payload",
                        phase="session_discovery",
                    )
                session_ids.append(session_id)
            return tuple(session_ids)

    def list_command_tool_expansions(
        self,
        *,
        session_id: str,
        command_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]:
        """Read one exact command's bounded expansion history via its owner index."""

        if not session_id or not command_id:
            raise ValueError("session_id and command_id must be non-empty")
        if not 1 <= max_items <= 1_000:
            raise ValueError("max_items must be between 1 and 1000")
        with self._connection_lock:
            codec = self._codec("command_tool_expansion")
            rows = self.connection.execute(
                """
                SELECT expansion_id
                FROM command_tool_expansion_records
                WHERE session_id = ? AND command_id = ?
                ORDER BY expansion_revision, expansion_id
                LIMIT ?
                """,
                (session_id, command_id, max_items + 1),
            ).fetchall()
            if len(rows) > max_items:
                raise SQLiteControlStoreError(
                    "sqlite_command_tool_expansion_query_budget_exceeded",
                    "Command tool expansion history exceeded its explicit item budget",
                    phase="entity_query",
                )
            snapshots: list[KernelRecordSnapshot] = []
            for row in rows:
                snapshot = codec.read(self.connection, entity_id=str(row[0]))
                if snapshot is None:
                    raise SQLiteControlStoreError(
                        "sqlite_command_tool_expansion_index_drift",
                        "Command expansion index references a missing canonical record",
                        phase="entity_query",
                    )
                if (
                    snapshot.payload.get("session_id") != session_id
                    or snapshot.payload.get("command_id") != command_id
                ):
                    raise SQLiteControlStoreError(
                        "sqlite_command_tool_expansion_scope_drift",
                        "Command expansion owner index differs from canonical payload",
                        phase="entity_query",
                    )
                snapshots.append(snapshot)
            return tuple(snapshots)

    def begin(self, request: UnitOfWorkRequest) -> "SQLiteKernelUnitOfWork":
        return SQLiteKernelUnitOfWork(store=self, request=request)

    def _codec(self, entity_type: str) -> SQLiteKernelEntityCodec:
        codec = self.codecs.get(entity_type)
        if codec is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unmapped",
                f"Kernel entity type {entity_type!r} has no explicit owner-table codec",
                phase="entity_mapping",
            )
        return codec

    def _mutation_write_allowed(self, session_id: object, channel: object) -> int:
        return int(
            isinstance(session_id, str)
            and isinstance(channel, str)
            and session_id == self._active_write_session_id
            and channel in self._active_write_channels
        )

    def _activate_mutation_gate(
        self, *, session_id: str, codecs: tuple[SQLiteKernelEntityCodec, ...]
    ) -> None:
        if self._active_write_session_id is not None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_mutation_gate_nested",
                "Kernel mutation authority gate cannot nest",
                phase="mutation_gate",
            )
        channels: set[str] = set()
        for codec in codecs:
            declared = getattr(codec, "mutation_channels", ())
            if not isinstance(declared, tuple) or not all(
                isinstance(item, str) for item in declared
            ):
                raise SQLiteControlStoreError(
                    "sqlite_kernel_codec_channel_invalid",
                    "Kernel entity codec mutation channels are invalid",
                    phase="mutation_gate",
                )
            channels.update(declared)
        self._active_write_session_id = session_id
        self._active_write_channels = frozenset(channels)

    def _clear_mutation_gate(self) -> None:
        self._active_write_session_id = None
        self._active_write_channels = frozenset()


class SQLiteKernelUnitOfWork:
    def __init__(self, *, store: SQLiteControlStore, request: UnitOfWorkRequest) -> None:
        self.store = store
        self.request = request
        self._mutations: list[KernelStateMutation] = []
        self._events: list[DurableEventRecord] = []
        self._outbox: list[OutboxRecord] = []
        self._closed = False
        self._lock_held = False
        store._connection_lock.acquire()
        self._lock_held = True
        try:
            if store.connection.in_transaction:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_uow_nested",
                    "Kernel Unit of Work cannot nest",
                    phase="begin",
                )
            store.connection.execute("BEGIN IMMEDIATE")
        except SQLiteControlStoreError:
            self._release_store_lock()
            raise
        except sqlite3.Error as exc:
            self._release_store_lock()
            raise SQLiteControlStoreError(
                "sqlite_kernel_uow_begin_failed",
                "Failed to acquire SQLite writer",
                phase="begin",
            ) from exc
        self._started = monotonic()

    def read(self, *, entity_type: str, entity_id: str) -> KernelRecordSnapshot | None:
        self._require_open()
        return self.store._codec(entity_type).read(
            self.store.connection, entity_id=entity_id
        )

    def stage(self, mutation: KernelStateMutation) -> None:
        self._require_open()
        self.store._codec(mutation.entity_type)
        identity = (mutation.entity_type, mutation.entity_id)
        if any((item.entity_type, item.entity_id) == identity for item in self._mutations):
            raise SQLiteControlStoreError(
                "sqlite_kernel_mutation_duplicate",
                "One Unit of Work may mutate an entity only once",
                phase="stage",
            )
        self._mutations.append(mutation)

    def append_event(self, event: DurableEventRecord) -> None:
        self._require_open()
        self._events.append(event)

    def append_outbox(self, record: OutboxRecord) -> None:
        self._require_open()
        self._outbox.append(record)

    def commit(self) -> UnitOfWorkReceipt:
        self._require_open()
        try:
            return self._commit_locked()
        finally:
            self._release_store_lock()

    def _commit_locked(self) -> UnitOfWorkReceipt:
        try:
            self._check_budget()
            session = self.read(entity_type="session", entity_id=self.request.session_id)
            session_bootstrap = any(
                mutation.entity_type == "session"
                and mutation.entity_id == self.request.session_id
                and mutation.kind is KernelMutationKind.CREATE
                for mutation in self._mutations
            )
            if session is None:
                session_fence_valid = (
                    session_bootstrap and self.request.expected_session_version == 1
                )
            else:
                session_fence_valid = (
                    not session_bootstrap
                    and session.state_version == self.request.expected_session_version
                )
            if not session_fence_valid:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_session_stale",
                    "Session version differs from Unit of Work admission",
                    phase="session_fence",
                )
            mutation_codecs = tuple(
                self.store._codec(mutation.entity_type)
                for mutation in self._mutations
            )
            self.store._activate_mutation_gate(
                session_id=self.request.session_id,
                codecs=mutation_codecs,
            )
            for mutation in self._mutations:
                codec = self.store._codec(mutation.entity_type)
                current = codec.read(
                    self.store.connection, entity_id=mutation.entity_id
                )
                if mutation.kind is KernelMutationKind.CREATE:
                    if current is not None:
                        self._cas_error(mutation)
                    next_version: int | None = 1
                else:
                    if (
                        current is None
                        or current.state_version != mutation.expected_state_version
                    ):
                        self._cas_error(mutation)
                    next_version = (
                        None
                        if mutation.kind is KernelMutationKind.DELETE
                        else current.state_version + 1
                    )
                codec.apply(
                    self.store.connection,
                    mutation=mutation,
                    next_state_version=next_version,
                )
                if getattr(codec, "uses_store_version_ledger", False):
                    self._apply_version_ledger(
                        codec=codec,
                        mutation=mutation,
                        next_state_version=next_version,
                    )
            event_ids = {event.event_id for event in self._events}
            if len(event_ids) != len(self._events):
                raise SQLiteControlStoreError(
                    "sqlite_kernel_event_duplicate",
                    "Unit of Work contains duplicate event identities",
                    phase="event",
                )
            if any(record.occurrence_id not in event_ids for record in self._outbox):
                raise SQLiteControlStoreError(
                    "sqlite_kernel_outbox_occurrence_missing",
                    "Outbox must reference an event in the same Unit of Work",
                    phase="outbox",
                )
            event_times: dict[str, str] = {}
            for record in self._outbox:
                previous = event_times.setdefault(record.occurrence_id, record.created_at)
                if previous != record.created_at:
                    raise SQLiteControlStoreError(
                        "sqlite_kernel_event_time_ambiguous",
                        "Outbox records disagree on their occurrence time",
                        phase="event",
                    )
            if set(event_times) != event_ids:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_event_time_missing",
                    "Every durable event requires an atomic outbox occurrence time",
                    phase="event",
                )
            for event in self._events:
                self.store.connection.execute(
                    """
                    INSERT INTO openzyme_store_durable_event_records
                    (event_id, command_id, event_kind, event_digest, event_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.command_id,
                        event.event_type,
                        event.event_digest,
                        self._json(event.canonical_payload),
                        event_times[event.event_id],
                    ),
                )
            for record in self._outbox:
                self.store.connection.execute(
                    """
                    INSERT INTO openzyme_store_outbox_records
                    (outbox_id, event_id, destination, payload_digest, payload_json,
                     created_at, delivered_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        record.outbox_id,
                        record.occurrence_id,
                        record.topic,
                        record.payload_digest,
                        self._json(record.payload),
                        record.created_at,
                    ),
                )
            self._check_budget()
            self.store.connection.commit()
            self._closed = True
        except Exception:
            self.store.connection.rollback()
            self._closed = True
            raise
        finally:
            self.store._clear_mutation_gate()
        resulting = self.store.read(
            entity_type="session", entity_id=self.request.session_id
        )
        assert resulting is not None
        return UnitOfWorkReceipt.create(
            unit_of_work_id=self.request.unit_of_work_id,
            command_id=self.request.command_id,
            committed=True,
            mutation_digests=tuple(item.mutation_digest for item in self._mutations),
            event_digests=tuple(item.event_digest for item in self._events),
            outbox_payload_digests=tuple(item.payload_digest for item in self._outbox),
            resulting_session_version=resulting.state_version,
        )

    def rollback(self) -> None:
        try:
            if not self._closed and self.store.connection.in_transaction:
                self.store.connection.rollback()
            self._closed = True
            self.store._clear_mutation_gate()
        finally:
            self._release_store_lock()

    def _release_store_lock(self) -> None:
        if self._lock_held:
            self._lock_held = False
            self.store._connection_lock.release()

    def _check_budget(self) -> None:
        if (monotonic() - self._started) * 1_000 > self.store.max_duration_ms:
            raise SQLiteControlStoreError(
                "sqlite_kernel_uow_budget_exceeded",
                "Kernel Unit of Work exceeded its duration budget",
                phase="duration_budget",
            )

    def _require_open(self) -> None:
        if self._closed:
            raise SQLiteControlStoreError(
                "sqlite_kernel_uow_closed",
                "Kernel Unit of Work is already closed",
                phase="lifecycle",
            )

    @staticmethod
    def _cas_error(mutation: KernelStateMutation) -> None:
        raise SQLiteControlStoreError(
            "sqlite_kernel_record_stale",
            "Kernel record compare-and-swap failed",
            phase="cas",
        )

    @staticmethod
    def _json(value: Mapping[str, object]) -> str:
        return json.dumps(
            json_compatible(value), sort_keys=True, separators=(",", ":")
        )

    def _apply_version_ledger(
        self,
        *,
        codec: SQLiteKernelEntityCodec,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            cursor = self.store.connection.execute(
                """
                DELETE FROM openzyme_store_kernel_entity_versions
                WHERE entity_type = ? AND entity_id = ? AND state_version = ?
                """,
                (
                    mutation.entity_type,
                    mutation.entity_id,
                    mutation.expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                self._cas_error(mutation)
            return
        assert mutation.payload is not None and next_state_version is not None
        snapshot = KernelRecordSnapshot.create(
            entity_type=mutation.entity_type,
            entity_id=mutation.entity_id,
            state_version=next_state_version,
            payload=mutation.payload,
        )
        session_indexer = getattr(codec, "session_id_for_ledger", None)
        if session_indexer is not None:
            session_id = session_indexer(mutation.payload)
        else:
            session_id = (
                mutation.entity_id
                if mutation.entity_type == "session"
                else mutation.payload.get("session_id")
            )
        if session_id is not None and not isinstance(session_id, str):
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_session_invalid",
                "Kernel record session identity is not a string",
                phase="entity_mapping",
            )
        if mutation.kind is KernelMutationKind.CREATE:
            self.store.connection.execute(
                """
                INSERT INTO openzyme_store_kernel_entity_versions
                (entity_type, entity_id, session_id, owner_component_id,
                 state_version, record_digest)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mutation.entity_type,
                    mutation.entity_id,
                    session_id,
                    codec.owner_id,
                    next_state_version,
                    snapshot.record_digest,
                ),
            )
            return
        cursor = self.store.connection.execute(
            """
            UPDATE openzyme_store_kernel_entity_versions
            SET session_id = ?, state_version = ?, record_digest = ?
            WHERE entity_type = ? AND entity_id = ? AND owner_component_id = ?
              AND state_version = ?
            """,
            (
                session_id,
                next_state_version,
                snapshot.record_digest,
                mutation.entity_type,
                mutation.entity_id,
                codec.owner_id,
                mutation.expected_state_version,
            ),
        )
        if cursor.rowcount != 1:
            self._cas_error(mutation)


__all__ = [
    "SQLiteControlStore",
    "SQLiteControlStoreError",
    "SQLiteKernelEntityCodec",
    "SQLiteKernelUnitOfWork",
]
