from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import re
import sqlite3
from typing import Iterable

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


STORE_SCHEMA_GENERATION = "openzyme_store_sqlite_composite@3"
STORE_SCHEMA_USER_VERSION = 3
_RESOURCE_PACKAGE = "openzyme_store_sqlite.migrations"
_OBJECT_NAME = re.compile(
    r"\b(?:TABLE|INDEX|TRIGGER|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


class SQLiteMigrationCatalogError(RuntimeError):
    error_code = "sqlite_migration_catalog_rejected"

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
class SQLiteMigrationDescriptor:
    migration_id: str
    owner_component_id: str
    state_namespace: str
    resource_name: str
    sql_digest: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "migration_id",
            "owner_component_id",
            "state_namespace",
            "resource_name",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.sql_digest, field_name="sql_digest")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on must not contain duplicates")

    def to_dict(self) -> dict[str, object]:
        return {
            "migration_id": self.migration_id,
            "owner_component_id": self.owner_component_id,
            "state_namespace": self.state_namespace,
            "resource_name": self.resource_name,
            "sql_digest": self.sql_digest,
            "depends_on": list(self.depends_on),
        }


def _resource_sql(resource_name: str) -> str:
    return files(_RESOURCE_PACKAGE).joinpath(resource_name).read_text(encoding="utf-8")


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


_COMPOSITION_SQL = _resource_sql("001_composition_state.sql")
_DEPLOYMENT_PROOF_SQL = _resource_sql("002_deployment_proof.sql")
STORE_MIGRATIONS: tuple[SQLiteMigrationDescriptor, ...] = (
    SQLiteMigrationDescriptor(
        migration_id="001_composition_state",
        owner_component_id="openzyme.store.sqlite",
        state_namespace="openzyme.store",
        resource_name="001_composition_state.sql",
        sql_digest=_sha256_text(_COMPOSITION_SQL),
    ),
    SQLiteMigrationDescriptor(
        migration_id="002_deployment_proof",
        owner_component_id="openzyme.store.sqlite",
        state_namespace="openzyme.store",
        resource_name="002_deployment_proof.sql",
        sql_digest=_sha256_text(_DEPLOYMENT_PROOF_SQL),
        depends_on=("001_composition_state",),
    ),
)


@dataclass(frozen=True, slots=True)
class ClosedSQLiteMigrationCatalog:
    migrations: tuple[SQLiteMigrationDescriptor, ...]

    def __post_init__(self) -> None:
        ids = [item.migration_id for item in self.migrations]
        resources = [item.resource_name for item in self.migrations]
        if not self.migrations or len(ids) != len(set(ids)):
            raise SQLiteMigrationCatalogError(
                "migration ids must be non-empty and unique",
                phase="catalog_identity",
                observed=ids,
            )
        if len(resources) != len(set(resources)):
            raise SQLiteMigrationCatalogError(
                "migration resources must be unique",
                phase="catalog_identity",
                observed=resources,
            )
        seen: set[str] = set()
        for item in self.migrations:
            if any(dependency not in seen for dependency in item.depends_on):
                raise SQLiteMigrationCatalogError(
                    "migration dependency is missing or not topologically ordered",
                    phase="catalog_dependency",
                    observed=item.to_dict(),
                )
            sql = _resource_sql(item.resource_name)
            observed_digest = _sha256_text(sql)
            if observed_digest != item.sql_digest:
                raise SQLiteMigrationCatalogError(
                    "migration resource digest drifted",
                    phase="migration_digest",
                    observed={
                        "migration_id": item.migration_id,
                        "expected": item.sql_digest,
                        "observed": observed_digest,
                    },
                )
            seen.add(item.migration_id)

    @property
    def catalog_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_sqlite_migration_catalog@1",
                "schema_generation": STORE_SCHEMA_GENERATION,
                "migrations": [item.to_dict() for item in self.migrations],
            }
        )

    def sql(self, migration_id: str) -> str:
        matches = [item for item in self.migrations if item.migration_id == migration_id]
        if len(matches) != 1:
            raise SQLiteMigrationCatalogError(
                "unknown migration id",
                phase="migration_lookup",
                observed=migration_id,
            )
        return _resource_sql(matches[0].resource_name)

    def declared_objects(self) -> tuple[str, ...]:
        names: list[str] = []
        for item in self.migrations:
            names.extend(match.group("name") for match in _OBJECT_NAME.finditer(self.sql(item.migration_id)))
        if len(names) != len(set(names)):
            raise SQLiteMigrationCatalogError(
                "migration catalog declares an object more than once",
                phase="object_ownership",
                observed=sorted(name for name in set(names) if names.count(name) > 1),
            )
        return tuple(sorted(names))


STORE_MIGRATION_CATALOG = ClosedSQLiteMigrationCatalog(STORE_MIGRATIONS)


def install_store_schema_for_offline_migration(
    connection: sqlite3.Connection,
    *,
    catalog: ClosedSQLiteMigrationCatalog = STORE_MIGRATION_CATALOG,
) -> None:
    """Install the target Store schema only from an explicit offline command."""

    if connection.in_transaction:
        raise SQLiteMigrationCatalogError(
            "offline migration cannot start inside a transaction",
            phase="offline_migration_admission",
        )
    try:
        body = "\n".join(catalog.sql(item.migration_id) for item in catalog.migrations)
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + body
            + f"\nPRAGMA user_version = {STORE_SCHEMA_USER_VERSION};\nCOMMIT;"
        )
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise SQLiteMigrationCatalogError(
            "offline Store migration failed",
            phase="offline_migration_apply",
            observed=exc.__class__.__qualname__,
        ) from exc


def schema_object_rows(connection: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            """
            SELECT type, name, COALESCE(sql, '')
            FROM sqlite_master
            WHERE name LIKE 'openzyme_store_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
    )


def schema_manifest_digest(rows: Iterable[tuple[str, str, str]]) -> str:
    return canonical_sha256_digest(
        [
            {"object_type": object_type, "object_name": name, "sql": sql}
            for object_type, name, sql in rows
        ]
    )


__all__ = [
    "ClosedSQLiteMigrationCatalog",
    "SQLiteMigrationCatalogError",
    "SQLiteMigrationDescriptor",
    "STORE_MIGRATION_CATALOG",
    "STORE_MIGRATIONS",
    "STORE_SCHEMA_GENERATION",
    "STORE_SCHEMA_USER_VERSION",
    "install_store_schema_for_offline_migration",
    "schema_manifest_digest",
    "schema_object_rows",
]
