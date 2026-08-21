from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
import sqlite3
from typing import Any

from openzyme_contracts import canonical_sha256_digest


OWNER_SCHEMA_PROOF = "openzyme_owner_partitioned_schema_proof@1"
_MANIFEST_RESOURCE = "manifests/migration-catalog.json"


class OwnerPartitionedSchemaVerificationError(RuntimeError):
    error_code = "owner_partitioned_schema_verification_failed"

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
class OwnerSchemaProfile:
    profile_id: str
    semantic_owner_ids: tuple[str, ...]
    expected_foreign_key_count: int

    def __post_init__(self) -> None:
        if not self.profile_id or not self.profile_id.isascii():
            raise ValueError("owner schema profile_id must be non-empty ASCII")
        owners = tuple(sorted(self.semantic_owner_ids))
        if not owners or len(owners) != len(set(owners)):
            raise ValueError("owner schema profile owners must be non-empty and unique")
        if "openzyme.store.sqlite" in owners:
            raise ValueError(
                "target owner profiles must use Store migrations, not legacy Store tables"
            )
        if self.expected_foreign_key_count < 0:
            raise ValueError("expected_foreign_key_count must be non-negative")
        object.__setattr__(self, "semantic_owner_ids", owners)

    @property
    def profile_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_owner_schema_profile@1",
            "profile_id": self.profile_id,
            "semantic_owner_ids": list(self.semantic_owner_ids),
            "expected_foreign_key_count": self.expected_foreign_key_count,
        }


OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE = OwnerSchemaProfile(
    profile_id="openzyme_standard_local_file_sqlite_git@1",
    semantic_owner_ids=(
        "openzyme.kernel",
        "openzyme.process.podman",
        "openzyme.workspace.git.lfs",
    ),
    expected_foreign_key_count=300,
)
ENZYMEDESIGN_OWNER_SCHEMA_PROFILE = OwnerSchemaProfile(
    profile_id="enzymedesign_local_single_process_file_sqlite@1",
    semantic_owner_ids=(
        "openzyme.compute",
        "openzyme.hpc",
        "openzyme.kernel",
        "openzyme.process.podman",
        "openzyme.reporting",
        "openzyme.research",
        "openzyme.science",
        "openzyme.workspace.git.lfs",
    ),
    expected_foreign_key_count=421,
)


@dataclass(frozen=True, slots=True)
class OwnerPartitionedSchemaProof:
    schema_profile_id: str
    schema_profile_digest: str
    semantic_owner_ids: tuple[str, ...]
    source_user_version: int
    source_migration_digest: str
    owner_migration_catalog_digest: str
    table_owner_manifest_digest: str
    observed_schema_digest: str
    owner_closure_digest: str
    table_count: int
    index_count: int
    trigger_count: int
    foreign_key_count: int
    mutation_applied: bool = False
    plugin_import_performed: bool = False
    writer_enabled: bool = False

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": OWNER_SCHEMA_PROOF,
            "schema_profile_id": self.schema_profile_id,
            "schema_profile_digest": self.schema_profile_digest,
            "semantic_owner_ids": list(self.semantic_owner_ids),
            "source_user_version": self.source_user_version,
            "source_migration_digest": self.source_migration_digest,
            "owner_migration_catalog_digest": self.owner_migration_catalog_digest,
            "table_owner_manifest_digest": self.table_owner_manifest_digest,
            "observed_schema_digest": self.observed_schema_digest,
            "owner_closure_digest": self.owner_closure_digest,
            "table_count": self.table_count,
            "index_count": self.index_count,
            "trigger_count": self.trigger_count,
            "foreign_key_count": self.foreign_key_count,
            "mutation_applied": self.mutation_applied,
            "plugin_import_performed": self.plugin_import_performed,
            "writer_enabled": self.writer_enabled,
        }


