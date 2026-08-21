from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import sqlite3

from .legacy_deployment_schema_proofs import DeploymentSchemaProofError
from .legacy_deployment_schema_proofs import verify_fresh_install_bootstrap
from .legacy_deployment_schema_proofs import verify_offline_removal_ledger


MIGRATION_IDS: tuple[str, ...] = ("001_file_workspace_final",)
CURRENT_SQLITE_SCHEMA_VERSION = 2
FINAL_SCHEMA_GENERATION = "openzyme_file_workspace_final@2"
FINAL_SCHEMA_MANIFEST_DIGEST = (
    "sha256:042166dc38007b1345efdec5f0e87a983abaacf93f1824271dbdc83223c2d680"
)
FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST = (
    "sha256:32897934dfe44919ca3cbf5e0302cbf22eb8808e16ad3a91476eb732fbe2d1a6"
)
_COMPLETE_REMOVAL_STATES = frozenset(
    {"fresh_install_complete", "offline_removal_complete"}
)
_FORBIDDEN_SCHEMA_TERMS = (
    "arti" + "fact",
    "materialization",
    "staging_ref",
    "storage_uri",
)


class SQLiteSchemaMismatchError(RuntimeError):
    """Detailed fail-closed rejection of a non-current deployment database."""

    error_code = "sqlite_schema_mismatch"

    def __init__(
        self,
        message: str,
        *,
        phase: str = "startup_schema_verification",
        expected: object | None = None,
        observed: object | None = None,
        operator_action: str = "inspect_the_deployment_database",
    ) -> None:
        self.phase = phase
        self.expected = expected
        self.observed = observed
        self.operator_action = operator_action
        self.mutation_applied = False
        self.fallback_performed = False
        self.diagnostic_context = {
            "phase": phase,
            "expected": expected,
            "observed": observed,
            "operator_action": operator_action,
            "mutation_applied": False,
            "fallback_performed": False,
        }
        super().__init__(
            f"{message}; phase={phase}; expected={expected!r}; "
            f"observed={observed!r}; operator_action={operator_action}; "
            "mutation_applied=false; fallback_performed=false"
        )


def get_migration_sql(migration_id: str) -> str:
    if migration_id not in MIGRATION_IDS:
        raise ValueError(f"unknown current migration id: {migration_id}")
    return files("openzyme_store_sqlite.migrations").joinpath(
        f"{migration_id}.sql"
    ).read_text()


