"""Atomic SQLite adoption for an already verified offline @2 cutover plan."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import canonical_sha256_digest

from .authority_mapping import AgentAuthorityStoreMappingReceipt
from .authority_mapping import LEGACY_AUTHORITY_PHYSICAL_COLUMNS
from .authority_mapping import map_legacy_agent_capability_lease_row
from .composite_startup import CompositeSQLiteStartupProof
from .composite_startup import verify_composite_store_schema_read_only
from .deployment_proof import DeploymentProofVariant
from .deployment_proof import FreshInstallCompositionSeed
from .deployment_proof import SQLiteDeploymentProofError
from .offline_cutover import OfflineCutoverDisposition
from .offline_cutover import OfflineCutoverItemKind
from .offline_cutover import OfflineCutoverLedgerReceipt
from .offline_cutover import OfflineCutoverState
from .offline_cutover import SessionCutoverDispositionKind
from .offline_cutover_planning import OfflineBackupSetProof
from .offline_cutover_planning import OfflineCutoverDryRunProof
from .offline_cutover_planning import OfflineQuiescenceReceipt
from .startup_composition_state import SessionCompositionStateProof
from .startup_composition_state import verify_session_composition_state_read_only


@dataclass(frozen=True, slots=True)
class OfflineSessionAdoption:
    pin: SessionCompositionPin
    initial_binding: SessionCapabilityBindingRevision

    def __post_init__(self) -> None:
        if (
            self.pin.session_id != self.initial_binding.session_id
            or self.pin.initial_capability_binding_id
            != self.initial_binding.binding_id
            or self.pin.initial_capability_binding_revision != 1
            or self.initial_binding.revision != 1
            or self.pin.initial_capability_binding_digest
            != self.initial_binding.binding_digest
            or not self.pin.has_valid_digest()
            or not self.initial_binding.has_valid_digest()
        ):
            raise ValueError("offline Session adoption pin/binding identity drifted")


@dataclass(frozen=True, slots=True)
class OfflineCutoverApplicationPlan:
    target_seed: FreshInstallCompositionSeed
    dry_run: OfflineCutoverDryRunProof
    quiescence: OfflineQuiescenceReceipt
    backup_set: OfflineBackupSetProof
    authority_mappings: tuple[AgentAuthorityStoreMappingReceipt, ...]
    session_adoptions: tuple[OfflineSessionAdoption, ...]
    ledger: OfflineCutoverLedgerReceipt

    def __post_init__(self) -> None:
        if not self.dry_run.ready:
            raise ValueError("offline cutover plan contains dry-run blockers")
        if self.ledger.state is not OfflineCutoverState.COMPLETE:
            raise ValueError("offline cutover application requires a complete ledger")
        if self.quiescence.deployment_inventory_digest != self.dry_run.proof_digest:
            raise ValueError("quiescence does not bind the exact dry-run inventory")
        if self.ledger.source_release_digest != self.dry_run.source_release_digest:
            raise ValueError("ledger source release differs from dry run")
        target_release = self.target_seed.activation_epoch.release_identity.release_digest
        if (
            self.ledger.target_release_digest != target_release
            or self.dry_run.target_release_digest != target_release
            or self.ledger.target_schema_manifest_digest
            != self.target_seed.schema_proof.complete_schema_manifest_digest
            or self.ledger.table_owner_manifest_digest
            != self.target_seed.table_owner_manifest_digest
        ):
            raise ValueError("ledger target identity differs from the selected seed")
        if self.ledger.quiescence_receipt_digest != self.quiescence.receipt_digest:
            raise ValueError("ledger does not bind the exact quiescence receipt")
        if self.ledger.unsettled_effect_set_digest != (
            self.quiescence.unsettled_effect_set_digest
        ):
            raise ValueError("ledger unsettled-effect closure differs from quiescence")
        if tuple(self.ledger.backups) != tuple(self.backup_set.receipts):
            raise ValueError("ledger backup set differs from independent verification")
        mappings = tuple(
            sorted(self.authority_mappings, key=lambda item: item.lease.lease_id)
        )
        adoptions = tuple(
            sorted(self.session_adoptions, key=lambda item: item.pin.session_id)
        )
        if len({item.lease.lease_id for item in mappings}) != len(mappings):
            raise ValueError("authority mapping identities must be unique")
        if len({item.pin.session_id for item in adoptions}) != len(adoptions):
            raise ValueError("Session adoption identities must be unique")
        object.__setattr__(self, "authority_mappings", mappings)
        object.__setattr__(self, "session_adoptions", adoptions)
        if self.ledger.authority_mapping_set_digest != canonical_sha256_digest(
            [item.mapping_digest for item in mappings]
        ):
            raise ValueError("ledger authority mapping closure drifted")
        if self.ledger.inventory_binding_set_digest != canonical_sha256_digest(
            [item.initial_binding.binding_digest for item in adoptions]
        ):
            raise ValueError("ledger capability binding closure drifted")
        migrated = {
            item.session_id: item
            for item in self.ledger.session_dispositions
            if item.disposition is SessionCutoverDispositionKind.MIGRATED_AT2
        }
        if set(migrated) != {item.pin.session_id for item in adoptions}:
            raise ValueError("ledger migrated Session set differs from adoptions")
        for adoption in adoptions:
            disposition = migrated[adoption.pin.session_id]
            if (
                adoption.pin.deployment_epoch_id
                != self.target_seed.activation_epoch.epoch_id
                or adoption.pin.deployment_activation_digest
                != self.target_seed.activation_epoch.activation_digest
                or adoption.pin.release_identity
                != self.target_seed.activation_epoch.release_identity
                or disposition.composition_pin_digest != adoption.pin.pin_digest
                or disposition.capability_binding_digest
                != adoption.initial_binding.binding_digest
            ):
                raise ValueError("Session adoption differs from target epoch or ledger")
        _require_ledger_item_closure(self)


@dataclass(frozen=True, slots=True)
class OfflineCutoverDeploymentProof:
    schema: CompositeSQLiteStartupProof
    session_composition: SessionCompositionStateProof
    ledger_digest: str
    deployment_state_digest: str
    authority_mapping_set_digest: str
    mutation_applied: bool = False
    plugin_import_performed: bool = False
    writer_enabled: bool = False

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_offline_cutover_deployment_proof@2",
                "schema_proof_digest": self.schema.proof_digest,
                "session_composition_proof_digest": (
                    self.session_composition.proof_digest
                ),
                "ledger_digest": self.ledger_digest,
                "deployment_state_digest": self.deployment_state_digest,
                "authority_mapping_set_digest": self.authority_mapping_set_digest,
                "mutation_applied": self.mutation_applied,
                "plugin_import_performed": self.plugin_import_performed,
                "writer_enabled": self.writer_enabled,
            }
        )


def apply_offline_cutover_transaction(
    connection: sqlite3.Connection,
    *,
    plan: OfflineCutoverApplicationPlan,
) -> OfflineCutoverDeploymentProof:
    """Commit target identities, adoption rows and complete ledger atomically."""

    if connection.in_transaction:
        raise _error("offline cutover requires no active transaction", "admission")
    current = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=plan.target_seed.owner_schema_profile,
    )
    if current.proof_digest != plan.target_seed.schema_proof.proof_digest:
        raise _error(
            "offline target schema proof became stale",
            "schema_identity",
            expected=plan.target_seed.schema_proof.proof_digest,
            observed=current.proof_digest,
        )
    _require_target_metadata_empty(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _verify_authority_mappings(connection, plan.authority_mappings)
        _insert_composition_rows(connection, plan.target_seed)
        _insert_session_adoptions(connection, plan.session_adoptions)
        _insert_cutover_ledger(connection, plan)
        _insert_deployment_state(connection, plan)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return verify_offline_cutover_deployment_read_only(connection, plan=plan)


def verify_offline_cutover_deployment_read_only(
    connection: sqlite3.Connection,
    *,
    plan: OfflineCutoverApplicationPlan,
) -> OfflineCutoverDeploymentProof:
    initial_changes = connection.total_changes
    initial_transaction = connection.in_transaction
    try:
        schema = verify_composite_store_schema_read_only(
            connection,
            expectation=plan.target_seed.startup_expectation,
            owner_schema_profile=plan.target_seed.owner_schema_profile,
        )
        sessions = verify_session_composition_state_read_only(
            connection,
            activation_epoch=plan.target_seed.activation_epoch,
        )
        _verify_authority_mappings(connection, plan.authority_mappings)
        ledger_rows = connection.execute(
            "SELECT ledger_json FROM openzyme_store_offline_cutover_ledgers "
            "WHERE ledger_id = ? AND ledger_digest = ? AND state = 'complete'",
            (plan.ledger.ledger_id, plan.ledger.ledger_digest),
        ).fetchall()
        if len(ledger_rows) != 1 or _json_object(ledger_rows[0][0]) != plan.ledger.payload:
            raise _error(
                "offline cutover ledger is absent or drifted",
                "ledger_readback",
                expected=plan.ledger.ledger_digest,
                observed=len(ledger_rows),
            )
        _verify_child_rows(connection, plan)
        state_payload = _deployment_state_payload(plan)
        state_digest = canonical_sha256_digest(state_payload)
        row = connection.execute(
            "SELECT * FROM openzyme_store_deployment_schema_state"
        ).fetchone()
        columns = tuple(
            str(item[1])
            for item in connection.execute(
                "PRAGMA table_info(openzyme_store_deployment_schema_state)"
            ).fetchall()
        )
        observed = None if row is None else dict(zip(columns, row, strict=True))
        expected = {"singleton": 1, **state_payload, "state_digest": state_digest}
        if observed != expected:
            raise _error(
                "offline deployment state is absent or drifted",
                "deployment_state",
                expected=expected,
                observed=observed,
            )
        return OfflineCutoverDeploymentProof(
            schema=schema,
            session_composition=sessions,
            ledger_digest=plan.ledger.ledger_digest,
            deployment_state_digest=state_digest,
            authority_mapping_set_digest=plan.ledger.authority_mapping_set_digest,
        )
    finally:
        if (
            connection.total_changes != initial_changes
            or connection.in_transaction != initial_transaction
        ):
            raise RuntimeError("offline cutover verifier violated zero-mutation")


def _require_ledger_item_closure(plan: OfflineCutoverApplicationPlan) -> None:
    by_kind = {
        kind: {item.item_id for item in plan.ledger.items if item.item_kind is kind}
        for kind in OfflineCutoverItemKind
    }
    if by_kind[OfflineCutoverItemKind.AUTHORITY] != {
        item.lease.lease_id for item in plan.authority_mappings
    }:
        raise ValueError("ledger authority items differ from mapped lease rows")
    if by_kind[OfflineCutoverItemKind.SESSION] != {
        item.session_id for item in plan.ledger.session_dispositions
    }:
        raise ValueError("ledger Session items differ from Session dispositions")
    if any(
        item.observed_disposition is not item.expected_disposition
        or item.observed_disposition is OfflineCutoverDisposition.BLOCKED
        or item.error_code is not None
        for item in plan.ledger.items
    ):
        raise ValueError("ledger item closure is not complete")


def _require_target_metadata_empty(connection: sqlite3.Connection) -> None:
    tables = (
        "openzyme_store_deployment_activation_epochs",
        "openzyme_store_fresh_install_receipts",
        "openzyme_store_offline_cutover_ledgers",
        "openzyme_store_extension_bundle_records",
        "openzyme_store_catalog_identity_records",
        "openzyme_store_session_composition_pins",
        "openzyme_store_session_capability_binding_revisions",
        "openzyme_store_deployment_schema_state",
    )
    nonempty = {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
        if int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    }
    if nonempty:
        raise _error(
            "offline cutover refuses partially activated target metadata",
            "target_metadata_empty",
            expected={},
            observed=nonempty,
        )


def _verify_authority_mappings(
    connection: sqlite3.Connection,
    expected: tuple[AgentAuthorityStoreMappingReceipt, ...],
) -> None:
    observed = []
    selected_columns = ", ".join(LEGACY_AUTHORITY_PHYSICAL_COLUMNS)
    for row in connection.execute(
        f"""
        SELECT {selected_columns}
        FROM agent_capability_lease_records
        WHERE record_kind = 'legacy_capability_lease'
        ORDER BY lease_id
        """
    ).fetchall():
        observed.append(
            map_legacy_agent_capability_lease_row(
                dict(zip(LEGACY_AUTHORITY_PHYSICAL_COLUMNS, row, strict=True))
            )
        )
    if tuple(observed) != tuple(expected):
        raise _error(
            "legacy authority rows differ from the exact public mapping set",
            "authority_mapping",
            expected=[item.mapping_digest for item in expected],
            observed=[item.mapping_digest for item in observed],
        )


def _insert_composition_rows(
    connection: sqlite3.Connection,
    seed: FreshInstallCompositionSeed,
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
    connection.execute(
        "INSERT INTO openzyme_store_extension_bundle_records VALUES (?, ?, ?, ?)",
        (
            canonical_sha256_digest(payloads["extension_bundle"]),
            _json(payloads["extension_bundle"]),
            epoch.epoch_id,
            epoch.activated_at,
        ),
    )
    for kind, payload in seed.catalog_payloads:
        connection.execute(
            "INSERT INTO openzyme_store_catalog_identity_records VALUES (?, ?, ?, ?, ?)",
            (
                kind,
                canonical_sha256_digest(payload),
                epoch.epoch_id,
                _json(payload),
                epoch.activated_at,
            ),
        )


def _insert_session_adoptions(
    connection: sqlite3.Connection,
    adoptions: tuple[OfflineSessionAdoption, ...],
) -> None:
    for adoption in adoptions:
        pin = adoption.pin
        binding = adoption.initial_binding
        if connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_id = ?",
            (pin.session_id,),
        ).fetchone()[0] != 1:
            raise _error(
                "Session adoption source row is absent",
                "session_adoption_source",
                expected=pin.session_id,
                observed=None,
            )
        connection.execute(
            """
            INSERT INTO openzyme_store_session_capability_binding_revisions (
                binding_id, session_id, revision, extension_bundle_digest,
                route_catalog_digest, binding_digest, binding_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding.binding_id,
                binding.session_id,
                binding.revision,
                binding.extension_bundle_digest,
                binding.route_catalog_digest,
                binding.binding_digest,
                _json(binding.to_dict()),
                binding.created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO openzyme_store_session_composition_pins (
                pin_id, session_id, deployment_epoch_id,
                deployment_activation_digest, distribution_id,
                composition_bundle_digest, release_digest, pin_digest,
                pin_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pin.pin_id,
                pin.session_id,
                pin.deployment_epoch_id,
                pin.deployment_activation_digest,
                pin.distribution_id,
                pin.composition_bundle_digest,
                pin.release_identity.release_digest,
                pin.pin_digest,
                _json(pin.to_dict()),
                pin.created_at,
            ),
        )


