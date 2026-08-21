from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

from openzyme_contracts import canonical_sha256_digest

from .composite_startup import CompositeSQLiteStartupProof
from .composite_startup import SQLiteStartupCompositionExpectation
from .composite_startup import verify_composite_store_schema_read_only
from .migration_catalog import install_store_schema_for_offline_migration
from .owner_startup import OwnerSchemaProfile
from .owner_startup import install_owner_partitioned_schema_for_offline_migration


SQLITE_STORE_ADAPTER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": "openzyme.control-store-port@1",
        "transaction": "begin_immediate_single_writer",
        "startup": "read_only_before_writer",
        "migration": "explicit_offline_only",
        "event_outbox": "same_transaction",
        "extension_state": "namespace_confined",
        "fallback": False,
    }
)
SQLITE_STORE_CONFIGURATION_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_sqlite_store_configuration@1",
        "fields": {
            "database_path": "absolute_path",
            "busy_timeout_ms": {"minimum": 1, "maximum": 60_000},
        },
        "additionalProperties": False,
    }
)
SQLITE_STORE_PREFLIGHT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": "openzyme_sqlite_store_preflight@1",
        "checks": ["absolute_path", "parent_exists", "database_file_kind"],
        "opens_database": False,
        "mutates_database": False,
    }
)


class SQLiteStoreAdapterError(RuntimeError):
    error_code = "sqlite_store_adapter_rejected"

    def __init__(self, message: str, *, phase: str, observed: object = None) -> None:
        self.phase = phase
        self.observed = observed
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; observed={observed!r}; "
            "mutation_applied=false; fallback_performed=false"
        )


