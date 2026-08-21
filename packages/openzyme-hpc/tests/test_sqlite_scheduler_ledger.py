from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import canonical_sha256_digest
from openzyme_hpc import SQLiteSchedulerOccurrenceLedger
from openzyme_hpc import SQLiteSchedulerOccurrenceLedgerError
from openzyme_hpc import SchedulerDispatchReceipt
from openzyme_hpc import SchedulerOccurrenceIdentity
from openzyme_hpc import SchedulerOccurrenceKind
from openzyme_hpc import install_hpc_inventory_schema_for_offline_migration


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-22T12:00:00+00:00"


def _identity(*, request: str = "request-1") -> SchedulerOccurrenceIdentity:
    return SchedulerOccurrenceIdentity(
        provider_id="openzyme.hpc.slurm",
        operation_kind=SchedulerOccurrenceKind.SUBMIT,
        operation_id="submit-1",
        request_digest=canonical_sha256_digest({"request": request}),
    )


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    return connection


def test_scheduler_ledger_recovers_private_handle_after_restart() -> None:
    connection = _connection()
    identity = _identity()
    first = SQLiteSchedulerOccurrenceLedger(connection, _Clock())
    assert first.reserve(identity) is True
    uncertain = SchedulerDispatchReceipt.create(
        operation_id=identity.operation_id,
        request_digest=identity.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        opaque_handle_id=None,
        accepted=None,
        fallback_performed=False,
        diagnostic_id="diagnostic-submit-pending",
    )
    assert first.settle(identity, uncertain).ledger_version == 2

    restarted = SQLiteSchedulerOccurrenceLedger(connection, _Clock())
    terminal = SchedulerDispatchReceipt.create(
        operation_id=identity.operation_id,
        request_digest=identity.request_digest,
        effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
        opaque_handle_id="slurmh-123",
        accepted=True,
        fallback_performed=False,
        diagnostic_id=None,
    )
    settled = restarted.settle(
        identity,
        terminal,
        raw_scheduler_id="slurm-job-987",
    )

    assert settled.ledger_version == 3
    handle = SQLiteSchedulerOccurrenceLedger(connection, _Clock()).get_handle(
        identity.provider_id,
        "slurmh-123",
    )
    assert handle is not None
    assert handle.operation_id == identity.operation_id
    assert handle.raw_scheduler_id == "slurm-job-987"
    assert "slurm-job-987" not in repr(handle)


def test_scheduler_ledger_rejects_identity_collision_and_terminal_replacement() -> None:
    connection = _connection()
    ledger = SQLiteSchedulerOccurrenceLedger(connection, _Clock())
    identity = _identity()
    ledger.reserve(identity)
    receipt = SchedulerDispatchReceipt.create(
        operation_id=identity.operation_id,
        request_digest=identity.request_digest,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        opaque_handle_id=None,
        accepted=False,
        fallback_performed=False,
        diagnostic_id=None,
    )
    ledger.settle(identity, receipt)

    with pytest.raises(SQLiteSchedulerOccurrenceLedgerError):
        ledger.reserve(_identity(request="different"))
    with pytest.raises(SQLiteSchedulerOccurrenceLedgerError):
        ledger.settle(identity, receipt, raw_scheduler_id="slurm-job-987")