def _insert_cutover_ledger(
    connection: sqlite3.Connection,
    plan: OfflineCutoverApplicationPlan,
) -> None:
    for backup in plan.ledger.backups:
        connection.execute(
            "INSERT INTO openzyme_store_offline_backup_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                backup.backup_id,
                backup.backup_kind.value,
                backup.source_identity_digest,
                backup.backup_identity_digest,
                backup.verification_digest,
                int(backup.recoverable),
                _json(backup.payload),
                backup.verified_at,
            ),
        )
    payload = plan.ledger.payload
    master_columns = tuple(
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(openzyme_store_offline_cutover_ledgers)"
        ).fetchall()
    )
    master = {
        "ledger_id": plan.ledger.ledger_id,
        **{name: payload[name] for name in master_columns if name in payload},
        "ledger_digest": plan.ledger.ledger_digest,
        "ledger_json": _json(payload),
    }
    connection.execute(
        f"INSERT INTO openzyme_store_offline_cutover_ledgers "
        f"({', '.join(master_columns)}) VALUES "
        f"({', '.join('?' for _ in master_columns)})",
        tuple(master[name] for name in master_columns),
    )
    for item in plan.ledger.items:
        connection.execute(
            "INSERT INTO openzyme_store_offline_cutover_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan.ledger.ledger_id,
                item.item_kind.value,
                item.item_id,
                item.expected_disposition.value,
                item.observed_disposition.value,
                item.item_digest,
                item.error_code,
                _json(item.payload),
            ),
        )
    for item in plan.ledger.session_dispositions:
        connection.execute(
            "INSERT INTO openzyme_store_session_cutover_dispositions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.session_id,
                plan.ledger.ledger_id,
                item.disposition.value,
                item.composition_pin_digest,
                item.capability_binding_digest,
                item.disposition_digest,
                _json(item.payload),
            ),
        )


