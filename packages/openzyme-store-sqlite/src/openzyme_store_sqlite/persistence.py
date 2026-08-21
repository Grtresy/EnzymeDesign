from __future__ import annotations

import json
import sqlite3
from typing import Any

from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


class SQLitePersistenceError(RuntimeError):
    error_code = "sqlite_persistence_rejected"

    def __init__(self, message: str, *, phase: str, observed: object = None) -> None:
        self.phase = phase
        self.observed = observed
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; observed={observed!r}; "
            "mutation_applied=false; fallback_performed=false"
        )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _closed_json(raw: str, *, expected_fields: set[str], phase: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise SQLitePersistenceError(
            "stored JSON fields are not closed",
            phase=phase,
            observed=sorted(value) if isinstance(value, dict) else type(value).__name__,
        )
    return value


class SQLiteSessionCapabilityBindingRepository:
    """Append-only monotonic implementation of the Kernel binding repository Port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def latest(self, session_id: str) -> SessionCapabilityBindingRevision | None:
        row = self.connection.execute(
            """
            SELECT binding_json
            FROM openzyme_store_session_capability_binding_revisions
            WHERE session_id = ?
            ORDER BY revision DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return None if row is None else self._decode(str(row[0]))

    def append(
        self,
        binding: SessionCapabilityBindingRevision,
        *,
        expected_previous_revision: int | None,
    ) -> None:
        if not self.connection.in_transaction:
            raise SQLitePersistenceError(
                "binding append requires an active Kernel Unit of Work",
                phase="transaction_admission",
            )
        if not binding.has_valid_digest():
            raise SQLitePersistenceError(
                "binding digest is invalid",
                phase="binding_digest",
                observed=binding.binding_id,
            )
        previous = self.latest(binding.session_id)
        observed_revision = None if previous is None else previous.revision
        expected_revision = 1 if previous is None else previous.revision + 1
        if (
            observed_revision != expected_previous_revision
            or binding.revision != expected_revision
        ):
            raise SQLitePersistenceError(
                "binding predecessor or revision drifted",
                phase="binding_compare_and_swap",
                observed={
                    "expected_previous_revision": expected_previous_revision,
                    "observed_previous_revision": observed_revision,
                    "binding_revision": binding.revision,
                    "required_revision": expected_revision,
                },
            )
        if previous is not None and (
            binding.extension_bundle_digest != previous.extension_bundle_digest
            or binding.route_catalog_digest != previous.route_catalog_digest
        ):
            raise SQLitePersistenceError(
                "binding attempted to hot-swap a Session bundle",
                phase="binding_bundle",
                observed=binding.session_id,
            )
        try:
            self.connection.execute(
                """
                INSERT INTO openzyme_store_session_capability_binding_revisions (
                    binding_id, session_id, revision, extension_bundle_digest,
                    route_catalog_digest, binding_digest, binding_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.binding_id,
                    binding.session_id,
                    binding.revision,
                    binding.extension_bundle_digest,
                    binding.route_catalog_digest,
                    binding.binding_digest,
                    _json(binding.to_dict()),
                    binding.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise SQLitePersistenceError(
                "binding identity conflicted",
                phase="binding_write",
                observed=exc.__class__.__qualname__,
            ) from exc

    @staticmethod
    def _decode(raw: str) -> SessionCapabilityBindingRevision:
        payload = _closed_json(
            raw,
            expected_fields={
                "schema_version",
                "binding_id",
                "session_id",
                "revision",
                "extension_bundle_digest",
                "route_catalog_digest",
                "inventory_bindings",
                "created_by_actor_id",
                "created_at",
                "binding_digest",
            },
            phase="binding_decode",
        )
        raw_bindings = payload["inventory_bindings"]
        if not isinstance(raw_bindings, list):
            raise SQLitePersistenceError(
                "stored binding inventory list is invalid",
                phase="binding_decode",
            )
        bindings = tuple(
            TargetInventoryBinding(
                target_id=str(item["target_id"]),
                inventory_generation=int(item["inventory_generation"]),
                inventory_digest=str(item["inventory_digest"]),
                qualification_valid_until=str(item["qualification_valid_until"]),
            )
            for item in raw_bindings
            if isinstance(item, dict)
            and set(item)
            == {
                "target_id",
                "inventory_generation",
                "inventory_digest",
                "qualification_valid_until",
            }
        )
        if len(bindings) != len(raw_bindings):
            raise SQLitePersistenceError(
                "stored inventory binding fields are not closed",
                phase="binding_decode",
            )
        binding = SessionCapabilityBindingRevision(
            binding_id=str(payload["binding_id"]),
            session_id=str(payload["session_id"]),
            revision=int(payload["revision"]),
            extension_bundle_digest=str(payload["extension_bundle_digest"]),
            route_catalog_digest=str(payload["route_catalog_digest"]),
            inventory_bindings=bindings,
            created_by_actor_id=str(payload["created_by_actor_id"]),
            created_at=str(payload["created_at"]),
            binding_digest=str(payload["binding_digest"]),
        )
        if not binding.has_valid_digest():
            raise SQLitePersistenceError(
                "stored binding digest drifted",
                phase="binding_decode",
                observed=binding.binding_id,
            )
        return binding


class SQLiteCompositionIdentityRepository:
    """Stores stable release facts only; transient target health is not accepted."""

    _CATALOG_KINDS = frozenset(
        {
            "adapter_bundle",
            "extension_bundle",
            "declared_tool",
            "route",
            "projection",
            "migration",
            "workspace_backend",
        }
    )

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append_extension_bundle(
        self,
        *,
        bundle_digest: str,
        bundle: dict[str, Any],
        activation_epoch_id: str,
        created_at: str,
    ) -> None:
        self._require_transaction()
        require_digest(bundle_digest, field_name="bundle_digest")
        require_identifier(activation_epoch_id, field_name="activation_epoch_id")
        if canonical_sha256_digest(bundle) != bundle_digest:
            raise SQLitePersistenceError(
                "extension bundle digest differs from its payload",
                phase="extension_bundle_digest",
            )
        self._insert_exact(
            """
            INSERT INTO openzyme_store_extension_bundle_records (
                bundle_digest, bundle_json, activated_epoch_id, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (bundle_digest, _json(bundle), activation_epoch_id, created_at),
            phase="extension_bundle_write",
        )

    def append_catalog_identity(
        self,
        *,
        catalog_kind: str,
        catalog_digest: str,
        activation_epoch_id: str,
        catalog: dict[str, Any],
        created_at: str,
    ) -> None:
        self._require_transaction()
        if catalog_kind not in self._CATALOG_KINDS:
            raise SQLitePersistenceError(
                "catalog kind is not in the closed set",
                phase="catalog_admission",
                observed=catalog_kind,
            )
        require_digest(catalog_digest, field_name="catalog_digest")
        if canonical_sha256_digest(catalog) != catalog_digest:
            raise SQLitePersistenceError(
                "catalog digest differs from its payload",
                phase="catalog_digest",
                observed=catalog_kind,
            )
        self._insert_exact(
            """
            INSERT INTO openzyme_store_catalog_identity_records (
                catalog_kind, catalog_digest, activation_epoch_id,
                catalog_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                catalog_kind,
                catalog_digest,
                activation_epoch_id,
                _json(catalog),
                created_at,
            ),
            phase="catalog_write",
        )

    def _require_transaction(self) -> None:
        if not self.connection.in_transaction:
            raise SQLitePersistenceError(
                "composition identity write requires an active Unit of Work",
                phase="transaction_admission",
            )

    def _insert_exact(self, sql: str, parameters: tuple[object, ...], *, phase: str) -> None:
        try:
            self.connection.execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            raise SQLitePersistenceError(
                "immutable composition identity conflicted",
                phase=phase,
                observed=exc.__class__.__qualname__,
            ) from exc


class SQLiteResourceCapabilityFactRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append(self, fact: ResourceCapabilityFact, *, created_at: str) -> None:
        if not self.connection.in_transaction:
            raise SQLitePersistenceError(
                "resource fact write requires an active Unit of Work",
                phase="transaction_admission",
            )
        try:
            self.connection.execute(
                """
                INSERT INTO openzyme_store_resource_capability_fact_records (
                    target_id, inventory_generation, capability_id, fact_digest,
                    inventory_digest, fact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.target_id,
                    fact.inventory_generation,
                    fact.capability_id,
                    fact.fact_digest,
                    fact.inventory_digest,
                    _json(fact.to_dict()),
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise SQLitePersistenceError(
                "resource capability fact conflicted",
                phase="resource_fact_write",
                observed=exc.__class__.__qualname__,
            ) from exc

    def list_generation(
        self,
        *,
        target_id: str,
        inventory_generation: int,
    ) -> tuple[ResourceCapabilityFact, ...]:
        rows = self.connection.execute(
            """
            SELECT fact_json
            FROM openzyme_store_resource_capability_fact_records
            WHERE target_id = ? AND inventory_generation = ?
            ORDER BY capability_id
            """,
            (target_id, inventory_generation),
        ).fetchall()
        return tuple(self._decode(str(row[0])) for row in rows)

    @staticmethod
    def _decode(raw: str) -> ResourceCapabilityFact:
        payload = _closed_json(
            raw,
            expected_fields={
                "schema_version",
                "capability_id",
                "kind",
                "target_id",
                "inventory_generation",
                "qualification_digest",
                "environment_digest",
                "inventory_digest",
                "contract_version",
                "operations",
                "version",
            },
            phase="resource_fact_decode",
        )
        fact = ResourceCapabilityFact(
            capability_id=str(payload["capability_id"]),
            kind=ResourceCapabilityKind(str(payload["kind"])),
            target_id=str(payload["target_id"]),
            inventory_generation=int(payload["inventory_generation"]),
            qualification_digest=str(payload["qualification_digest"]),
            environment_digest=str(payload["environment_digest"]),
            inventory_digest=str(payload["inventory_digest"]),
            contract_version=str(payload["contract_version"]),
            operations=tuple(str(item) for item in payload["operations"]),
            version=None if payload["version"] is None else str(payload["version"]),
        )
        return fact


class SQLiteWorkspaceOperationReceiptRepository:
    """Persists immutable operation facts, never inferred scientific/Task state."""

    _CERTAINTIES = frozenset({"no_effect", "dispatch_in_doubt", "settled"})

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append(
        self,
        *,
        operation_id: str,
        workspace_id: str,
        workspace_generation: int,
        operation_kind: str,
        effect_certainty: str,
        receipt: dict[str, Any],
        settled_at: str,
    ) -> str:
        if not self.connection.in_transaction:
            raise SQLitePersistenceError(
                "workspace receipt write requires an active Unit of Work",
                phase="transaction_admission",
            )
        if effect_certainty not in self._CERTAINTIES:
            raise SQLitePersistenceError(
                "effect certainty is not in the closed set",
                phase="workspace_receipt_admission",
                observed=effect_certainty,
            )
        if workspace_generation < 1:
            raise SQLitePersistenceError(
                "workspace generation must be positive",
                phase="workspace_receipt_admission",
                observed=workspace_generation,
            )
        receipt_digest = canonical_sha256_digest(receipt)
        try:
            self.connection.execute(
                """
                INSERT INTO openzyme_store_workspace_operation_receipts (
                    operation_id, workspace_id, workspace_generation,
                    operation_kind, effect_certainty, receipt_digest,
                    receipt_json, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    workspace_id,
                    workspace_generation,
                    operation_kind,
                    effect_certainty,
                    receipt_digest,
                    _json(receipt),
                    settled_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise SQLitePersistenceError(
                "workspace receipt identity conflicted",
                phase="workspace_receipt_write",
                observed=exc.__class__.__qualname__,
            ) from exc
        return receipt_digest


__all__ = [
    "SQLiteCompositionIdentityRepository",
    "SQLitePersistenceError",
    "SQLiteResourceCapabilityFactRepository",
    "SQLiteSessionCapabilityBindingRepository",
    "SQLiteWorkspaceOperationReceiptRepository",
]
