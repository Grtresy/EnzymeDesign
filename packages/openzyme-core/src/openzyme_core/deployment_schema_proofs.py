from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
from typing import Any


FRESH_INSTALL_RECEIPT_SCHEMA = "fresh_install_bootstrap_receipt@1"
FRESH_INSTALL_MIGRATION_SOURCE = (
    "openzyme_core.migrations:001_file_workspace_final.sql"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class DeploymentSchemaProofError(ValueError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        phase: str,
        expected: object | None = None,
        observed: object | None = None,
        operator_action: str,
    ) -> None:
        self.error_code = error_code
        self.phase = phase
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
            f"{error_code}: {message}; phase={phase}; expected={expected!r}; "
            f"observed={observed!r}; operator_action={operator_action}; "
            "mutation_applied=false; fallback_performed=false"
        )


@dataclass(frozen=True, slots=True)
class FreshInstallBootstrapReceipt:
    schema_generation: str
    schema_manifest_digest: str
    empty_application_table_count: int
    empty_application_table_set_digest: str
    migration_source: str = FRESH_INSTALL_MIGRATION_SOURCE
    startup_variant: str = "fresh_install"
    legacy_initialization_performed: bool = False
    empty_application_row_count: int = 0
    schema_version: str = FRESH_INSTALL_RECEIPT_SCHEMA

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "startup_variant": self.startup_variant,
            "schema_generation": self.schema_generation,
            "schema_manifest_digest": self.schema_manifest_digest,
            "migration_source": self.migration_source,
            "legacy_initialization_performed": self.legacy_initialization_performed,
            "empty_application_table_count": self.empty_application_table_count,
            "empty_application_table_set_digest": (
                self.empty_application_table_set_digest
            ),
            "empty_application_row_count": self.empty_application_row_count,
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_digest(self.payload)