def _schema_manifest_digest(connection: sqlite3.Connection) -> str:
    rows = [
        {
            "type": row[0],
            "name": row[1],
            "table": row[2],
            "sql": row[3],
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
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _has_user_schema(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        LIMIT 1
        """
    ).fetchone() is not None


def _initialize_final_schema(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        raise SQLiteSchemaMismatchError(
            "final schema initialization cannot run inside a transaction"
        )
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + get_migration_sql(MIGRATION_IDS[0])
            + "\nCOMMIT;"
        )
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise SQLiteSchemaMismatchError("failed to initialize final SQLite schema") from exc


def _verify_final_schema(connection: sqlite3.Connection) -> None:
    initial_total_changes = connection.total_changes
    initial_transaction_state = connection.in_transaction
    try:
        _verify_final_schema_read_only(connection)
    except SQLiteSchemaMismatchError:
        raise
    except DeploymentSchemaProofError as exc:
        raise SQLiteSchemaMismatchError(
            str(exc),
            phase=exc.phase,
            expected=exc.diagnostic_context["expected"],
            observed=exc.diagnostic_context["observed"],
            operator_action=str(exc.diagnostic_context["operator_action"]),
        ) from exc
    except sqlite3.Error as exc:
        raise SQLiteSchemaMismatchError(
            "final SQLite schema verification query failed",
            phase="startup_schema_query",
            expected="readable current deployment schema",
            observed=exc.__class__.__qualname__,
            operator_action="inspect_database_integrity_and_permissions",
        ) from exc
    finally:
        if (
            connection.total_changes != initial_total_changes
            or connection.in_transaction != initial_transaction_state
        ):
            raise RuntimeError(
                "startup schema verifier violated its read-only contract; "
                f"initial_total_changes={initial_total_changes}; "
                f"observed_total_changes={connection.total_changes}; "
                f"initial_in_transaction={initial_transaction_state}; "
                f"observed_in_transaction={connection.in_transaction}"
            )


def _verify_final_schema_read_only(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version != CURRENT_SQLITE_SCHEMA_VERSION:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: use the explicit offline migration path",
            phase="schema_version",
            expected=CURRENT_SQLITE_SCHEMA_VERSION,
            observed=user_version,
            operator_action="run_the_authorized_offline_migration_or_fresh_install",
        )
    rows = connection.execute(
        """
        SELECT name, COALESCE(sql, '') FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    offending = sorted(
        name
        for name, sql in rows
        if any(term in f"{name} {sql}".lower() for term in _FORBIDDEN_SCHEMA_TERMS)
    )
    if offending:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: final schema contains retired structures",
            phase="forbidden_structure_scan",
            expected=[],
            observed=offending,
            operator_action="run_the_authorized_offline_migration_or_fresh_install",
        )
    state = connection.execute(
        """
        SELECT schema_generation, removal_state, removal_receipt_digest,
               manifest_digest
        FROM deployment_schema_state WHERE singleton = 1
        """
    ).fetchone()
    if state is None or state[0] != FINAL_SCHEMA_GENERATION:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: final generation marker is absent",
            phase="schema_generation",
            expected=FINAL_SCHEMA_GENERATION,
            observed=None if state is None else state[0],
            operator_action="run_the_authorized_offline_migration_or_fresh_install",
        )
    if state[1] not in _COMPLETE_REMOVAL_STATES:
        raise SQLiteSchemaMismatchError(
            "legacy_removal_incomplete: complete the same offline removal plan",
            phase="deployment_variant",
            expected=sorted(_COMPLETE_REMOVAL_STATES),
            observed=state[1],
            operator_action="complete_the_same_offline_removal_plan",
        )
    observed_manifest = _schema_manifest_digest(connection)
    if (
        state[3] != FINAL_SCHEMA_MANIFEST_DIGEST
        or observed_manifest != FINAL_SCHEMA_MANIFEST_DIGEST
    ):
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: final schema manifest differs",
            phase="schema_manifest",
            expected=FINAL_SCHEMA_MANIFEST_DIGEST,
            observed={"stored": state[3], "recomputed": observed_manifest},
            operator_action="deploy_the_exact_current_final_schema",
        )
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise SQLiteSchemaMismatchError(
            "final SQLite foreign-key closure is invalid",
            phase="foreign_key_closure",
            expected=[],
            observed=foreign_key_errors,
            operator_action="repair_the_database_using_the_authorized_offline_path",
        )
    if state[1] == "fresh_install_complete":
        verify_fresh_install_bootstrap(
            connection,
            schema_generation=state[0],
            schema_manifest_digest=state[3],
            stored_receipt_digest=state[2],
            expected_receipt_digest=FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST,
        )
    else:
        verify_offline_removal_ledger(
            connection,
            schema_generation=state[0],
            schema_manifest_digest=state[3],
            stored_receipt_digest=state[2],
        )


def apply_sqlite_migrations(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version == 0 and not _has_user_schema(connection):
        _initialize_final_schema(connection)
    elif user_version != CURRENT_SQLITE_SCHEMA_VERSION:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: normal startup never performs an offline upgrade"
        )
    _verify_final_schema(connection)
    connection.execute("PRAGMA foreign_keys = ON")


__all__ = [
    "CURRENT_SQLITE_SCHEMA_VERSION",
    "FINAL_SCHEMA_GENERATION",
    "FINAL_SCHEMA_MANIFEST_DIGEST",
    "FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST",
    "MIGRATION_IDS",
    "SQLiteSchemaMismatchError",
    "apply_sqlite_migrations",
    "get_migration_sql",
]
