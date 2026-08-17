#!/usr/bin/env python3
"""Build an exact frozen legacy byte/reference inventory for the offline migrator."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from offline_historical_migrator import AllowlistedStorageReader
from offline_historical_migrator import FrozenObject
from offline_historical_migrator import FrozenReference
from offline_historical_migrator import INVENTORY_SCHEMA
from offline_historical_migrator import MigrationBlocked
from offline_historical_migrator import byte_digest
from offline_historical_migrator import canonical_bytes
from offline_historical_migrator import digest
from offline_historical_migrator import normalize_relative_path
from offline_historical_migrator import operator_source_digests
from offline_historical_migrator import sqlite_schema_inventory


def quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def row_payload(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def storage_snapshot_observation(
    *,
    roots: dict[str, Path],
    source_map: dict[str, dict[str, object]],
    objects: tuple[FrozenObject, ...],
) -> dict[str, object]:
    expected_paths: set[tuple[str, str]] = set()
    for source in source_map.values():
        expected_paths.add(
            (
                str(source["source_root_id"]),
                normalize_relative_path(str(source["source_relative_path"])),
            )
        )
    physical_files = []
    observed_paths: set[tuple[str, str]] = set()
    for root_id, raw_root in sorted(roots.items()):
        root = raw_root.resolve(strict=True)
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise MigrationBlocked("legacy storage snapshot contains a symlink")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            observed_paths.add((root_id, relative))
            physical_files.append(
                {
                    "root_id": root_id,
                    "relative_path": relative,
                    "content_digest": file_digest(path),
                    "size": path.stat().st_size,
                }
            )
    if observed_paths != expected_paths:
        raise MigrationBlocked(
            "legacy storage root contains an omitted or missing physical source"
        )
    return {
        "schema": "historical_storage_snapshot_observation@1",
        "physical_files": physical_files,
        "object_source_identity_digests": sorted(
            item.source_identity_digest for item in objects
        ),
    }


def exact_primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    columns = connection.execute(f"PRAGMA table_info({quoted(table)})").fetchall()
    keys = tuple(
        str(row[1])
        for row in sorted(columns, key=lambda row: int(row[5]))
        if int(row[5]) > 0
    )
    if not keys:
        raise MigrationBlocked(f"legacy reference table {table!r} has no primary key")
    return keys


def build_objects(
    *,
    connection: sqlite3.Connection,
    source_map: dict[str, dict[str, object]],
    reader: AllowlistedStorageReader,
) -> tuple[FrozenObject, ...]:
    rows = connection.execute(
        """
        SELECT artifact.*, session.project_id, pin.binding_id, pin.binding_version,
               pin.resolved_base_commit
        FROM session_artifact_records AS artifact
        JOIN sessions AS session ON session.session_id = artifact.session_id
        JOIN session_repository_binding_pins AS pin
          ON pin.session_id = artifact.session_id
        ORDER BY artifact.session_id, artifact.artifact_id
        """
    ).fetchall()
    objects = []
    for row in rows:
        storage_uri = str(row["storage_uri"])
        source = source_map.get(storage_uri)
        if source is None:
            raise MigrationBlocked(f"storage locator {storage_uri!r} is not explicitly mapped")
        raw_row = row_payload(row)
        raw_row.pop("project_id")
        raw_row.pop("binding_id")
        raw_row.pop("binding_version")
        raw_row.pop("resolved_base_commit")
        metadata = json.loads(str(row["metadata_json"] or "{}"))
        owner = {
            "project_id": row["project_id"],
            "session_id": row["session_id"],
            "task_id": row["task_id"],
            "lane_id": row["lane_id"],
            "invocation_id": row["invocation_id"],
            "run_id": row["run_id"],
        }
        lineage = {
            "artifact_id": row["artifact_id"],
            "kind": row["kind"],
            "relative_path": row["relative_path"],
            "metadata": metadata,
        }
        root_id = str(source["source_root_id"])
        relative = normalize_relative_path(str(source["source_relative_path"]))
        root = reader.roots.get(root_id)
        if root is None:
            raise MigrationBlocked(f"mapped source root {root_id!r} is not allowlisted")
        source_file = root.joinpath(*relative.split("/"))
        if source_file.is_symlink():
            raise MigrationBlocked(f"mapped source {storage_uri!r} is a symlink")
        resolved = source_file.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise MigrationBlocked(f"mapped source {storage_uri!r} escaped its root")
        raw = resolved.read_bytes()
        start = int(source.get("byte_range_start", 0))
        length_value = source.get("byte_range_length")
        length = None if length_value is None else int(length_value)
        if (
            start < 0
            or start > len(raw)
            or (length is not None and (length < 0 or start + length > len(raw)))
        ):
            raise MigrationBlocked(
                f"mapped byte range is outside source {storage_uri!r}"
            )
        content = raw[start:] if length is None else raw[start : start + length]
        identity = {
            "source_scheme": str(source["source_scheme"]),
            "root_id": root_id,
            "relative_path": relative,
            "file_size": len(raw),
            "slice_start": start,
            "slice_size": len(content),
            "slice_digest": byte_digest(content),
        }
        declared = metadata.get("content_digest")
        if declared is not None and declared != byte_digest(content):
            raise MigrationBlocked(f"declared digest differs for {row['artifact_id']!r}")
        item = FrozenObject(
            object_id=str(row["artifact_id"]),
            project_id=str(row["project_id"]),
            session_id=str(row["session_id"]),
            kind=str(row["kind"]),
            source_scheme=str(source["source_scheme"]),
            source_root_id=root_id,
            source_relative_path=relative,
            source_identity_digest=digest(identity),
            expected_content_digest=byte_digest(content),
            expected_size=len(content),
            relative_path=str(row["relative_path"]),
            owner_identity_digest=digest(owner),
            lineage_digest=digest(lineage),
            source_row_version_digest=digest(raw_row),
            repository_binding_id=str(row["binding_id"]),
            repository_binding_version=int(row["binding_version"]),
            repository_base_commit=str(row["resolved_base_commit"]),
            byte_range_start=start,
            byte_range_length=length,
        )
        reader.read(item)
        objects.append(item)
    if set(source_map) != {str(row["storage_uri"]) for row in rows}:
        raise MigrationBlocked("source map contains an unknown or omitted storage identity")
    return tuple(objects)


def build_references(
    *,
    connection: sqlite3.Connection,
    objects: tuple[FrozenObject, ...],
    rules: tuple[dict[str, object], ...],
) -> tuple[FrozenReference, ...]:
    object_ids = {item.object_id for item in objects}
    references = []
    covered: set[tuple[str, str, str]] = set()
    for rule in rules:
        table = str(rule["table"])
        field = str(rule["field"])
        replacement_kind = str(rule["replacement_kind"])
        replacement_field = str(rule["replacement_field"])
        primary_keys = exact_primary_key(connection, table)
        table_columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({quoted(table)})").fetchall()
        }
        if replacement_field not in table_columns:
            raise MigrationBlocked(f"typed replacement field {table}.{replacement_field} is missing")
        selected = ", ".join(
            quoted(item)
            for item in dict.fromkeys((*primary_keys, field, replacement_field))
        )
        rows = connection.execute(
            f"SELECT {selected} FROM {quoted(table)} WHERE {quoted(field)} IS NOT NULL"
        ).fetchall()
        for row in rows:
            original_id = str(row[field])
            if original_id not in object_ids:
                raise MigrationBlocked(
                    f"{table}.{field} contains an unknown source identity"
                )
            primary = {key: row[key] for key in primary_keys}
            primary_digest = digest(primary)
            reference_id = "historical_reference_" + digest(
                {"table": table, "primary": primary, "field": field}
            )[-32:]
            source_version = connection.execute(
                f"SELECT * FROM {quoted(table)} WHERE "
                + " AND ".join(f"{quoted(key)} = ?" for key in primary_keys),
                tuple(primary[key] for key in primary_keys),
            ).fetchone()
            if source_version is None:
                raise MigrationBlocked("reference row disappeared during inventory")
            frozen_source_row = row_payload(source_version)
            replacement_value = row[replacement_field]
            if replacement_kind == "historical_ref":
                if replacement_value is not None:
                    raise MigrationBlocked(
                        f"historical replacement {table}.{replacement_field} is already occupied"
                    )
                expected_replacement_ref = None
            else:
                expected_replacement_ref = str(replacement_value or "")
                if not expected_replacement_ref:
                    raise MigrationBlocked(
                        f"typed replacement {table}.{replacement_field} is absent"
                    )
            references.append(
                FrozenReference(
                    reference_id=reference_id,
                    source_table=table,
                    source_primary_key=primary,
                    source_field=field,
                    replacement_field=replacement_field,
                    object_id=original_id,
                    replacement_kind=replacement_kind,
                    expected_replacement_ref=expected_replacement_ref,
                    source_row_payload=frozen_source_row,
                    source_row_version_digest=digest(frozen_source_row),
                )
            )
            covered.add((table, field, primary_digest))

    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        if not str(row[0]).startswith("historical_artifact_")
    ]
    source_table = "session_artifact_records"
    for table in tables:
        columns = connection.execute(f"PRAGMA table_info({quoted(table)})").fetchall()
        legacy_fields = [
            str(row[1])
            for row in columns
            if any(token in str(row[1]).lower() for token in ("artifact", "staging_ref"))
        ]
        if table == source_table:
            legacy_fields = [field for field in legacy_fields if field != "artifact_id"]
        if not legacy_fields:
            continue
        primary_keys = exact_primary_key(connection, table)
        for field in legacy_fields:
            selected = ", ".join(quoted(item) for item in (*primary_keys, field))
            rows = connection.execute(
                f"SELECT {selected} FROM {quoted(table)} WHERE {quoted(field)} IS NOT NULL"
            ).fetchall()
            for row in rows:
                primary = digest({key: row[key] for key in primary_keys})
                if (table, field, primary) not in covered:
                    raise MigrationBlocked(
                        f"untyped legacy reference remains at {table}.{field}"
                    )
    return tuple(sorted(references, key=lambda item: item.reference_id))


def execute(args: argparse.Namespace) -> None:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("schema") != "historical_inventory_config@1":
        raise MigrationBlocked("inventory config schema is unsupported")
    root_entries = tuple(config.get("source_roots", []))
    object_entries = tuple(config.get("source_objects", []))
    roots = {
        str(item["root_id"]): Path(str(item["path"])) for item in root_entries
    }
    source_map = {
        str(item["storage_uri"]): {
            key: value for key, value in item.items() if key != "storage_uri"
        }
        for item in object_entries
    }
    if len(roots) != len(root_entries) or len(source_map) != len(object_entries):
        raise MigrationBlocked("inventory config contains duplicate source identities")
    lfs_policy = config.get("lfs_policy")
    if (
        not isinstance(lfs_policy, dict)
        or lfs_policy.get("schema") != "git_lfs_content_policy@1"
        or not isinstance(lfs_policy.get("threshold_bytes"), int)
        or int(lfs_policy["threshold_bytes"]) < 0
    ):
        raise MigrationBlocked("inventory Git LFS policy is unsupported")
    if args.database.with_name(args.database.name + "-wal").exists():
        raise MigrationBlocked("database WAL exists during frozen inventory")
    database_snapshot_digest = file_digest(args.database)
    if database_snapshot_digest != config.get("database_snapshot_digest"):
        raise MigrationBlocked("database bytes differ from the frozen snapshot")
    connection = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        schema = sqlite_schema_inventory(connection)
        objects = build_objects(
            connection=connection,
            source_map=source_map,
            reader=AllowlistedStorageReader(roots),
        )
        references = build_references(
            connection=connection,
            objects=objects,
            rules=tuple(config.get("reference_rules", [])),
        )
    finally:
        connection.close()
    if file_digest(args.database) != database_snapshot_digest:
        raise MigrationBlocked("database changed while inventory was built")
    storage_observation = storage_snapshot_observation(
        roots=roots,
        source_map=source_map,
        objects=objects,
    )
    storage_snapshot_digest = digest(storage_observation)
    if storage_snapshot_digest != config.get("storage_snapshot_digest"):
        raise MigrationBlocked("storage bytes differ from the frozen snapshot")
    source_digests = operator_source_digests()
    payload = {
        "schema": INVENTORY_SCHEMA,
        "database_snapshot_digest": config["database_snapshot_digest"],
        "storage_snapshot_digest": config["storage_snapshot_digest"],
        "writer_freeze_receipt_digest": config["writer_freeze_receipt_digest"],
        "database_high_watermark_digest": config["database_high_watermark_digest"],
        "storage_generation_digest": config["storage_generation_digest"],
        "created_at": config["created_at"],
        "schema_inventory_digest": schema["structure_set_digest"],
        "source_root_path_digests": {
            root_id: digest(str(path.resolve(strict=True)))
            for root_id, path in sorted(roots.items())
        },
        "lfs_policy": lfs_policy,
        "lfs_policy_digest": digest(lfs_policy),
        "operator_source_digests": source_digests,
        "operator_source_set_digest": digest(source_digests),
        "expected_object_set_digest": digest(
            sorted(digest(item.identity) for item in objects)
        ),
        "expected_reference_set_digest": digest(
            sorted(digest(asdict(item)) for item in references)
        ),
        "expected_byte_total": sum(item.expected_size for item in objects),
        "objects": [asdict(item) for item in objects],
        "references": [asdict(item) for item in references],
        "schema_inventory": schema,
        "storage_snapshot_observation": storage_observation,
        "blockers": [],
    }
    args.output.write_bytes(canonical_bytes({**payload, "inventory_digest": digest(payload)}))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--database", required=True, type=Path)
    value.add_argument("--config", required=True, type=Path)
    value.add_argument("--output", required=True, type=Path)
    return value


if __name__ == "__main__":
    execute(parser().parse_args())
