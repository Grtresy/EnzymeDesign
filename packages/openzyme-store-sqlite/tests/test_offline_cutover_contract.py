from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import OfflineBackupKind
from openzyme_store_sqlite import OfflineBackupReceipt
from openzyme_store_sqlite import OfflineCutoverDisposition
from openzyme_store_sqlite import OfflineCutoverItem
from openzyme_store_sqlite import OfflineCutoverItemKind
from openzyme_store_sqlite import OfflineCutoverLedgerReceipt
from openzyme_store_sqlite import OfflineCutoverState
from openzyme_store_sqlite import SessionCutoverDisposition
from openzyme_store_sqlite import SessionCutoverDispositionKind


def _digest(label: str) -> str:
    return canonical_sha256_digest({"identity": label})


def _backups() -> tuple[OfflineBackupReceipt, ...]:
    return tuple(
        OfflineBackupReceipt(
            backup_id=f"backup-{kind.value}",
            backup_kind=kind,
            source_identity_digest=_digest(f"source:{kind.value}"),
            backup_identity_digest=_digest(f"backup:{kind.value}"),
            verification_digest=_digest(f"verify:{kind.value}"),
            recoverable=True,
            verified_at="2026-08-20T00:00:00+00:00",
        )
        for kind in OfflineBackupKind
    )


def _ledger() -> OfflineCutoverLedgerReceipt:
    item = OfflineCutoverItem(
        item_kind=OfflineCutoverItemKind.SESSION,
        item_id="session-1",
        expected_disposition=OfflineCutoverDisposition.MIGRATED,
        observed_disposition=OfflineCutoverDisposition.MIGRATED,
        item_payload={"source_contract": "file_workspace_public@1"},
        size_bytes=123,
    )
    session = SessionCutoverDisposition(
        session_id="session-1",
        disposition=SessionCutoverDispositionKind.MIGRATED_AT2,
        composition_pin_digest=_digest("pin"),
        capability_binding_digest=_digest("binding"),
        evidence_digest=_digest("session-evidence"),
    )
    values = {
        field_name: _digest(field_name)
        for field_name in (
            "source_release_digest",
            "target_release_digest",
            "source_schema_manifest_digest",
            "target_schema_manifest_digest",
            "legacy_migration_receipt_digest",
            "component_inventory_digest",
            "table_owner_manifest_digest",
            "import_owner_manifest_digest",
            "authority_mapping_set_digest",
            "inventory_binding_set_digest",
            "continuation_set_digest",
            "unsettled_effect_set_digest",
            "quiescence_receipt_digest",
        )
    }
    return OfflineCutoverLedgerReceipt(
        ledger_id="cutover-1",
        state=OfflineCutoverState.COMPLETE,
        backups=_backups(),
        session_dispositions=(session,),
        items=(item,),
        completed_at="2026-08-20T01:00:00+00:00",
        **values,
    )


def test_complete_cutover_ledger_has_deterministic_closed_set_and_byte_digests() -> None:
    first = _ledger()
    second = _ledger()

    assert first.ledger_digest == second.ledger_digest
    assert first.expected_byte_total == 123
    assert first.migrated_byte_total == 123
    assert first.error_item_set_digest == canonical_sha256_digest([])
    assert first.payload["backup_set_digest"] == first.backup_set_digest


def test_complete_cutover_rejects_blocked_or_mismatched_item() -> None:
    ledger = _ledger()
    blocked = replace(
        ledger.items[0],
        observed_disposition=OfflineCutoverDisposition.BLOCKED,
        error_code="session_mapping_ambiguous",
    )

    with pytest.raises(ValueError, match="empty error closure"):
        replace(ledger, items=(blocked,))


def test_cutover_requires_three_independently_verified_recoverable_backups() -> None:
    ledger = _ledger()

    with pytest.raises(ValueError, match="exact database/configuration/storage"):
        replace(ledger, backups=ledger.backups[:2])
    with pytest.raises(ValueError, match="independently recoverable"):
        replace(ledger.backups[0], recoverable=False)


def test_blocked_session_cannot_carry_a_fabricated_at2_pin() -> None:
    session = _ledger().session_dispositions[0]

    with pytest.raises(ValueError, match="cannot fabricate"):
        replace(session, disposition=SessionCutoverDispositionKind.BLOCKED)