def verify_owner_partitioned_schema_read_only(
    connection: sqlite3.Connection,
    *,
    profile: OwnerSchemaProfile | None = None,
    composite_user_version: int | None = None,
) -> OwnerPartitionedSchemaProof:
    """Verify the current owner-partitioned production schema before any writer.

    This verifier reads only packaged Store resources and SQLite metadata. It does not
    import Plugin modules, execute migrations, or create a transaction.
    """

    initial_changes = connection.total_changes
    initial_transaction = connection.in_transaction
    try:
        manifest = _load_manifest()
        _verify_packaged_bundle_resources(manifest)
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        expected_user_version = (
            int(manifest["source_user_version"])
            if composite_user_version is None
            else composite_user_version
        )
        if user_version != expected_user_version:
            raise OwnerPartitionedSchemaVerificationError(
                "SQLite user_version differs from the owner catalog",
                phase="user_version",
                observed={
                    "expected_database_user_version": expected_user_version,
                    "observed_database_user_version": user_version,
                    "owner_source_user_version": manifest["source_user_version"],
                },
            )
        rows = tuple(
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                """
                SELECT type, name, COALESCE(sql, '')
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                  AND name NOT LIKE 'openzyme_store_%'
                  AND sql IS NOT NULL
                ORDER BY type, name
                """
            ).fetchall()
        )
        observed = {(kind, name) for kind, name, _ in rows}
        owner_rows = _owner_rows(manifest, profile=profile)
        expected = {
            (_sqlite_kind(phase), identity)
            for phase, identity, _owner in owner_rows
            if phase in {"tables", "indexes", "triggers"}
        }
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        if missing or unexpected:
            raise OwnerPartitionedSchemaVerificationError(
                "SQLite object closure differs from owner migration catalog",
                phase="object_closure",
                observed={"missing": missing, "unexpected": unexpected},
            )
        counts = {
            "tables": sum(kind == "table" for kind, _name in observed),
            "indexes": sum(kind == "index" for kind, _name in observed),
            "triggers": sum(kind == "trigger" for kind, _name in observed),
        }
        foreign_keys = _foreign_keys(
            connection,
            tuple(name for kind, name in observed if kind == "table"),
        )
        counts["foreign_keys"] = len(foreign_keys)
        expected_counts = _expected_object_counts(manifest, profile=profile)
        expected_foreign_key_count = (
            int(manifest["expected_object_counts"]["foreign_keys"])
            if profile is None
            else profile.expected_foreign_key_count
        )
        expected_counts["foreign_keys"] = expected_foreign_key_count
        if counts != expected_counts:
            raise OwnerPartitionedSchemaVerificationError(
                "SQLite object counts differ from owner migration catalog",
                phase="object_counts",
                observed={"expected": expected_counts, "observed": counts},
            )
        selected_tables = {
            identity for phase, identity, _owner in owner_rows if phase == "tables"
        }
        cross_owner = [edge for edge in foreign_keys if edge[1] not in selected_tables]
        if cross_owner:
            raise OwnerPartitionedSchemaVerificationError(
                "owner schema profile has an unselected foreign-key target",
                phase="foreign_key_owner_closure",
                observed=cross_owner,
            )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise OwnerPartitionedSchemaVerificationError(
                "SQLite foreign-key closure is invalid",
                phase="foreign_key_check",
                observed=violations,
            )
        owner_payload = [
            {
                "object_kind": _sqlite_kind(phase),
                "object_name": identity,
                "semantic_owner": owner,
            }
            for phase, identity, owner in owner_rows
            if phase in {"tables", "indexes", "triggers"}
        ]
        return OwnerPartitionedSchemaProof(
            schema_profile_id=(
                "legacy_full_owner_schema@1" if profile is None else profile.profile_id
            ),
            schema_profile_digest=(
                canonical_sha256_digest(
                    {
                        "schema_version": "openzyme_owner_schema_profile@1",
                        "profile_id": "legacy_full_owner_schema@1",
                        "semantic_owner_ids": sorted(
                            {owner for _phase, _identity, owner in owner_rows}
                        ),
                        "expected_foreign_key_count": expected_foreign_key_count,
                    }
                )
                if profile is None
                else profile.profile_digest
            ),
            semantic_owner_ids=tuple(
                sorted({owner for _phase, _identity, owner in owner_rows})
            ),
            source_user_version=user_version,
            source_migration_digest=str(manifest["source_migration_digest"]),
            owner_migration_catalog_digest=str(manifest["catalog_digest"]),
            table_owner_manifest_digest=str(
                manifest["table_owner_manifest_digest"]
            ),
            observed_schema_digest=canonical_sha256_digest(
                [
                    {"object_kind": kind, "object_name": name, "sql": sql}
                    for kind, name, sql in rows
                ]
            ),
            owner_closure_digest=canonical_sha256_digest(owner_payload),
            table_count=counts["tables"],
            index_count=counts["indexes"],
            trigger_count=counts["triggers"],
            foreign_key_count=counts["foreign_keys"],
        )
    except OwnerPartitionedSchemaVerificationError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        raise OwnerPartitionedSchemaVerificationError(
            "owner-partitioned schema verification failed closed",
            phase="verification",
            observed=exc.__class__.__qualname__,
        ) from exc
    finally:
        if (
            connection.total_changes != initial_changes
            or connection.in_transaction != initial_transaction
        ):
            raise RuntimeError(
                "owner-partitioned startup verifier violated zero-mutation"
            )


def _load_manifest() -> dict[str, Any]:
    raw = files("openzyme_store_sqlite").joinpath(_MANIFEST_RESOURCE).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_id") != (
        "openzyme_owner_partitioned_migration_catalog@1"
    ):
        raise OwnerPartitionedSchemaVerificationError(
            "packaged owner migration catalog is invalid",
            phase="catalog_schema",
        )
    return value


