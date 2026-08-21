from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceOperationIdentity
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedger
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedgerError
from openzyme_store_sqlite import install_store_schema_for_offline_migration


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-22T12:00:00+00:00"


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    install_store_schema_for_offline_migration(connection)
    return connection


def _identity(*, intent: str = "intent-1") -> WorkspaceOperationIdentity:
    return WorkspaceOperationIdentity(
        provider_id="openzyme.filesystem.podman",
        operation_kind="filesystem",
        operation_id="operation-1",
        intent_digest=canonical_sha256_digest({"intent": intent}),
        session_id="session-1",
        workspace_id="workspace-1",
        generation=3,
        state_version=2,
    )


def _receipt(
    certainty: ExternalEffectCertainty,
    *,
    result: bytes = b"",
) -> WorkspaceOperationReceipt:
    return WorkspaceOperationReceipt.create(
        operation_id="operation-1",
        workspace_id="workspace-1",
        generation=3,
        state_version=2,
        effect_certainty=certainty,
        mutation_applied=(
            None
            if certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else False
            if certainty is ExternalEffectCertainty.NO_EFFECT
            else True
        ),
        result_payload=result,
        diagnostic_id=(
            "diagnostic-operation-pending"
            if certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else None
        ),
    )


def test_workspace_ledger_reserves_once_and_recovers_terminal_receipt() -> None:
    connection = _connection()
    identity = _identity()
    first = SQLiteWorkspaceOperationLedger(connection, _Clock())

    assert first.reserve(identity) is True
    assert first.reserve(identity) is False
    assert first.read(identity).ledger_version == 1
    assert first.read(identity).receipt is None

    uncertain = first.settle(
        identity,
        _receipt(ExternalEffectCertainty.DISPATCH_IN_DOUBT),
    )
    assert uncertain.ledger_version == 2

    restarted = SQLiteWorkspaceOperationLedger(connection, _Clock())
    assert restarted.read(identity) == uncertain
    terminal_receipt = _receipt(
        ExternalEffectCertainty.TERMINAL_KNOWN,
        result=b'{"path":"results/out.txt"}',
    )
    terminal = restarted.settle(identity, terminal_receipt)

    assert terminal.ledger_version == 3
    assert SQLiteWorkspaceOperationLedger(connection, _Clock()).read(identity) == terminal


def test_workspace_ledger_rejects_identity_collision_and_terminal_replacement() -> None:
    connection = _connection()
    ledger = SQLiteWorkspaceOperationLedger(connection, _Clock())
    identity = _identity()
    ledger.reserve(identity)
    terminal = _receipt(ExternalEffectCertainty.TERMINAL_KNOWN, result=b"{}")
    ledger.settle(identity, terminal)

    with pytest.raises(SQLiteWorkspaceOperationLedgerError):
        ledger.reserve(_identity(intent="different"))
    with pytest.raises(SQLiteWorkspaceOperationLedgerError):
        ledger.settle(
            identity,
            _receipt(ExternalEffectCertainty.NO_EFFECT),
        )
