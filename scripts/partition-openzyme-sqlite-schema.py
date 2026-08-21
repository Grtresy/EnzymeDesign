#!/usr/bin/env python3
"""Generate/check owner-partitioned SQLite migration bundles.

This is an engineering build tool. It reads the current final migration and the
source-bound table-owner manifest, then writes deterministic owner/phase assets.
It never opens a deployment database. `--check` performs no writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OWNER_MANIFEST = ROOT / "docs/v3/architecture/table-owner-manifest.json"
SOURCE_MIGRATION = (
    ROOT
    / "packages/openzyme-store-sqlite/src/openzyme_store_sqlite/migrations"
    / "001_file_workspace_final.sql"
)
OUTPUT_ROOT = (
    ROOT
    / "packages/openzyme-store-sqlite/src/openzyme_store_sqlite/migrations/owners"
)
CATALOG_PATH = (
    ROOT
    / "packages/openzyme-store-sqlite/src/openzyme_store_sqlite/manifests"
    / "migration-catalog.json"
)

_CREATE_TABLE = re.compile(
    r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?'
    r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE | re.DOTALL,
)
_CREATE_INDEX = re.compile(
    r'^CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?'
    r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)["`\]]?\s+ON\s+["`\[]?'
    r'(?P<table>[A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE | re.DOTALL,
)
_CREATE_TRIGGER_NAME = re.compile(
    r'^CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?'
    r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE | re.DOTALL,
)
_CREATE_TRIGGER_TABLE = re.compile(
    r'\b(?:BEFORE|AFTER|INSTEAD\s+OF)\b.+?\bON\s+["`\[]?'
    r'(?P<table>[A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE | re.DOTALL,
)
_INSERT = re.compile(
    r'^INSERT\s+INTO\s+["`\[]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE | re.DOTALL,
)

_OWNER_SLUGS = {
    "openzyme.kernel": "kernel",
    "openzyme.workspace.git.lfs": "workspace_git_lfs",
    "openzyme.store.sqlite": "store",
    "openzyme.process.podman": "process_podman",
    "openzyme.research": "research",
    "openzyme.reporting": "reporting",
    "openzyme.science": "science",
    "openzyme.compute": "compute",
    "openzyme.hpc": "hpc",
}
_PHASE_ORDER = {"tables": 10, "indexes": 20, "triggers": 30, "finalize": 40}


class PartitionError(RuntimeError):
    pass


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    # Keep build-time catalog identities byte-for-byte aligned with
    # openzyme_contracts.canonical_json_bytes without importing a workspace
    # package into this standalone repository tool.
    return _digest_bytes(
        (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )


def _statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise PartitionError("source migration ends with an incomplete statement")
    return tuple(statements)


def _matches_owner_rule(table: str, rule: dict[str, Any]) -> bool:
    return table in rule.get("exact_names", []) or any(
        table.startswith(prefix) for prefix in rule.get("prefixes", [])
    )


def _owner_for(table: str, manifest: dict[str, Any]) -> str:
    owners = [
        str(rule["target_owner"])
        for rule in manifest["semantic_owner_rules"]
        if _matches_owner_rule(table, rule)
    ]
    if len(owners) != 1:
        raise PartitionError(f"table {table!r} has {len(owners)} semantic owners")
    return owners[0]


def _classify(
    statement: str,
    manifest: dict[str, Any],
) -> tuple[str, str, str]:
    classified = re.sub(
        r"^(?:\s*--[^\n]*(?:\n|$))*\s*",
        "",
        statement,
    )
    if match := _CREATE_TABLE.match(classified):
        table = match.group("name")
        return _owner_for(table, manifest), "tables", table
    if match := _CREATE_INDEX.match(classified):
        table = match.group("table")
        return _owner_for(table, manifest), "indexes", match.group("name")
    if match := _CREATE_TRIGGER_NAME.match(classified):
        table_match = _CREATE_TRIGGER_TABLE.search(classified)
        if table_match is None:
            raise PartitionError(
                f"cannot resolve origin table for trigger {match.group('name')!r}"
            )
        table = table_match.group("table")
        return _owner_for(table, manifest), "triggers", match.group("name")
    if match := _INSERT.match(classified):
        table = match.group("table")
        owner = _owner_for(table, manifest)
        if owner != "openzyme.store.sqlite":
            raise PartitionError(f"seed statement targets non-Store table {table!r}")
        return owner, "finalize", f"seed:{table}"
    if classified.upper().startswith("PRAGMA USER_VERSION"):
        return "openzyme.store.sqlite", "finalize", "pragma:user_version"
    raise PartitionError(f"unclassified migration statement: {classified[:80]!r}")


def _schema_rows(connection: sqlite3.Connection) -> list[dict[str, str]]:
    return [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table": str(row[2]),
            "sql": str(row[3]),
        }
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
    ]


def _render() -> tuple[dict[Path, bytes], dict[str, Any]]:
    manifest = json.loads(OWNER_MANIFEST.read_text(encoding="utf-8"))
    sql = SOURCE_MIGRATION.read_text(encoding="utf-8")
    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    identities: set[str] = set()
    counts = {"tables": 0, "indexes": 0, "triggers": 0, "finalize": 0}
    for statement in _statements(sql):
        owner, phase, identity = _classify(statement, manifest)
        if identity in identities:
            raise PartitionError(f"duplicate migration object identity {identity!r}")
        identities.add(identity)
        grouped.setdefault((owner, phase), []).append((identity, statement))
        counts[phase] += 1

    expected = manifest["expected_object_counts"]
    observed_objects = {
        "tables": counts["tables"],
        "indexes": counts["indexes"],
        "triggers": counts["triggers"],
        "foreign_keys": expected["foreign_keys"],
    }
    if observed_objects != expected or counts["finalize"] != 2:
        raise PartitionError(
            f"migration statement closure drifted: {counts!r}; expected={expected!r}"
        )

    assets: dict[Path, bytes] = {}
    entries: list[dict[str, Any]] = []
    for (owner, phase), values in sorted(
        grouped.items(),
        key=lambda item: (_PHASE_ORDER[item[0][1]], _OWNER_SLUGS[item[0][0]]),
    ):
        slug = _OWNER_SLUGS.get(owner)
        if slug is None:
            raise PartitionError(f"owner {owner!r} has no stable bundle slug")
        relative = Path(
            f"{_PHASE_ORDER[phase]:02d}_{slug}_{phase}.sql"
        )
        body = (
            "-- Generated by scripts/partition-openzyme-sqlite-schema.py.\n"
            f"-- semantic_owner: {owner}\n"
            f"-- phase: {phase}\n\n"
            + "\n\n".join(statement for _, statement in values)
            + "\n"
        ).encode("utf-8")
        assets[relative] = body
        entries.append(
            {
                "migration_id": relative.stem,
                "semantic_owner": owner,
                "phase": phase,
                "resource": f"migrations/owners/{relative.as_posix()}",
                "resource_digest": _digest_bytes(body),
                "object_count": len(values),
                "object_identities": [identity for identity, _ in values],
            }
        )

    canonical = sqlite3.connect(":memory:")
    canonical.executescript(sql)
    canonical_rows = _schema_rows(canonical)
    canonical_user_version = int(canonical.execute("PRAGMA user_version").fetchone()[0])
    canonical.close()

    partitioned = sqlite3.connect(":memory:")
    partitioned.executescript(
        "\n".join(
            assets[Path(Path(entry["resource"]).name)].decode("utf-8")
            for entry in entries
        )
    )
    partitioned_rows = _schema_rows(partitioned)
    partitioned_user_version = int(
        partitioned.execute("PRAGMA user_version").fetchone()[0]
    )
    foreign_keys = sum(
        len(partitioned.execute(f'PRAGMA foreign_key_list("{row["name"]}")').fetchall())
        for row in partitioned_rows
        if row["type"] == "table"
    )
    partitioned.close()
    if canonical_rows != partitioned_rows or canonical_user_version != partitioned_user_version:
        raise PartitionError("partitioned migrations do not reproduce sqlite_master exactly")
    if foreign_keys != expected["foreign_keys"]:
        raise PartitionError(
            f"partitioned foreign-key closure drifted: {foreign_keys}"
        )

    catalog_payload = {
        "schema_id": "openzyme_owner_partitioned_migration_catalog@1",
        "source_migration": SOURCE_MIGRATION.relative_to(ROOT).as_posix(),
        "source_migration_digest": _digest_bytes(sql.encode("utf-8")),
        "source_schema_manifest_digest": _canonical_digest(canonical_rows),
        "source_user_version": canonical_user_version,
        "table_owner_manifest_digest": manifest["table_owner_digest"],
        "physical_store_owner": manifest["physical_store_owner"],
        "physical_table_rename_policy": manifest["physical_table_rename_policy"],
        "expected_object_counts": expected,
        "bundle_order": [entry["migration_id"] for entry in entries],
        "bundles": entries,
    }
    catalog = {
        **catalog_payload,
        "catalog_digest": _canonical_digest(catalog_payload),
    }
    return assets, catalog


def _catalog_bytes(catalog: dict[str, Any]) -> bytes:
    return (
        json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _check(assets: dict[Path, bytes], catalog: dict[str, Any]) -> None:
    expected_paths = {OUTPUT_ROOT / relative for relative in assets}
    observed_paths = set(OUTPUT_ROOT.glob("*.sql")) if OUTPUT_ROOT.exists() else set()
    drift: list[str] = []
    for relative, expected in assets.items():
        path = OUTPUT_ROOT / relative
        if not path.is_file() or path.read_bytes() != expected:
            drift.append(path.relative_to(ROOT).as_posix())
    drift.extend(path.relative_to(ROOT).as_posix() for path in observed_paths - expected_paths)
    expected_catalog = _catalog_bytes(catalog)
    if not CATALOG_PATH.is_file() or CATALOG_PATH.read_bytes() != expected_catalog:
        drift.append(CATALOG_PATH.relative_to(ROOT).as_posix())
    if drift:
        raise PartitionError(f"owner migration assets drifted: {sorted(drift)}")


def _write(assets: dict[Path, bytes], catalog: dict[str, Any]) -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT_ROOT.glob("*.sql"):
        if old.name not in {path.name for path in assets}:
            old.unlink()
    for relative, content in assets.items():
        (OUTPUT_ROOT / relative).write_bytes(content)
    CATALOG_PATH.write_bytes(_catalog_bytes(catalog))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    assets, catalog = _render()
    if args.check:
        _check(assets, catalog)
    else:
        _write(assets, catalog)
    print(
        json.dumps(
            {
                "catalog_digest": catalog["catalog_digest"],
                "bundle_count": len(assets),
                "object_counts": catalog["expected_object_counts"],
                "mutation_applied": not args.check,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