@dataclass(frozen=True, slots=True)
class SQLiteStoreConfiguration:
    database_path: str
    busy_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, str) or not self.database_path:
            raise ValueError("database_path must be a non-empty absolute path")
        path = Path(self.database_path)
        if not path.is_absolute():
            raise ValueError("database_path must be absolute")
        if (
            not isinstance(self.busy_timeout_ms, int)
            or isinstance(self.busy_timeout_ms, bool)
            or not 1 <= self.busy_timeout_ms <= 60_000
        ):
            raise ValueError("busy_timeout_ms must be between 1 and 60000")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SQLiteStoreConfiguration:
        if set(payload).difference({"database_path", "busy_timeout_ms"}):
            raise ValueError("SQLite Store configuration contains unknown fields")
        if "database_path" not in payload:
            raise ValueError("SQLite Store configuration requires database_path")
        return cls(
            database_path=str(payload["database_path"]),
            busy_timeout_ms=int(payload.get("busy_timeout_ms", 5_000)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_sqlite_store_configuration@1",
            "database_path": self.database_path,
            "busy_timeout_ms": self.busy_timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class SQLiteStorePreflightObservation:
    database_path: str
    parent_exists: bool
    database_exists: bool
    database_is_regular_file: bool
    mutation_applied: bool = False
    database_opened: bool = False

    @property
    def ready_for_existing_database(self) -> bool:
        return (
            self.parent_exists
            and self.database_exists
            and self.database_is_regular_file
        )

    @property
    def observation_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_sqlite_store_preflight_observation@1",
            "database_path": self.database_path,
            "parent_exists": self.parent_exists,
            "database_exists": self.database_exists,
            "database_is_regular_file": self.database_is_regular_file,
            "mutation_applied": self.mutation_applied,
            "database_opened": self.database_opened,
        }


class SQLiteConnectionProvider:
    """Connection lifecycle; normal startup never initializes or upgrades schema."""

    def __init__(self, configuration: SQLiteStoreConfiguration) -> None:
        self.configuration = configuration

    def preflight(self) -> SQLiteStorePreflightObservation:
        path = Path(self.configuration.database_path)
        try:
            stat = path.stat()
        except FileNotFoundError:
            stat = None
        return SQLiteStorePreflightObservation(
            database_path=str(path),
            parent_exists=path.parent.is_dir(),
            database_exists=stat is not None,
            database_is_regular_file=False if stat is None else path.is_file(),
        )

    def open_verifier(self) -> sqlite3.Connection:
        observation = self.preflight()
        if not observation.ready_for_existing_database:
            raise SQLiteStoreAdapterError(
                "existing SQLite database is not ready for read-only verification",
                phase="connection_preflight",
                observed=observation.to_dict(),
            )
        uri = "file:" + quote(self.configuration.database_path, safe="/") + "?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.execute(f"PRAGMA busy_timeout = {self.configuration.busy_timeout_ms}")
            connection.execute("PRAGMA query_only = ON")
            return connection
        except sqlite3.Error as exc:
            raise SQLiteStoreAdapterError(
                "failed to open read-only SQLite verifier connection",
                phase="connection_open_read_only",
                observed=exc.__class__.__qualname__,
            ) from exc

    def verify(
        self,
        *,
        expectation: SQLiteStartupCompositionExpectation | None = None,
        owner_schema_profile: OwnerSchemaProfile | None = None,
    ) -> CompositeSQLiteStartupProof:
        connection = self.open_verifier()
        try:
            return verify_composite_store_schema_read_only(
                connection,
                expectation=expectation,
                owner_schema_profile=owner_schema_profile,
            )
        finally:
            connection.close()

    def open_writer(self, proof: CompositeSQLiteStartupProof) -> sqlite3.Connection:
        if proof.composition is None:
            raise SQLiteStoreAdapterError(
                "writer activation requires an exact composition startup proof",
                phase="writer_activation",
                observed="schema_only_proof",
            )
        owner_schema_profile = (
            None
            if proof.owner_schema.schema_profile_id == "legacy_full_owner_schema@1"
            else OwnerSchemaProfile(
                profile_id=proof.owner_schema.schema_profile_id,
                semantic_owner_ids=proof.owner_schema.semantic_owner_ids,
                expected_foreign_key_count=proof.owner_schema.foreign_key_count,
            )
        )
        verifier = self.verify(
            expectation=proof.composition.expectation,
            owner_schema_profile=owner_schema_profile,
        )
        if verifier.proof_digest != proof.proof_digest:
            raise SQLiteStoreAdapterError(
                "startup schema proof became stale before writer activation",
                phase="writer_activation",
                observed={
                    "expected": proof.proof_digest,
                    "observed": verifier.proof_digest,
                },
            )
        try:
            connection = sqlite3.connect(self.configuration.database_path)
            connection.execute(f"PRAGMA busy_timeout = {self.configuration.busy_timeout_ms}")
            connection.execute("PRAGMA foreign_keys = ON")
            # Revalidate on the exact writer handle before returning authority.
            exact = verify_composite_store_schema_read_only(
                connection,
                expectation=proof.composition.expectation,
                owner_schema_profile=owner_schema_profile,
            )
            if exact.proof_digest != proof.proof_digest:
                connection.close()
                raise SQLiteStoreAdapterError(
                    "writer handle schema differs from the admitted proof",
                    phase="writer_activation",
                    observed=exact.proof_digest,
                )
            return connection
        except SQLiteStoreAdapterError:
            raise
        except sqlite3.Error as exc:
            raise SQLiteStoreAdapterError(
                "failed to open verified SQLite writer connection",
                phase="connection_open_writer",
                observed=exc.__class__.__qualname__,
            ) from exc

    def bootstrap_fresh_offline(
        self,
        *,
        owner_schema_profile: OwnerSchemaProfile | None = None,
    ) -> CompositeSQLiteStartupProof:
        """Explicit offline operation; refuses an existing path and never runs at startup."""

        path = Path(self.configuration.database_path)
        if path.exists():
            raise SQLiteStoreAdapterError(
                "fresh Store bootstrap refuses an existing path",
                phase="offline_bootstrap_admission",
                observed=str(path),
            )
        if not path.parent.is_dir():
            raise SQLiteStoreAdapterError(
                "fresh Store bootstrap parent directory is absent",
                phase="offline_bootstrap_admission",
                observed=str(path.parent),
            )
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
        try:
            connection = sqlite3.connect(str(path))
            install_owner_partitioned_schema_for_offline_migration(
                connection,
                profile=owner_schema_profile,
            )
            install_store_schema_for_offline_migration(connection)
            proof = verify_composite_store_schema_read_only(
                connection,
                owner_schema_profile=owner_schema_profile,
            )
            connection.close()
            return proof
        except Exception:
            # The operation owns only the just-created empty target. Preserve it for
            # operator inspection; do not hide the failed occurrence by deleting it.
            raise


__all__ = [
    "SQLITE_STORE_ADAPTER_CONTRACT_DIGEST",
    "SQLITE_STORE_CONFIGURATION_SCHEMA_DIGEST",
    "SQLITE_STORE_PREFLIGHT_CONTRACT_DIGEST",
    "SQLiteConnectionProvider",
    "SQLiteStoreAdapterError",
    "SQLiteStoreConfiguration",
    "SQLiteStorePreflightObservation",
]
