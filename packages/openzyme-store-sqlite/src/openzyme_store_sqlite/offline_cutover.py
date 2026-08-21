"""Closed receipts used by the explicit one-way @2 offline cutover."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from types import MappingProxyType
from typing import Mapping

from openzyme_contracts import canonical_json_bytes
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


OFFLINE_CUTOVER_LEDGER_SCHEMA_VERSION = "openzyme_offline_cutover_ledger@2"
OFFLINE_BACKUP_RECEIPT_SCHEMA_VERSION = "openzyme_offline_backup_receipt@2"
SESSION_CUTOVER_DISPOSITION_SCHEMA_VERSION = (
    "openzyme_session_cutover_disposition@2"
)


class OfflineCutoverState(StrEnum):
    PLANNED = "planned"
    APPLYING = "applying"
    COMPLETE = "complete"
    FAILED = "failed"


class OfflineBackupKind(StrEnum):
    DATABASE = "database"
    CONFIGURATION = "configuration"
    STORAGE = "storage"


class OfflineCutoverItemKind(StrEnum):
    COMPONENT = "component"
    TABLE = "table"
    IMPORT = "import"
    SESSION = "session"
    AUTHORITY = "authority"
    INVENTORY_BINDING = "inventory_binding"
    CONTINUATION = "continuation"
    CONTROLLED_OPERATION = "controlled_operation"
    WORKSPACE = "workspace"
    STORAGE = "storage"
    CONFIGURATION = "configuration"


class OfflineCutoverDisposition(StrEnum):
    MIGRATED = "migrated"
    RETAINED_HISTORICAL = "retained_historical"
    ALREADY_ABSENT = "already_absent"
    BLOCKED = "blocked"


class SessionCutoverDispositionKind(StrEnum):
    MIGRATED_AT2 = "migrated_at2"
    CLOSED_HISTORICAL_AT1 = "closed_historical_at1"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class OfflineBackupReceipt:
    backup_id: str
    backup_kind: OfflineBackupKind
    source_identity_digest: str
    backup_identity_digest: str
    verification_digest: str
    recoverable: bool
    verified_at: str

    def __post_init__(self) -> None:
        require_identifier(self.backup_id, field_name="backup_id")
        require_identifier(self.verified_at, field_name="verified_at")
        for field_name in (
            "source_identity_digest",
            "backup_identity_digest",
            "verification_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if not self.recoverable:
            raise ValueError("cutover backup must be independently recoverable")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": OFFLINE_BACKUP_RECEIPT_SCHEMA_VERSION,
            "backup_id": self.backup_id,
            "backup_kind": self.backup_kind.value,
            "source_identity_digest": self.source_identity_digest,
            "backup_identity_digest": self.backup_identity_digest,
            "verification_digest": self.verification_digest,
            "recoverable": self.recoverable,
            "verified_at": self.verified_at,
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(self.payload)


@dataclass(frozen=True, slots=True)
class OfflineCutoverItem:
    item_kind: OfflineCutoverItemKind
    item_id: str
    expected_disposition: OfflineCutoverDisposition
    observed_disposition: OfflineCutoverDisposition
    item_payload: Mapping[str, object]
    size_bytes: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.item_id, field_name="item_id")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise ValueError("size_bytes must be a non-negative integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        if self.error_code is not None:
            require_identifier(self.error_code, field_name="error_code")
        object.__setattr__(
            self,
            "item_payload",
            MappingProxyType(json.loads(canonical_json_bytes(self.item_payload))),
        )

    @property
    def payload(self) -> dict[str, object]:
        return {
            "item_kind": self.item_kind.value,
            "item_id": self.item_id,
            "expected_disposition": self.expected_disposition.value,
            "observed_disposition": self.observed_disposition.value,
            "item_payload": dict(self.item_payload),
            "size_bytes": self.size_bytes,
            "error_code": self.error_code,
        }

    @property
    def item_digest(self) -> str:
        return canonical_sha256_digest(self.payload)


@dataclass(frozen=True, slots=True)
class SessionCutoverDisposition:
    session_id: str
    disposition: SessionCutoverDispositionKind
    composition_pin_digest: str | None
    capability_binding_digest: str | None
    evidence_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.session_id, field_name="session_id")
        require_digest(self.evidence_digest, field_name="evidence_digest")
        for field_name in ("composition_pin_digest", "capability_binding_digest"):
            value = getattr(self, field_name)
            if value is not None:
                require_digest(value, field_name=field_name)
        if self.disposition is SessionCutoverDispositionKind.MIGRATED_AT2 and (
            self.composition_pin_digest is None
            or self.capability_binding_digest is None
        ):
            raise ValueError("migrated @2 Session requires exact pin and binding")
        if self.disposition is SessionCutoverDispositionKind.BLOCKED and (
            self.composition_pin_digest is not None
            or self.capability_binding_digest is not None
        ):
            raise ValueError("blocked Session cannot fabricate an @2 pin or binding")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": SESSION_CUTOVER_DISPOSITION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "disposition": self.disposition.value,
            "composition_pin_digest": self.composition_pin_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "evidence_digest": self.evidence_digest,
        }

    @property
    def disposition_digest(self) -> str:
        return canonical_sha256_digest(self.payload)


@dataclass(frozen=True, slots=True)
class OfflineCutoverLedgerReceipt:
    ledger_id: str
    state: OfflineCutoverState
    source_release_digest: str
    target_release_digest: str
    source_schema_manifest_digest: str
    target_schema_manifest_digest: str
    legacy_migration_receipt_digest: str
    component_inventory_digest: str
    table_owner_manifest_digest: str
    import_owner_manifest_digest: str
    authority_mapping_set_digest: str
    inventory_binding_set_digest: str
    continuation_set_digest: str
    unsettled_effect_set_digest: str
    quiescence_receipt_digest: str
    backups: tuple[OfflineBackupReceipt, ...]
    session_dispositions: tuple[SessionCutoverDisposition, ...]
    items: tuple[OfflineCutoverItem, ...]
    completed_at: str | None

    def __post_init__(self) -> None:
        require_identifier(self.ledger_id, field_name="ledger_id")
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
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        backups = tuple(sorted(self.backups, key=lambda item: item.backup_kind.value))
        if (
            len({item.backup_kind for item in backups}) != len(backups)
            or {item.backup_kind for item in backups} != set(OfflineBackupKind)
        ):
            raise ValueError("cutover requires exact database/configuration/storage backups")
        sessions = tuple(sorted(self.session_dispositions, key=lambda item: item.session_id))
        items = tuple(sorted(self.items, key=lambda item: (item.item_kind.value, item.item_id)))
        if len({item.session_id for item in sessions}) != len(sessions):
            raise ValueError("session dispositions must be unique")
        if len({(item.item_kind, item.item_id) for item in items}) != len(items):
            raise ValueError("cutover item identities must be unique")
        object.__setattr__(self, "backups", backups)
        object.__setattr__(self, "session_dispositions", sessions)
        object.__setattr__(self, "items", items)
        if self.state is OfflineCutoverState.COMPLETE:
            if not self.completed_at:
                raise ValueError("complete cutover requires completed_at")
            if any(
                item.error_code is not None
                or item.observed_disposition is OfflineCutoverDisposition.BLOCKED
                or item.observed_disposition is not item.expected_disposition
                for item in items
            ):
                raise ValueError("complete cutover requires an empty error closure")
            if any(
                item.disposition is SessionCutoverDispositionKind.BLOCKED
                for item in sessions
            ):
                raise ValueError("complete cutover cannot contain blocked Sessions")
        elif self.completed_at is not None:
            raise ValueError("only a complete cutover may carry completed_at")

    @property
    def backup_set_digest(self) -> str:
        return canonical_sha256_digest(
            [item.receipt_digest for item in self.backups]
        )

    @property
    def session_disposition_set_digest(self) -> str:
        return canonical_sha256_digest(
            [item.disposition_digest for item in self.session_dispositions]
        )

    def item_set_digest(self, disposition: OfflineCutoverDisposition | None) -> str:
        return canonical_sha256_digest(
            [
                item.item_digest
                for item in self.items
                if disposition is None or item.observed_disposition is disposition
            ]
        )

    @property
    def error_item_set_digest(self) -> str:
        return canonical_sha256_digest(
            [item.item_digest for item in self.items if item.error_code is not None]
        )

    @property
    def expected_byte_total(self) -> int:
        return sum(item.size_bytes for item in self.items)

    @property
    def migrated_byte_total(self) -> int:
        return sum(
            item.size_bytes
            for item in self.items
            if item.observed_disposition is OfflineCutoverDisposition.MIGRATED
        )

    @property
    def payload(self) -> dict[str, object]:
        backups = {item.backup_kind: item for item in self.backups}
        return {
            "schema_version": OFFLINE_CUTOVER_LEDGER_SCHEMA_VERSION,
            "ledger_id": self.ledger_id,
            "state": self.state.value,
            "source_release_digest": self.source_release_digest,
            "target_release_digest": self.target_release_digest,
            "source_schema_manifest_digest": self.source_schema_manifest_digest,
            "target_schema_manifest_digest": self.target_schema_manifest_digest,
            "legacy_migration_receipt_digest": self.legacy_migration_receipt_digest,
            "database_backup_digest": backups[OfflineBackupKind.DATABASE].receipt_digest,
            "configuration_backup_digest": backups[
                OfflineBackupKind.CONFIGURATION
            ].receipt_digest,
            "storage_backup_digest": backups[OfflineBackupKind.STORAGE].receipt_digest,
            "backup_set_digest": self.backup_set_digest,
            "component_inventory_digest": self.component_inventory_digest,
            "table_owner_manifest_digest": self.table_owner_manifest_digest,
            "import_owner_manifest_digest": self.import_owner_manifest_digest,
            "session_disposition_set_digest": self.session_disposition_set_digest,
            "authority_mapping_set_digest": self.authority_mapping_set_digest,
            "inventory_binding_set_digest": self.inventory_binding_set_digest,
            "continuation_set_digest": self.continuation_set_digest,
            "unsettled_effect_set_digest": self.unsettled_effect_set_digest,
            "quiescence_receipt_digest": self.quiescence_receipt_digest,
            "expected_item_set_digest": self.item_set_digest(None),
            "migrated_item_set_digest": self.item_set_digest(
                OfflineCutoverDisposition.MIGRATED
            ),
            "retained_historical_item_set_digest": self.item_set_digest(
                OfflineCutoverDisposition.RETAINED_HISTORICAL
            ),
            "already_absent_item_set_digest": self.item_set_digest(
                OfflineCutoverDisposition.ALREADY_ABSENT
            ),
            "error_item_set_digest": self.error_item_set_digest,
            "expected_byte_total": self.expected_byte_total,
            "migrated_byte_total": self.migrated_byte_total,
            "completed_at": self.completed_at,
            "backups": [item.payload for item in self.backups],
            "session_dispositions": [item.payload for item in self.session_dispositions],
            "items": [item.payload for item in self.items],
        }

    @property
    def ledger_digest(self) -> str:
        return canonical_sha256_digest(self.payload)


__all__ = [
    "OFFLINE_BACKUP_RECEIPT_SCHEMA_VERSION",
    "OFFLINE_CUTOVER_LEDGER_SCHEMA_VERSION",
    "SESSION_CUTOVER_DISPOSITION_SCHEMA_VERSION",
    "OfflineBackupKind",
    "OfflineBackupReceipt",
    "OfflineCutoverDisposition",
    "OfflineCutoverItem",
    "OfflineCutoverItemKind",
    "OfflineCutoverLedgerReceipt",
    "OfflineCutoverState",
    "SessionCutoverDisposition",
    "SessionCutoverDispositionKind",
]