def _deployment_state_payload(
    plan: OfflineCutoverApplicationPlan,
) -> dict[str, object]:
    seed = plan.target_seed
    release = seed.activation_epoch.release_identity
    return {
        "schema_generation": seed.schema_proof.store_schema.schema_generation,
        "schema_manifest_digest": seed.schema_proof.complete_schema_manifest_digest,
        "proof_variant": DeploymentProofVariant.OFFLINE_REMOVAL_COMPLETE.value,
        "proof_receipt_digest": plan.ledger.ledger_digest,
        "deployment_epoch_id": seed.activation_epoch.epoch_id,
        "deployment_activation_digest": seed.activation_epoch.activation_digest,
        **{field: getattr(release, field) for field in release.__dataclass_fields__},
        "installed_wheel_set_digest": seed.installed_wheel_set_digest,
        "table_owner_manifest_digest": seed.table_owner_manifest_digest,
    }


def _insert_deployment_state(
    connection: sqlite3.Connection,
    plan: OfflineCutoverApplicationPlan,
) -> None:
    payload = _deployment_state_payload(plan)
    columns = tuple(payload)
    connection.execute(
        "INSERT INTO openzyme_store_deployment_schema_state "
        f"(singleton, {', '.join(columns)}, state_digest) VALUES "
        f"({', '.join('?' for _ in range(len(columns) + 2))})",
        (1, *(payload[name] for name in columns), canonical_sha256_digest(payload)),
    )


