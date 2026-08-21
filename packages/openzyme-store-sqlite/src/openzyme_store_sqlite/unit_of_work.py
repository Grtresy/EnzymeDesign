from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
import json
import sqlite3
from time import monotonic
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ExtensionMutationResult
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionTransactionParticipant

from .extension_state import ExtensionStateStore
from .extension_state import ExtensionStateStoreError
from .extension_state import _extension_authorizer


class SQLiteUnitOfWorkError(RuntimeError):
    error_code = "sqlite_unit_of_work_rejected"

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        observed: object = None,
    ) -> None:
        self.phase = phase
        self.observed = observed
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; observed={observed!r}; "
            "mutation_applied=false; fallback_performed=false"
        )


class SQLiteUnitOfWork(AbstractContextManager["SQLiteUnitOfWork"]):
    """One short single-writer transaction; never performs external I/O."""

    def __init__(self, connection: sqlite3.Connection, *, max_duration_ms: int = 5_000) -> None:
        if not isinstance(max_duration_ms, int) or isinstance(max_duration_ms, bool):
            raise ValueError("max_duration_ms must be an integer")
        if not 1 <= max_duration_ms <= 5_000:
            raise ValueError("max_duration_ms must be between 1 and 5000")
        self.connection = connection
        self.max_duration_ms = max_duration_ms
        self._started = 0.0
        self._completed = False

    def __enter__(self) -> SQLiteUnitOfWork:
        if self.connection.in_transaction:
            raise SQLiteUnitOfWorkError(
                "Unit of Work cannot nest inside another transaction",
                phase="begin",
            )
        try:
            self.connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise SQLiteUnitOfWorkError(
                "failed to acquire SQLite single-writer transaction",
                phase="begin",
                observed=exc.__class__.__qualname__,
            ) from exc
        self._started = monotonic()
        return self

    def _check_duration(self) -> None:
        elapsed_ms = int((monotonic() - self._started) * 1_000)
        if elapsed_ms > self.max_duration_ms:
            raise SQLiteUnitOfWorkError(
                "Unit of Work exceeded its duration budget",
                phase="duration_budget",
                observed={
                    "elapsed_ms": elapsed_ms,
                    "max_duration_ms": self.max_duration_ms,
                },
            )

    def append_event_with_outbox(
        self,
        *,
        event_id: str,
        command_id: str,
        event_kind: str,
        event: dict[str, Any],
        outbox_id: str,
        destination: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> tuple[str, str]:
        self._check_duration()
        event_json = json.dumps(event, sort_keys=True, separators=(",", ":"))
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        event_digest = canonical_sha256_digest(event)
        payload_digest = canonical_sha256_digest(payload)
        try:
            self.connection.execute(
                """
                INSERT INTO openzyme_store_durable_event_records (
                    event_id, command_id, event_kind, event_digest,
                    event_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, command_id, event_kind, event_digest, event_json, created_at),
            )
            self.connection.execute(
                """
                INSERT INTO openzyme_store_outbox_records (
                    outbox_id, event_id, destination, payload_digest,
                    payload_json, created_at, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    outbox_id,
                    event_id,
                    destination,
                    payload_digest,
                    payload_json,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise SQLiteUnitOfWorkError(
                "event/outbox identity conflicted",
                phase="event_outbox_write",
                observed=exc.__class__.__qualname__,
            ) from exc
        return event_digest, payload_digest

    def commit(self) -> None:
        self._check_duration()
        self.connection.commit()
        self._completed = True

    def rollback(self) -> None:
        if self.connection.in_transaction:
            self.connection.rollback()
        self._completed = True

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None or not self._completed:
            self.rollback()
        return False


class SQLiteExtensionTransactionCoordinator:
    """Enlist typed extension participants in one Kernel-authorized UoW."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(
        self,
        *,
        command: ExtensionStateCommand,
        participant: ExtensionTransactionParticipant,
        timestamp: str,
        core_mutation: Callable[[sqlite3.Connection], None] | None = None,
    ) -> ExtensionMutationResult:
        if (
            participant.participant_id != command.participant_id
            or participant.state_namespace != command.namespace
        ):
            raise SQLiteUnitOfWorkError(
                "participant identity does not match the authorized command",
                phase="participant_admission",
                observed={
                    "command_participant": command.participant_id,
                    "participant": participant.participant_id,
                    "command_namespace": command.namespace,
                    "participant_namespace": participant.state_namespace,
                },
            )
        # prepare needs a budget before a plan exists. The hard ceiling prevents an
        # implementation from using prepare as an unbounded read channel.
        from openzyme_extension_spi import ExtensionTransactionBudget

        prepare_budget = ExtensionTransactionBudget(
            max_reads=100,
            max_mutations=100,
            max_payload_bytes=1_048_576,
            max_duration_ms=1_000,
        )
        try:
            with SQLiteUnitOfWork(
                self.connection,
                max_duration_ms=5_000,
            ) as unit:
                reader = ExtensionStateStore(
                    self.connection,
                    namespace=command.namespace,
                    budget=prepare_budget,
                    writable=False,
                    timestamp=timestamp,
                    authorizer_managed_externally=True,
                )
                with _extension_authorizer(
                    self.connection,
                    writable=False,
                    namespace=command.namespace,
                ):
                    plan = participant.prepare(command, reader)
                if (
                    plan.participant_id != command.participant_id
                    or plan.namespace != command.namespace
                    or plan.command_id != command.context.command_id
                    or not plan.plan_digest
                ):
                    raise SQLiteUnitOfWorkError(
                        "prepared extension plan does not bind the command",
                        phase="participant_prepare",
                    )
                if len(plan.mutations) > plan.budget.max_mutations:
                    raise SQLiteUnitOfWorkError(
                        "prepared extension plan exceeds its declared budget",
                        phase="participant_prepare",
                    )
                if core_mutation is not None:
                    core_mutation(self.connection)
                writer = ExtensionStateStore(
                    self.connection,
                    namespace=command.namespace,
                    budget=plan.budget,
                    writable=True,
                    timestamp=timestamp,
                    authorizer_managed_externally=True,
                )
                with _extension_authorizer(
                    self.connection,
                    writable=True,
                    namespace=command.namespace,
                ):
                    result = participant.apply(plan, writer)
                if (
                    result.plan_id != plan.plan_id
                    or result.participant_id != plan.participant_id
                    or result.namespace != plan.namespace
                ):
                    raise SQLiteUnitOfWorkError(
                        "extension result does not bind the prepared plan",
                        phase="participant_apply",
                    )
                if result.mutation_applied != bool(plan.mutations):
                    raise SQLiteUnitOfWorkError(
                        "extension result mutation fact differs from the plan",
                        phase="participant_apply",
                    )
                if result.changed_records != writer.changed_records:
                    raise SQLiteUnitOfWorkError(
                        "extension result changed records differ from Store receipts",
                        phase="participant_apply",
                    )
                if writer.counter.mutations != len(plan.mutations):
                    raise SQLiteUnitOfWorkError(
                        "participant did not apply the exact prepared mutation set",
                        phase="participant_apply",
                        observed={
                            "planned": len(plan.mutations),
                            "applied": writer.counter.mutations,
                        },
                    )
                writer.counter.check_time(namespace=command.namespace)
                unit.commit()
                return result
        except (SQLiteUnitOfWorkError, ExtensionStateStoreError):
            raise
        except Exception as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise SQLiteUnitOfWorkError(
                "extension participant failed and the entire mutation was rolled back",
                phase="participant_execution",
                observed=exc.__class__.__qualname__,
            ) from exc


__all__ = [
    "SQLiteExtensionTransactionCoordinator",
    "SQLiteUnitOfWork",
    "SQLiteUnitOfWorkError",
]
