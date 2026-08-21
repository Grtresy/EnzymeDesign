from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_contracts import canonical_sha256_digest

from .migration_catalog import ClosedSQLiteMigrationCatalog
from .migration_catalog import STORE_MIGRATION_CATALOG
from .migration_catalog import STORE_SCHEMA_GENERATION
from .migration_catalog import STORE_SCHEMA_USER_VERSION
from .migration_catalog import schema_manifest_digest
from .migration_catalog import schema_object_rows


STORE_OBJECT_OWNER = "openzyme.store.sqlite"


class SQLiteStartupVerificationError(RuntimeError):
    error_code = "sqlite_startup_verification_failed"

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        expected: object = None,
        observed: object = None,
        operator_action: str = "run_the_authorized_offline_migration",
    ) -> None:
        self.phase = phase
        self.expected = expected
        self.observed = observed
        self.operator_action = operator_action
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{message}; phase={phase}; expected={expected!r}; "
            f"observed={observed!r}; operator_action={operator_action}; "
            "mutation_applied=false; fallback_performed=false"
        )


@dataclass(frozen=True, slots=True)
class SQLiteStartupSchemaProof:
    schema_generation: str
    user_version: int
    migration_catalog_digest: str
    schema_manifest_digest: str
    object_owner_digest: str
    object_count: int
    foreign_key_count: int
    mutation_applied: bool = False
    plugin_import_performed: bool = False
    writer_enabled: bool = False

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_sqlite_startup_schema_proof@1",
            "schema_generation": self.schema_generation,
            "user_version": self.user_version,
            "migration_catalog_digest": self.migration_catalog_digest,
            "schema_manifest_digest": self.schema_manifest_digest,
            "object_owner_digest": self.object_owner_digest,
            "object_count": self.object_count,
            "foreign_key_count": self.foreign_key_count,
            "mutation_applied": self.mutation_applied,
            "plugin_import_performed": self.plugin_import_performed,
            "writer_enabled": self.writer_enabled,
        }


def _foreign_keys(connection: sqlite3.Connection, tables: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    edges: list[tuple[str, str]] = []
    for table in tables:
        # table comes only from sqlite_master and is quoted as an identifier.
        escaped = table.replace('"', '""')
        for row in connection.execute(f'PRAGMA foreign_key_list("{escaped}")').fetchall():
            edges.append((table, str(row[2])))
    return tuple(sorted(edges))


def verify_store_schema_read_only(
    connection: sqlite3.Connection,
    *,
    catalog: ClosedSQLiteMigrationCatalog = STORE_MIGRATION_CATALOG,
) -> SQLiteStartupSchemaProof:
    """Verify the exact Store closure without importing Plugins or enabling writers."""

    initial_changes = connection.total_changes
    initial_transaction = connection.in_transaction
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version != STORE_SCHEMA_USER_VERSION:
            raise SQLiteStartupVerificationError(
                "Store schema user version differs",
                phase="user_version",
                expected=STORE_SCHEMA_USER_VERSION,
                observed=user_version,
            )
        rows = schema_object_rows(connection)
        observed_names = tuple(sorted(row[1] for row in rows))
        expected_names = catalog.declared_objects()
        missing = sorted(set(expected_names).difference(observed_names))
        unexpected = sorted(set(observed_names).difference(expected_names))
        if missing or unexpected:
            raise SQLiteStartupVerificationError(
                "Store schema object closure differs",
                phase="object_closure",
                expected=list(expected_names),
                observed={"missing": missing, "unexpected": unexpected},
            )
        if any(not name.startswith("openzyme_store_") for name in observed_names):
            raise SQLiteStartupVerificationError(
                "Store migration crossed its declared object namespace",
                phase="object_namespace",
                expected="openzyme_store_*",
                observed=[name for name in observed_names if not name.startswith("openzyme_store_")],
            )
        tables = tuple(row[1] for row in rows if row[0] == "table")
        foreign_keys = _foreign_keys(connection, tables)
        cross_owner = [edge for edge in foreign_keys if edge[1] not in tables]
        if cross_owner:
            raise SQLiteStartupVerificationError(
                "Store migration contains a cross-owner foreign key",
                phase="foreign_key_ownership",
                expected=list(tables),
                observed=cross_owner,
            )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SQLiteStartupVerificationError(
                "Store foreign-key closure is invalid",
                phase="foreign_key_closure",
                expected=[],
                observed=violations,
            )
        owner_payload = {
            "owner": STORE_OBJECT_OWNER,
            "objects": [
                {"object_type": row[0], "object_name": row[1]}
                for row in rows
            ],
            "foreign_keys": [list(edge) for edge in foreign_keys],
        }
        return SQLiteStartupSchemaProof(
            schema_generation=STORE_SCHEMA_GENERATION,
            user_version=user_version,
            migration_catalog_digest=catalog.catalog_digest,
            schema_manifest_digest=schema_manifest_digest(rows),
            object_owner_digest=canonical_sha256_digest(owner_payload),
            object_count=len(rows),
            foreign_key_count=len(foreign_keys),
        )
    except SQLiteStartupVerificationError:
        raise
    except sqlite3.Error as exc:
        raise SQLiteStartupVerificationError(
            "Store verification query failed",
            phase="verification_query",
            expected="readable exact schema",
            observed=exc.__class__.__qualname__,
            operator_action="inspect_database_integrity_and_permissions",
        ) from exc
    finally:
        if (
            connection.total_changes != initial_changes
            or connection.in_transaction != initial_transaction
        ):
            raise RuntimeError(
                "Store startup verifier violated its zero-mutation contract"
            )


__all__ = [
    "SQLiteStartupSchemaProof",
    "SQLiteStartupVerificationError",
    "STORE_OBJECT_OWNER",
    "verify_store_schema_read_only",
]