def _verify_child_rows(
    connection: sqlite3.Connection,
    plan: OfflineCutoverApplicationPlan,
) -> None:
    expected = {
        "backup": len(plan.ledger.backups),
        "item": len(plan.ledger.items),
        "session": len(plan.ledger.session_dispositions),
    }
    observed = {
        "backup": int(
            connection.execute(
                "SELECT COUNT(*) FROM openzyme_store_offline_backup_receipts"
            ).fetchone()[0]
        ),
        "item": int(
            connection.execute(
                "SELECT COUNT(*) FROM openzyme_store_offline_cutover_items WHERE ledger_id = ?",
                (plan.ledger.ledger_id,),
            ).fetchone()[0]
        ),
        "session": int(
            connection.execute(
                "SELECT COUNT(*) FROM openzyme_store_session_cutover_dispositions WHERE ledger_id = ?",
                (plan.ledger.ledger_id,),
            ).fetchone()[0]
        ),
    }
    if observed != expected:
        raise _error(
            "offline cutover child-row closure drifted",
            "ledger_child_rows",
            expected=expected,
            observed=observed,
        )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _json_object(raw: object) -> dict[str, object]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise _error(
            "offline cutover JSON is invalid",
            "json_decode",
            observed=exc.__class__.__name__,
        ) from exc
    if not isinstance(value, dict):
        raise _error(
            "offline cutover JSON must be an object",
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
        operator_action=(
            "keep the old release frozen; restore exact backups only before @2 "
            "activation, otherwise quiesce and apply a forward repair"
        ),
    )


__all__ = [
    "OfflineCutoverApplicationPlan",
    "OfflineCutoverDeploymentProof",
    "OfflineSessionAdoption",
    "apply_offline_cutover_transaction",
    "verify_offline_cutover_deployment_read_only",
]