def _application_table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
              AND name <> 'deployment_schema_state'
            ORDER BY name
            """
        ).fetchall()
    )


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _fresh_receipt_from_schema(
    *,
    table_names: tuple[str, ...],
    schema_generation: str,
    schema_manifest_digest: str,
) -> FreshInstallBootstrapReceipt:
    return FreshInstallBootstrapReceipt(
        schema_generation=schema_generation,
        schema_manifest_digest=schema_manifest_digest,
        empty_application_table_count=len(table_names),
        empty_application_table_set_digest=canonical_digest(list(table_names)),
    )


def build_fresh_install_bootstrap_receipt(
    connection: sqlite3.Connection,
    *,
    schema_generation: str,
    schema_manifest_digest: str,
) -> FreshInstallBootstrapReceipt:
    table_names = _application_table_names(connection)
    nonempty_tables = {
        table_name: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quoted_identifier(table_name)}"
            ).fetchone()[0]
        )
        for table_name in table_names
    }
    nonempty_tables = {
        name: row_count
        for name, row_count in nonempty_tables.items()
        if row_count != 0
    }
    if nonempty_tables:
        raise DeploymentSchemaProofError(
            "fresh_install_not_empty",
            "fresh installation contains product or legacy rows",
            phase="fresh_empty_object_set",
            expected={},
            observed=nonempty_tables,
            operator_action="recreate_from_an_exact_empty_database",
        )
    return _fresh_receipt_from_schema(
        table_names=table_names,
        schema_generation=schema_generation,
        schema_manifest_digest=schema_manifest_digest,
    )


def verify_fresh_install_bootstrap(
    connection: sqlite3.Connection,
    *,
    schema_generation: str,
    schema_manifest_digest: str,
    stored_receipt_digest: str,
    expected_receipt_digest: str,
) -> FreshInstallBootstrapReceipt:
    table_names = _application_table_names(connection)
    offline_proof_rows = {
        table_name: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quoted_identifier(table_name)}"
            ).fetchone()[0]
        )
        for table_name in ("legacy_removal_ledger", "legacy_removal_items")
    }
    offline_proof_rows = {
        name: row_count
        for name, row_count in offline_proof_rows.items()
        if row_count != 0
    }
    if offline_proof_rows:
        raise DeploymentSchemaProofError(
            "fresh_variant_contains_offline_proof_rows",
            "fresh startup cannot consume or retain an offline removal ledger",
            phase="fresh_variant_isolation",
            expected={},
            observed=offline_proof_rows,
            operator_action="recreate_or_verify_the_exact_deployment_variant",
        )
    receipt = _fresh_receipt_from_schema(
        table_names=table_names,
        schema_generation=schema_generation,
        schema_manifest_digest=schema_manifest_digest,
    )
    if (
        stored_receipt_digest != expected_receipt_digest
        or receipt.receipt_digest != expected_receipt_digest
    ):
        raise DeploymentSchemaProofError(
            "fresh_install_receipt_mismatch",
            "fresh bootstrap receipt is not independently reproducible",
            phase="fresh_receipt_verification",
            expected=expected_receipt_digest,
            observed={
                "stored": stored_receipt_digest,
                "recomputed": receipt.receipt_digest,
            },
            operator_action="recreate_from_the_current_final_migration",
        )
    return receipt


def _row_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    columns = tuple(str(item[0]) for item in cursor.description or ())
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DeploymentSchemaProofError(
            "offline_ledger_digest_invalid",
            "offline removal ledger contains a malformed digest",
            phase="offline_ledger_verification",
            expected=f"{field_name}=sha256:<64-lowercase-hex>",
            observed=value,
            operator_action="inspect_the_authorized_offline_removal_receipt",
        )
    return value


def verify_offline_removal_ledger(
    connection: sqlite3.Connection,
    *,
    schema_generation: str,
    schema_manifest_digest: str,
    stored_receipt_digest: str,
) -> dict[str, object]:
    ledgers = _row_dicts(
        connection.execute("SELECT * FROM legacy_removal_ledger ORDER BY receipt_id")
    )
    if len(ledgers) != 1 or ledgers[0]["receipt_digest"] != stored_receipt_digest:
        raise DeploymentSchemaProofError(
            "offline_ledger_identity_mismatch",
            "offline startup requires one exact receipt-bound ledger",
            phase="offline_ledger_verification",
            expected={"count": 1, "receipt_digest": stored_receipt_digest},
            observed={
                "count": len(ledgers),
                "receipt_digests": [row["receipt_digest"] for row in ledgers],
            },
            operator_action="resume_or_repair_the_exact_offline_removal_plan",
        )
    ledger = ledgers[0]
    if (
        ledger["schema_generation"] != schema_generation
        or ledger["state"] != "complete"
        or not isinstance(ledger["completed_at"], str)
        or not ledger["completed_at"].strip()
    ):
        raise DeploymentSchemaProofError(
            "offline_ledger_incomplete",
            "offline removal ledger is not a completed current-generation proof",
            phase="offline_ledger_verification",
            expected={"schema_generation": schema_generation, "state": "complete"},
            observed={
                "schema_generation": ledger["schema_generation"],
                "state": ledger["state"],
                "completed_at": ledger["completed_at"],
            },
            operator_action="complete_the_same_offline_removal_plan",
        )
    for field_name in (
        "manifest_digest",
        "historical_receipt_digest",
        "database_backup_digest",
        "storage_backup_digest",
        "quiescence_receipt_digest",
        "expected_object_set_digest",
        "removed_object_set_digest",
        "already_absent_set_digest",
        "root_identity_set_digest",
        "error_object_set_digest",
        "receipt_digest",
    ):
        _require_digest(ledger[field_name], field_name)
    items = _row_dicts(
        connection.execute(
            "SELECT * FROM legacy_removal_items WHERE receipt_id=? "
            "ORDER BY object_identity",
            (ledger["receipt_id"],),
        )
    )
    identities = [str(item["object_identity"]) for item in items]
    removed = [
        str(item["object_identity"]) for item in items if item["state"] == "removed"
    ]
    already_absent = [
        str(item["object_identity"])
        for item in items
        if item["state"] == "already_absent"
    ]
    errors = [
        str(item["object_identity"]) for item in items if item["state"] == "error"
    ]
    unsupported_states = sorted(
        {
            str(item["state"])
            for item in items
            if item["state"] not in {"removed", "already_absent", "error"}
        }
    )
    computed = {
        "expected_object_set_digest": canonical_digest(identities),
        "removed_object_set_digest": canonical_digest(removed),
        "already_absent_set_digest": canonical_digest(already_absent),
        "root_identity_set_digest": canonical_digest(
            sorted(
                {
                    (str(item["root_identity"]), str(item["root_path_digest"]))
                    for item in items
                }
            )
        ),
        "error_object_set_digest": canonical_digest(errors),
        "expected_byte_total": sum(int(item["size_bytes"]) for item in items),
        "removed_byte_total": sum(
            int(item["size_bytes"]) for item in items if item["state"] == "removed"
        ),
    }
    mismatches = {
        key: {"stored": ledger[key], "computed": value}
        for key, value in computed.items()
        if ledger[key] != value
    }
    if unsupported_states or errors or mismatches:
        raise DeploymentSchemaProofError(
            "offline_ledger_closure_mismatch",
            "offline removal item, byte, or error closure differs",
            phase="offline_item_closure",
            expected={"unsupported_states": [], "errors": [], "mismatches": {}},
            observed={
                "unsupported_states": unsupported_states,
                "errors": errors,
                "mismatches": mismatches,
            },
            operator_action="inspect_and_reconcile_the_exact_removal_item_ledger",
        )
    receipt_payload = {
        "schema": "legacy_subsystem_removal_receipt@2",
        "receipt_id": ledger["receipt_id"],
        "schema_generation": ledger["schema_generation"],
        "final_schema_manifest_digest": schema_manifest_digest,
        "manifest_digest": ledger["manifest_digest"],
        "historical_receipt_digest": ledger["historical_receipt_digest"],
        "database_backup_digest": ledger["database_backup_digest"],
        "storage_backup_digest": ledger["storage_backup_digest"],
        "quiescence_receipt_digest": ledger["quiescence_receipt_digest"],
        "expected_object_set_digest": ledger["expected_object_set_digest"],
        "removed_object_set_digest": ledger["removed_object_set_digest"],
        "already_absent_set_digest": ledger["already_absent_set_digest"],
        "root_identity_set_digest": ledger["root_identity_set_digest"],
        "error_object_set_digest": ledger["error_object_set_digest"],
        "expected_byte_total": ledger["expected_byte_total"],
        "removed_byte_total": ledger["removed_byte_total"],
        "completed_at": ledger["completed_at"],
        "state": "complete",
    }
    recomputed_receipt_digest = canonical_digest(receipt_payload)
    if recomputed_receipt_digest != stored_receipt_digest:
        raise DeploymentSchemaProofError(
            "offline_receipt_digest_mismatch",
            "offline removal receipt digest does not bind the closed ledger",
            phase="offline_receipt_verification",
            expected=stored_receipt_digest,
            observed=recomputed_receipt_digest,
            operator_action="inspect_the_exact_offline_removal_receipt",
        )
    return {**receipt_payload, "receipt_digest": recomputed_receipt_digest}


__all__ = [
    "DeploymentSchemaProofError",
    "FRESH_INSTALL_MIGRATION_SOURCE",
    "FRESH_INSTALL_RECEIPT_SCHEMA",
    "FreshInstallBootstrapReceipt",
    "build_fresh_install_bootstrap_receipt",
    "canonical_digest",
    "verify_fresh_install_bootstrap",
    "verify_offline_removal_ledger",
]
