from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import json_compatible
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_store_sqlite import KernelCommandReceiptSQLiteKernelEntityCodec
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteControlStoreError
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _request(command_id: str, *, expected_session_version: int) -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command_id}",
        command_id=command_id,
        session_id="session-1",
        actor_id="agent-1",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=expected_session_version,
        idempotency_key=f"idempotency-{command_id}",
        command_digest=canonical_sha256_digest({"command_id": command_id}),
    )


def _store() -> tuple[sqlite3.Connection, SQLiteControlStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    store = SQLiteControlStore(
        connection,
        codecs=(
            SessionSQLiteKernelEntityCodec(),
            KernelCommandReceiptSQLiteKernelEntityCodec(),
        ),
    )
    bootstrap = store.begin(_request("bootstrap", expected_session_version=1))
    bootstrap.stage(
        KernelStateMutation.create(
            mutation_id="mutation-session-create",
            kind=KernelMutationKind.CREATE,
            entity_type="session",
            entity_id="session-1",
            expected_state_version=None,
            payload={
                "session_id": "session-1",
                "project_id": "project-1",
                "title": "Session",
                "objective": "Verify immutable receipts",
                "status": "active",
                "created_at": "2026-08-21T00:00:00+00:00",
                "updated_at": "2026-08-21T00:00:00+00:00",
            },
        )
    )
    bootstrap.commit()
    return connection, store


def _payload() -> dict[str, object]:
    receipt = KernelMutationReceipt.create(
        command_id="command-publish",
        service_id="openzyme.kernel.publication-application",
        operation="publish",
        mutation_applied=True,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        result={"publication_id": "publication-1"},
    )
    return {
        "session_id": "session-1",
        "command_digest": canonical_sha256_digest({"publish": 1}),
        "receipt": receipt.to_dict(),
        "created_at": "2026-08-21T00:01:00+00:00",
    }


def test_kernel_command_receipt_round_trips_through_immutable_owner_ledger() -> None:
    connection, store = _store()
    unit = store.begin(_request("publish", expected_session_version=1))
    payload = _payload()
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-command-receipt",
            kind=KernelMutationKind.CREATE,
            entity_type="kernel_command_receipt",
            entity_id="publish-idempotency-1",
            expected_state_version=None,
            payload=payload,
        )
    )

    unit.commit()

    stored = store.read(
        entity_type="kernel_command_receipt",
        entity_id="publish-idempotency-1",
    )
    assert stored is not None
    assert stored.state_version == 1
    assert json_compatible(stored.payload) == json_compatible(payload)
    row = connection.execute(
        "SELECT command_type, status FROM command_receipt_records "
        "WHERE command_receipt_id = 'publish-idempotency-1'"
    ).fetchone()
    assert row == ("openzyme.kernel.publication-application.publish", "completed")


def test_kernel_command_receipt_rejects_digest_drift_before_insert() -> None:
    connection, store = _store()
    payload = _payload()
    payload["receipt"] = {**payload["receipt"], "result": {"publication_id": "other"}}
    unit = store.begin(_request("drift", expected_session_version=1))
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-command-receipt-drift",
            kind=KernelMutationKind.CREATE,
            entity_type="kernel_command_receipt",
            entity_id="publish-idempotency-drift",
            expected_state_version=None,
            payload=payload,
        )
    )

    with pytest.raises(SQLiteControlStoreError) as rejected:
        unit.commit()

    assert rejected.value.code == "sqlite_kernel_command_receipt_digest_mismatch"
    assert connection.execute(
        "SELECT COUNT(*) FROM command_receipt_records"
    ).fetchone()[0] == 0
