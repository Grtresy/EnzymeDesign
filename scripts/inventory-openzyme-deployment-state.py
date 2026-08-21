#!/usr/bin/env python3
"""Read-only inventory for offline OpenZyme composition/session classification.

The command never imports product packages, starts a service, executes a
migration, or writes SQLite.  It reports only safe aggregate counts, schema
proof identities and file digests; row bodies, credentials and private
locators are deliberately excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TABLE_OWNER_PATH = ROOT / "docs" / "v3" / "architecture" / "table-owner-manifest.json"
TERMINAL_SESSION_STATES = frozenset({"completed", "failed", "archived"})
TERMINAL_OPERATION_STATES = frozenset({"completed", "failed", "recovery_failed"})
TERMINAL_CONTINUATION_STATES = frozenset(
    {"rejected", "completed", "failed", "recovery_failed"}
)


class DeploymentInventoryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_owner_rules() -> list[dict[str, Any]]:
    document = json.loads(TABLE_OWNER_PATH.read_text(encoding="utf-8"))
    if document.get("schema_id") != "openzyme_table_owner_manifest@1":
        raise DeploymentInventoryError("unexpected table-owner manifest schema")
    return list(document["semantic_owner_rules"])


def _owner(table_name: str, rules: list[dict[str, Any]]) -> str:
    matches = [
        rule["target_owner"]
        for rule in rules
        if table_name in rule["exact_names"]
        or any(table_name.startswith(prefix) for prefix in rule["prefixes"])
    ]
    if len(matches) != 1:
        raise DeploymentInventoryError(
            f"table {table_name!r} has {len(matches)} semantic owners"
        )
    return str(matches[0])


def _table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )


def _count(connection: sqlite3.Connection, table_name: str) -> int:
    if '"' in table_name:
        raise DeploymentInventoryError("invalid SQLite table identity")
    return int(
        connection.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0]
    )


def _status_count(
    connection: sqlite3.Connection,
    table_name: str,
    terminal_states: frozenset[str],
) -> tuple[int, int]:
    total = _count(connection, table_name)
    placeholders = ",".join("?" for _ in terminal_states)
    terminal = int(
        connection.execute(
            f'SELECT count(*) FROM "{table_name}" WHERE status IN ({placeholders})',
            tuple(sorted(terminal_states)),
        ).fetchone()[0]
    )
    return total, total - terminal


def observe(database_path: Path, *, locator_id: str) -> dict[str, Any]:
    path = database_path.resolve(strict=True)
    if not path.is_file():
        raise DeploymentInventoryError("database locator is not a regular file")
    wal_path = path.with_name(f"{path.name}-wal")
    wal_size = wal_path.stat().st_size if wal_path.is_file() else 0
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        before_changes = connection.total_changes
        tables = _table_names(connection)
        table_set = set(tables)
        rules = _load_owner_rules()
        owner_counts: dict[str, dict[str, int]] = {}
        for table_name in tables:
            owner = _owner(table_name, rules)
            bucket = owner_counts.setdefault(owner, {"tables": 0, "rows": 0})
            bucket["tables"] += 1
            bucket["rows"] += _count(connection, table_name)

        deployment_rows = []
        if "deployment_schema_state" in table_set:
            for row in connection.execute(
                "SELECT schema_generation, manifest_digest, removal_state, "
                "removal_receipt_digest FROM deployment_schema_state ORDER BY singleton"
            ):
                deployment_rows.append(dict(row))

        sessions_total, sessions_non_terminal = _status_count(
            connection, "sessions", TERMINAL_SESSION_STATES
        )
        continuations_total, continuations_unsettled = _status_count(
            connection, "continuation_state_records", TERMINAL_CONTINUATION_STATES
        )
        operations_total, operations_unsettled = _status_count(
            connection, "controlled_operation_records", TERMINAL_OPERATION_STATES
        )
        authority_rows = _count(connection, "agent_capability_lease_records")
        authority_active = int(
            connection.execute(
                "SELECT count(*) FROM agent_capability_lease_records "
                "WHERE status = 'active'"
            ).fetchone()[0]
        )
        result = {
            "schema_id": "openzyme_pre_split_deployment_state_inventory@1",
            "observation": {
                "mode": "sqlite_mode_ro_query_only",
                "locator_id": locator_id,
                "database_digest": _sha256(path),
                "database_size_bytes": path.stat().st_size,
                "wal_present": wal_size > 0,
                "wal_size_bytes": wal_size,
                "sqlite_user_version": int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                ),
                "quick_check": str(
                    connection.execute("PRAGMA quick_check").fetchone()[0]
                ),
                "mutation_applied": False,
            },
            "deployment_proof_rows": deployment_rows,
            "classification_inputs": {
                "sessions_total": sessions_total,
                "sessions_non_terminal": sessions_non_terminal,
                "session_contract_pins": _count(
                    connection, "file_workspace_session_contract_records"
                ),
                "continuations_total": continuations_total,
                "continuations_unsettled": continuations_unsettled,
                "controlled_operations_total": operations_total,
                "controlled_operations_unsettled": operations_unsettled,
                "workspace_backend_pins": _count(
                    connection, "session_repository_binding_pins"
                ),
                "authority_leases_total": authority_rows,
                "authority_leases_active": authority_active,
                "hpc_target_qualifications": _count(
                    connection, "executor_hpc_target_qualifications"
                ),
                "table_owner_aggregates": dict(sorted(owner_counts.items())),
            },
            "classification": (
                "fresh_empty_candidate"
                if sessions_total == 0
                and continuations_unsettled == 0
                and operations_unsettled == 0
                and wal_size == 0
                else "requires_offline_session_and_effect_classification"
            ),
            "authority": "read_only_engineering_evidence_only",
            "forbidden_inferences": [
                "not_at2_cutover_authority",
                "not_plugin_activation_authority",
                "not_live_provider_or_hpc_readiness",
                "not_session_task_or_scientific_terminal_authority"
            ],
        }
        if connection.total_changes != before_changes:
            raise DeploymentInventoryError("read-only inventory mutated SQLite")
        return result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--locator-id", required=True)
    arguments = parser.parse_args()
    try:
        result = observe(arguments.database, locator_id=arguments.locator_id)
    except (DeploymentInventoryError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"deployment-state-inventory: FAIL: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