def _verify_packaged_bundle_resources(manifest: dict[str, Any]) -> None:
    bundles = manifest.get("bundles")
    order = manifest.get("bundle_order")
    if not isinstance(bundles, list) or not isinstance(order, list):
        raise OwnerPartitionedSchemaVerificationError(
            "owner migration catalog lacks bundles or order",
            phase="catalog_shape",
        )
    identities = [bundle.get("migration_id") for bundle in bundles]
    if identities != order or len(identities) != len(set(identities)):
        raise OwnerPartitionedSchemaVerificationError(
            "owner migration bundle order is not exact and unique",
            phase="catalog_order",
            observed=identities,
        )
    for bundle in bundles:
        resource_name = str(bundle["resource"])
        resource = files("openzyme_store_sqlite").joinpath(resource_name)
        observed_digest = "sha256:" + hashlib.sha256(resource.read_bytes()).hexdigest()
        if observed_digest != bundle["resource_digest"]:
            raise OwnerPartitionedSchemaVerificationError(
                "owner migration resource digest drifted",
                phase="bundle_digest",
                observed={
                    "migration_id": bundle["migration_id"],
                    "expected": bundle["resource_digest"],
                    "actual": observed_digest,
                },
            )


def install_owner_partitioned_schema_for_offline_migration(
    connection: sqlite3.Connection,
    *,
    profile: OwnerSchemaProfile | None = None,
) -> None:
    """Install the exact owner-partitioned production schema into an empty database."""

    if connection.in_transaction:
        raise OwnerPartitionedSchemaVerificationError(
            "owner schema installation cannot start inside a transaction",
            phase="offline_migration_admission",
        )
    existing = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
        LIMIT 1
        """
    ).fetchone()
    if existing is not None:
        raise OwnerPartitionedSchemaVerificationError(
            "owner schema installation requires an empty database",
            phase="offline_migration_admission",
            observed=str(existing[0]),
        )
    manifest = _load_manifest()
    _verify_packaged_bundle_resources(manifest)
    body = "\n".join(
        files("openzyme_store_sqlite")
        .joinpath(str(bundle["resource"]))
        .read_text(encoding="utf-8")
        for bundle in _selected_bundles(manifest, profile=profile)
    )
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + body + "\nCOMMIT;")
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise OwnerPartitionedSchemaVerificationError(
            "owner-partitioned offline installation failed",
            phase="offline_migration_apply",
            observed=exc.__class__.__qualname__,
        ) from exc


def _selected_bundles(
    manifest: dict[str, Any],
    *,
    profile: OwnerSchemaProfile | None,
) -> tuple[dict[str, Any], ...]:
    if profile is None:
        return tuple(manifest["bundles"])
    available_owners = {
        str(bundle["semantic_owner"])
        for bundle in manifest["bundles"]
        if str(bundle["phase"]) in {"tables", "indexes", "triggers"}
    }
    unknown = set(profile.semantic_owner_ids).difference(available_owners)
    if unknown:
        raise OwnerPartitionedSchemaVerificationError(
            "owner schema profile names an unknown semantic owner",
            phase="profile_owner",
            observed=sorted(unknown),
        )
    return tuple(
        bundle
        for bundle in manifest["bundles"]
        if str(bundle["semantic_owner"]) in profile.semantic_owner_ids
        and str(bundle["phase"]) in {"tables", "indexes", "triggers"}
    )


def _expected_object_counts(
    manifest: dict[str, Any],
    *,
    profile: OwnerSchemaProfile | None,
) -> dict[str, int]:
    if profile is None:
        counts = dict(manifest["expected_object_counts"])
        counts.pop("foreign_keys", None)
        return counts
    counts = {"tables": 0, "indexes": 0, "triggers": 0}
    for bundle in _selected_bundles(manifest, profile=profile):
        counts[str(bundle["phase"])] += int(bundle["object_count"])
    return counts


def _owner_rows(
    manifest: dict[str, Any],
    *,
    profile: OwnerSchemaProfile | None = None,
) -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for bundle in _selected_bundles(manifest, profile=profile):
        phase = str(bundle["phase"])
        identities = bundle["object_identities"]
        if not isinstance(identities, list) or len(identities) != bundle["object_count"]:
            raise OwnerPartitionedSchemaVerificationError(
                "owner migration object count drifted",
                phase="bundle_object_count",
                observed=bundle["migration_id"],
            )
        rows.extend(
            (phase, str(identity), str(bundle["semantic_owner"]))
            for identity in identities
        )
    keys = [(phase, identity) for phase, identity, _owner in rows]
    if len(keys) != len(set(keys)):
        raise OwnerPartitionedSchemaVerificationError(
            "an SQLite object has multiple semantic owners",
            phase="owner_collision",
        )
    return tuple(rows)


def _sqlite_kind(phase: str) -> str:
    return {"tables": "table", "indexes": "index", "triggers": "trigger"}[phase]


def _foreign_keys(
    connection: sqlite3.Connection,
    tables: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    edges: list[tuple[str, str, str]] = []
    for table in sorted(tables):
        escaped = table.replace('"', '""')
        for row in connection.execute(
            f'PRAGMA foreign_key_list("{escaped}")'
        ).fetchall():
            edges.append((table, str(row[2]), str(row[3])))
    return tuple(sorted(edges))


__all__ = [
    "ENZYMEDESIGN_OWNER_SCHEMA_PROFILE",
    "OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE",
    "OWNER_SCHEMA_PROOF",
    "OwnerPartitionedSchemaProof",
    "OwnerPartitionedSchemaVerificationError",
    "OwnerSchemaProfile",
    "install_owner_partitioned_schema_for_offline_migration",
    "verify_owner_partitioned_schema_read_only",
]
