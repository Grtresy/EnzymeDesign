"""Unified target Store startup proof over owner tables and Store mechanism tables."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .migration_catalog import STORE_SCHEMA_USER_VERSION
from .migration_catalog import schema_manifest_digest
from .owner_startup import OwnerPartitionedSchemaProof
from .owner_startup import OwnerSchemaProfile
from .owner_startup import verify_owner_partitioned_schema_read_only
from .startup import SQLiteStartupSchemaProof
from .startup import verify_store_schema_read_only


_COMPOSITION_CATALOG_KINDS = frozenset(
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


class SQLiteStartupCompositionVerificationError(RuntimeError):
    error_code = "sqlite_startup_composition_verification_failed"

    def __init__(self, message: str, *, phase: str, observed: object = None) -> None:
        self.phase = phase
        self.observed = observed
        self.mutation_applied = False
        self.plugin_import_performed = False
        self.writer_enabled = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; observed={observed!r}; "
            "mutation_applied=false; plugin_import_performed=false; "
            "writer_enabled=false; fallback_performed=false"
        )


@dataclass(frozen=True, slots=True)
class SQLiteStartupCompositionExpectation:
    """Operator-selected stable identities, supplied without importing Plugins."""

    activation_epoch_id: str
    extension_bundle_digest: str
    catalog_digests: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        require_identifier(self.activation_epoch_id, field_name="activation_epoch_id")
        require_digest(
            self.extension_bundle_digest,
            field_name="extension_bundle_digest",
        )
        kinds = tuple(kind for kind, _ in self.catalog_digests)
        if len(kinds) != len(set(kinds)):
            raise ValueError("startup catalog kinds must be unique")
        unknown = set(kinds).difference(_COMPOSITION_CATALOG_KINDS)
        if unknown:
            raise ValueError(f"startup catalog kinds are unknown: {sorted(unknown)!r}")
        required = {"adapter_bundle", "extension_bundle", "migration"}
        missing = required.difference(kinds)
        if missing:
            raise ValueError(
                f"startup composition is missing required catalogs: {sorted(missing)!r}"
            )
        for kind, digest in self.catalog_digests:
            require_identifier(kind, field_name="catalog_kind")
            require_digest(digest, field_name=f"{kind}_catalog_digest")
        object.__setattr__(self, "catalog_digests", tuple(sorted(self.catalog_digests)))

    @property
    def expectation_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_sqlite_startup_composition_expectation@1",
            "activation_epoch_id": self.activation_epoch_id,
            "extension_bundle_digest": self.extension_bundle_digest,
            "catalog_digests": [
                {"catalog_kind": kind, "catalog_digest": digest}
                for kind, digest in self.catalog_digests
            ],
        }


@dataclass(frozen=True, slots=True)
class SQLiteStartupCompositionProof:
    expectation: SQLiteStartupCompositionExpectation
    extension_bundle_record_digest: str
    catalog_record_set_digest: str
    verified_catalog_count: int

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_sqlite_startup_composition_proof@1",
            "expectation_digest": self.expectation.expectation_digest,
            "extension_bundle_record_digest": self.extension_bundle_record_digest,
            "catalog_record_set_digest": self.catalog_record_set_digest,
            "verified_catalog_count": self.verified_catalog_count,
            "mutation_applied": False,
            "plugin_import_performed": False,
            "writer_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class CompositeSQLiteStartupProof:
    user_version: int
    owner_schema_proof_digest: str
    store_schema_proof_digest: str
    complete_schema_manifest_digest: str
    complete_object_count: int
    owner_schema: OwnerPartitionedSchemaProof
    store_schema: SQLiteStartupSchemaProof
    composition: SQLiteStartupCompositionProof | None = None
    mutation_applied: bool = False
    plugin_import_performed: bool = False
    writer_enabled: bool = False

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_composite_sqlite_startup_proof@1",
            "user_version": self.user_version,
            "owner_schema_proof_digest": self.owner_schema_proof_digest,
            "store_schema_proof_digest": self.store_schema_proof_digest,
            "complete_schema_manifest_digest": self.complete_schema_manifest_digest,
            "complete_object_count": self.complete_object_count,
            "composition_proof_digest": (
                None if self.composition is None else self.composition.proof_digest
            ),
            "mutation_applied": self.mutation_applied,
            "plugin_import_performed": self.plugin_import_performed,
            "writer_enabled": self.writer_enabled,
        }


def verify_composite_store_schema_read_only(
    connection: sqlite3.Connection,
    *,
    expectation: SQLiteStartupCompositionExpectation | None = None,
    owner_schema_profile: OwnerSchemaProfile | None = None,
) -> CompositeSQLiteStartupProof:
    """Verify both exact closures before any target writer or Plugin import."""

    initial_changes = connection.total_changes
    initial_transaction = connection.in_transaction
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version != STORE_SCHEMA_USER_VERSION:
            # The component verifiers provide the typed, operator-facing failure.
            verify_owner_partitioned_schema_read_only(
                connection,
                profile=owner_schema_profile,
                composite_user_version=STORE_SCHEMA_USER_VERSION,
            )
        owner = verify_owner_partitioned_schema_read_only(
            connection,
            profile=owner_schema_profile,
            composite_user_version=STORE_SCHEMA_USER_VERSION,
        )
        store = verify_store_schema_read_only(connection)
        rows = tuple(
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                """
                SELECT type, name, COALESCE(sql, '')
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                ORDER BY type, name
                """
            ).fetchall()
        )
        composition = (
            None
            if expectation is None
            else _verify_composition_identity(connection, expectation)
        )
        return CompositeSQLiteStartupProof(
            user_version=user_version,
            owner_schema_proof_digest=owner.proof_digest,
            store_schema_proof_digest=store.proof_digest,
            complete_schema_manifest_digest=schema_manifest_digest(rows),
            complete_object_count=len(rows),
            owner_schema=owner,
            store_schema=store,
            composition=composition,
        )
    finally:
        if (
            connection.total_changes != initial_changes
            or connection.in_transaction != initial_transaction
        ):
            raise RuntimeError("composite startup verifier violated zero-mutation")


def _verify_composition_identity(
    connection: sqlite3.Connection,
    expectation: SQLiteStartupCompositionExpectation,
) -> SQLiteStartupCompositionProof:
    bundle_row = connection.execute(
        """
        SELECT bundle_json, activated_epoch_id
        FROM openzyme_store_extension_bundle_records
        WHERE bundle_digest = ?
        """,
        (expectation.extension_bundle_digest,),
    ).fetchone()
    if bundle_row is None or str(bundle_row[1]) != expectation.activation_epoch_id:
        raise SQLiteStartupCompositionVerificationError(
            "selected extension bundle record is absent or belongs to another epoch",
            phase="extension_bundle",
            observed=None if bundle_row is None else str(bundle_row[1]),
        )
    bundle_payload = _closed_json_object(str(bundle_row[0]), phase="extension_bundle")
    if canonical_sha256_digest(bundle_payload) != expectation.extension_bundle_digest:
        raise SQLiteStartupCompositionVerificationError(
            "selected extension bundle payload digest drifted",
            phase="extension_bundle_digest",
            observed=canonical_sha256_digest(bundle_payload),
        )

    expected_catalogs = dict(expectation.catalog_digests)
    rows = connection.execute(
        """
        SELECT catalog_kind, catalog_digest, catalog_json
        FROM openzyme_store_catalog_identity_records
        WHERE activation_epoch_id = ?
        ORDER BY catalog_kind
        """,
        (expectation.activation_epoch_id,),
    ).fetchall()
    observed_kinds = [str(row[0]) for row in rows]
    if len(observed_kinds) != len(set(observed_kinds)) or set(observed_kinds) != set(
        expected_catalogs
    ):
        raise SQLiteStartupCompositionVerificationError(
            "activation epoch catalog closure differs from the selected composition",
            phase="catalog_closure",
            observed={
                "expected": sorted(expected_catalogs),
                "observed": observed_kinds,
            },
        )
    safe_records: list[dict[str, str]] = []
    for kind_value, digest_value, raw_value in rows:
        kind = str(kind_value)
        digest = str(digest_value)
        payload = _closed_json_value(str(raw_value), phase=f"catalog:{kind}")
        payload_digest = canonical_sha256_digest(payload)
        if digest != expected_catalogs[kind] or payload_digest != digest:
            raise SQLiteStartupCompositionVerificationError(
                "catalog identity or payload digest drifted",
                phase="catalog_digest",
                observed={
                    "catalog_kind": kind,
                    "expected": expected_catalogs[kind],
                    "row": digest,
                    "payload": payload_digest,
                },
            )
        safe_records.append({"catalog_kind": kind, "catalog_digest": digest})
    return SQLiteStartupCompositionProof(
        expectation=expectation,
        extension_bundle_record_digest=canonical_sha256_digest(
            {
                "bundle_digest": expectation.extension_bundle_digest,
                "activation_epoch_id": expectation.activation_epoch_id,
            }
        ),
        catalog_record_set_digest=canonical_sha256_digest(safe_records),
        verified_catalog_count=len(safe_records),
    )


def _closed_json_object(raw: str, *, phase: str) -> dict[str, object]:
    value = _closed_json_value(raw, phase=phase)
    if not isinstance(value, dict):
        raise SQLiteStartupCompositionVerificationError(
            "composition identity JSON must be an object",
            phase=phase,
            observed=type(value).__name__,
        )
    return value


def _closed_json_value(raw: str, *, phase: str) -> dict[str, object] | list[object]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SQLiteStartupCompositionVerificationError(
            "composition identity JSON is invalid",
            phase=phase,
            observed=exc.__class__.__qualname__,
        ) from exc
    if not isinstance(value, dict | list):
        raise SQLiteStartupCompositionVerificationError(
            "composition catalog JSON must be an object or array",
            phase=phase,
            observed=type(value).__name__,
        )
    return value


__all__ = [
    "CompositeSQLiteStartupProof",
    "SQLiteStartupCompositionExpectation",
    "SQLiteStartupCompositionProof",
    "SQLiteStartupCompositionVerificationError",
    "verify_composite_store_schema_read_only",
]
