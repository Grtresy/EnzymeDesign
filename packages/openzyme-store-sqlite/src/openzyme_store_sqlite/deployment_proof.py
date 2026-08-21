"""Deterministic target deployment proof persisted by the SQLite Store Adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import sqlite3

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .composite_startup import CompositeSQLiteStartupProof
from .composite_startup import SQLiteStartupCompositionExpectation
from .composite_startup import verify_composite_store_schema_read_only
from .owner_startup import OwnerSchemaProfile


FRESH_INSTALL_BOOTSTRAP_RECEIPT_SCHEMA_VERSION = (
    "openzyme_fresh_install_bootstrap_receipt@2"
)
DEPLOYMENT_SCHEMA_STATE_SCHEMA_VERSION = "openzyme_deployment_schema_state@2"

_CATALOG_KINDS = (
    "adapter_bundle",
    "extension_bundle",
    "declared_tool",
    "route",
    "projection",
    "migration",
    "workspace_backend",
)
_SEED_TABLES = frozenset(
    {
        "openzyme_store_deployment_activation_epochs",
        "openzyme_store_fresh_install_receipts",
        "openzyme_store_extension_bundle_records",
        "openzyme_store_catalog_identity_records",
        "openzyme_store_deployment_schema_state",
    }
)


class DeploymentProofVariant(StrEnum):
    FRESH_INSTALL_COMPLETE = "fresh_install_complete"
    OFFLINE_REMOVAL_COMPLETE = "offline_removal_complete"


class SQLiteDeploymentProofError(RuntimeError):
    error_code = "sqlite_deployment_proof_rejected"

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        expected: object = None,
        observed: object = None,
        operator_action: str,
    ) -> None:
        self.phase = phase
        self.expected = expected
        self.observed = observed
        self.operator_action = operator_action
        self.mutation_applied = False
        self.plugin_import_performed = False
        self.writer_enabled = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; expected={expected!r}; observed={observed!r}; "
            f"operator_action={operator_action}; mutation_applied=false; "
            "plugin_import_performed=false; writer_enabled=false; "
            "fallback_performed=false"
        )


@dataclass(frozen=True, slots=True)
class MigrationSourceIdentity:
    owner_component_id: str
    migration_id: str
    migration_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.owner_component_id, field_name="owner_component_id")
        require_identifier(self.migration_id, field_name="migration_id")
        require_digest(self.migration_digest, field_name="migration_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "owner_component_id": self.owner_component_id,
            "migration_id": self.migration_id,
            "migration_digest": self.migration_digest,
        }


@dataclass(frozen=True, slots=True)
class FreshInstallBootstrapReceiptV2:
    distribution_id: str
    schema_generation: str
    schema_manifest_digest: str
    owner_schema_profile_id: str
    owner_schema_profile_digest: str
    release_identity: LayeredReleaseIdentity
    migration_sources: tuple[MigrationSourceIdentity, ...]
    installed_wheel_set_digest: str
    table_owner_manifest_digest: str
    empty_application_table_count: int
    empty_application_table_set_digest: str
    legacy_schema_initialized: bool = False
    legacy_storage_initialized: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "distribution_id",
            "schema_generation",
            "owner_schema_profile_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "schema_manifest_digest",
            "owner_schema_profile_digest",
            "installed_wheel_set_digest",
            "table_owner_manifest_digest",
            "empty_application_table_set_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.empty_application_table_count < 1:
            raise ValueError("empty_application_table_count must be positive")
        ordered = tuple(
            sorted(
                self.migration_sources,
                key=lambda item: (item.owner_component_id, item.migration_id),
            )
        )
        if not ordered or len(ordered) != len(set(ordered)):
            raise ValueError("migration_sources must be non-empty and unique")
        object.__setattr__(self, "migration_sources", ordered)
        if self.legacy_schema_initialized or self.legacy_storage_initialized:
            raise ValueError("fresh @2 bootstrap cannot initialize legacy state")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": FRESH_INSTALL_BOOTSTRAP_RECEIPT_SCHEMA_VERSION,
            "proof_variant": DeploymentProofVariant.FRESH_INSTALL_COMPLETE.value,
            "distribution_id": self.distribution_id,
            "schema_generation": self.schema_generation,
            "schema_manifest_digest": self.schema_manifest_digest,
            "owner_schema_profile_id": self.owner_schema_profile_id,
            "owner_schema_profile_digest": self.owner_schema_profile_digest,
            "release_identity": self.release_identity.to_dict(),
            "migration_sources": [item.to_dict() for item in self.migration_sources],
            "installed_wheel_set_digest": self.installed_wheel_set_digest,
            "table_owner_manifest_digest": self.table_owner_manifest_digest,
            "empty_application_table_count": self.empty_application_table_count,
            "empty_application_table_set_digest": (
                self.empty_application_table_set_digest
            ),
            "legacy_schema_initialized": self.legacy_schema_initialized,
            "legacy_storage_initialized": self.legacy_storage_initialized,
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(self.payload)


@dataclass(frozen=True, slots=True)
class FreshInstallCompositionSeed:
    schema_proof: CompositeSQLiteStartupProof
    owner_schema_profile: OwnerSchemaProfile
    activation_epoch: DeploymentActivationEpoch
    catalog_payloads: tuple[tuple[str, object], ...]
    migration_sources: tuple[MigrationSourceIdentity, ...]
    installed_wheel_set_digest: str
    table_owner_manifest_digest: str

    def __post_init__(self) -> None:
        require_digest(
            self.installed_wheel_set_digest,
            field_name="installed_wheel_set_digest",
        )
        require_digest(
            self.table_owner_manifest_digest,
            field_name="table_owner_manifest_digest",
        )
        kinds = tuple(kind for kind, _ in self.catalog_payloads)
        if kinds != _CATALOG_KINDS:
            raise ValueError(f"catalog_payloads must use exact order {_CATALOG_KINDS!r}")
        if not self.activation_epoch.has_valid_digest():
            raise ValueError("activation_epoch digest is invalid")
        if (
            self.activation_epoch.release_identity.core_schema_digest
            != self.schema_proof.complete_schema_manifest_digest
        ):
            raise ValueError("release identity does not bind the exact schema manifest")

    @property
    def catalog_digests(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (kind, canonical_sha256_digest(payload))
            for kind, payload in self.catalog_payloads
        )

    @property
    def startup_expectation(self) -> SQLiteStartupCompositionExpectation:
        return SQLiteStartupCompositionExpectation(
            activation_epoch_id=self.activation_epoch.epoch_id,
            extension_bundle_digest=self.activation_epoch.release_identity.extension_bundle_digest,
            catalog_digests=self.catalog_digests,
        )


@dataclass(frozen=True, slots=True)
class FreshInstallDeploymentProof:
    schema: CompositeSQLiteStartupProof
    receipt: FreshInstallBootstrapReceiptV2
    deployment_state_digest: str
    activation_digest: str
    mutation_applied: bool = False
    plugin_import_performed: bool = False
    writer_enabled: bool = False

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_fresh_install_deployment_proof@2",
                "schema_proof_digest": self.schema.proof_digest,
                "receipt_digest": self.receipt.receipt_digest,
                "deployment_state_digest": self.deployment_state_digest,
                "activation_digest": self.activation_digest,
                "mutation_applied": self.mutation_applied,
                "plugin_import_performed": self.plugin_import_performed,
                "writer_enabled": self.writer_enabled,
            }
        )


def seed_fresh_install_composition_offline(
    connection: sqlite3.Connection,
    seed: FreshInstallCompositionSeed,
) -> FreshInstallDeploymentProof:
    """Seed one exact fresh composition; this is never a normal startup path."""

    if connection.in_transaction:
        raise _error("fresh bootstrap requires no active transaction", "admission")
    current = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=seed.owner_schema_profile,
    )
    if current.proof_digest != seed.schema_proof.proof_digest:
        raise _error(
            "fresh schema proof became stale",
            "schema_identity",
            expected=seed.schema_proof.proof_digest,
            observed=current.proof_digest,
        )
    table_names = _application_table_names(connection)
    nonempty = _nonempty_tables(connection, table_names)
    if nonempty:
        raise _error(
            "fresh bootstrap refuses a non-empty database",
            "fresh_empty_closure",
            expected={},
            observed=nonempty,
        )
    receipt = _receipt(seed, table_names)
    state_payload = _deployment_state_payload(seed, receipt)
    state_digest = canonical_sha256_digest(state_payload)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _insert_seed_rows(connection, seed, receipt, state_payload, state_digest)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return verify_fresh_install_deployment_read_only(connection, seed=seed)


def verify_fresh_install_deployment_read_only(
    connection: sqlite3.Connection,
    *,
    seed: FreshInstallCompositionSeed,
) -> FreshInstallDeploymentProof:
    """Recompute the exact fresh proof without importing Plugins or enabling writers."""

    initial_changes = connection.total_changes
    initial_transaction = connection.in_transaction
    try:
        schema = verify_composite_store_schema_read_only(
            connection,
            expectation=seed.startup_expectation,
            owner_schema_profile=seed.owner_schema_profile,
        )
        table_names = _application_table_names(connection)
        receipt = _receipt(seed, table_names)
        receipt_rows = connection.execute(
            "SELECT receipt_json FROM openzyme_store_fresh_install_receipts "
            "WHERE receipt_digest = ?",
            (receipt.receipt_digest,),
        ).fetchall()
        if len(receipt_rows) != 1 or _json_object(receipt_rows[0][0]) != receipt.payload:
            raise _error(
                "fresh bootstrap receipt is absent or drifted",
                "fresh_receipt",
                expected=receipt.receipt_digest,
                observed=len(receipt_rows),
            )
        state_payload = _deployment_state_payload(seed, receipt)
        state_digest = canonical_sha256_digest(state_payload)
        states = connection.execute(
            "SELECT * FROM openzyme_store_deployment_schema_state"
        ).fetchall()
        columns = tuple(
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(openzyme_store_deployment_schema_state)"
            ).fetchall()
        )
        observed = None if len(states) != 1 else dict(zip(columns, states[0], strict=True))
        expected = {"singleton": 1, **state_payload, "state_digest": state_digest}
        if observed != expected:
            raise _error(
                "deployment schema state differs from the fresh receipt",
                "deployment_state",
                expected=expected,
                observed=observed,
            )
        epoch_rows = connection.execute(
            "SELECT activation_digest, activation_json FROM "
            "openzyme_store_deployment_activation_epochs WHERE epoch_id = ?",
            (seed.activation_epoch.epoch_id,),
        ).fetchall()
        if len(epoch_rows) != 1 or (
            str(epoch_rows[0][0]) != seed.activation_epoch.activation_digest
            or _json_object(epoch_rows[0][1]) != seed.activation_epoch.to_dict()
        ):
            raise _error(
                "deployment activation epoch is absent or drifted",
                "activation_epoch",
                expected=seed.activation_epoch.activation_digest,
                observed=len(epoch_rows),
            )
        return FreshInstallDeploymentProof(
            schema=schema,
            receipt=receipt,
            deployment_state_digest=state_digest,
            activation_digest=seed.activation_epoch.activation_digest,
        )
    finally:
        if (
            connection.total_changes != initial_changes
            or connection.in_transaction != initial_transaction
        ):
            raise RuntimeError("fresh deployment verifier violated zero-mutation")


def _receipt(
    seed: FreshInstallCompositionSeed,
    table_names: tuple[str, ...],
) -> FreshInstallBootstrapReceiptV2:
    application_tables = tuple(name for name in table_names if name not in _SEED_TABLES)
    return FreshInstallBootstrapReceiptV2(
        distribution_id=seed.activation_epoch.distribution_id,
        schema_generation=seed.schema_proof.store_schema.schema_generation,
        schema_manifest_digest=seed.schema_proof.complete_schema_manifest_digest,
        owner_schema_profile_id=seed.owner_schema_profile.profile_id,
        owner_schema_profile_digest=seed.owner_schema_profile.profile_digest,
        release_identity=seed.activation_epoch.release_identity,
        migration_sources=seed.migration_sources,
        installed_wheel_set_digest=seed.installed_wheel_set_digest,
        table_owner_manifest_digest=seed.table_owner_manifest_digest,
        empty_application_table_count=len(application_tables),
        empty_application_table_set_digest=canonical_sha256_digest(application_tables),
    )


def _deployment_state_payload(
    seed: FreshInstallCompositionSeed,
    receipt: FreshInstallBootstrapReceiptV2,
) -> dict[str, object]:
    release = seed.activation_epoch.release_identity
    return {
        "schema_generation": receipt.schema_generation,
        "schema_manifest_digest": receipt.schema_manifest_digest,
        "proof_variant": DeploymentProofVariant.FRESH_INSTALL_COMPLETE.value,
        "proof_receipt_digest": receipt.receipt_digest,
        "deployment_epoch_id": seed.activation_epoch.epoch_id,
        "deployment_activation_digest": seed.activation_epoch.activation_digest,
        **{
            field: getattr(release, field)
            for field in release.__dataclass_fields__
        },
        "installed_wheel_set_digest": seed.installed_wheel_set_digest,
        "table_owner_manifest_digest": seed.table_owner_manifest_digest,
    }


def _insert_seed_rows(
    connection: sqlite3.Connection,
    seed: FreshInstallCompositionSeed,
    receipt: FreshInstallBootstrapReceiptV2,
    state_payload: dict[str, object],
    state_digest: str,
) -> None:
    epoch = seed.activation_epoch
    connection.execute(
        "INSERT INTO openzyme_store_deployment_activation_epochs VALUES (?, ?, ?, ?, ?, ?)",
        (
            epoch.epoch_id,
            epoch.sequence,
            epoch.distribution_id,
            epoch.activation_digest,
            _json(epoch.to_dict()),
            epoch.activated_at,
        ),
    )
    payloads = dict(seed.catalog_payloads)
    extension_digest = canonical_sha256_digest(payloads["extension_bundle"])
    connection.execute(
        "INSERT INTO openzyme_store_extension_bundle_records VALUES (?, ?, ?, ?)",
        (extension_digest, _json(payloads["extension_bundle"]), epoch.epoch_id, epoch.activated_at),
    )
    for kind, payload in seed.catalog_payloads:
        connection.execute(
            "INSERT INTO openzyme_store_catalog_identity_records VALUES (?, ?, ?, ?, ?)",
            (kind, canonical_sha256_digest(payload), epoch.epoch_id, _json(payload), epoch.activated_at),
        )
    connection.execute(
        "INSERT INTO openzyme_store_fresh_install_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            receipt.receipt_digest,
            receipt.distribution_id,
            receipt.schema_generation,
            receipt.schema_manifest_digest,
            receipt.owner_schema_profile_id,
            receipt.owner_schema_profile_digest,
            epoch.activation_digest,
            receipt.installed_wheel_set_digest,
            receipt.table_owner_manifest_digest,
            _json(receipt.payload),
        ),
    )
    columns = tuple(state_payload)
    connection.execute(
        "INSERT INTO openzyme_store_deployment_schema_state "
        f"(singleton, {', '.join(columns)}, state_digest) "
        f"VALUES ({', '.join('?' for _ in range(len(columns) + 2))})",
        (1, *(state_payload[name] for name in columns), state_digest),
    )


def _application_table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    )


def _nonempty_tables(
    connection: sqlite3.Connection,
    table_names: tuple[str, ...],
) -> dict[str, int]:
    return {
        name: count
        for name in table_names
        if (count := int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]))
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _json_object(raw: object) -> dict[str, object]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise _error(
            "deployment proof JSON is invalid",
            "json_decode",
            observed=exc.__class__.__qualname__,
        ) from exc
    if not isinstance(value, dict):
        raise _error(
            "deployment proof JSON must be an object",
            "json_decode",
            observed=type(value).__name__,
        )
    return value


def _error(
    message: str,
    phase: str,
    *,
    expected: object = None,
    observed: object = None,
) -> SQLiteDeploymentProofError:
    return SQLiteDeploymentProofError(
        message,
        phase=phase,
        expected=expected,
        observed=observed,
        operator_action="run_the_exact_offline_bootstrap_or_repair_workflow",
    )


__all__ = [
    "DEPLOYMENT_SCHEMA_STATE_SCHEMA_VERSION",
    "FRESH_INSTALL_BOOTSTRAP_RECEIPT_SCHEMA_VERSION",
    "DeploymentProofVariant",
    "FreshInstallBootstrapReceiptV2",
    "FreshInstallCompositionSeed",
    "FreshInstallDeploymentProof",
    "MigrationSourceIdentity",
    "SQLiteDeploymentProofError",
    "seed_fresh_install_composition_offline",
    "verify_fresh_install_deployment_read_only",
]
