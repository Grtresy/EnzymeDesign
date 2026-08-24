"""Explicit codecs from target Kernel records to existing business owner tables."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import sqlite3
from typing import Any

from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import EVIDENCE_REF_SCHEMA_VERSION
from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import FailureObservation
from openzyme_contracts import PublishedRevision
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import CommandToolExpansion
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import VerifiedWorkspaceCheckpoint
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import parse_failure_observation
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible

from .control_store import SQLiteControlStoreError
from .control_store import SQLiteKernelEntityCodec


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(
        json_compatible(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_json(value: object, *, code: str, subject: str) -> JsonValue:
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise SQLiteControlStoreError(
            code,
            f"{subject} contains invalid JSON",
            phase="entity_decode",
        ) from exc


def _require_target_payload(
    payload: Mapping[str, JsonValue],
    *,
    fields: tuple[str, ...],
    identity_field: str,
    entity_id: str,
    code: str,
    subject: str,
) -> None:
    if set(payload) != set(fields) or payload.get(identity_field) != entity_id:
        raise SQLiteControlStoreError(
            code,
            f"{subject} differs from its target closed contract or identity",
            phase="entity_encode",
        )


def _require_runtime_identifier(value: JsonValue, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise SQLiteControlStoreError(
            "sqlite_runtime_coordination_payload_invalid",
            f"Runtime coordination field {field_name} is not a valid identifier",
            phase="entity_encode",
        )
    try:
        require_identifier(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise SQLiteControlStoreError(
            "sqlite_runtime_coordination_payload_invalid",
            f"Runtime coordination field {field_name} is not a valid identifier",
            phase="entity_encode",
        ) from exc


def _require_runtime_digest(value: JsonValue, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise SQLiteControlStoreError(
            "sqlite_runtime_coordination_payload_invalid",
            f"Runtime coordination field {field_name} is not a valid digest",
            phase="entity_encode",
        )
    try:
        require_digest(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise SQLiteControlStoreError(
            "sqlite_runtime_coordination_payload_invalid",
            f"Runtime coordination field {field_name} is not a valid digest",
            phase="entity_encode",
        ) from exc


def _require_positive_runtime_integer(value: JsonValue, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SQLiteControlStoreError(
            "sqlite_runtime_coordination_payload_invalid",
            f"Runtime coordination field {field_name} must be positive",
            phase="entity_encode",
        )


class AgentAuthorityLeaseSQLiteKernelEntityCodec:
    """Maps public authority semantics onto the retained physical lease table."""

    entity_type = "agent_authority_lease"
    owner_id = "openzyme.kernel"
    table_names = (
        "agent_capability_lease_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT l.lease_id, l.session_id, l.agent_member_id,
                   l.authority_grants_json, l.authority_generation,
                   l.authority_fence, l.authority_state, l.issued_at,
                   l.authority_expires_at, l.agent_id, l.workspace_generation,
                   l.parent_lease_id, l.policy_digest, l.idempotency_key,
                   l.updated_at, l.authority_lease_digest,
                   l.authority_schema_version, l.record_kind,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM agent_capability_lease_records AS l
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'agent_authority_lease'
             AND v.entity_id = l.lease_id
            WHERE l.lease_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[17] != "agent_authority_lease":
            raise SQLiteControlStoreError(
                "sqlite_authority_lease_not_adopted",
                "Legacy capability lease row has not been adopted as target authority",
                phase="entity_decode",
            )
        if row[18] is None or row[20] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "AgentAuthorityLease row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        try:
            grants = json.loads(str(row[3]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_authority_grants_invalid",
                "AgentAuthorityLease grants are not valid JSON",
                phase="entity_decode",
            ) from exc
        payload: Mapping[str, JsonValue] = {
            "schema_version": row[16],
            "lease_id": row[0],
            "session_id": row[1],
            "agent_member_id": row[2],
            "grants": grants,
            "generation": row[4],
            "fence": row[5],
            "state": row[6],
            "issued_at": row[7],
            "expires_at": row[8],
            "agent_id": row[9],
            "workspace_generation": row[10],
            "parent_lease_id": row[11],
            "policy_digest": row[12],
            "idempotency_key": row[13],
            "updated_at": row[14],
            "lease_digest": row[15],
        }
        try:
            lease = AgentAuthorityLease.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_authority_lease_invalid",
                "AgentAuthorityLease owner row violates the public closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[18]),
            payload=lease.to_dict(),
        )
        if snapshot.record_digest != row[19]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "AgentAuthorityLease owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM agent_capability_lease_records WHERE lease_id = ?",
                (mutation.entity_id,),
            )
            return
        payload = self._payload(mutation)
        values = (
            payload["lease_id"],
            payload["session_id"],
            payload["agent_member_id"],
            payload["agent_id"],
            payload["workspace_generation"],
            payload["policy_digest"],
            payload["parent_lease_id"],
            payload["idempotency_key"],
            payload["issued_at"],
            payload["updated_at"],
            None,
            "agent_authority_lease",
            self._json(payload["grants"]),
            payload["generation"],
            payload["fence"],
            payload["state"],
            payload["expires_at"],
            payload["lease_digest"],
            payload["schema_version"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO agent_capability_lease_records
                (lease_id, session_id, agent_member_id, agent_id,
                 workspace_generation, policy_digest, parent_lease_id,
                 idempotency_key, issued_at, updated_at, schema_version,
                 record_kind, authority_grants_json, authority_generation,
                 authority_fence, authority_state, authority_expires_at,
                 authority_lease_digest, authority_schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE agent_capability_lease_records
            SET session_id = ?, agent_member_id = ?, agent_id = ?,
                workspace_generation = ?, policy_digest = ?, parent_lease_id = ?,
                idempotency_key = ?, issued_at = ?, updated_at = ?,
                schema_version = NULL, record_kind = 'agent_authority_lease',
                authority_grants_json = ?, authority_generation = ?,
                authority_fence = ?, authority_state = ?,
                authority_expires_at = ?, authority_lease_digest = ?,
                authority_schema_version = ?
            WHERE lease_id = ? AND record_kind = 'agent_authority_lease'
            """,
            (
                payload["session_id"],
                payload["agent_member_id"],
                payload["agent_id"],
                payload["workspace_generation"],
                payload["policy_digest"],
                payload["parent_lease_id"],
                payload["idempotency_key"],
                payload["issued_at"],
                payload["updated_at"],
                self._json(payload["grants"]),
                payload["generation"],
                payload["fence"],
                payload["state"],
                payload["expires_at"],
                payload["lease_digest"],
                payload["schema_version"],
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "AgentAuthorityLease target row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        try:
            lease = AgentAuthorityLease.from_dict(mutation.payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_authority_lease_invalid",
                "AgentAuthorityLease mutation violates the public closed contract",
                phase="entity_encode",
            ) from exc
        if lease.lease_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_authority_lease_identity_mismatch",
                "AgentAuthorityLease payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class SessionCapabilityBindingSQLiteKernelEntityCodec:
    """Maps immutable Session binding revisions to their dedicated owner table."""

    entity_type = "session_capability_binding_revision"
    owner_id = "openzyme.kernel"
    table_names = (
        "openzyme_store_session_capability_binding_revisions",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT b.binding_json, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM openzyme_store_session_capability_binding_revisions AS b
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'session_capability_binding_revision'
             AND v.entity_id = b.binding_id
            WHERE b.binding_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[1] is None or row[3] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Session capability binding lacks exact target CAS metadata",
                phase="entity_decode",
            )
        try:
            payload = json.loads(str(row[0]))
            binding = SessionCapabilityBindingRevision.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_session_capability_binding_invalid",
                "Session capability binding owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        if binding.binding_id != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_capability_binding_identity_mismatch",
                "Session capability binding owner identity drifted",
                phase="entity_decode",
            )
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[1]),
            payload=binding.to_dict(),
        )
        if snapshot.record_digest != row[2]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Session capability binding differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_session_capability_binding_immutable",
                "Session capability binding revisions are append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            binding = SessionCapabilityBindingRevision.from_dict(mutation.payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_session_capability_binding_invalid",
                "Session capability binding mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if binding.binding_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_capability_binding_identity_mismatch",
                "Session capability binding payload identity differs from its mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO openzyme_store_session_capability_binding_revisions
            (binding_id, session_id, revision, extension_bundle_digest,
             route_catalog_digest, binding_digest, binding_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding.binding_id,
                binding.session_id,
                binding.revision,
                binding.extension_bundle_digest,
                binding.route_catalog_digest,
                binding.binding_digest,
                self._json(binding.to_dict()),
                binding.created_at,
            ),
        )

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class SessionCompositionPinSQLiteKernelEntityCodec:
    """Maps the immutable per-Session Distribution pin to its owner table."""

    entity_type = "session_composition_pin"
    owner_id = "openzyme.kernel"
    table_names = (
        "openzyme_store_session_composition_pins",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT p.pin_json, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM openzyme_store_session_composition_pins AS p
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'session_composition_pin'
             AND v.entity_id = p.pin_id
            WHERE p.pin_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[1] is None or row[3] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Session composition pin lacks exact target CAS metadata",
                phase="entity_decode",
            )
        try:
            payload = json.loads(str(row[0]))
            pin = SessionCompositionPin.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_session_composition_pin_invalid",
                "Session composition pin owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        if pin.pin_id != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_composition_pin_identity_mismatch",
                "Session composition pin owner identity drifted",
                phase="entity_decode",
            )
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[1]),
            payload=pin.to_dict(),
        )
        if snapshot.record_digest != row[2]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Session composition pin differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_session_composition_pin_immutable",
                "Session composition pins are create-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            pin = SessionCompositionPin.from_dict(mutation.payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_session_composition_pin_invalid",
                "Session composition pin mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if pin.pin_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_composition_pin_identity_mismatch",
                "Session composition pin payload identity differs from its mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO openzyme_store_session_composition_pins
            (pin_id, session_id, deployment_epoch_id,
             deployment_activation_digest, distribution_id,
             composition_bundle_digest, release_digest, pin_digest,
             pin_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                self._json(pin.to_dict()),
                pin.created_at,
            ),
        )

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class AgentRuntimeSignalSQLiteKernelEntityCodec:
    """Maps one runtime-signal occurrence to its retained structured table."""

    entity_type = "agent_runtime_signal"
    owner_id = "openzyme.kernel"
    table_names = ("agent_runtime_signals", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "signal_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "reason",
        "status",
        "created_at",
        "task_id",
        "lane_id",
        "correlation_id",
        "source_ref",
        "claimed_at",
        "claimed_by",
        "claim_token",
        "claim_expires_at",
        "attempt_count",
        "completed_at",
        "error_message",
        "last_error",
        "session_lease_token",
        "session_fencing_token",
        "runtime_lease_generation",
        "capability_lease_id",
        "capability_lease_digest",
        "workspace_generation",
        "process_epoch",
        "enqueue_command_digest",
        "claim_command_digest",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT s.signal_id, s.session_id, s.agent_id, s.agent_member_id,
                   s.reason, s.status, s.created_at, s.task_id, s.lane_id,
                   s.correlation_id, s.source_ref, s.claimed_at, s.claimed_by,
                   s.claim_token, s.claim_expires_at, s.attempt_count,
                   s.completed_at, s.error_message, s.last_error,
                   s.session_lease_token, s.session_fencing_token,
                   s.runtime_lease_generation, s.capability_lease_id,
                   s.capability_lease_digest, s.workspace_generation,
                   s.process_epoch, s.enqueue_command_digest,
                   s.claim_command_digest, s.record_kind,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM agent_runtime_signals AS s
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'agent_runtime_signal'
             AND v.entity_id = s.signal_id
            WHERE s.signal_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[28] != "kernel_runtime_signal":
            raise SQLiteControlStoreError(
                "sqlite_runtime_signal_not_adopted",
                "Legacy runtime signal has not been adopted as target Kernel state",
                phase="entity_decode",
            )
        if row[29] is None or row[31] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "AgentRuntimeSignal row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[29]),
            payload=payload,
        )
        if snapshot.record_digest != row[30]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "AgentRuntimeSignal owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM agent_runtime_signals WHERE signal_id = ?",
                (mutation.entity_id,),
            )
            return
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        values = tuple(payload[field] for field in self._FIELDS)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO agent_runtime_signals
                (signal_id, session_id, agent_id, agent_member_id, reason,
                 status, created_at, task_id, lane_id, correlation_id,
                 source_ref, claimed_at, claimed_by, claim_token,
                 claim_expires_at, attempt_count, completed_at, error_message,
                 last_error, session_lease_token, session_fencing_token,
                 runtime_lease_generation, capability_lease_id,
                 capability_lease_digest, workspace_generation, process_epoch,
                 enqueue_command_digest, claim_command_digest, record_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'kernel_runtime_signal')
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE agent_runtime_signals
            SET session_id = ?, agent_id = ?, agent_member_id = ?, reason = ?,
                status = ?, created_at = ?, task_id = ?, lane_id = ?,
                correlation_id = ?, source_ref = ?, claimed_at = ?,
                claimed_by = ?, claim_token = ?, claim_expires_at = ?,
                attempt_count = ?, completed_at = ?, error_message = ?,
                last_error = ?, session_lease_token = ?,
                session_fencing_token = ?, runtime_lease_generation = ?,
                capability_lease_id = ?, capability_lease_digest = ?,
                workspace_generation = ?, process_epoch = ?,
                enqueue_command_digest = ?, claim_command_digest = ?
            WHERE signal_id = ? AND record_kind = 'kernel_runtime_signal'
            """,
            (*values[1:], mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "AgentRuntimeSignal target row disappeared before replacement",
                phase="entity_apply",
            )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        if set(payload) != set(cls._FIELDS) or payload.get("signal_id") != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_runtime_signal_payload_invalid",
                "AgentRuntimeSignal payload differs from its target closed contract",
                phase="entity_encode",
            )
        if payload["status"] not in {
            "pending",
            "claimed",
            "completed",
            "failed",
            "cancelled",
        }:
            raise SQLiteControlStoreError(
                "sqlite_runtime_signal_payload_invalid",
                "AgentRuntimeSignal status is invalid",
                phase="entity_encode",
            )
        for field_name in ("workspace_generation", "process_epoch"):
            value = payload[field_name]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise SQLiteControlStoreError(
                    "sqlite_runtime_signal_payload_invalid",
                    f"AgentRuntimeSignal {field_name} must be positive",
                    phase="entity_encode",
                )
        attempt_count = payload["attempt_count"]
        if (
            not isinstance(attempt_count, int)
            or isinstance(attempt_count, bool)
            or attempt_count < 0
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_signal_payload_invalid",
                "AgentRuntimeSignal attempt_count must be non-negative",
                phase="entity_encode",
            )
        if payload["status"] == "claimed" and any(
            payload[field_name] is None
            for field_name in (
                "claimed_at",
                "claimed_by",
                "claim_token",
                "claim_expires_at",
                "session_lease_token",
                "session_fencing_token",
                "runtime_lease_generation",
                "claim_command_digest",
            )
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_signal_claim_invalid",
                "Claimed AgentRuntimeSignal lacks its exact lease identity",
                phase="entity_encode",
            )


class RuntimeCommandSQLiteKernelEntityCodec:
    """Persists the durable bounded scheduler command independently of turns."""

    entity_type = "runtime_command"
    owner_id = "openzyme.kernel"
    table_names = ("runtime_command_records", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "schema_version",
        "command_id",
        "session_id",
        "command_type",
        "request_digest",
        "idempotency_key",
        "status",
        "max_signals",
        "max_steps_per_agent",
        "auto_enqueue_ready_tasks",
        "state_version",
        "fencing_token",
        "accepted_at",
        "claim_owner",
        "lease_token",
        "lease_expires_at",
        "bounded_outcome_summary",
        "failure_id",
        "diagnostic_id",
        "error_code",
        "safe_error_summary",
        "safe_retry_hint",
        "started_at",
        "completed_at",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT r.schema_version, r.command_id, r.session_id, r.command_type,
                   r.request_digest, r.idempotency_key, r.status, r.max_signals,
                   r.max_steps_per_agent, r.auto_enqueue_ready_tasks,
                   r.state_version, r.fencing_token, r.accepted_at,
                   r.claim_owner, r.lease_token, r.lease_expires_at,
                   r.bounded_outcome_summary_json, r.failure_id,
                   r.diagnostic_id, r.error_code, r.safe_error_summary,
                   r.safe_retry_hint, r.started_at, r.completed_at,
                   v.state_version, v.record_digest,
                   v.owner_component_id
            FROM runtime_command_records AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'runtime_command'
             AND v.entity_id = r.command_id
            WHERE r.command_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[24] is None or row[26] != self.owner_id or row[24] != row[10]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "RuntimeCommand row lacks matching target CAS metadata",
                phase="entity_decode",
            )
        summary = (
            None
            if row[16] is None
            else _decode_json(
                row[16],
                code="sqlite_runtime_command_json_invalid",
                subject="RuntimeCommand outcome summary",
            )
        )
        payload: dict[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        payload["auto_enqueue_ready_tasks"] = bool(row[9])
        payload["bounded_outcome_summary"] = summary
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[24]),
            payload=payload,
        )
        if snapshot.record_digest != row[25]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "RuntimeCommand differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_immutable",
                "RuntimeCommand records cannot be deleted",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        if payload["state_version"] != next_state_version:
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_state_version_mismatch",
                "RuntimeCommand payload version differs from its CAS transition",
                phase="entity_encode",
            )
        summary_json = (
            None
            if payload["bounded_outcome_summary"] is None
            else _canonical_json(payload["bounded_outcome_summary"])
        )
        values = (
            payload["command_id"],
            payload["session_id"],
            payload["schema_version"],
            payload["command_type"],
            payload["request_digest"],
            payload["idempotency_key"],
            payload["status"],
            payload["max_signals"],
            payload["max_steps_per_agent"],
            int(payload["auto_enqueue_ready_tasks"] is True),
            payload["claim_owner"],
            payload["lease_token"],
            payload["lease_expires_at"],
            payload["fencing_token"],
            payload["state_version"],
            summary_json,
            payload["failure_id"],
            payload["diagnostic_id"],
            payload["error_code"],
            payload["safe_error_summary"],
            payload["safe_retry_hint"],
            payload["accepted_at"],
            payload["started_at"],
            payload["completed_at"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            if payload["status"] != "accepted" or payload["state_version"] != 1:
                raise SQLiteControlStoreError(
                    "sqlite_runtime_command_lifecycle_invalid",
                    "RuntimeCommand must be created in accepted version 1",
                    phase="entity_encode",
                )
            connection.execute(
                """
                INSERT INTO runtime_command_records
                (command_id, session_id, schema_version, command_type,
                 request_digest, idempotency_key, status, max_signals,
                 max_steps_per_agent, auto_enqueue_ready_tasks, claim_owner,
                 lease_token, lease_expires_at, fencing_token, state_version,
                 bounded_outcome_summary_json, failure_id, diagnostic_id,
                 error_code, safe_error_summary, safe_retry_hint, accepted_at,
                 started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        previous = connection.execute(
            """
            SELECT session_id, command_type, request_digest, idempotency_key,
                   max_signals, max_steps_per_agent, auto_enqueue_ready_tasks,
                   status, state_version, fencing_token, accepted_at
            FROM runtime_command_records WHERE command_id = ?
            """,
            (mutation.entity_id,),
        ).fetchone()
        if previous is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "RuntimeCommand target row disappeared before replacement",
                phase="entity_apply",
            )
        immutable = (
            payload["session_id"],
            payload["command_type"],
            payload["request_digest"],
            payload["idempotency_key"],
            payload["max_signals"],
            payload["max_steps_per_agent"],
            int(payload["auto_enqueue_ready_tasks"] is True),
        )
        if immutable != previous[:7] or payload["accepted_at"] != previous[10]:
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_identity_drift",
                "RuntimeCommand immutable request identity changed",
                phase="entity_encode",
            )
        allowed = {
            "accepted": {"claimed", "cancelled", "locked"},
            "claimed": {"claimed", "completed", "failed", "locked", "cancelled"},
        }
        if payload["status"] not in allowed.get(str(previous[7]), set()):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_lifecycle_invalid",
                "RuntimeCommand lifecycle transition is invalid",
                phase="entity_encode",
            )
        if payload["state_version"] != int(previous[8]) + 1:
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_state_version_mismatch",
                "RuntimeCommand state version must advance exactly once",
                phase="entity_encode",
            )
        if payload["fencing_token"] < int(previous[9]):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_fence_stale",
                "RuntimeCommand fencing token cannot move backwards",
                phase="entity_encode",
            )
        if payload["status"] == "failed":
            pair = connection.execute(
                """
                SELECT f.failure_id, f.diagnostic_id, f.session_id,
                       d.diagnostic_id, d.failure_id, d.session_id
                FROM failure_observation_records AS f
                JOIN private_diagnostic_records AS d
                  ON d.diagnostic_id = f.diagnostic_id
                 AND d.failure_id = f.failure_id
                WHERE f.failure_id = ? AND d.diagnostic_id = ?
                """,
                (payload["failure_id"], payload["diagnostic_id"]),
            ).fetchone()
            if pair != (
                payload["failure_id"],
                payload["diagnostic_id"],
                payload["session_id"],
                payload["diagnostic_id"],
                payload["failure_id"],
                payload["session_id"],
            ):
                raise SQLiteControlStoreError(
                    "sqlite_runtime_command_failure_pair_invalid",
                    "Failed RuntimeCommand does not resolve its exact diagnostic pair",
                    phase="entity_encode",
                )
        connection.execute(
            """
            UPDATE runtime_command_records
            SET status = ?, claim_owner = ?, lease_token = ?,
                lease_expires_at = ?, fencing_token = ?, state_version = ?,
                bounded_outcome_summary_json = ?, error_code = ?,
                failure_id = ?, diagnostic_id = ?, safe_error_summary = ?,
                safe_retry_hint = ?, started_at = ?, completed_at = ?
            WHERE command_id = ?
            """,
            (
                payload["status"],
                payload["claim_owner"],
                payload["lease_token"],
                payload["lease_expires_at"],
                payload["fencing_token"],
                payload["state_version"],
                summary_json,
                payload["error_code"],
                payload["failure_id"],
                payload["diagnostic_id"],
                payload["safe_error_summary"],
                payload["safe_retry_hint"],
                payload["started_at"],
                payload["completed_at"],
                mutation.entity_id,
            ),
        )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        if set(payload) != set(cls._FIELDS) or payload.get("command_id") != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_payload_invalid",
                "RuntimeCommand differs from its closed contract or identity",
                phase="entity_encode",
            )
        if (
            payload["schema_version"] != "runtime_command@1"
            or payload["command_type"] != "runtime.drain"
            or payload["status"]
            not in {"accepted", "claimed", "completed", "failed", "locked", "cancelled"}
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_payload_invalid",
                "RuntimeCommand schema, type, or status is invalid",
                phase="entity_encode",
            )
        for field_name in (
            "command_id",
            "session_id",
            "idempotency_key",
            "accepted_at",
        ):
            _require_runtime_identifier(payload[field_name], field_name=field_name)
        _require_runtime_digest(payload["request_digest"], field_name="request_digest")
        for field_name in ("max_signals", "max_steps_per_agent", "state_version"):
            _require_positive_runtime_integer(
                payload[field_name], field_name=field_name
            )
        fence = payload["fencing_token"]
        if not isinstance(fence, int) or isinstance(fence, bool) or fence < 0:
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_payload_invalid",
                "RuntimeCommand fencing_token must be non-negative",
                phase="entity_encode",
            )
        if not isinstance(payload["auto_enqueue_ready_tasks"], bool):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_payload_invalid",
                "RuntimeCommand auto-enqueue fact must be boolean",
                phase="entity_encode",
            )
        for field_name in (
            "claim_owner",
            "lease_token",
            "lease_expires_at",
            "failure_id",
            "diagnostic_id",
            "error_code",
            "started_at",
            "completed_at",
        ):
            if payload[field_name] is not None:
                _require_runtime_identifier(payload[field_name], field_name=field_name)
        if payload["bounded_outcome_summary"] is not None and not isinstance(
            payload["bounded_outcome_summary"], Mapping
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_payload_invalid",
                "RuntimeCommand outcome summary must be an object or null",
                phase="entity_encode",
            )
        if payload["status"] == "claimed" and any(
            payload[field] is None
            for field in (
                "claim_owner",
                "lease_token",
                "lease_expires_at",
                "started_at",
            )
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_claim_invalid",
                "Claimed RuntimeCommand lacks its exact claim identity",
                phase="entity_encode",
            )
        if (
            payload["status"] in {"completed", "failed", "locked", "cancelled"}
            and payload["completed_at"] is None
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_terminal_invalid",
                "Terminal RuntimeCommand lacks completed_at",
                phase="entity_encode",
            )
        failure_pair = (payload["failure_id"], payload["diagnostic_id"])
        if payload["status"] == "failed":
            if any(value is None for value in failure_pair):
                raise SQLiteControlStoreError(
                    "sqlite_runtime_command_failure_pair_invalid",
                    "Failed RuntimeCommand requires failure and diagnostic identities",
                    phase="entity_encode",
                )
        elif any(value is not None for value in failure_pair):
            raise SQLiteControlStoreError(
                "sqlite_runtime_command_failure_pair_invalid",
                "Only failed RuntimeCommand may carry failure identities",
                phase="entity_encode",
            )


class ApprovalRequestSQLiteKernelEntityCodec:
    """Maps target ApprovalRequest state onto the retained approval table."""

    entity_type = "approval_request"
    owner_id = "openzyme.kernel"
    table_names = ("approval_requests", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "approval_id",
        "session_id",
        "requester_actor_id",
        "intent_digest",
        "workflow_authority_id",
        "workflow_authority_epoch",
        "workflow_authority_digest",
        "requested_action",
        "scope_id",
        "task_id",
        "reason",
        "status",
        "created_at",
        "expires_at",
        "resolved_at",
        "resolver_actor_id",
        "resolution_ref",
        "operation_dispatched",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT a.approval_id, a.session_id, a.requester_actor_id,
                   a.intent_digest, a.workflow_authority_id,
                   a.workflow_authority_epoch, a.workflow_authority_digest,
                   a.requested_action, a.scope_id, a.task_id, a.reason,
                   a.status, a.created_at, a.expires_at, a.resolved_at,
                   a.resolver_actor_id, a.resolution_ref,
                   a.operation_dispatched, a.record_kind,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM approval_requests AS a
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'approval_request'
             AND v.entity_id = a.approval_id
            WHERE a.approval_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[18] != "kernel_approval_request":
            raise SQLiteControlStoreError(
                "sqlite_approval_request_not_adopted",
                "Legacy approval row has not been adopted as target Kernel authority",
                phase="entity_decode",
            )
        if row[19] is None or row[21] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "ApprovalRequest row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        payload["operation_dispatched"] = bool(row[17])
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[19]),
            payload=payload,
        )
        if snapshot.record_digest != row[20]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "ApprovalRequest owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM approval_requests WHERE approval_id = ?",
                (mutation.entity_id,),
            )
            return
        assert mutation.payload is not None
        payload = dict(mutation.payload)
        self._validate_payload(payload, entity_id=mutation.entity_id)
        authority_row = connection.execute(
            "SELECT status, epoch, binding_digest "
            "FROM workflow_authority_binding_records WHERE authority_id = ?",
            (payload["workflow_authority_id"],),
        ).fetchone()
        if authority_row != (
            WorkflowAuthorityStatus.ACTIVE.value,
            payload["workflow_authority_epoch"],
            payload["workflow_authority_digest"],
        ):
            raise SQLiteControlStoreError(
                "sqlite_workflow_authority_epoch_stale",
                "ApprovalRequest does not bind a current workflow authority",
                phase="entity_encode",
            )
        values = (
            payload["approval_id"],
            payload["session_id"],
            payload["task_id"],
            "kernel_authority",
            payload["requested_action"],
            payload["status"],
            payload["resolution_ref"],
            payload["created_at"],
            payload["resolved_at"],
            "kernel_approval_request",
            payload["requester_actor_id"],
            payload["intent_digest"],
            payload["workflow_authority_id"],
            payload["workflow_authority_epoch"],
            payload["workflow_authority_digest"],
            payload["scope_id"],
            payload["reason"],
            payload["expires_at"],
            payload["resolver_actor_id"],
            int(payload["operation_dispatched"] is True),
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO approval_requests
                (approval_id, session_id, task_id, kind, requested_action,
                 status, resolution_ref, created_at, resolved_at, record_kind,
                 requester_actor_id, intent_digest, workflow_authority_id,
                 workflow_authority_epoch, workflow_authority_digest,
                 scope_id, reason, expires_at, resolver_actor_id,
                 operation_dispatched)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE approval_requests
            SET session_id = ?, task_id = ?, kind = 'kernel_authority',
                requested_action = ?, status = ?, request_ref = NULL,
                resolution_ref = ?, created_at = ?, resolved_at = ?,
                requester_actor_id = ?, intent_digest = ?,
                workflow_authority_id = ?, workflow_authority_epoch = ?,
                workflow_authority_digest = ?, scope_id = ?, reason = ?,
                expires_at = ?, resolver_actor_id = ?,
                operation_dispatched = ?
            WHERE approval_id = ? AND record_kind = 'kernel_approval_request'
            """,
            (
                payload["session_id"],
                payload["task_id"],
                payload["requested_action"],
                payload["status"],
                payload["resolution_ref"],
                payload["created_at"],
                payload["resolved_at"],
                payload["requester_actor_id"],
                payload["intent_digest"],
                payload["workflow_authority_id"],
                payload["workflow_authority_epoch"],
                payload["workflow_authority_digest"],
                payload["scope_id"],
                payload["reason"],
                payload["expires_at"],
                payload["resolver_actor_id"],
                int(payload["operation_dispatched"] is True),
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "ApprovalRequest target row disappeared before replacement",
                phase="entity_apply",
            )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        if set(payload) != set(cls._FIELDS):
            raise SQLiteControlStoreError(
                "sqlite_approval_request_payload_invalid",
                "ApprovalRequest payload differs from the target closed contract",
                phase="entity_encode",
            )
        if payload["approval_id"] != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_approval_request_identity_mismatch",
                "ApprovalRequest payload identity differs from its mutation",
                phase="entity_encode",
            )
        if payload["status"] not in {
            "pending",
            "approved",
            "rejected",
        } or not isinstance(payload["operation_dispatched"], bool):
            raise SQLiteControlStoreError(
                "sqlite_approval_request_payload_invalid",
                "ApprovalRequest status or dispatch fact is invalid",
                phase="entity_encode",
            )
        for field_name in ("workflow_authority_id",):
            _require_runtime_identifier(payload[field_name], field_name=field_name)
        _require_positive_runtime_integer(
            payload["workflow_authority_epoch"],
            field_name="workflow_authority_epoch",
        )
        _require_runtime_digest(
            payload["workflow_authority_digest"],
            field_name="workflow_authority_digest",
        )


class ContinuationSQLiteKernelEntityCodec:
    """Maps Kernel continuation delivery state to the retained continuation table."""

    entity_type = "continuation"
    owner_id = "openzyme.kernel"
    table_names = (
        "continuation_state_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "continuation_id",
        "session_id",
        "owner_actor_id",
        "source_version",
        "source_ref",
        "source_digest",
        "recipient_actor_id",
        "resume_strategy",
        "process_epoch",
        "state",
        "delivery_attempt",
        "delivery_receipt_digest",
        "failure_id",
        "error_code",
        "created_at",
        "updated_at",
        "task_transition_performed",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT c.continuation_id, c.session_id, c.owner_actor_id,
                   c.source_version, c.source_ref, c.source_digest,
                   c.recipient_actor_id, c.resume_strategy, c.process_epoch,
                   c.kernel_state, c.delivery_attempt,
                   c.delivery_receipt_digest, c.failure_id, c.error_code,
                   c.created_at, c.updated_at, c.task_transition_performed,
                   c.record_kind, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM continuation_state_records AS c
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'continuation'
             AND v.entity_id = c.continuation_id
            WHERE c.continuation_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[17] != "kernel_continuation":
            raise SQLiteControlStoreError(
                "sqlite_continuation_not_adopted",
                "Legacy continuation has not been adopted as target Kernel state",
                phase="entity_decode",
            )
        if row[18] is None or row[20] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Continuation row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        try:
            payload["source_version"] = int(row[3])
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_continuation_source_version_invalid",
                "Continuation source version is not an integer",
                phase="entity_decode",
            ) from exc
        payload["task_transition_performed"] = bool(row[16])
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[18]),
            payload=payload,
        )
        if snapshot.record_digest != row[19]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Continuation owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM continuation_state_records WHERE continuation_id = ?",
                (mutation.entity_id,),
            )
            return
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO continuation_state_records
                (continuation_id, session_id, record_kind, owner_actor_id,
                 source_version, source_ref, source_digest, recipient_actor_id,
                 resume_strategy, process_epoch, kernel_state,
                 delivery_attempt, delivery_receipt_digest, failure_id,
                 error_code, created_at, updated_at, task_transition_performed)
                VALUES (?, ?, 'kernel_continuation', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["continuation_id"],
                    payload["session_id"],
                    payload["owner_actor_id"],
                    payload["source_version"],
                    payload["source_ref"],
                    payload["source_digest"],
                    payload["recipient_actor_id"],
                    payload["resume_strategy"],
                    payload["process_epoch"],
                    payload["state"],
                    payload["delivery_attempt"],
                    payload["delivery_receipt_digest"],
                    payload["failure_id"],
                    payload["error_code"],
                    payload["created_at"],
                    payload["updated_at"],
                    int(payload["task_transition_performed"] is True),
                ),
            )
            return
        cursor = connection.execute(
            """
            UPDATE continuation_state_records
            SET session_id = ?, owner_actor_id = ?, source_version = ?,
                source_ref = ?, source_digest = ?, recipient_actor_id = ?,
                resume_strategy = ?, process_epoch = ?, kernel_state = ?,
                delivery_attempt = ?, delivery_receipt_digest = ?,
                failure_id = ?, error_code = ?, created_at = ?, updated_at = ?,
                task_transition_performed = ?
            WHERE continuation_id = ? AND record_kind = 'kernel_continuation'
            """,
            (
                payload["session_id"],
                payload["owner_actor_id"],
                payload["source_version"],
                payload["source_ref"],
                payload["source_digest"],
                payload["recipient_actor_id"],
                payload["resume_strategy"],
                payload["process_epoch"],
                payload["state"],
                payload["delivery_attempt"],
                payload["delivery_receipt_digest"],
                payload["failure_id"],
                payload["error_code"],
                payload["created_at"],
                payload["updated_at"],
                int(payload["task_transition_performed"] is True),
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Continuation target row disappeared before replacement",
                phase="entity_apply",
            )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        if (
            set(payload) != set(cls._FIELDS)
            or payload.get("continuation_id") != entity_id
        ):
            raise SQLiteControlStoreError(
                "sqlite_continuation_payload_invalid",
                "Continuation payload differs from its target closed contract",
                phase="entity_encode",
            )
        if payload["state"] not in {"ready", "delivered", "failed"}:
            raise SQLiteControlStoreError(
                "sqlite_continuation_payload_invalid",
                "Continuation state is invalid",
                phase="entity_encode",
            )
        attempt = payload["delivery_attempt"]
        if (
            not isinstance(payload["source_version"], int)
            or isinstance(payload["source_version"], bool)
            or payload["source_version"] < 1
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt < 0
            or payload["task_transition_performed"] is not False
        ):
            raise SQLiteControlStoreError(
                "sqlite_continuation_payload_invalid",
                "Continuation delivery attempt or Task-transition fact is invalid",
                phase="entity_encode",
            )


class ControlledOperationSQLiteKernelEntityCodec:
    """Maps the generic effect-certainty state machine to its retained owner table."""

    entity_type = "controlled_operation"
    owner_id = "openzyme.kernel"
    table_names = (
        "controlled_operation_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "session_id",
        "actor_id",
        "owner_plugin_id",
        "operation_id",
        "intent_digest",
        "route_id",
        "authority_lease_id",
        "authority_generation",
        "authority_fence",
        "authority_operation",
        "scope_id",
        "dispatch_generation",
        "state",
        "effect_certainty",
        "mutation_applied",
        "deadline",
        "approval_required",
        "approval_id",
        "cancel_intent_digest",
        "result_handle",
        "terminal_receipt_digest",
        "last_observation_digest",
        "error_code",
        "diagnostic_id",
        "created_at",
        "updated_at",
        "safe_intent",
        "fallback_performed",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT o.session_id, o.actor_id, o.owner_plugin_id, o.operation_id,
                   o.intent_digest, o.target_route_id, o.authority_lease_id,
                   o.authority_generation, o.authority_fence,
                   o.authority_operation, o.scope_id, o.dispatch_generation,
                   o.kernel_state, o.effect_certainty, o.mutation_applied,
                   o.deadline, o.approval_required, o.approval_id,
                   o.cancel_intent_digest, o.result_handle,
                   o.terminal_receipt_digest, o.last_observation_digest,
                   o.error_code, o.diagnostic_id, o.created_at, o.updated_at,
                   o.safe_intent_json, o.fallback_performed, o.record_kind,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM controlled_operation_records AS o
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'controlled_operation'
             AND v.entity_id = o.operation_id
            WHERE o.operation_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[28] != "kernel_controlled_operation":
            raise SQLiteControlStoreError(
                "sqlite_controlled_operation_not_adopted",
                "Legacy controlled operation has not been adopted as target Kernel state",
                phase="entity_decode",
            )
        if row[29] is None or row[31] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "ControlledOperation row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        try:
            payload: dict[str, JsonValue] = {
                field: row[index] for index, field in enumerate(self._FIELDS)
            }
            payload["mutation_applied"] = None if row[14] is None else bool(row[14])
            payload["approval_required"] = bool(row[16])
            payload["safe_intent"] = json.loads(str(row[26]))
            payload["fallback_performed"] = bool(row[27])
        except json.JSONDecodeError as exc:
            raise SQLiteControlStoreError(
                "sqlite_controlled_operation_json_invalid",
                "ControlledOperation safe intent is not valid JSON",
                phase="entity_decode",
            ) from exc
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[29]),
            payload=payload,
        )
        if snapshot.record_digest != row[30]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "ControlledOperation owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM controlled_operation_records WHERE operation_id = ?",
                (mutation.entity_id,),
            )
            return
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        values = self._values(payload)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO controlled_operation_records
                (session_id, actor_id, owner_plugin_id, operation_id,
                 intent_digest, target_route_id, authority_lease_id,
                 authority_generation, authority_fence, authority_operation,
                 scope_id, dispatch_generation, kernel_state,
                 effect_certainty, mutation_applied, deadline,
                 approval_required, approval_id, cancel_intent_digest,
                 result_handle, terminal_receipt_digest,
                 last_observation_digest, error_code, diagnostic_id,
                 created_at, updated_at, safe_intent_json,
                 fallback_performed, record_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'kernel_controlled_operation')
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE controlled_operation_records
            SET session_id = ?, actor_id = ?, owner_plugin_id = ?,
                intent_digest = ?, target_route_id = ?, authority_lease_id = ?,
                authority_generation = ?, authority_fence = ?,
                authority_operation = ?, scope_id = ?, dispatch_generation = ?,
                kernel_state = ?, effect_certainty = ?, mutation_applied = ?,
                deadline = ?, approval_required = ?, approval_id = ?,
                cancel_intent_digest = ?, result_handle = ?,
                terminal_receipt_digest = ?, last_observation_digest = ?,
                error_code = ?, diagnostic_id = ?, created_at = ?,
                updated_at = ?, safe_intent_json = ?, fallback_performed = ?
            WHERE operation_id = ?
              AND record_kind = 'kernel_controlled_operation'
            """,
            (*values[:3], *values[4:], mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "ControlledOperation target row disappeared before replacement",
                phase="entity_apply",
            )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        if set(payload) != set(cls._FIELDS) or payload.get("operation_id") != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_controlled_operation_payload_invalid",
                "ControlledOperation payload differs from its target closed contract",
                phase="entity_encode",
            )
        if payload["state"] not in {
            "admitted",
            "active",
            "reconcile_required",
            "settled",
            "cancel_requested",
            "cancelled",
        } or payload["effect_certainty"] not in {
            "no_effect",
            "dispatch_in_doubt",
            "effect_known",
            "terminal_known",
        }:
            raise SQLiteControlStoreError(
                "sqlite_controlled_operation_payload_invalid",
                "ControlledOperation state or effect certainty is invalid",
                phase="entity_encode",
            )
        for field_name in (
            "authority_generation",
            "authority_fence",
            "dispatch_generation",
        ):
            value = payload[field_name]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise SQLiteControlStoreError(
                    "sqlite_controlled_operation_payload_invalid",
                    f"ControlledOperation {field_name} must be positive",
                    phase="entity_encode",
                )
        if (
            not isinstance(payload["approval_required"], bool)
            or payload["fallback_performed"] is not False
        ):
            raise SQLiteControlStoreError(
                "sqlite_controlled_operation_payload_invalid",
                "ControlledOperation governance facts are invalid",
                phase="entity_encode",
            )
        certainty = payload["effect_certainty"]
        mutation_applied = payload["mutation_applied"]
        if (
            (certainty == "no_effect" and mutation_applied is not False)
            or (certainty == "dispatch_in_doubt" and mutation_applied is not None)
            or (
                certainty in {"effect_known", "terminal_known"}
                and not isinstance(mutation_applied, bool)
            )
        ):
            raise SQLiteControlStoreError(
                "sqlite_controlled_operation_effect_fact_invalid",
                "ControlledOperation effect certainty and mutation fact disagree",
                phase="entity_encode",
            )

    @staticmethod
    def _values(payload: Mapping[str, JsonValue]) -> tuple[object, ...]:
        return (
            payload["session_id"],
            payload["actor_id"],
            payload["owner_plugin_id"],
            payload["operation_id"],
            payload["intent_digest"],
            payload["route_id"],
            payload["authority_lease_id"],
            payload["authority_generation"],
            payload["authority_fence"],
            payload["authority_operation"],
            payload["scope_id"],
            payload["dispatch_generation"],
            payload["state"],
            payload["effect_certainty"],
            None
            if payload["mutation_applied"] is None
            else int(payload["mutation_applied"] is True),
            payload["deadline"],
            int(payload["approval_required"] is True),
            payload["approval_id"],
            payload["cancel_intent_digest"],
            payload["result_handle"],
            payload["terminal_receipt_digest"],
            payload["last_observation_digest"],
            payload["error_code"],
            payload["diagnostic_id"],
            payload["created_at"],
            payload["updated_at"],
            json.dumps(
                json_compatible(payload["safe_intent"]),
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            int(payload["fallback_performed"] is True),
        )


class SessionRuntimeLeaseSQLiteKernelEntityCodec:
    """Maps one current Session runtime lease to its retained lease table."""

    entity_type = "session_runtime_lease"
    owner_id = "openzyme.kernel"
    table_names = ("session_runtime_leases", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "session_id",
        "owner_id",
        "lease_token",
        "mode",
        "generation",
        "fencing_token",
        "acquired_at",
        "heartbeat_at",
        "expires_at",
        "released_at",
        "last_error",
        "acquire_command_digest",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT l.session_id, l.owner_id, l.lease_token, l.mode,
                   l.generation, l.fencing_token, l.acquired_at,
                   l.heartbeat_at, l.expires_at, l.released_at, l.last_error,
                   l.acquire_command_digest, l.record_kind,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM session_runtime_leases AS l
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'session_runtime_lease'
             AND v.entity_id = l.kernel_entity_id
            WHERE l.kernel_entity_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[12] != "kernel_session_runtime_lease":
            raise SQLiteControlStoreError(
                "sqlite_session_runtime_lease_not_adopted",
                "Legacy runtime lease has not been adopted as target Kernel state",
                phase="entity_decode",
            )
        if row[13] is None or row[15] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "SessionRuntimeLease row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[13]),
            payload=payload,
        )
        if snapshot.record_digest != row[14]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "SessionRuntimeLease owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM session_runtime_leases WHERE kernel_entity_id = ?",
                (mutation.entity_id,),
            )
            return
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        values = tuple(payload[field] for field in self._FIELDS)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO session_runtime_leases
                (session_id, owner_id, lease_token, mode, generation,
                 fencing_token, acquired_at, heartbeat_at, expires_at,
                 released_at, last_error, acquire_command_digest,
                 record_kind, kernel_entity_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'kernel_session_runtime_lease', ?)
                """,
                (*values, mutation.entity_id),
            )
            return
        cursor = connection.execute(
            """
            UPDATE session_runtime_leases
            SET session_id = ?, owner_id = ?, lease_token = ?, mode = ?,
                generation = ?, fencing_token = ?, acquired_at = ?,
                heartbeat_at = ?, expires_at = ?, released_at = ?,
                last_error = ?, acquire_command_digest = ?
            WHERE kernel_entity_id = ?
              AND record_kind = 'kernel_session_runtime_lease'
            """,
            (*values, mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "SessionRuntimeLease target row disappeared before replacement",
                phase="entity_apply",
            )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        if set(payload) != set(cls._FIELDS) or payload.get("session_id") != entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_runtime_lease_payload_invalid",
                "SessionRuntimeLease payload differs from its target identity contract",
                phase="entity_encode",
            )
        for field_name in ("generation", "fencing_token"):
            value = payload[field_name]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise SQLiteControlStoreError(
                    "sqlite_session_runtime_lease_payload_invalid",
                    f"SessionRuntimeLease {field_name} must be positive",
                    phase="entity_encode",
                )


class FailureObservationSQLiteKernelEntityCodec:
    """Maps immutable public-safe failures to their structured owner table."""

    entity_type = "failure_observation"
    owner_id = "openzyme.kernel"
    table_names = (
        "failure_observation_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT f.schema_version, f.failure_id, f.session_id, f.source_kind,
                   f.source_ref, f.source_version, f.phase, f.failure_class,
                   f.recoverability, f.effect_certainty, f.retry_eligibility,
                   f.actor_kind, f.error_code, f.safe_summary, f.facts_json,
                   f.likely_causes_json, f.evidence_refs_json, f.created_at,
                   f.task_id, f.lane_id, f.agent_id, f.safe_hint,
                   f.private_diagnostic_digest, f.component, f.operation,
                   f.identities_json, f.mutation_applied, f.fallback_performed,
                   f.cause_chain_json, f.diagnostic_id, f.next_action,
                   v.state_version, v.record_digest,
                   v.owner_component_id
            FROM failure_observation_records AS f
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'failure_observation'
             AND v.entity_id = f.failure_id
            WHERE f.failure_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[31] is None or row[33] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "FailureObservation row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        try:
            payload: dict[str, JsonValue] = {
                "schema_version": row[0],
                "failure_id": row[1],
                "session_id": row[2],
                "source_kind": row[3],
                "source_ref": row[4],
                "source_version": row[5],
                "phase": row[6],
                "failure_class": row[7],
                "recoverability": row[8],
                "effect_certainty": row[9],
                "retry_eligibility": row[10],
                "actor_kind": row[11],
                "error_code": row[12],
                "safe_summary": row[13],
                "facts": json.loads(str(row[14])),
                "likely_causes": json.loads(str(row[15])),
                "evidence_refs": json.loads(str(row[16])),
                "created_at": row[17],
                "task_id": row[18],
                "lane_id": row[19],
                "agent_id": row[20],
                "safe_hint": row[21],
                "component": row[23],
                "operation": row[24],
                "identities": json.loads(str(row[25])),
                "mutation_applied": (None if row[26] is None else bool(row[26])),
                "fallback_performed": bool(row[27]),
                "cause_chain": json.loads(str(row[28])),
                "diagnostic_id": row[29],
                "next_action": row[30],
            }
            if row[22] is not None:
                payload["private_diagnostic_digest"] = row[22]
            parsed = parse_failure_observation(payload)
            if not isinstance(parsed, FailureObservation):
                raise ValueError("historical failure is not target canonical state")
            payload = parsed.to_internal_dict()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_failure_observation_invalid",
                "FailureObservation owner row violates its public-safe contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[31]),
            payload=payload,
        )
        if snapshot.record_digest != row[32]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "FailureObservation owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_failure_observation_immutable",
                "FailureObservation is append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            thawed = json_compatible(mutation.payload)
            if not isinstance(thawed, Mapping):
                raise ValueError("failure observation must be an object")
            parsed = parse_failure_observation(thawed)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_failure_observation_invalid",
                "FailureObservation mutation violates its public-safe contract",
                phase="entity_encode",
            ) from exc
        if (
            not isinstance(parsed, FailureObservation)
            or parsed.failure_id != mutation.entity_id
        ):
            raise SQLiteControlStoreError(
                "sqlite_failure_observation_identity_mismatch",
                "FailureObservation payload identity differs from its mutation",
                phase="entity_encode",
            )
        payload = parsed.to_internal_dict()
        connection.execute(
            """
            INSERT INTO failure_observation_records
            (failure_id, schema_version, session_id, task_id, lane_id, agent_id,
             source_kind, source_ref, source_version, phase, failure_class,
             recoverability, effect_certainty, retry_eligibility, actor_kind,
             error_code, safe_summary, safe_hint, facts_json,
             likely_causes_json, evidence_refs_json, private_diagnostic_digest,
             component, operation, identities_json, mutation_applied,
             fallback_performed, cause_chain_json, diagnostic_id, next_action,
             created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["failure_id"],
                payload["schema_version"],
                payload["session_id"],
                payload["task_id"],
                payload["lane_id"],
                payload["agent_id"],
                payload["source_kind"],
                payload["source_ref"],
                payload["source_version"],
                payload["phase"],
                payload["failure_class"],
                payload["recoverability"],
                payload["effect_certainty"],
                payload["retry_eligibility"],
                payload["actor_kind"],
                payload["error_code"],
                payload["safe_summary"],
                payload["safe_hint"],
                self._json(payload["facts"]),
                self._json(payload["likely_causes"]),
                self._json(payload["evidence_refs"]),
                payload.get("private_diagnostic_digest"),
                payload["component"],
                payload["operation"],
                self._json(payload["identities"]),
                (
                    None
                    if payload["mutation_applied"] is None
                    else int(payload["mutation_applied"] is True)
                ),
                int(payload["fallback_performed"] is True),
                self._json(payload["cause_chain"]),
                payload["diagnostic_id"],
                payload["next_action"],
                payload["created_at"],
            ),
        )

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class PrivateDiagnosticSQLiteKernelEntityCodec:
    """Maps operator-only diagnostic sidecars to their append-only owner table."""

    entity_type = "private_diagnostic"
    owner_id = "openzyme.kernel"
    table_names = (
        "private_diagnostic_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self,
        connection: sqlite3.Connection,
        *,
        entity_id: str,
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT d.diagnostic_id, d.schema_version, d.failure_id, d.session_id,
                   d.component, d.operation, d.phase, d.exception_type,
                   d.exception_message, d.traceback_text, d.cause_chain_json,
                   d.errno, d.return_code, d.bounded_stdout, d.bounded_stderr,
                   d.private_context_json, d.source_kind, d.source_ref,
                   d.source_version, d.correlation_id, d.created_at,
                   d.record_digest, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM private_diagnostic_records AS d
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'private_diagnostic'
             AND v.entity_id = d.diagnostic_id
            WHERE d.diagnostic_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[22] is None or row[24] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "PrivateDiagnostic row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        try:
            payload: dict[str, Any] = {
                "diagnostic_id": row[0],
                "schema_version": row[1],
                "failure_id": row[2],
                "session_id": row[3],
                "component": row[4],
                "operation": row[5],
                "phase": row[6],
                "exception_type": row[7],
                "exception_message": row[8],
                "traceback_text": row[9],
                "cause_chain": json.loads(str(row[10])),
                "errno": row[11],
                "return_code": row[12],
                "bounded_stdout": row[13],
                "bounded_stderr": row[14],
                "private_context": json.loads(str(row[15])),
                "source_kind": row[16],
                "source_ref": row[17],
                "source_version": row[18],
                "correlation_id": row[19],
                "created_at": row[20],
                "record_digest": row[21],
            }
            diagnostic = PrivateDiagnosticRecord.from_dict(payload)
            payload = diagnostic.to_dict()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_private_diagnostic_invalid",
                "PrivateDiagnostic owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[22]),
            payload=payload,
        )
        if snapshot.record_digest != row[23]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "PrivateDiagnostic owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_private_diagnostic_immutable",
                "PrivateDiagnostic is append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            thawed = json_compatible(mutation.payload)
            if not isinstance(thawed, Mapping):
                raise ValueError("private diagnostic must be an object")
            diagnostic = PrivateDiagnosticRecord.from_dict(thawed)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_private_diagnostic_invalid",
                "PrivateDiagnostic mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if diagnostic.diagnostic_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_private_diagnostic_identity_mismatch",
                "PrivateDiagnostic payload identity differs from its mutation",
                phase="entity_encode",
            )
        failure = connection.execute(
            """
            SELECT private_diagnostic_digest, diagnostic_id, session_id,
                   component, operation, phase, source_kind, source_ref,
                   source_version
            FROM failure_observation_records
            WHERE failure_id = ?
            """,
            (diagnostic.failure_id,),
        ).fetchone()
        if failure != (
            diagnostic.record_digest,
            diagnostic.diagnostic_id,
            diagnostic.session_id,
            diagnostic.component,
            diagnostic.operation,
            diagnostic.phase,
            diagnostic.source_kind,
            diagnostic.source_ref,
            diagnostic.source_version,
        ):
            raise SQLiteControlStoreError(
                "sqlite_private_diagnostic_failure_mismatch",
                "PrivateDiagnostic does not match its exact public failure",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO private_diagnostic_records
            (diagnostic_id, schema_version, failure_id, session_id, component,
             operation, phase, exception_type, exception_message,
             traceback_text, cause_chain_json, errno, return_code,
             bounded_stdout, bounded_stderr, private_context_json, source_kind,
             source_ref, source_version, correlation_id, created_at,
             record_digest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?)
            """,
            (
                diagnostic.diagnostic_id,
                diagnostic.schema_version,
                diagnostic.failure_id,
                diagnostic.session_id,
                diagnostic.component,
                diagnostic.operation,
                diagnostic.phase,
                diagnostic.exception_type,
                diagnostic.exception_message,
                diagnostic.traceback_text,
                _canonical_json(list(diagnostic.cause_chain)),
                diagnostic.errno,
                diagnostic.return_code,
                diagnostic.bounded_stdout,
                diagnostic.bounded_stderr,
                _canonical_json(diagnostic.private_context),
                diagnostic.source_kind,
                diagnostic.source_ref,
                diagnostic.source_version,
                diagnostic.correlation_id,
                diagnostic.created_at,
                diagnostic.record_digest,
            ),
        )


class _ClosedResidentJSONSQLiteKernelEntityCodec:
    """Typed mapper for one explicit resident-teammate owner table.

    Every subclass binds one closed contract parser and one physical table.  The
    payload JSON is not a generic state escape hatch: indexed identities are
    duplicated and checked against the parsed contract, and only the selected
    Kernel entity codec can open the table mutation gate.
    """

    owner_id = "openzyme.kernel"
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    create_only = True
    entity_type: str
    table_names: tuple[str, ...]
    _table_name: str
    _identity_column: str
    _identity_field: str
    _schema_version: str
    _digest_field: str
    _indexed_fields: tuple[tuple[str, str], ...]
    _state_version_field: str | None = None

    @classmethod
    def _payload_index_value(
        cls,
        payload: Mapping[str, JsonValue],
        field_path: str,
    ) -> JsonValue:
        value: JsonValue = payload
        for part in field_path.split("."):
            if value is None:
                return None
            if not isinstance(value, Mapping) or part not in value:
                raise SQLiteControlStoreError(
                    "sqlite_resident_contract_index_path_invalid",
                    f"{cls.entity_type} indexed field path is absent",
                    phase="entity_encode",
                )
            value = value[part]
        return value

    @classmethod
    def _normalize_payload(
        cls,
        payload: Mapping[str, JsonValue],
    ) -> dict[str, JsonValue]:
        raise NotImplementedError

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if cls._state_version_field is not None:
            if normalized[cls._state_version_field] != next_state_version:
                raise SQLiteControlStoreError(
                    "sqlite_resident_contract_state_version_mismatch",
                    f"{cls.entity_type} state version differs from target CAS",
                    phase="entity_encode",
                )

    def read(
        self,
        connection: sqlite3.Connection,
        *,
        entity_id: str,
    ) -> KernelRecordSnapshot | None:
        indexed_columns = tuple(column for column, _ in self._indexed_fields)
        selected = ", ".join(f"r.{column}" for column in indexed_columns)
        row = connection.execute(
            f"""
            SELECT {selected}, r.payload_json, r.{self._digest_field},
                   r.schema_version, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM {self._table_name} AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = ? AND v.entity_id = r.{self._identity_column}
            WHERE r.{self._identity_column} = ?
            """,
            (self.entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        offset = len(indexed_columns)
        if row[offset + 3] is None or row[offset + 5] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                f"{self.entity_type} row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        decoded = _decode_json(
            row[offset],
            code="sqlite_resident_contract_json_invalid",
            subject=self.entity_type,
        )
        if not isinstance(decoded, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_resident_contract_payload_invalid",
                f"{self.entity_type} payload must be a closed JSON object",
                phase="entity_decode",
            )
        normalized = self._normalize_payload(decoded)
        for index, (_, payload_field) in enumerate(self._indexed_fields):
            if self._payload_index_value(normalized, payload_field) != row[index]:
                raise SQLiteControlStoreError(
                    "sqlite_resident_contract_index_mismatch",
                    f"{self.entity_type} indexed owner fields differ from payload",
                    phase="entity_decode",
                )
        if (
            normalized[self._digest_field] != row[offset + 1]
            or normalized["schema_version"] != row[offset + 2]
            or row[offset + 2] != self._schema_version
        ):
            raise SQLiteControlStoreError(
                "sqlite_resident_contract_digest_mismatch",
                f"{self.entity_type} owner digest/schema differs from payload",
                phase="entity_decode",
            )
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[offset + 3]),
            payload=normalized,
        )
        if snapshot.record_digest != row[offset + 4]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                f"{self.entity_type} owner row differs from target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            raise SQLiteControlStoreError(
                "sqlite_resident_contract_history_immutable",
                f"{self.entity_type} history cannot be deleted",
                phase="entity_apply",
            )
        if self.create_only and mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_resident_contract_immutable",
                f"{self.entity_type} records are create-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        normalized = self._normalize_payload(mutation.payload)
        if normalized[self._identity_field] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_resident_contract_identity_mismatch",
                f"{self.entity_type} identity differs from mutation target",
                phase="entity_encode",
            )
        self._validate_transition(
            connection,
            normalized=normalized,
            mutation=mutation,
            next_state_version=next_state_version,
        )
        columns = tuple(column for column, _ in self._indexed_fields) + (
            "payload_json",
            self._digest_field,
            "schema_version",
        )
        values = tuple(
            self._payload_index_value(normalized, payload_field)
            for _, payload_field in self._indexed_fields
        ) + (
            _canonical_json(normalized),
            normalized[self._digest_field],
            normalized["schema_version"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO {self._table_name} ({', '.join(columns)}) "
                f"VALUES ({placeholders})",
                values,
            )
            return
        assignments = ", ".join(f"{column} = ?" for column in columns[1:])
        cursor = connection.execute(
            f"UPDATE {self._table_name} SET {assignments} "
            f"WHERE {self._identity_column} = ?",
            values[1:] + (mutation.entity_id,),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                f"{self.entity_type} owner row disappeared before replacement",
                phase="entity_apply",
            )


class WorkspaceProvisioningIntentSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "workspace_provisioning_intent"
    _table_name = "workspace_provisioning_intent_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "intent_id"
    _identity_field = "intent_id"
    _schema_version = "workspace_provisioning_intent@1"
    _digest_field = "intent_digest"
    _state_version_field = "state_version"
    create_only = False
    _indexed_fields = (
        ("intent_id", "intent_id"),
        ("session_id", "session_id"),
        ("agent_member_id", "agent_member_id"),
        ("workspace_id", "workspace_id"),
        ("generation", "generation"),
        ("status", "status"),
        ("state_version", "state_version"),
        ("claim_epoch", "claim_epoch"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return WorkspaceProvisioningIntent.from_dict(
                json_compatible(payload)
            ).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_intent_payload_invalid",
                "WorkspaceProvisioningIntent violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        super()._validate_transition(
            connection,
            normalized=normalized,
            mutation=mutation,
            next_state_version=next_state_version,
        )
        if mutation.kind is KernelMutationKind.CREATE:
            if (
                normalized["status"] != WorkspaceProvisioningStatus.PENDING.value
                or normalized["claim_epoch"] != 0
            ):
                raise SQLiteControlStoreError(
                    "sqlite_workspace_provisioning_lifecycle_invalid",
                    "new provisioning intent must be pending at epoch zero",
                    phase="entity_encode",
                )
            return
        row = connection.execute(
            "SELECT payload_json FROM workspace_provisioning_intent_records WHERE intent_id = ?",
            (mutation.entity_id,),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "WorkspaceProvisioningIntent owner row is missing",
                phase="entity_encode",
            )
        current_value = _decode_json(
            row[0],
            code="sqlite_resident_contract_json_invalid",
            subject=cls.entity_type,
        )
        assert isinstance(current_value, Mapping)
        current = WorkspaceProvisioningIntent.from_dict(json_compatible(current_value))
        proposed = WorkspaceProvisioningIntent.from_dict(json_compatible(normalized))
        allowed = {
            WorkspaceProvisioningStatus.PENDING: {WorkspaceProvisioningStatus.CLAIMED},
            WorkspaceProvisioningStatus.CLAIMED: {
                WorkspaceProvisioningStatus.CLAIMED,
                WorkspaceProvisioningStatus.READY,
                WorkspaceProvisioningStatus.BLOCKED,
                WorkspaceProvisioningStatus.CANCELLED,
            },
            WorkspaceProvisioningStatus.READY: set(),
            WorkspaceProvisioningStatus.BLOCKED: set(),
            WorkspaceProvisioningStatus.CANCELLED: set(),
        }
        if proposed.status not in allowed[current.status]:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_lifecycle_invalid",
                "WorkspaceProvisioningIntent lifecycle transition is invalid",
                phase="entity_encode",
            )
        expected_epoch = (
            current.claim_epoch + 1
            if proposed.status is WorkspaceProvisioningStatus.CLAIMED
            else current.claim_epoch
        )
        if proposed.claim_epoch != expected_epoch:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_claim_epoch_stale",
                "WorkspaceProvisioningIntent claim epoch is stale",
                phase="entity_encode",
            )


class WorkspaceProvisioningReceiptSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    """Own immutable Adapter observations accepted by Kernel settlement."""

    entity_type = "workspace_provisioning_receipt"
    _table_name = "workspace_provisioning_receipt_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "receipt_id"
    _identity_field = "receipt_id"
    _schema_version = "workspace_provisioning_receipt@1"
    _digest_field = "receipt_digest"
    _indexed_fields = (
        ("receipt_id", "receipt_id"),
        ("session_id", "session_id"),
        ("intent_id", "intent_id"),
        ("agent_member_id", "agent_member_id"),
        ("workspace_id", "workspace_id"),
        ("generation", "generation"),
        ("controlled_operation_id", "controlled_operation_id"),
        ("request_id", "request_id"),
        ("claim_epoch", "claim_epoch"),
        ("disposition", "disposition"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return WorkspaceProvisioningReceipt.from_dict(
                json_compatible(payload)
            ).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_payload_invalid",
                "WorkspaceProvisioningReceipt violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        super()._validate_transition(
            connection,
            normalized=normalized,
            mutation=mutation,
            next_state_version=next_state_version,
        )
        row = connection.execute(
            "SELECT payload_json FROM workspace_provisioning_intent_records "
            "WHERE intent_id = ?",
            (normalized["intent_id"],),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_intent_missing",
                "WorkspaceProvisioningReceipt requires its durable intent",
                phase="entity_encode",
            )
        current_value = _decode_json(
            row[0],
            code="sqlite_resident_contract_json_invalid",
            subject=cls.entity_type,
        )
        if not isinstance(current_value, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_intent_invalid",
                "WorkspaceProvisioningReceipt intent owner row is invalid",
                phase="entity_encode",
            )
        current = WorkspaceProvisioningIntent.from_dict(json_compatible(current_value))
        receipt = WorkspaceProvisioningReceipt.from_dict(json_compatible(normalized))
        observed_request = WorkspaceProvisioningRequest(
            request_id=receipt.request_id,
            intent_id=receipt.intent_id,
            intent_digest=receipt.intent_digest,
            claim_token=receipt.claim_token,
            claim_epoch=receipt.claim_epoch,
            session_id=receipt.session_id,
            agent_member_id=receipt.agent_member_id,
            workspace_id=receipt.workspace_id,
            generation=receipt.generation,
            repository_pin_digest=receipt.repository_pin_digest,
            provider_id=receipt.provider_id,
            target_id=receipt.target_id,
            adapter_binding_digest=receipt.adapter_binding_digest,
            controlled_operation_id=receipt.controlled_operation_id,
        )
        if observed_request.request_digest != receipt.request_digest:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_request_stale",
                "WorkspaceProvisioningReceipt does not bind its exact Adapter request",
                phase="entity_encode",
            )
        if current.status not in {
            WorkspaceProvisioningStatus.CLAIMED,
            WorkspaceProvisioningStatus.BLOCKED,
        }:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_lifecycle_invalid",
                "Provisioning receipt requires a claimed or reconcilable intent",
                phase="entity_encode",
            )
        if current.status is WorkspaceProvisioningStatus.BLOCKED and (
            not current.reconcile_required or current.terminal_receipt_digest is None
        ):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_reconciliation_invalid",
                "Blocked provisioning intent is not eligible for reconciliation",
                phase="entity_encode",
            )
        expected_intent_digest = current.intent_digest
        if current.status is WorkspaceProvisioningStatus.BLOCKED:
            rows = connection.execute(
                "SELECT payload_json "
                "FROM workspace_provisioning_reconciliation_records "
                "WHERE intent_id = ? AND status = 'claimed' "
                "ORDER BY attempt",
                (current.intent_id,),
            ).fetchall()
            matching: list[WorkspaceProvisioningReconciliation] = []
            for reconciliation_row in rows:
                reconciliation_value = _decode_json(
                    reconciliation_row[0],
                    code="sqlite_resident_contract_json_invalid",
                    subject="workspace_provisioning_reconciliation",
                )
                if not isinstance(reconciliation_value, Mapping):
                    continue
                reconciliation = WorkspaceProvisioningReconciliation.from_dict(
                    json_compatible(reconciliation_value)
                )
                if reconciliation.provision_request == observed_request:
                    matching.append(reconciliation)
            if len(matching) != 1:
                raise SQLiteControlStoreError(
                    "sqlite_workspace_provisioning_receipt_reconciliation_stale",
                    "Reconciliation receipt requires one exact claimed durable observation",
                    phase="entity_encode",
                )
            expected_intent_digest = matching[0].provision_request.intent_digest
        if (
            receipt.intent_digest != expected_intent_digest
            or receipt.session_id != current.session_id
            or receipt.agent_member_id != current.agent_member_id
            or receipt.workspace_id != current.workspace_id
            or receipt.generation != current.generation
            or receipt.repository_pin_digest != current.repository_pin_digest
            or receipt.provider_id != current.provider_id
            or receipt.target_id != current.target_id
            or receipt.adapter_binding_digest != current.adapter_binding_digest
            or receipt.controlled_operation_id != current.controlled_operation_id
            or receipt.claim_token != current.claim_token
            or receipt.claim_epoch != current.claim_epoch
        ):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_receipt_identity_stale",
                "WorkspaceProvisioningReceipt differs from its current occurrence",
                phase="entity_encode",
            )


class WorkspaceProvisioningReconciliationSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    """Own one explicit, claim-fenced observation of a blocked dispatch."""

    entity_type = "workspace_provisioning_reconciliation"
    _table_name = "workspace_provisioning_reconciliation_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "reconciliation_id"
    _identity_field = "reconciliation_id"
    _schema_version = "workspace_provisioning_reconciliation@1"
    _digest_field = "reconciliation_digest"
    _state_version_field = "state_version"
    create_only = False
    _indexed_fields = (
        ("reconciliation_id", "reconciliation_id"),
        ("session_id", "session_id"),
        ("intent_id", "intent_id"),
        ("source_receipt_id", "source_receipt_id"),
        ("attempt", "attempt"),
        ("parent_reconciliation_id", "parent_reconciliation_id"),
        ("status", "status"),
        ("state_version", "state_version"),
        ("claim_epoch", "claim_epoch"),
        ("identity_digest", "identity_digest"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return WorkspaceProvisioningReconciliation.from_dict(
                json_compatible(payload)
            ).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_payload_invalid",
                "WorkspaceProvisioningReconciliation violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        super()._validate_transition(
            connection,
            normalized=normalized,
            mutation=mutation,
            next_state_version=next_state_version,
        )
        proposed = WorkspaceProvisioningReconciliation.from_dict(
            json_compatible(normalized)
        )
        if mutation.kind is KernelMutationKind.CREATE:
            if (
                proposed.status is not WorkspaceProvisioningReconciliationStatus.PENDING
                or proposed.state_version != 1
                or proposed.claim_epoch != 0
            ):
                raise SQLiteControlStoreError(
                    "sqlite_workspace_provisioning_reconciliation_lifecycle_invalid",
                    "New reconciliation must be pending at state version one",
                    phase="entity_encode",
                )
            cls._validate_source_graph(connection, proposed)
            cls._validate_parent(connection, proposed)
            return

        row = connection.execute(
            "SELECT payload_json FROM workspace_provisioning_reconciliation_records "
            "WHERE reconciliation_id = ?",
            (mutation.entity_id,),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "WorkspaceProvisioningReconciliation owner row is missing",
                phase="entity_encode",
            )
        current_value = _decode_json(
            row[0],
            code="sqlite_resident_contract_json_invalid",
            subject=cls.entity_type,
        )
        if not isinstance(current_value, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_payload_invalid",
                "Current reconciliation owner payload is invalid",
                phase="entity_encode",
            )
        current = WorkspaceProvisioningReconciliation.from_dict(
            json_compatible(current_value)
        )
        if proposed.identity_digest != current.identity_digest:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_identity_stale",
                "Reconciliation occurrence identity cannot change",
                phase="entity_encode",
            )
        allowed = {
            WorkspaceProvisioningReconciliationStatus.PENDING: {
                WorkspaceProvisioningReconciliationStatus.CLAIMED,
            },
            WorkspaceProvisioningReconciliationStatus.CLAIMED: {
                WorkspaceProvisioningReconciliationStatus.CLAIMED,
                WorkspaceProvisioningReconciliationStatus.READY,
                WorkspaceProvisioningReconciliationStatus.BLOCKED,
            },
            WorkspaceProvisioningReconciliationStatus.READY: set(),
            WorkspaceProvisioningReconciliationStatus.BLOCKED: set(),
        }
        if proposed.status not in allowed[current.status]:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_lifecycle_invalid",
                "WorkspaceProvisioningReconciliation lifecycle transition is invalid",
                phase="entity_encode",
            )
        expected_claim_epoch = (
            current.claim_epoch + 1
            if proposed.status is WorkspaceProvisioningReconciliationStatus.CLAIMED
            else current.claim_epoch
        )
        if proposed.claim_epoch != expected_claim_epoch:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_claim_epoch_stale",
                "WorkspaceProvisioningReconciliation claim epoch is stale",
                phase="entity_encode",
            )
        cls._validate_source_graph(connection, proposed)

    @staticmethod
    def _validate_source_graph(
        connection: sqlite3.Connection,
        reconciliation: WorkspaceProvisioningReconciliation,
    ) -> None:
        intent_row = connection.execute(
            "SELECT payload_json FROM workspace_provisioning_intent_records "
            "WHERE intent_id = ?",
            (reconciliation.intent_id,),
        ).fetchone()
        receipt_row = connection.execute(
            "SELECT payload_json FROM workspace_provisioning_receipt_records "
            "WHERE receipt_id = ?",
            (reconciliation.source_receipt_id,),
        ).fetchone()
        if intent_row is None or receipt_row is None:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_source_missing",
                "Reconciliation requires its blocked intent and source receipt",
                phase="entity_encode",
            )
        intent_value = _decode_json(
            intent_row[0],
            code="sqlite_resident_contract_json_invalid",
            subject="workspace_provisioning_intent",
        )
        receipt_value = _decode_json(
            receipt_row[0],
            code="sqlite_resident_contract_json_invalid",
            subject="workspace_provisioning_receipt",
        )
        if not isinstance(intent_value, Mapping) or not isinstance(
            receipt_value, Mapping
        ):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_source_invalid",
                "Reconciliation source owner payload is invalid",
                phase="entity_encode",
            )
        intent = WorkspaceProvisioningIntent.from_dict(json_compatible(intent_value))
        receipt = WorkspaceProvisioningReceipt.from_dict(json_compatible(receipt_value))
        request = reconciliation.provision_request
        if (
            intent.status is not WorkspaceProvisioningStatus.BLOCKED
            or not intent.reconcile_required
            or intent.state_version != reconciliation.blocked_intent_state_version
            or intent.intent_digest != reconciliation.blocked_intent_digest
            or receipt.receipt_digest != reconciliation.source_receipt_digest
            or receipt.intent_id != intent.intent_id
            or receipt.terminal_receipt_digest != reconciliation.dispatch_receipt_digest
            or receipt.effect_certainty.value != "dispatch_in_doubt"
            or not receipt.reconcile_required
            or request.request_id != receipt.request_id
            or request.request_digest != receipt.request_digest
            or request.intent_id != intent.intent_id
            or request.session_id != intent.session_id
            or request.agent_member_id != intent.agent_member_id
            or request.workspace_id != intent.workspace_id
            or request.generation != intent.generation
            or request.repository_pin_digest != intent.repository_pin_digest
            or request.provider_id != intent.provider_id
            or request.target_id != intent.target_id
            or request.adapter_binding_digest != intent.adapter_binding_digest
            or request.controlled_operation_id != intent.controlled_operation_id
            or request.claim_token != intent.claim_token
            or request.claim_epoch != intent.claim_epoch
        ):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_source_stale",
                "Reconciliation differs from the exact blocked dispatch occurrence",
                phase="entity_encode",
            )

    @staticmethod
    def _validate_parent(
        connection: sqlite3.Connection,
        reconciliation: WorkspaceProvisioningReconciliation,
    ) -> None:
        if reconciliation.parent_reconciliation_id is None:
            return
        row = connection.execute(
            "SELECT payload_json FROM workspace_provisioning_reconciliation_records "
            "WHERE reconciliation_id = ?",
            (reconciliation.parent_reconciliation_id,),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_parent_missing",
                "Reconciliation lineage parent is absent",
                phase="entity_encode",
            )
        value = _decode_json(
            row[0],
            code="sqlite_resident_contract_json_invalid",
            subject="workspace_provisioning_reconciliation",
        )
        if not isinstance(value, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_parent_invalid",
                "Reconciliation lineage parent is invalid",
                phase="entity_encode",
            )
        parent = WorkspaceProvisioningReconciliation.from_dict(json_compatible(value))
        if (
            parent.status is not WorkspaceProvisioningReconciliationStatus.BLOCKED
            or not parent.reconcile_required
            or parent.intent_id != reconciliation.intent_id
            or parent.attempt + 1 != reconciliation.attempt
            or parent.provision_request.request_digest
            != reconciliation.provision_request.request_digest
        ):
            raise SQLiteControlStoreError(
                "sqlite_workspace_provisioning_reconciliation_parent_stale",
                "Reconciliation lineage parent is not eligible for another observation",
                phase="entity_encode",
            )


class WorkflowAuthorityBindingSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "workflow_authority_binding"
    _table_name = "workflow_authority_binding_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "authority_id"
    _identity_field = "authority_id"
    _schema_version = "workflow_authority_binding@1"
    _digest_field = "binding_digest"
    _state_version_field = "state_version"
    create_only = False
    _indexed_fields = (
        ("authority_id", "authority_id"),
        ("session_id", "session_id"),
        ("request_lineage_id", "request_lineage_id"),
        ("parent_authority_id", "parent_authority_id"),
        ("status", "status"),
        ("epoch", "epoch"),
        ("state_version", "state_version"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return WorkflowAuthorityBinding.from_dict(
                json_compatible(payload)
            ).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workflow_authority_binding_payload_invalid",
                "WorkflowAuthorityBinding violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        super()._validate_transition(
            connection,
            normalized=normalized,
            mutation=mutation,
            next_state_version=next_state_version,
        )
        if mutation.kind is KernelMutationKind.CREATE:
            if (
                normalized["status"] != WorkflowAuthorityStatus.ACTIVE.value
                or normalized["epoch"] != 1
            ):
                raise SQLiteControlStoreError(
                    "sqlite_workflow_authority_lifecycle_invalid",
                    "new workflow authority must be active at epoch one",
                    phase="entity_encode",
                )
            return
        row = connection.execute(
            "SELECT payload_json FROM workflow_authority_binding_records WHERE authority_id = ?",
            (mutation.entity_id,),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "WorkflowAuthorityBinding owner row is missing",
                phase="entity_encode",
            )
        current_value = _decode_json(
            row[0],
            code="sqlite_resident_contract_json_invalid",
            subject=cls.entity_type,
        )
        assert isinstance(current_value, Mapping)
        current = WorkflowAuthorityBinding.from_dict(json_compatible(current_value))
        proposed = WorkflowAuthorityBinding.from_dict(json_compatible(normalized))
        if (
            current.status is not WorkflowAuthorityStatus.ACTIVE
            or proposed.status is WorkflowAuthorityStatus.ACTIVE
            or proposed.epoch != current.epoch + 1
        ):
            raise SQLiteControlStoreError(
                "sqlite_workflow_authority_epoch_stale",
                "workflow authority transition is terminal or carries a stale epoch",
                phase="entity_encode",
            )


class RuntimeSignalAuthorityLinkSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "runtime_signal_authority_link"
    _table_name = "runtime_signal_authority_link_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "signal_id"
    _identity_field = "signal_id"
    _schema_version = "runtime_signal_authority_link@1"
    _digest_field = "link_digest"
    _indexed_fields = (
        ("signal_id", "signal_id"),
        ("session_id", "session_id"),
        ("authority_id", "authority_id"),
        ("authority_epoch", "authority_epoch"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return RuntimeSignalAuthorityLink.from_dict(
                json_compatible(payload)
            ).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_signal_authority_link_payload_invalid",
                "RuntimeSignalAuthorityLink violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        row = connection.execute(
            "SELECT status, epoch, binding_digest FROM workflow_authority_binding_records WHERE authority_id = ?",
            (normalized["authority_id"],),
        ).fetchone()
        if row is None or row != (
            WorkflowAuthorityStatus.ACTIVE.value,
            normalized["authority_epoch"],
            normalized["authority_binding_digest"],
        ):
            raise SQLiteControlStoreError(
                "sqlite_workflow_authority_epoch_stale",
                "runtime signal link does not bind a current active authority",
                phase="entity_encode",
            )


class RuntimeTurnContextSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "runtime_turn_context"
    _table_name = "runtime_turn_context_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "context_id"
    _identity_field = "context_id"
    _schema_version = "runtime_turn_context@1"
    _digest_field = "context_digest"
    _indexed_fields = (
        ("context_id", "context_id"),
        ("session_id", "session_id"),
        ("turn_id", "turn_id"),
        ("signal_id", "signal_id"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return RuntimeTurnContext.from_dict(json_compatible(payload)).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_context_payload_invalid",
                "RuntimeTurnContext violates its closed contract",
                phase="entity_encode",
            ) from exc


class ToolExposureSnapshotSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "tool_exposure_snapshot"
    _table_name = "tool_exposure_snapshot_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "exposure_snapshot_id"
    _identity_field = "exposure_snapshot_id"
    _schema_version = "tool_exposure_snapshot@1"
    _digest_field = "exposure_snapshot_digest"
    _indexed_fields = (
        ("exposure_snapshot_id", "exposure_snapshot_id"),
        ("session_id", "session_id"),
        ("turn_id", "turn_id"),
        ("workflow_authority_id", "workflow_authority_id"),
        ("workflow_authority_epoch", "workflow_authority_epoch"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return ToolExposureSnapshot.from_dict(json_compatible(payload)).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_tool_exposure_snapshot_payload_invalid",
                "ToolExposureSnapshot violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        row = connection.execute(
            "SELECT status, epoch, binding_digest FROM workflow_authority_binding_records WHERE authority_id = ?",
            (normalized["workflow_authority_id"],),
        ).fetchone()
        if row is None or row != (
            WorkflowAuthorityStatus.ACTIVE.value,
            normalized["workflow_authority_epoch"],
            normalized["workflow_authority_digest"],
        ):
            raise SQLiteControlStoreError(
                "sqlite_workflow_authority_epoch_stale",
                "tool exposure snapshot does not bind current workflow authority",
                phase="entity_encode",
            )


class CommandToolExpansionSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "command_tool_expansion"
    _table_name = "command_tool_expansion_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "expansion_id"
    _identity_field = "expansion_id"
    _schema_version = "command_tool_expansion@1"
    _digest_field = "expansion_digest"
    _indexed_fields = (
        ("expansion_id", "expansion_id"),
        ("command_id", "command_id"),
        ("session_id", "session_id"),
        ("exposure_snapshot_id", "exposure_snapshot_id"),
        ("expansion_revision", "expansion_revision"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        try:
            return CommandToolExpansion.from_dict(json_compatible(payload)).to_dict()
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_command_tool_expansion_payload_invalid",
                "CommandToolExpansion violates its closed contract",
                phase="entity_encode",
            ) from exc

    @classmethod
    def _validate_transition(
        cls,
        connection: sqlite3.Connection,
        *,
        normalized: Mapping[str, JsonValue],
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        row = connection.execute(
            "SELECT payload_json FROM tool_exposure_snapshot_records WHERE exposure_snapshot_id = ?",
            (normalized["exposure_snapshot_id"],),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_tool_exposure_snapshot_missing",
                "command tool expansion requires its exact exposure snapshot",
                phase="entity_encode",
            )
        snapshot_value = _decode_json(
            row[0],
            code="sqlite_resident_contract_json_invalid",
            subject="tool_exposure_snapshot",
        )
        assert isinstance(snapshot_value, Mapping)
        snapshot = ToolExposureSnapshot.from_dict(json_compatible(snapshot_value))
        expansion = CommandToolExpansion.from_dict(json_compatible(normalized))
        try:
            from openzyme_contracts import validate_command_tool_expansion

            validate_command_tool_expansion(snapshot, expansion)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_command_tool_expansion_not_deferred",
                "command tool expansion is not an exact Deferred subset",
                phase="entity_encode",
            ) from exc


class _CreateOnlyRuntimeSQLiteKernelEntityCodec:
    """Shared mechanics for explicit create-only bounded-turn owner tables."""

    owner_id = "openzyme.kernel"
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    entity_type: str
    table_names: tuple[str, ...]
    _table_name: str
    _identity_field: str
    _fields: tuple[str, ...]
    _columns: tuple[str, ...]
    _json_fields: frozenset[str] = frozenset()
    _boolean_fields: frozenset[str] = frozenset()
    _immutable_code = "sqlite_runtime_coordination_immutable"

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        identity_column = self._columns[self._fields.index(self._identity_field)]
        selected = ", ".join(f"r.{column}" for column in self._columns)
        row = connection.execute(
            f"""
            SELECT {selected}, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM {self._table_name} AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = ? AND v.entity_id = r.{identity_column}
            WHERE r.{identity_column} = ?
            """,
            (self.entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        field_count = len(self._fields)
        if row[field_count] is None or row[field_count + 2] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                f"{self.entity_type} row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {}
        for index, field_name in enumerate(self._fields):
            value: JsonValue = row[index]
            if field_name in self._json_fields:
                value = _decode_json(
                    value,
                    code="sqlite_runtime_coordination_json_invalid",
                    subject=self.entity_type,
                )
            elif field_name in self._boolean_fields:
                value = bool(value)
            payload[field_name] = value
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[field_count]),
            payload=payload,
        )
        if snapshot.record_digest != row[field_count + 1]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                f"{self.entity_type} owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                self._immutable_code,
                f"{self.entity_type} records are create-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        values: list[JsonValue | str | int] = []
        for field_name in self._fields:
            value = payload[field_name]
            if field_name in self._json_fields:
                value = _canonical_json(value)
            elif field_name in self._boolean_fields:
                value = int(value is True)
            values.append(value)
        placeholders = ", ".join("?" for _ in self._columns)
        connection.execute(
            f"INSERT INTO {self._table_name} "
            f"({', '.join(self._columns)}) VALUES ({placeholders})",
            tuple(values),
        )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        raise NotImplementedError


def _validate_runtime_message_set(value: JsonValue) -> None:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 512:
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_command_payload_invalid",
            "RuntimeTurnCommand messages must be a bounded non-empty array",
            phase="entity_encode",
        )
    message_ids: list[str] = []
    expected = {
        "schema_version",
        "message_id",
        "role",
        "content",
        "correlation_id",
        "tool_call_id",
    }
    for item in value:
        if not isinstance(item, Mapping) or set(item) != expected:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_command_payload_invalid",
                "RuntimeTurnCommand contains a non-closed message",
                phase="entity_encode",
            )
        if item["schema_version"] != "runtime_message@1" or item["role"] not in {
            "system",
            "user",
            "assistant",
            "tool",
        }:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_command_payload_invalid",
                "RuntimeTurnCommand message schema or role is invalid",
                phase="entity_encode",
            )
        message_id = item["message_id"]
        _require_runtime_identifier(message_id, field_name="message_id")
        assert isinstance(message_id, str)
        message_ids.append(message_id)
        content = item["content"]
        if not isinstance(content, str) or not content or len(content) > 131_072:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_command_payload_invalid",
                "RuntimeTurnCommand message content is not bounded",
                phase="entity_encode",
            )
        for optional_id in ("correlation_id", "tool_call_id"):
            if item[optional_id] is not None:
                _require_runtime_identifier(item[optional_id], field_name=optional_id)
        if item["role"] == "tool" and item["tool_call_id"] is None:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_command_payload_invalid",
                "Runtime tool messages require tool_call_id",
                phase="entity_encode",
            )
    if len(message_ids) != len(set(message_ids)):
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_command_payload_invalid",
            "RuntimeTurnCommand message identities must be unique",
            phase="entity_encode",
        )


def _normalize_runtime_turn_outcome_receipt(
    payload: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    thawed = json_compatible(payload)
    if (
        not isinstance(thawed, dict)
        or set(thawed)
        != {
            "schema_version",
            "receipt_id",
            "outcome",
            "accepted_at",
            "receipt_digest",
        }
        or thawed.get("schema_version") != "runtime_turn_outcome_receipt@1"
    ):
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcomeReceipt has an invalid closed schema",
            phase="entity_encode",
        )
    for field_name in ("receipt_id", "accepted_at"):
        _require_runtime_identifier(thawed[field_name], field_name=field_name)
    _require_runtime_digest(thawed["receipt_digest"], field_name="receipt_digest")
    outcome = thawed["outcome"]
    expected_outcome = {
        "schema_version",
        "outcome_id",
        "command_id",
        "command_digest",
        "turn_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "runtime_lease_generation",
        "runtime_fence",
        "process_epoch",
        "workflow_authority_id",
        "workflow_authority_epoch",
        "workflow_authority_digest",
        "tool_exposure_snapshot_id",
        "tool_exposure_snapshot_digest",
        "disposition",
        "summary",
        "messages",
        "tool_requests",
        "usage",
        "continuation_id",
        "waiting_approval_id",
        "failure",
        "task_id",
        "lane_id",
        "correlation_id",
        "outcome_digest",
    }
    if (
        not isinstance(outcome, dict)
        or set(outcome) != expected_outcome
        or outcome.get("schema_version") != "runtime_turn_outcome@1"
    ):
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcome has an invalid closed schema",
            phase="entity_encode",
        )
    for field_name in (
        "outcome_id",
        "command_id",
        "turn_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "workflow_authority_id",
        "tool_exposure_snapshot_id",
    ):
        _require_runtime_identifier(outcome[field_name], field_name=field_name)
    for field_name in (
        "command_digest",
        "workflow_authority_digest",
        "tool_exposure_snapshot_digest",
        "outcome_digest",
    ):
        _require_runtime_digest(outcome[field_name], field_name=field_name)
    for field_name in (
        "signal_attempt",
        "runtime_lease_generation",
        "runtime_fence",
        "process_epoch",
        "workflow_authority_epoch",
    ):
        _require_positive_runtime_integer(outcome[field_name], field_name=field_name)
    for field_name in (
        "continuation_id",
        "waiting_approval_id",
        "task_id",
        "lane_id",
        "correlation_id",
    ):
        if outcome[field_name] is not None:
            _require_runtime_identifier(outcome[field_name], field_name=field_name)
    if (
        outcome["disposition"]
        not in {
            "ready_for_next_step",
            "waiting_approval",
            "waiting_continuation",
            "idle",
            "step_limit_reached",
            "failed",
        }
        or not isinstance(outcome["summary"], str)
        or not outcome["summary"]
        or len(outcome["summary"]) > 16_384
    ):
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcome disposition or summary is invalid",
            phase="entity_encode",
        )
    messages = outcome["messages"]
    if not isinstance(messages, list) or len(messages) > 512:
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcome messages exceed their closed bound",
            phase="entity_encode",
        )
    if messages:
        _validate_runtime_message_set(messages)
    tool_requests = outcome["tool_requests"]
    if not isinstance(tool_requests, list) or len(tool_requests) > 64:
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcome tool requests exceed their closed bound",
            phase="entity_encode",
        )
    request_ids: list[str] = []
    for request in tool_requests:
        if (
            not isinstance(request, dict)
            or set(request)
            != {
                "schema_version",
                "request_id",
                "invocation",
                "affordance_snapshot_digest",
            }
            or request.get("schema_version") != "runtime_tool_request@1"
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_outcome_payload_invalid",
                "RuntimeTurnOutcome contains a non-closed tool request",
                phase="entity_encode",
            )
        _require_runtime_identifier(request["request_id"], field_name="request_id")
        _require_runtime_digest(
            request["affordance_snapshot_digest"],
            field_name="affordance_snapshot_digest",
        )
        assert isinstance(request["request_id"], str)
        request_ids.append(request["request_id"])
    if len(request_ids) != len(set(request_ids)):
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcome tool request IDs must be unique",
            phase="entity_encode",
        )
    failure = outcome["failure"]
    if failure is not None:
        if not isinstance(failure, dict):
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_outcome_payload_invalid",
                "RuntimeTurnOutcome failure must be an object",
                phase="entity_encode",
            )
        try:
            parsed = parse_failure_observation(failure)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_outcome_payload_invalid",
                "RuntimeTurnOutcome failure violates its closed contract",
                phase="entity_encode",
            ) from exc
        if (
            not isinstance(parsed, FailureObservation)
            or parsed.session_id != outcome["session_id"]
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_outcome_payload_invalid",
                "RuntimeTurnOutcome failure identity differs from the outcome",
                phase="entity_encode",
            )
    if (outcome["disposition"] == "failed") != (failure is not None):
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_payload_invalid",
            "RuntimeTurnOutcome failure and disposition must agree",
            phase="entity_encode",
        )
    canonical_outcome = dict(outcome)
    supplied_outcome_digest = canonical_outcome.pop("outcome_digest")
    if canonical_sha256_digest(canonical_outcome) != supplied_outcome_digest:
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_digest_mismatch",
            "RuntimeTurnOutcome digest differs from its closed payload",
            phase="entity_encode",
        )
    canonical_receipt = dict(thawed)
    supplied_receipt_digest = canonical_receipt.pop("receipt_digest")
    if canonical_sha256_digest(canonical_receipt) != supplied_receipt_digest:
        raise SQLiteControlStoreError(
            "sqlite_runtime_turn_outcome_digest_mismatch",
            "RuntimeTurnOutcomeReceipt digest differs from its closed payload",
            phase="entity_encode",
        )
    return thawed


class RuntimeTurnOutcomeSQLiteKernelEntityCodec(
    _ClosedResidentJSONSQLiteKernelEntityCodec
):
    entity_type = "runtime_turn_outcome"
    _table_name = "runtime_turn_outcome_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_column = "receipt_id"
    _identity_field = "receipt_id"
    _schema_version = "runtime_turn_outcome_receipt@1"
    _digest_field = "receipt_digest"
    _indexed_fields = (
        ("receipt_id", "receipt_id"),
        ("outcome_id", "outcome.outcome_id"),
        ("command_id", "outcome.command_id"),
        ("session_id", "outcome.session_id"),
        ("failure_id", "outcome.failure.failure_id"),
        ("outcome_digest", "outcome.outcome_digest"),
    )

    @classmethod
    def _normalize_payload(
        cls, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        return _normalize_runtime_turn_outcome_receipt(payload)

    @classmethod
    def session_id_for_ledger(
        cls,
        payload: Mapping[str, JsonValue],
    ) -> JsonValue:
        """Expose the receipt's closed nested Session identity to the CAS index."""

        normalized = cls._normalize_payload(payload)
        return cls._payload_index_value(normalized, "outcome.session_id")


class RuntimeTurnCommandSQLiteKernelEntityCodec(
    _CreateOnlyRuntimeSQLiteKernelEntityCodec
):
    """Persists bounded turn commands apart from legacy runtime.drain rows."""

    entity_type = "runtime_turn_command"
    _table_name = "runtime_turn_command_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_field = "command_id"
    _fields = (
        "command_id",
        "turn_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "signal_claim_token",
        "runtime_lease_token",
        "runtime_lease_generation",
        "runtime_fence",
        "process_epoch",
        "distribution_id",
        "distribution_manifest_digest",
        "release_digest",
        "adapter_bundle_digest",
        "extension_bundle_digest",
        "declared_tool_catalog_digest",
        "capability_binding_id",
        "capability_binding_revision",
        "capability_binding_digest",
        "affordance_snapshot_id",
        "affordance_snapshot_digest",
        "workflow_authority_id",
        "workflow_authority_epoch",
        "workflow_authority_digest",
        "signal_authority_link_digest",
        "tool_exposure_snapshot_id",
        "tool_exposure_snapshot_digest",
        "context",
        "runtime_adapter_id",
        "runtime_adapter_contract_digest",
        "max_steps",
        "max_duration_seconds",
        "max_input_units",
        "max_output_units",
        "messages",
        "task_id",
        "lane_id",
        "continuation_id",
        "command_digest",
        "schema_version",
    )
    _columns = tuple(
        (
            "messages_json"
            if field_name == "messages"
            else "context_json"
            if field_name == "context"
            else field_name
        )
        for field_name in _fields
    )
    _json_fields = frozenset({"context", "messages"})

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        _require_target_payload(
            payload,
            fields=cls._fields,
            identity_field=cls._identity_field,
            entity_id=entity_id,
            code="sqlite_runtime_turn_command_payload_invalid",
            subject="RuntimeTurnCommand",
        )
        if payload["schema_version"] != "runtime_turn_command@2":
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_command_payload_invalid",
                "RuntimeTurnCommand schema version is invalid",
                phase="entity_encode",
            )
        for field_name in (
            "command_id",
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "signal_claim_token",
            "runtime_lease_token",
            "distribution_id",
            "capability_binding_id",
            "affordance_snapshot_id",
            "workflow_authority_id",
            "tool_exposure_snapshot_id",
            "runtime_adapter_id",
        ):
            _require_runtime_identifier(payload[field_name], field_name=field_name)
        for field_name in ("task_id", "lane_id", "continuation_id"):
            if payload[field_name] is not None:
                _require_runtime_identifier(payload[field_name], field_name=field_name)
        for field_name in (
            "signal_attempt",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
            "capability_binding_revision",
            "workflow_authority_epoch",
            "max_steps",
            "max_duration_seconds",
            "max_input_units",
            "max_output_units",
        ):
            _require_positive_runtime_integer(
                payload[field_name], field_name=field_name
            )
        for field_name in (
            "distribution_manifest_digest",
            "release_digest",
            "adapter_bundle_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_digest",
            "affordance_snapshot_digest",
            "workflow_authority_digest",
            "signal_authority_link_digest",
            "tool_exposure_snapshot_digest",
            "runtime_adapter_contract_digest",
            "command_digest",
        ):
            _require_runtime_digest(payload[field_name], field_name=field_name)
        _validate_runtime_message_set(payload["messages"])
        context_value = payload["context"]
        if not isinstance(context_value, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_context_payload_invalid",
                "RuntimeTurnCommand context must be a closed object",
                phase="entity_encode",
            )
        try:
            context = RuntimeTurnContext.from_dict(json_compatible(context_value))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_context_payload_invalid",
                "RuntimeTurnCommand context violates its closed contract",
                phase="entity_encode",
            ) from exc
        if (
            context.session_id != payload["session_id"]
            or context.agent_id != payload["agent_id"]
            or context.agent_member_id != payload["agent_member_id"]
            or context.turn_id != payload["turn_id"]
            or context.signal_id != payload["signal_id"]
            or context.task_id != payload["task_id"]
            or context.lane_id != payload["lane_id"]
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_context_identity_mismatch",
                "RuntimeTurnCommand context identity differs from command",
                phase="entity_encode",
            )
        canonical = {
            key: payload[key] for key in cls._fields if key != "command_digest"
        }
        if canonical_sha256_digest(canonical) != payload["command_digest"]:
            raise SQLiteControlStoreError(
                "sqlite_runtime_turn_command_digest_mismatch",
                "RuntimeTurnCommand digest does not match its closed payload",
                phase="entity_encode",
            )


class RuntimeContinuationIntentSQLiteKernelEntityCodec(
    _CreateOnlyRuntimeSQLiteKernelEntityCodec
):
    entity_type = "runtime_continuation_intent"
    _table_name = "runtime_continuation_intent_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_field = "continuation_id"
    _fields = (
        "continuation_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "source_command_id",
        "source_command_digest",
        "source_outcome_id",
        "source_outcome_digest",
        "source_signal_id",
        "source_signal_authority_link_digest",
        "source_workflow_authority_id",
        "source_workflow_authority_epoch",
        "source_workflow_authority_binding_digest",
        "process_epoch",
        "release_digest",
        "extension_bundle_digest",
        "declared_tool_catalog_digest",
        "capability_binding_id",
        "capability_binding_revision",
        "capability_binding_digest",
        "affordance_snapshot_id",
        "affordance_snapshot_digest",
        "delivery_status",
        "delivery_attempt",
        "delivery_signal_id",
        "delivery_signal_authority_link_digest",
        "delivery_identity_digest",
        "created_at",
        "delivered_at",
        "recipient_runtime_executed",
        "fallback_performed",
        "schema_version",
    )
    _columns = _fields
    _boolean_fields = frozenset({"recipient_runtime_executed", "fallback_performed"})
    _mutable_delivery_fields = frozenset(
        {
            "delivery_status",
            "delivery_attempt",
            "delivery_signal_id",
            "delivery_signal_authority_link_digest",
            "delivery_identity_digest",
            "delivered_at",
        }
    )

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        _require_target_payload(
            payload,
            fields=cls._fields,
            identity_field=cls._identity_field,
            entity_id=entity_id,
            code="sqlite_runtime_continuation_intent_payload_invalid",
            subject="RuntimeContinuationIntent",
        )
        if payload["schema_version"] != "runtime_continuation_intent@1":
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_intent_payload_invalid",
                "RuntimeContinuationIntent schema version is invalid",
                phase="entity_encode",
            )
        for field_name in (
            "continuation_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "source_command_id",
            "source_outcome_id",
            "source_signal_id",
            "source_workflow_authority_id",
            "capability_binding_id",
            "affordance_snapshot_id",
        ):
            _require_runtime_identifier(payload[field_name], field_name=field_name)
        for field_name in (
            "source_command_digest",
            "source_outcome_digest",
            "source_signal_authority_link_digest",
            "source_workflow_authority_binding_digest",
            "release_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_digest",
            "affordance_snapshot_digest",
        ):
            _require_runtime_digest(payload[field_name], field_name=field_name)
        for field_name in (
            "process_epoch",
            "capability_binding_revision",
            "source_workflow_authority_epoch",
        ):
            _require_positive_runtime_integer(
                payload[field_name], field_name=field_name
            )
        if (
            not isinstance(payload["delivery_attempt"], int)
            or isinstance(payload["delivery_attempt"], bool)
            or payload["delivery_attempt"] not in {0, 1}
            or payload["delivery_status"] not in {"pending", "delivered"}
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_intent_payload_invalid",
                "RuntimeContinuationIntent delivery lifecycle is invalid",
                phase="entity_encode",
            )
        for field_name in ("recipient_runtime_executed", "fallback_performed"):
            if payload[field_name] is not False:
                raise SQLiteControlStoreError(
                    "sqlite_runtime_continuation_intent_payload_invalid",
                    "RuntimeContinuationIntent cannot record runtime execution or fallback",
                    phase="entity_encode",
                )
        cls._require_timestamp(payload["created_at"], field_name="created_at")
        delivery_fields = (
            payload["delivery_signal_id"],
            payload["delivery_signal_authority_link_digest"],
            payload["delivery_identity_digest"],
            payload["delivered_at"],
        )
        if payload["delivery_status"] == "pending":
            if payload["delivery_attempt"] != 0 or any(
                value is not None for value in delivery_fields
            ):
                raise SQLiteControlStoreError(
                    "sqlite_runtime_continuation_intent_payload_invalid",
                    "Pending RuntimeContinuationIntent carries delivery facts",
                    phase="entity_encode",
                )
            return
        if payload["delivery_attempt"] != 1 or any(
            value is None for value in delivery_fields
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_intent_payload_invalid",
                "Delivered RuntimeContinuationIntent lacks exact delivery facts",
                phase="entity_encode",
            )
        _require_runtime_identifier(
            payload["delivery_signal_id"],
            field_name="delivery_signal_id",
        )
        _require_runtime_digest(
            payload["delivery_signal_authority_link_digest"],
            field_name="delivery_signal_authority_link_digest",
        )
        _require_runtime_digest(
            payload["delivery_identity_digest"],
            field_name="delivery_identity_digest",
        )
        cls._require_timestamp(payload["delivered_at"], field_name="delivered_at")

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        self._validate_source_authority_graph(connection, payload)
        if mutation.kind is KernelMutationKind.CREATE:
            super().apply(
                connection,
                mutation=mutation,
                next_state_version=next_state_version,
            )
            return
        if mutation.kind is not KernelMutationKind.REPLACE:
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_intent_transition_invalid",
                "RuntimeContinuationIntent cannot be deleted",
                phase="entity_apply",
            )
        current = self.read(connection, entity_id=mutation.entity_id)
        if current is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "RuntimeContinuationIntent disappeared before replacement",
                phase="entity_apply",
            )
        immutable_fields = set(self._fields).difference(self._mutable_delivery_fields)
        if any(
            current.payload[field_name] != payload[field_name]
            for field_name in immutable_fields
        ) or (
            current.payload["delivery_status"] != "pending"
            or payload["delivery_status"] != "delivered"
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_intent_transition_invalid",
                "RuntimeContinuationIntent replacement is not pending-to-delivered",
                phase="entity_apply",
            )
        self._validate_delivery_authority_graph(connection, payload)
        cursor = connection.execute(
            """
            UPDATE runtime_continuation_intent_records
            SET delivery_status = ?, delivery_attempt = ?, delivery_signal_id = ?,
                delivery_signal_authority_link_digest = ?,
                delivery_identity_digest = ?, delivered_at = ?
            WHERE continuation_id = ?
            """,
            (
                payload["delivery_status"],
                payload["delivery_attempt"],
                payload["delivery_signal_id"],
                payload["delivery_signal_authority_link_digest"],
                payload["delivery_identity_digest"],
                payload["delivered_at"],
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "RuntimeContinuationIntent disappeared before replacement",
                phase="entity_apply",
            )

    @staticmethod
    def _require_timestamp(value: JsonValue, *, field_name: str) -> None:
        try:
            if not isinstance(value, str):
                raise ValueError
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_intent_payload_invalid",
                f"RuntimeContinuationIntent {field_name} must include a timezone",
                phase="entity_encode",
            ) from exc

    @staticmethod
    def _validate_source_authority_graph(
        connection: sqlite3.Connection,
        payload: Mapping[str, JsonValue],
    ) -> None:
        link = connection.execute(
            """
            SELECT authority_id, authority_epoch, link_digest
            FROM runtime_signal_authority_link_records
            WHERE signal_id = ?
            """,
            (payload["source_signal_id"],),
        ).fetchone()
        binding = connection.execute(
            """
            SELECT status, epoch, binding_digest
            FROM workflow_authority_binding_records
            WHERE authority_id = ?
            """,
            (payload["source_workflow_authority_id"],),
        ).fetchone()
        if link != (
            payload["source_workflow_authority_id"],
            payload["source_workflow_authority_epoch"],
            payload["source_signal_authority_link_digest"],
        ) or binding != (
            WorkflowAuthorityStatus.ACTIVE.value,
            payload["source_workflow_authority_epoch"],
            payload["source_workflow_authority_binding_digest"],
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_source_authority_stale",
                "RuntimeContinuationIntent source authority graph is missing or stale",
                phase="entity_encode",
            )

    @staticmethod
    def _validate_delivery_authority_graph(
        connection: sqlite3.Connection,
        payload: Mapping[str, JsonValue],
    ) -> None:
        row = connection.execute(
            """
            SELECT payload_json, link_digest
            FROM runtime_signal_authority_link_records
            WHERE signal_id = ?
            """,
            (payload["delivery_signal_id"],),
        ).fetchone()
        if row is None:
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_delivery_link_missing",
                "RuntimeContinuationIntent delivery link is absent",
                phase="entity_encode",
            )
        value = _decode_json(
            row[0],
            code="sqlite_runtime_continuation_delivery_link_invalid",
            subject="RuntimeContinuationIntent delivery link",
        )
        try:
            if not isinstance(value, Mapping):
                raise ValueError
            link = RuntimeSignalAuthorityLink.from_dict(json_compatible(value))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_delivery_link_invalid",
                "RuntimeContinuationIntent delivery link violates its closed contract",
                phase="entity_encode",
            ) from exc
        if (
            row[1] != payload["delivery_signal_authority_link_digest"]
            or link.signal_id != payload["delivery_signal_id"]
            or link.session_id != payload["session_id"]
            or link.authority_id != payload["source_workflow_authority_id"]
            or link.authority_epoch != payload["source_workflow_authority_epoch"]
            or link.authority_binding_digest
            != payload["source_workflow_authority_binding_digest"]
            or link.causation_ref != payload["continuation_id"]
            or link.source_kind.value != "continuation_delivery"
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_continuation_delivery_link_invalid",
                "RuntimeContinuationIntent delivery link identity drifted",
                phase="entity_encode",
            )


class RuntimeSettlementIntentSQLiteKernelEntityCodec(
    _CreateOnlyRuntimeSQLiteKernelEntityCodec
):
    entity_type = "runtime_settlement_intent"
    _table_name = "runtime_settlement_intent_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_field = "settlement_id"
    _fields = (
        "settlement_id",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "source_command_id",
        "source_command_digest",
        "source_outcome_id",
        "source_outcome_digest",
        "disposition",
        "waiting_approval_id",
        "failure_id",
        "task_transition_performed",
        "schema_version",
    )
    _columns = _fields
    _boolean_fields = frozenset({"task_transition_performed"})

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        _require_target_payload(
            payload,
            fields=cls._fields,
            identity_field=cls._identity_field,
            entity_id=entity_id,
            code="sqlite_runtime_settlement_intent_payload_invalid",
            subject="RuntimeSettlementIntent",
        )
        if payload["schema_version"] != "runtime_settlement_intent@1":
            raise SQLiteControlStoreError(
                "sqlite_runtime_settlement_intent_payload_invalid",
                "RuntimeSettlementIntent schema version is invalid",
                phase="entity_encode",
            )
        for field_name in (
            "settlement_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "source_command_id",
            "source_outcome_id",
        ):
            _require_runtime_identifier(payload[field_name], field_name=field_name)
        for field_name in ("waiting_approval_id", "failure_id"):
            if payload[field_name] is not None:
                _require_runtime_identifier(payload[field_name], field_name=field_name)
        for field_name in ("source_command_digest", "source_outcome_digest"):
            _require_runtime_digest(payload[field_name], field_name=field_name)
        _require_positive_runtime_integer(
            payload["signal_attempt"], field_name="signal_attempt"
        )
        if (
            payload["disposition"]
            not in {
                "ready_for_next_step",
                "waiting_approval",
                "waiting_continuation",
                "idle",
                "step_limit_reached",
                "failed",
            }
            or payload["task_transition_performed"] is not False
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_settlement_intent_payload_invalid",
                "RuntimeSettlementIntent disposition or Task-transition fact is invalid",
                phase="entity_encode",
            )


class RuntimeOutcomeConsumptionSQLiteKernelEntityCodec(
    _CreateOnlyRuntimeSQLiteKernelEntityCodec
):
    entity_type = "runtime_outcome_consumption"
    _table_name = "runtime_outcome_consumption_records"
    table_names = (_table_name, "openzyme_store_kernel_entity_versions")
    _identity_field = "command_id"
    _fields = (
        "command_id",
        "consumption_id",
        "command_digest",
        "outcome_id",
        "outcome_digest",
        "outcome_receipt",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "continuation_intent",
        "settlement_intent",
        "consumed_at",
        "consumption_digest",
        "schema_version",
    )
    _columns = (
        "command_id",
        "consumption_id",
        "command_digest",
        "outcome_id",
        "outcome_digest",
        "outcome_receipt_json",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "continuation_intent_json",
        "settlement_intent_json",
        "consumed_at",
        "consumption_digest",
        "schema_version",
    )
    _json_fields = frozenset(
        {"outcome_receipt", "continuation_intent", "settlement_intent"}
    )

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                self._immutable_code,
                "runtime_outcome_consumption records are create-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate_payload(payload, entity_id=mutation.entity_id)
        receipt = payload["outcome_receipt"]
        assert isinstance(receipt, Mapping)
        normalized_receipt = _normalize_runtime_turn_outcome_receipt(receipt)
        outcome = normalized_receipt["outcome"]
        assert isinstance(outcome, Mapping)
        continuation = payload["continuation_intent"]
        settlement = payload["settlement_intent"]
        assert isinstance(settlement, Mapping)
        stored_receipt = connection.execute(
            """
            SELECT outcome_id, command_id, session_id, outcome_digest,
                   receipt_digest, payload_json
            FROM runtime_turn_outcome_records
            WHERE receipt_id = ?
            """,
            (normalized_receipt["receipt_id"],),
        ).fetchone()
        expected_receipt = (
            outcome["outcome_id"],
            outcome["command_id"],
            outcome["session_id"],
            outcome["outcome_digest"],
            normalized_receipt["receipt_digest"],
            _canonical_json(normalized_receipt),
        )
        if stored_receipt != expected_receipt:
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_receipt_missing",
                "RuntimeOutcomeConsumption requires the exact durable outcome receipt",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO runtime_outcome_consumption_records
            (command_id, consumption_id, command_digest, outcome_id,
             outcome_digest, outcome_receipt_id, outcome_receipt_json,
             session_id, agent_id, agent_member_id, signal_id, signal_attempt,
             continuation_intent_id, continuation_intent_json,
             settlement_intent_id, settlement_intent_json, consumed_at,
             consumption_digest, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["command_id"],
                payload["consumption_id"],
                payload["command_digest"],
                payload["outcome_id"],
                payload["outcome_digest"],
                normalized_receipt["receipt_id"],
                _canonical_json(normalized_receipt),
                payload["session_id"],
                payload["agent_id"],
                payload["agent_member_id"],
                payload["signal_id"],
                payload["signal_attempt"],
                None if continuation is None else continuation["continuation_id"],
                None if continuation is None else _canonical_json(continuation),
                settlement["settlement_id"],
                _canonical_json(settlement),
                payload["consumed_at"],
                payload["consumption_digest"],
                payload["schema_version"],
            ),
        )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT r.command_id, r.consumption_id, r.command_digest,
                   r.outcome_id, r.outcome_digest, r.outcome_receipt_id,
                   r.outcome_receipt_json, r.session_id, r.agent_id,
                   r.agent_member_id, r.signal_id, r.signal_attempt,
                   r.continuation_intent_id, r.continuation_intent_json,
                   r.settlement_intent_id, r.settlement_intent_json,
                   r.consumed_at, r.consumption_digest, r.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM runtime_outcome_consumption_records AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'runtime_outcome_consumption'
             AND v.entity_id = r.command_id
            WHERE r.command_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[19] is None or row[21] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "RuntimeOutcomeConsumption row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        continuation = (
            None
            if row[13] is None
            else _decode_json(
                row[13],
                code="sqlite_runtime_coordination_json_invalid",
                subject="RuntimeOutcomeConsumption continuation",
            )
        )
        settlement = _decode_json(
            row[15],
            code="sqlite_runtime_coordination_json_invalid",
            subject="RuntimeOutcomeConsumption settlement",
        )
        if (
            (
                continuation is not None
                and (
                    not isinstance(continuation, Mapping)
                    or continuation.get("continuation_id") != row[12]
                )
            )
            or not isinstance(settlement, Mapping)
            or settlement.get("settlement_id") != row[14]
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_reference_mismatch",
                "RuntimeOutcomeConsumption JSON differs from its explicit intent refs",
                phase="entity_decode",
            )
        receipt = _decode_json(
            row[6],
            code="sqlite_runtime_coordination_json_invalid",
            subject="RuntimeOutcomeConsumption outcome receipt",
        )
        if not isinstance(receipt, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_reference_mismatch",
                "RuntimeOutcomeConsumption receipt must be an object",
                phase="entity_decode",
            )
        normalized_receipt = _normalize_runtime_turn_outcome_receipt(receipt)
        if normalized_receipt["receipt_id"] != row[5]:
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_reference_mismatch",
                "RuntimeOutcomeConsumption receipt identity differs from its explicit ref",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "command_id": row[0],
            "consumption_id": row[1],
            "command_digest": row[2],
            "outcome_id": row[3],
            "outcome_digest": row[4],
            "outcome_receipt": normalized_receipt,
            "session_id": row[7],
            "agent_id": row[8],
            "agent_member_id": row[9],
            "signal_id": row[10],
            "signal_attempt": row[11],
            "continuation_intent": continuation,
            "settlement_intent": settlement,
            "consumed_at": row[16],
            "consumption_digest": row[17],
            "schema_version": row[18],
        }
        self._validate_payload(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[19]),
            payload=payload,
        )
        if snapshot.record_digest != row[20]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "RuntimeOutcomeConsumption differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    @classmethod
    def _validate_payload(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> None:
        _require_target_payload(
            payload,
            fields=cls._fields,
            identity_field=cls._identity_field,
            entity_id=entity_id,
            code="sqlite_runtime_outcome_consumption_payload_invalid",
            subject="RuntimeOutcomeConsumption",
        )
        if payload["schema_version"] != "runtime_outcome_consumption@2":
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_payload_invalid",
                "RuntimeOutcomeConsumption schema version is invalid",
                phase="entity_encode",
            )
        for field_name in (
            "command_id",
            "consumption_id",
            "outcome_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
        ):
            _require_runtime_identifier(payload[field_name], field_name=field_name)
        for field_name in (
            "command_digest",
            "outcome_digest",
            "consumption_digest",
        ):
            _require_runtime_digest(payload[field_name], field_name=field_name)
        _require_positive_runtime_integer(
            payload["signal_attempt"], field_name="signal_attempt"
        )
        receipt = payload["outcome_receipt"]
        if not isinstance(receipt, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_payload_invalid",
                "RuntimeOutcomeConsumption outcome receipt must be an object",
                phase="entity_encode",
            )
        normalized_receipt = _normalize_runtime_turn_outcome_receipt(receipt)
        outcome = normalized_receipt["outcome"]
        assert isinstance(outcome, Mapping)
        expected_outcome_identity = {
            "command_id": payload["command_id"],
            "command_digest": payload["command_digest"],
            "outcome_id": payload["outcome_id"],
            "outcome_digest": payload["outcome_digest"],
            "session_id": payload["session_id"],
            "agent_id": payload["agent_id"],
            "agent_member_id": payload["agent_member_id"],
            "signal_id": payload["signal_id"],
            "signal_attempt": payload["signal_attempt"],
        }
        if any(
            outcome.get(key) != expected
            for key, expected in expected_outcome_identity.items()
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_reference_mismatch",
                "RuntimeOutcomeConsumption receipt identities do not match",
                phase="entity_encode",
            )
        try:
            consumed_at = payload["consumed_at"]
            if not isinstance(consumed_at, str):
                raise ValueError
            instant = datetime.fromisoformat(consumed_at.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_payload_invalid",
                "RuntimeOutcomeConsumption consumed_at must include a timezone",
                phase="entity_encode",
            ) from exc
        continuation = payload["continuation_intent"]
        if continuation is not None:
            if not isinstance(continuation, Mapping):
                raise SQLiteControlStoreError(
                    "sqlite_runtime_outcome_consumption_payload_invalid",
                    "RuntimeOutcomeConsumption continuation must be an object",
                    phase="entity_encode",
                )
            RuntimeContinuationIntentSQLiteKernelEntityCodec._validate_payload(
                continuation,
                entity_id=str(continuation.get("continuation_id")),
            )
        settlement = payload["settlement_intent"]
        if not isinstance(settlement, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_payload_invalid",
                "RuntimeOutcomeConsumption settlement must be an object",
                phase="entity_encode",
            )
        RuntimeSettlementIntentSQLiteKernelEntityCodec._validate_payload(
            settlement,
            entity_id=str(settlement.get("settlement_id")),
        )
        for nested in tuple(item for item in (continuation, settlement) if item):
            assert isinstance(nested, Mapping)
            expected = {
                "session_id": payload["session_id"],
                "agent_id": payload["agent_id"],
                "agent_member_id": payload["agent_member_id"],
                "source_command_id": payload["command_id"],
                "source_command_digest": payload["command_digest"],
                "source_outcome_id": payload["outcome_id"],
                "source_outcome_digest": payload["outcome_digest"],
            }
            if any(nested.get(key) != value for key, value in expected.items()):
                raise SQLiteControlStoreError(
                    "sqlite_runtime_outcome_consumption_reference_mismatch",
                    "RuntimeOutcomeConsumption intent identities do not match",
                    phase="entity_encode",
                )
        assert isinstance(settlement, Mapping)
        if (
            settlement.get("signal_id") != payload["signal_id"]
            or settlement.get("signal_attempt") != payload["signal_attempt"]
            or settlement.get("disposition") != outcome.get("disposition")
            or settlement.get("waiting_approval_id")
            != outcome.get("waiting_approval_id")
            or settlement.get("failure_id")
            != (
                None
                if outcome.get("failure") is None
                else outcome["failure"].get("failure_id")
            )
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_reference_mismatch",
                "RuntimeOutcomeConsumption settlement signal identity does not match",
                phase="entity_encode",
            )
        expected_continuation_id = outcome.get("continuation_id")
        if (continuation is None) != (expected_continuation_id is None) or (
            continuation is not None
            and continuation.get("continuation_id") != expected_continuation_id
        ):
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_reference_mismatch",
                "RuntimeOutcomeConsumption continuation differs from its outcome",
                phase="entity_encode",
            )
        canonical = {
            key: payload[key] for key in cls._fields if key != "consumption_digest"
        }
        if canonical_sha256_digest(canonical) != payload["consumption_digest"]:
            raise SQLiteControlStoreError(
                "sqlite_runtime_outcome_consumption_digest_mismatch",
                "RuntimeOutcomeConsumption digest does not match its closed payload",
                phase="entity_encode",
            )


class SessionSQLiteKernelEntityCodec:
    """Maps the target Session record to the existing ``sessions`` table."""

    entity_type = "session"
    owner_id = "openzyme.kernel"
    table_names = ("sessions", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "session_id",
        "project_id",
        "title",
        "objective",
        "status",
        "created_at",
        "updated_at",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT s.session_id, s.project_id, s.title, s.objective, s.status,
                   s.created_at, s.updated_at, v.state_version, v.record_digest,
                   v.owner_component_id
            FROM sessions AS s
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'session' AND v.entity_id = s.session_id
            WHERE s.session_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[7] is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Session owner row lacks target CAS metadata",
                phase="entity_decode",
            )
        if row[9] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_owner_mismatch",
                "Session CAS metadata names another semantic owner",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[7]),
            payload=payload,
        )
        if snapshot.record_digest != row[8]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Session owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (mutation.entity_id,)
            )
            return
        payload = self._payload(mutation)
        values = tuple(payload[field] for field in self._FIELDS)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO sessions
                (session_id, project_id, title, objective, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE sessions
            SET project_id = ?, title = ?, objective = ?, status = ?,
                created_at = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                payload["project_id"],
                payload["title"],
                payload["objective"],
                payload["status"],
                payload["created_at"],
                payload["updated_at"],
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Session owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != set(self._FIELDS):
            raise SQLiteControlStoreError(
                "sqlite_session_payload_invalid",
                "Session payload differs from the explicit existing-table codec",
                phase="entity_encode",
            )
        if mutation.payload["session_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_identity_mismatch",
                "Session payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload


class LaneSQLiteKernelEntityCodec:
    """Maps the target Lane record to the existing ``lanes`` owner table."""

    entity_type = "lane"
    owner_id = "openzyme.kernel"
    table_names = ("lanes", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "lane_id",
        "session_id",
        "name",
        "workspace_binding_id",
        "status",
        "created_at",
        "updated_at",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT l.lane_id, l.session_id, l.name, l.workspace_binding_id,
                   l.status, l.created_at, l.updated_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM lanes AS l
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'lane' AND v.entity_id = l.lane_id
            WHERE l.lane_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[7] is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Lane owner row lacks target CAS metadata",
                phase="entity_decode",
            )
        if row[9] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_owner_mismatch",
                "Lane CAS metadata names another semantic owner",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[7]),
            payload=payload,
        )
        if snapshot.record_digest != row[8]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Lane owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM lanes WHERE lane_id = ?", (mutation.entity_id,)
            )
            return
        payload = self._payload(mutation)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO lanes
                (lane_id, session_id, name, status, cwd, branch_name, claimed_ref,
                 workspace_binding_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, '.', NULL, NULL, ?, ?, ?)
                """,
                (
                    payload["lane_id"],
                    payload["session_id"],
                    payload["name"],
                    payload["status"],
                    payload["workspace_binding_id"],
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )
            return
        cursor = connection.execute(
            """
            UPDATE lanes
            SET session_id = ?, name = ?, status = ?, workspace_binding_id = ?,
                created_at = ?, updated_at = ?
            WHERE lane_id = ?
            """,
            (
                payload["session_id"],
                payload["name"],
                payload["status"],
                payload["workspace_binding_id"],
                payload["created_at"],
                payload["updated_at"],
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Lane owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != set(self._FIELDS):
            raise SQLiteControlStoreError(
                "sqlite_lane_payload_invalid",
                "Lane payload differs from the explicit existing-table codec",
                phase="entity_encode",
            )
        if mutation.payload["lane_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_lane_identity_mismatch",
                "Lane payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload


class AgentMemberSQLiteKernelEntityCodec:
    """Maps the target Agent roster record to ``agent_members``."""

    entity_type = "agent_member"
    owner_id = "openzyme.kernel"
    table_names = ("agent_members", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = frozenset(
        {
            "agent_member_id",
            "agent_id",
            "session_id",
            "parent_agent_id",
            "lane_id",
            "name",
            "role",
            "status",
            "process_epoch",
            "active_authority_lease_id",
            "workspace_generation",
            "owned_task_ids",
            "retirement_reason",
            "terminal_proof_digest",
            "retirement_settled",
            "retired_at",
            "created_at",
            "updated_at",
        }
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT m.member_id, m.agent_id, m.session_id, m.parent_agent_id,
                   m.lane_id, m.name, m.role, m.status, m.process_epoch,
                   m.active_authority_lease_id, m.workspace_generation,
                   m.owned_task_ids_json, m.retirement_reason,
                   m.terminal_proof_digest, m.retirement_settled, m.retired_at,
                   m.created_at, m.updated_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM agent_members AS m
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'agent_member' AND v.entity_id = m.member_id
            WHERE m.member_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        self._require_ledger(row, state_index=18, owner_index=20)
        payload: Mapping[str, JsonValue] = {
            "agent_member_id": row[0],
            "agent_id": row[1],
            "session_id": row[2],
            "parent_agent_id": row[3],
            "lane_id": row[4],
            "name": row[5],
            "role": row[6],
            "status": row[7],
            "process_epoch": row[8],
            "active_authority_lease_id": row[9],
            "workspace_generation": row[10],
            "owned_task_ids": self._string_array(row[11]),
            "retirement_reason": row[12],
            "terminal_proof_digest": row[13],
            "retirement_settled": bool(row[14]),
            "retired_at": row[15],
            "created_at": row[16],
            "updated_at": row[17],
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[18]),
            payload=payload,
        )
        if snapshot.record_digest != row[19]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "AgentMember owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM agent_members WHERE member_id = ?", (mutation.entity_id,)
            )
            return
        payload = self._payload(mutation)
        values = (
            payload["agent_id"],
            payload["session_id"],
            payload["lane_id"],
            payload["name"],
            payload["role"],
            payload["status"],
            payload["parent_agent_id"],
            payload["process_epoch"],
            payload["active_authority_lease_id"],
            payload["workspace_generation"],
            self._json(payload["owned_task_ids"]),
            payload["retirement_reason"],
            payload["terminal_proof_digest"],
            int(bool(payload["retirement_settled"])),
            payload["retired_at"],
            payload["created_at"],
            payload["updated_at"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO agent_members
                (member_id, agent_id, session_id, lane_id, task_id, name, role,
                 status, parent_agent_id, process_epoch, active_authority_lease_id,
                 workspace_generation, owned_task_ids_json, retirement_reason,
                 terminal_proof_digest, retirement_settled, retired_at, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (payload["agent_member_id"], *values),
            )
            return
        cursor = connection.execute(
            """
            UPDATE agent_members
            SET agent_id = ?, session_id = ?, lane_id = ?, name = ?, role = ?,
                status = ?, parent_agent_id = ?, process_epoch = ?,
                active_authority_lease_id = ?, workspace_generation = ?,
                owned_task_ids_json = ?, retirement_reason = ?,
                terminal_proof_digest = ?, retirement_settled = ?, retired_at = ?,
                created_at = ?, updated_at = ?
            WHERE member_id = ?
            """,
            (*values, mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "AgentMember owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != self._FIELDS:
            raise SQLiteControlStoreError(
                "sqlite_agent_member_payload_invalid",
                "AgentMember payload differs from the explicit existing-table codec",
                phase="entity_encode",
            )
        if mutation.payload["agent_member_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_agent_member_identity_mismatch",
                "AgentMember payload identity differs from its mutation",
                phase="entity_encode",
            )
        owned = mutation.payload["owned_task_ids"]
        if (
            not isinstance(owned, tuple | list)
            or any(not isinstance(item, str) for item in owned)
            or len(set(owned)) != len(owned)
        ):
            raise SQLiteControlStoreError(
                "sqlite_agent_member_owned_tasks_invalid",
                "AgentMember owned Task identities must be a unique string array",
                phase="entity_encode",
            )
        if not isinstance(mutation.payload["retirement_settled"], bool):
            raise SQLiteControlStoreError(
                "sqlite_agent_member_retirement_invalid",
                "AgentMember retirement settlement must be boolean",
                phase="entity_encode",
            )
        return mutation.payload

    def _require_ledger(
        self,
        row: sqlite3.Row | tuple[object, ...],
        *,
        state_index: int,
        owner_index: int,
    ) -> None:
        if row[state_index] is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "AgentMember owner row lacks target CAS metadata",
                phase="entity_decode",
            )
        if row[owner_index] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_owner_mismatch",
                "AgentMember CAS metadata names another semantic owner",
                phase="entity_decode",
            )

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _string_array(value: object) -> list[str]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_agent_member_owned_tasks_invalid",
                "AgentMember owned Task identities are not valid JSON",
                phase="entity_decode",
            ) from exc
        if not isinstance(decoded, list) or any(
            not isinstance(item, str) for item in decoded
        ):
            raise SQLiteControlStoreError(
                "sqlite_agent_member_owned_tasks_invalid",
                "AgentMember owned Task identities must be a string array",
                phase="entity_decode",
            )
        return decoded


class ConversationMessageSQLiteKernelEntityCodec:
    """Maps canonical conversation facts to the existing document owner table."""

    entity_type = "conversation_message"
    owner_id = "openzyme.kernel"
    table_names = ("engine_documents", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = frozenset(
        {
            "message_id",
            "session_id",
            "sender_actor_id",
            "admitted_by_actor_id",
            "sender_kind",
            "content",
            "message_type",
            "correlation_id",
            "task_id",
            "lane_id",
            "request_lineage_id",
            "workflow_refs",
            "skill_keys",
            "created_at",
        }
    )
    _DOCUMENT_FIELDS = frozenset(
        {
            "sender_actor_id",
            "admitted_by_actor_id",
            "sender_kind",
            "content",
            "message_type",
            "correlation_id",
            "task_id",
            "lane_id",
            "request_lineage_id",
            "workflow_refs",
            "skill_keys",
        }
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT d.document_id, d.session_id, d.invocation_id, d.document_kind,
                   d.payload_json, d.created_at, d.updated_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM engine_documents AS d
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'conversation_message'
             AND v.entity_id = d.document_id
            WHERE d.document_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[2] is not None or row[3] != "conversation_message" or row[6] != row[5]:
            raise SQLiteControlStoreError(
                "sqlite_conversation_owner_shape_invalid",
                "Conversation document owner row has incompatible legacy fields",
                phase="entity_decode",
            )
        if row[7] is None or row[9] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Conversation owner row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        document = self._document_payload(row[4])
        payload: Mapping[str, JsonValue] = {
            "message_id": row[0],
            "session_id": row[1],
            **document,
            "created_at": row[5],
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[7]),
            payload=payload,
        )
        if snapshot.record_digest != row[8]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Conversation owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM engine_documents WHERE document_id = ?",
                (mutation.entity_id,),
            )
            return
        payload = self._payload(mutation)
        document = self._json(
            {field: payload[field] for field in sorted(self._DOCUMENT_FIELDS)}
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO engine_documents
                (document_id, session_id, invocation_id, document_kind,
                 payload_json, created_at, updated_at)
                VALUES (?, ?, NULL, 'conversation_message', ?, ?, ?)
                """,
                (
                    payload["message_id"],
                    payload["session_id"],
                    document,
                    payload["created_at"],
                    payload["created_at"],
                ),
            )
            return
        cursor = connection.execute(
            """
            UPDATE engine_documents
            SET session_id = ?, invocation_id = NULL,
                document_kind = 'conversation_message', payload_json = ?,
                created_at = ?, updated_at = ?
            WHERE document_id = ?
            """,
            (
                payload["session_id"],
                document,
                payload["created_at"],
                payload["created_at"],
                mutation.entity_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Conversation owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != self._FIELDS:
            raise SQLiteControlStoreError(
                "sqlite_conversation_payload_invalid",
                "Conversation payload differs from the explicit document codec",
                phase="entity_encode",
            )
        if mutation.payload["message_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_conversation_identity_mismatch",
                "Conversation payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _document_payload(self, value: object) -> Mapping[str, JsonValue]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_conversation_document_invalid",
                "Conversation document payload is not valid JSON",
                phase="entity_decode",
            ) from exc
        if not isinstance(decoded, dict) or set(decoded) != self._DOCUMENT_FIELDS:
            raise SQLiteControlStoreError(
                "sqlite_conversation_document_invalid",
                "Conversation document payload differs from the closed target shape",
                phase="entity_decode",
            )
        return decoded


class ProtocolRecordSQLiteKernelEntityCodec:
    """Maps delegation/send/handoff facts to one stable protocol entity type."""

    entity_type = "protocol_record"
    owner_id = "openzyme.kernel"
    table_names = ("engine_documents", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = frozenset(
        {
            "protocol_ref",
            "session_id",
            "sender_actor_id",
            "recipient_actor_id",
            "operation",
            "payload",
            "status",
            "created_at",
            "recipient_runtime_executed",
            "task_transition_performed",
        }
    )
    _DOCUMENT_FIELDS = _FIELDS.difference({"protocol_ref", "session_id", "created_at"})

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT d.document_id, d.session_id, d.invocation_id, d.document_kind,
                   d.payload_json, d.created_at, d.updated_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM engine_documents AS d
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'protocol_record' AND v.entity_id = d.document_id
            WHERE d.document_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[2] is not None or row[3] != "protocol_record" or row[6] != row[5]:
            raise SQLiteControlStoreError(
                "sqlite_protocol_owner_shape_invalid",
                "Protocol document owner row has incompatible legacy fields",
                phase="entity_decode",
            )
        if row[7] is None or row[9] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Protocol owner row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        document = self._document_payload(row[4])
        payload: Mapping[str, JsonValue] = {
            "protocol_ref": row[0],
            "session_id": row[1],
            **document,
            "created_at": row[5],
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[7]),
            payload=payload,
        )
        if snapshot.record_digest != row[8]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Protocol owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM engine_documents WHERE document_id = ?",
                (mutation.entity_id,),
            )
            return
        payload = self._payload(mutation)
        document = self._json(
            {field: payload[field] for field in sorted(self._DOCUMENT_FIELDS)}
        )
        values = (
            payload["session_id"],
            document,
            payload["created_at"],
            payload["created_at"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO engine_documents
                (document_id, session_id, invocation_id, document_kind,
                 payload_json, created_at, updated_at)
                VALUES (?, ?, NULL, 'protocol_record', ?, ?, ?)
                """,
                (payload["protocol_ref"], *values),
            )
            return
        cursor = connection.execute(
            """
            UPDATE engine_documents
            SET session_id = ?, invocation_id = NULL,
                document_kind = 'protocol_record', payload_json = ?,
                created_at = ?, updated_at = ?
            WHERE document_id = ?
            """,
            (*values, mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Protocol owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != self._FIELDS:
            raise SQLiteControlStoreError(
                "sqlite_protocol_payload_invalid",
                "Protocol payload differs from the explicit document codec",
                phase="entity_encode",
            )
        if mutation.payload["protocol_ref"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_protocol_identity_mismatch",
                "Protocol payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _document_payload(self, value: object) -> Mapping[str, JsonValue]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_protocol_document_invalid",
                "Protocol document payload is not valid JSON",
                phase="entity_decode",
            ) from exc
        if not isinstance(decoded, dict) or set(decoded) != self._DOCUMENT_FIELDS:
            raise SQLiteControlStoreError(
                "sqlite_protocol_document_invalid",
                "Protocol document payload differs from the closed target shape",
                phase="entity_decode",
            )
        return decoded


class InboxMessageSQLiteKernelEntityCodec:
    """Maps one delivered Protocol inbox fact to ``inbox_messages``."""

    entity_type = "inbox_message"
    owner_id = "openzyme.kernel"
    table_names = ("inbox_messages", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "message_id",
        "session_id",
        "sender_actor_id",
        "sender_kind",
        "recipient_actor_id",
        "protocol_ref",
        "message_type",
        "correlation_id",
        "status",
        "created_at",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT i.message_id, i.session_id, i.sender, i.sender_kind,
                   i.recipient, i.recipient_kind, i.payload_ref, i.message_type,
                   i.correlation_id, i.status, i.created_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM inbox_messages AS i
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'inbox_message' AND v.entity_id = i.message_id
            WHERE i.message_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[3] not in {"agent", "user"} or row[5] != "agent" or row[6] is None:
            raise SQLiteControlStoreError(
                "sqlite_inbox_owner_shape_invalid",
                "Inbox owner row is not an Agent Protocol delivery",
                phase="entity_decode",
            )
        if row[11] is None or row[13] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Inbox owner row lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            "message_id": row[0],
            "session_id": row[1],
            "sender_actor_id": row[2],
            "sender_kind": row[3],
            "recipient_actor_id": row[4],
            "protocol_ref": row[6],
            "message_type": row[7],
            "correlation_id": row[8],
            "status": row[9],
            "created_at": row[10],
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[11]),
            payload=payload,
        )
        if snapshot.record_digest != row[12]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Inbox owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM inbox_messages WHERE message_id = ?", (mutation.entity_id,)
            )
            return
        payload = self._payload(mutation)
        values = (
            payload["session_id"],
            payload["sender_actor_id"],
            payload["sender_kind"],
            payload["recipient_actor_id"],
            payload["message_type"],
            payload["correlation_id"],
            payload["protocol_ref"],
            payload["status"],
            payload["created_at"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO inbox_messages
                (message_id, session_id, sender, sender_kind, recipient,
                 recipient_kind, message_type, correlation_id, payload_ref,
                 status, created_at)
                VALUES (?, ?, ?, ?, ?, 'agent', ?, ?, ?, ?, ?)
                """,
                (payload["message_id"], *values),
            )
            return
        cursor = connection.execute(
            """
            UPDATE inbox_messages
            SET session_id = ?, sender = ?, sender_kind = ?, recipient = ?,
                recipient_kind = 'agent', message_type = ?, correlation_id = ?,
                payload_ref = ?, status = ?, created_at = ?
            WHERE message_id = ?
            """,
            (*values, mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Inbox owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != set(self._FIELDS):
            raise SQLiteControlStoreError(
                "sqlite_inbox_payload_invalid",
                "Inbox payload differs from the explicit existing-table codec",
                phase="entity_encode",
            )
        if mutation.payload["message_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_inbox_identity_mismatch",
                "Inbox payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload


class MemorySQLiteKernelEntityCodec:
    """Maps canonical Memory facts to ``memory_entries``."""

    entity_type = "memory"
    owner_id = "openzyme.kernel"
    table_names = ("memory_entries", "openzyme_store_kernel_entity_versions")
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = (
        "memory_id",
        "session_id",
        "scope_kind",
        "scope_ref",
        "kind",
        "summary",
        "source_range",
        "author_actor_id",
        "created_at",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT m.memory_id, m.session_id, m.scope_kind, m.scope_ref, m.kind,
                   m.summary, m.source_range, m.author_actor_id, m.created_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM memory_entries AS m
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'memory' AND v.entity_id = m.memory_id
            WHERE m.memory_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[7] is None or row[9] is None or row[11] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Memory owner row lacks exact target identity or CAS metadata",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            field: row[index] for index, field in enumerate(self._FIELDS)
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[9]),
            payload=payload,
        )
        if snapshot.record_digest != row[10]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Memory owner row differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM memory_entries WHERE memory_id = ?", (mutation.entity_id,)
            )
            return
        payload = self._payload(mutation)
        values = tuple(payload[field] for field in self._FIELDS[1:-1])
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO memory_entries
                (memory_id, session_id, scope_kind, scope_ref, kind, summary,
                 source_range, author_actor_id, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (payload["memory_id"], *values, payload["created_at"]),
            )
            return
        cursor = connection.execute(
            """
            UPDATE memory_entries
            SET session_id = ?, scope_kind = ?, scope_ref = ?, kind = ?,
                summary = ?, source_range = ?, author_actor_id = ?,
                importance = 0, created_at = ?
            WHERE memory_id = ?
            """,
            (*values, payload["created_at"], mutation.entity_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Memory owner row disappeared before replacement",
                phase="entity_apply",
            )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != set(self._FIELDS):
            raise SQLiteControlStoreError(
                "sqlite_memory_payload_invalid",
                "Memory payload differs from the explicit existing-table codec",
                phase="entity_encode",
            )
        if mutation.payload["memory_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_memory_identity_mismatch",
                "Memory payload identity differs from its mutation",
                phase="entity_encode",
            )
        return mutation.payload


class TaskSQLiteKernelEntityCodec:
    """Maps the target Task record and dependency closure to existing tables."""

    entity_type = "task"
    owner_id = "openzyme.kernel"
    table_names = (
        "tasks",
        "task_dependencies",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _FIELDS = frozenset(
        {
            "task_id",
            "session_id",
            "subject",
            "description",
            "owner_actor_id",
            "priority",
            "kind",
            "lane_id",
            "finish_validator_ids",
            "status",
            "blocked_by",
            "assigned_ref",
            "failure_summary",
            "failure_ref",
            "evidence_refs",
            "finish_evidence_refs",
            "finish_validation_digest",
            "finished_by_actor_id",
            "created_at",
            "updated_at",
        }
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT t.task_id, t.session_id, t.subject, t.description,
                   t.owner_actor_id, t.priority, t.kind, t.lane_id,
                   t.finish_validator_ids_json, t.status, t.assigned_ref,
                   t.failure_summary, t.failure_ref, t.evidence_refs_json,
                   t.finish_evidence_refs_json, t.finish_validation_digest,
                   t.finished_by_actor_id, t.created_at, t.updated_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM tasks AS t
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'task' AND v.entity_id = t.task_id
            WHERE t.task_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[19] is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Task owner row lacks target CAS metadata",
                phase="entity_decode",
            )
        if row[21] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_owner_mismatch",
                "Task CAS metadata names another semantic owner",
                phase="entity_decode",
            )
        if row[4] is None:
            raise SQLiteControlStoreError(
                "sqlite_task_owner_unadopted",
                "Task owner_actor_id has not been adopted for the target Kernel",
                phase="entity_decode",
            )
        blocked_by = [
            str(item[0])
            for item in connection.execute(
                """
                SELECT blocked_by_task_id
                FROM task_dependencies
                WHERE task_id = ?
                ORDER BY blocked_by_task_id
                """,
                (entity_id,),
            ).fetchall()
        ]
        payload: Mapping[str, JsonValue] = {
            "task_id": row[0],
            "session_id": row[1],
            "subject": row[2],
            "description": row[3],
            "owner_actor_id": row[4],
            "priority": row[5],
            "kind": row[6],
            "lane_id": row[7],
            "finish_validator_ids": self._json_array(
                row[8], field_name="finish_validator_ids_json"
            ),
            "status": row[9],
            "blocked_by": blocked_by,
            "assigned_ref": row[10],
            "failure_summary": row[11],
            "failure_ref": row[12],
            "evidence_refs": self._json_array(row[13], field_name="evidence_refs_json"),
            "finish_evidence_refs": self._json_array(
                row[14], field_name="finish_evidence_refs_json"
            ),
            "finish_validation_digest": row[15],
            "finished_by_actor_id": row[16],
            "created_at": row[17],
            "updated_at": row[18],
        }
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[19]),
            payload=payload,
        )
        if snapshot.record_digest != row[20]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Task owner rows differ from their target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM tasks WHERE task_id = ?", (mutation.entity_id,)
            )
            return
        payload = self._payload(mutation)
        values = (
            payload["session_id"],
            payload["subject"],
            payload["description"],
            payload["status"],
            payload["priority"],
            payload["kind"],
            payload["assigned_ref"],
            payload["owner_actor_id"],
            self._json(payload["finish_validator_ids"]),
            self._json(payload["evidence_refs"]),
            self._json(payload["finish_evidence_refs"]),
            payload["finish_validation_digest"],
            payload["finished_by_actor_id"],
            payload["created_at"],
            payload["updated_at"],
            payload["lane_id"],
            payload["failure_summary"],
            payload["failure_ref"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO tasks
                (task_id, session_id, subject, description, status, priority, kind,
                 assigned_ref, owner_actor_id, finish_validator_ids_json,
                 evidence_refs_json, finish_evidence_refs_json,
                 finish_validation_digest, finished_by_actor_id, created_at,
                 updated_at, lane_id, failure_summary, failure_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (payload["task_id"], *values),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET session_id = ?, subject = ?, description = ?, status = ?,
                    priority = ?, kind = ?, assigned_ref = ?, owner_actor_id = ?,
                    finish_validator_ids_json = ?, evidence_refs_json = ?,
                    finish_evidence_refs_json = ?, finish_validation_digest = ?,
                    finished_by_actor_id = ?, created_at = ?, updated_at = ?,
                    lane_id = ?, failure_summary = ?, failure_ref = ?
                WHERE task_id = ?
                """,
                (*values, mutation.entity_id),
            )
            if cursor.rowcount != 1:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_owner_row_missing",
                    "Task owner row disappeared before replacement",
                    phase="entity_apply",
                )
            connection.execute(
                "DELETE FROM task_dependencies WHERE task_id = ?",
                (mutation.entity_id,),
            )
        connection.executemany(
            """
            INSERT INTO task_dependencies (task_id, blocked_by_task_id)
            VALUES (?, ?)
            """,
            (
                (mutation.entity_id, dependency_id)
                for dependency_id in payload["blocked_by"]
            ),
        )

    def _payload(self, mutation: KernelStateMutation) -> Mapping[str, JsonValue]:
        assert mutation.payload is not None
        if set(mutation.payload) != self._FIELDS:
            raise SQLiteControlStoreError(
                "sqlite_task_payload_invalid",
                "Task payload differs from the explicit existing-table codec",
                phase="entity_encode",
            )
        if mutation.payload["task_id"] != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_task_identity_mismatch",
                "Task payload identity differs from its mutation",
                phase="entity_encode",
            )
        for field_name in (
            "finish_validator_ids",
            "blocked_by",
            "evidence_refs",
            "finish_evidence_refs",
        ):
            value = mutation.payload[field_name]
            if not isinstance(value, tuple | list):
                raise SQLiteControlStoreError(
                    "sqlite_task_payload_invalid",
                    f"Task {field_name} must be an array",
                    phase="entity_encode",
                )
        blocked_by = mutation.payload["blocked_by"]
        if any(
            not isinstance(item, str) or item == mutation.entity_id
            for item in blocked_by
        ) or len(set(blocked_by)) != len(blocked_by):
            raise SQLiteControlStoreError(
                "sqlite_task_dependency_invalid",
                "Task dependencies must be unique other Task identities",
                phase="entity_encode",
            )
        return mutation.payload

    @staticmethod
    def _json(value: JsonValue) -> str:
        return json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _json_array(value: object, *, field_name: str) -> list[JsonValue]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_task_json_invalid",
                f"Task {field_name} is not valid JSON",
                phase="entity_decode",
            ) from exc
        if not isinstance(decoded, list):
            raise SQLiteControlStoreError(
                "sqlite_task_json_invalid",
                f"Task {field_name} must contain an array",
                phase="entity_decode",
            )
        return decoded


class ProjectRepositoryBindingSQLiteKernelEntityCodec:
    """Maps immutable Kernel repository identities to the retained binding table."""

    entity_type = "project_repository_binding"
    owner_id = "openzyme.kernel"
    table_names = (
        "project_repository_binding_versions",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT b.binding_id, b.project_id, b.binding_version,
                   b.repository_id, b.internal_git_service_id,
                   b.internal_git_endpoint, b.lfs_service_id, b.lfs_endpoint,
                   b.upstream_identity, b.upstream_url, b.object_format,
                   b.default_base_ref, b.default_base_commit,
                   b.private_ref_prefix, b.publication_ref_prefix,
                   b.historical_ref_prefix, b.repository_policy_version,
                   b.repository_policy_digest, b.canonical_digest,
                   b.schema_version, b.created_at, b.created_by,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM project_repository_binding_versions AS b
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'project_repository_binding'
             AND v.entity_id = b.binding_id
            WHERE b.binding_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[22] is None or row[24] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "ProjectRepositoryBinding lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "binding_id": row[0],
            "project_id": row[1],
            "binding_version": row[2],
            "repository_id": row[3],
            "internal_git_service_id": row[4],
            "internal_git_endpoint": row[5],
            "lfs_service_id": row[6],
            "lfs_endpoint": row[7],
            "upstream_identity": row[8],
            "upstream_url": row[9],
            "object_format": row[10],
            "default_base_ref": row[11],
            "default_base_commit": row[12],
            "ref_namespace_policy": {
                "private_prefix": row[13],
                "publication_prefix": row[14],
                "historical_prefix": row[15],
            },
            "repository_policy_version": row[16],
            "repository_policy_digest": row[17],
            "canonical_digest": row[18],
            "schema_version": row[19],
            "created_at": row[20],
            "created_by": row[21],
        }
        try:
            binding = ProjectRepositoryBinding.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_invalid",
                "ProjectRepositoryBinding owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[22]),
            payload=binding.to_dict(),
        )
        if snapshot.record_digest != row[23]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "ProjectRepositoryBinding differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_immutable",
                "ProjectRepositoryBinding versions are append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            binding = ProjectRepositoryBinding.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_invalid",
                "ProjectRepositoryBinding mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if binding.binding_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_identity_mismatch",
                "ProjectRepositoryBinding payload identity differs from its mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO project_repository_binding_versions
            (binding_id, project_id, binding_version, repository_id,
             internal_git_service_id, internal_git_endpoint, lfs_service_id,
             lfs_endpoint, upstream_identity, upstream_url, object_format,
             default_base_ref, default_base_commit, private_ref_prefix,
             publication_ref_prefix, historical_ref_prefix,
             repository_policy_version, repository_policy_digest,
             canonical_digest, schema_version, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding.binding_id,
                binding.project_id,
                binding.binding_version,
                binding.repository_id,
                binding.internal_git_service_id,
                binding.internal_git_endpoint,
                binding.lfs_service_id,
                binding.lfs_endpoint,
                binding.upstream_identity,
                binding.upstream_url,
                binding.object_format.value,
                binding.default_base_ref,
                binding.default_base_commit,
                binding.ref_namespace_policy.private_prefix,
                binding.ref_namespace_policy.publication_prefix,
                binding.ref_namespace_policy.historical_prefix,
                binding.repository_policy_version,
                binding.repository_policy_digest,
                binding.canonical_digest,
                binding.schema_version,
                binding.created_at,
                binding.created_by,
            ),
        )


class ProjectRepositoryBindingHeadSQLiteKernelEntityCodec:
    """Maps the current monotonic project binding head to a dedicated Kernel table."""

    entity_type = "project_repository_binding_head"
    owner_id = "openzyme.kernel"
    table_names = (
        "project_repository_binding_heads",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _fields = (
        "project_id",
        "binding_id",
        "binding_version",
        "binding_canonical_digest",
        "updated_at",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT h.project_id, h.binding_id, h.binding_version,
                   h.binding_canonical_digest, h.updated_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM project_repository_binding_heads AS h
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'project_repository_binding_head'
             AND v.entity_id = h.project_id
            WHERE h.project_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[5] is None or row[7] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Project repository binding head lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            "project_id": row[0],
            "binding_id": row[1],
            "binding_version": row[2],
            "binding_canonical_digest": row[3],
            "updated_at": row[4],
        }
        self._validate(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[5]),
            payload=payload,
        )
        if snapshot.record_digest != row[6]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Project repository binding head differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_head_required",
                "Project repository binding head cannot be deleted",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        payload = mutation.payload
        self._validate(payload, entity_id=mutation.entity_id)
        values = (
            payload["project_id"],
            payload["binding_id"],
            payload["binding_version"],
            payload["binding_canonical_digest"],
            payload["updated_at"],
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO project_repository_binding_heads
                (project_id, binding_id, binding_version,
                 binding_canonical_digest, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE project_repository_binding_heads
            SET binding_id = ?, binding_version = ?,
                binding_canonical_digest = ?, updated_at = ?
            WHERE project_id = ?
            """,
            (
                payload["binding_id"],
                payload["binding_version"],
                payload["binding_canonical_digest"],
                payload["updated_at"],
                payload["project_id"],
            ),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "Project repository binding head disappeared before replacement",
                phase="entity_apply",
            )

    @classmethod
    def _validate(cls, payload: Mapping[str, JsonValue], *, entity_id: str) -> None:
        _require_target_payload(
            payload,
            fields=cls._fields,
            identity_field="project_id",
            entity_id=entity_id,
            code="sqlite_project_repository_binding_head_invalid",
            subject="Project repository binding head",
        )
        for field_name in ("project_id", "binding_id", "updated_at"):
            value = payload[field_name]
            if not isinstance(value, str):
                raise SQLiteControlStoreError(
                    "sqlite_project_repository_binding_head_invalid",
                    f"Project repository binding head {field_name} must be a string",
                    phase="entity_encode",
                )
            try:
                require_identifier(value, field_name=field_name)
            except (TypeError, ValueError) as exc:
                raise SQLiteControlStoreError(
                    "sqlite_project_repository_binding_head_invalid",
                    f"Project repository binding head {field_name} is invalid",
                    phase="entity_encode",
                ) from exc
        version = payload["binding_version"]
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_head_invalid",
                "Project repository binding head version must be positive",
                phase="entity_encode",
            )
        digest = payload["binding_canonical_digest"]
        if not isinstance(digest, str):
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_head_invalid",
                "Project repository binding head digest must be a string",
                phase="entity_encode",
            )
        try:
            require_digest(digest, field_name="binding_canonical_digest")
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_project_repository_binding_head_invalid",
                "Project repository binding head digest is invalid",
                phase="entity_encode",
            ) from exc


class SessionRepositoryBindingPinSQLiteKernelEntityCodec:
    """Maps immutable per-Session repository pins to their retained owner table."""

    entity_type = "session_repository_binding_pin"
    owner_id = "openzyme.kernel"
    table_names = (
        "session_repository_binding_pins",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT p.session_id, p.project_id, p.binding_id,
                   p.binding_version, p.repository_id,
                   p.resolved_base_commit, p.binding_canonical_digest,
                   p.mapping_receipt_id, p.schema_version, p.pinned_at,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM session_repository_binding_pins AS p
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'session_repository_binding_pin'
             AND v.entity_id = p.session_id
            WHERE p.session_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[10] is None or row[12] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "SessionRepositoryBindingPin lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "session_id": row[0],
            "project_id": row[1],
            "binding_id": row[2],
            "binding_version": row[3],
            "repository_id": row[4],
            "resolved_base_commit": row[5],
            "binding_canonical_digest": row[6],
            "mapping_receipt_id": row[7],
            "schema_version": row[8],
            "pinned_at": row[9],
        }
        try:
            pin = SessionRepositoryBindingPin.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_session_repository_binding_pin_invalid",
                "SessionRepositoryBindingPin owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[10]),
            payload=pin.to_dict(),
        )
        if snapshot.record_digest != row[11]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "SessionRepositoryBindingPin differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_session_repository_binding_pin_immutable",
                "SessionRepositoryBindingPin is immutable",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            pin = SessionRepositoryBindingPin.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_session_repository_binding_pin_invalid",
                "SessionRepositoryBindingPin mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if pin.session_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_session_repository_binding_pin_identity_mismatch",
                "SessionRepositoryBindingPin payload identity differs from its mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO session_repository_binding_pins
            (session_id, project_id, binding_id, binding_version,
             repository_id, resolved_base_commit, binding_canonical_digest,
             mapping_receipt_id, schema_version, pinned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pin.session_id,
                pin.project_id,
                pin.binding_id,
                pin.binding_version,
                pin.repository_id,
                pin.resolved_base_commit,
                pin.binding_canonical_digest,
                pin.mapping_receipt_id,
                pin.schema_version,
                pin.pinned_at,
            ),
        )


class WorkspaceGenerationSQLiteKernelEntityCodec:
    """Maps Kernel workspace identity generations to a mechanism-neutral table."""

    entity_type = "workspace_generation"
    owner_id = "openzyme.kernel"
    table_names = (
        "workspace_generation_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT w.workspace_id, w.workspace_kind, w.session_id,
                   w.owner_member_id, w.generation, w.workspace_state_version,
                   w.status, w.provider_id, w.target_id, w.created_at,
                   w.updated_at, w.root_identity_digest,
                   w.target_qualification_digest, w.transition_receipt_digest,
                   w.controlled_operation_id, w.retired_at, w.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM workspace_generation_records AS w
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'workspace_generation'
             AND v.entity_id = w.workspace_id
            WHERE w.workspace_id = ?
            ORDER BY w.generation DESC
            LIMIT 1
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[17] is None or row[19] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "WorkspaceGeneration lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "workspace_id": row[0],
            "workspace_kind": row[1],
            "session_id": row[2],
            "owner_member_id": row[3],
            "generation": row[4],
            "state_version": row[5],
            "status": row[6],
            "provider_id": row[7],
            "target_id": row[8],
            "created_at": row[9],
            "updated_at": row[10],
            "root_identity_digest": row[11],
            "target_qualification_digest": row[12],
            "transition_receipt_digest": row[13],
            "controlled_operation_id": row[14],
            "retired_at": row[15],
            "schema_version": row[16],
        }
        try:
            generation = WorkspaceGeneration.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_generation_invalid",
                "WorkspaceGeneration owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[17]),
            payload=generation.to_dict(),
        )
        if snapshot.record_digest != row[18]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "WorkspaceGeneration differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            raise SQLiteControlStoreError(
                "sqlite_workspace_generation_required",
                "WorkspaceGeneration history cannot be deleted",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            generation = WorkspaceGeneration.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_generation_invalid",
                "WorkspaceGeneration mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if generation.workspace_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_workspace_generation_identity_mismatch",
                "WorkspaceGeneration payload identity differs from its mutation",
                phase="entity_encode",
            )
        values = (
            generation.workspace_id,
            generation.workspace_kind.value,
            generation.session_id,
            generation.owner_member_id,
            generation.generation,
            generation.state_version,
            generation.status.value,
            generation.provider_id,
            generation.target_id,
            generation.created_at,
            generation.updated_at,
            generation.root_identity_digest,
            generation.target_qualification_digest,
            generation.transition_receipt_digest,
            generation.controlled_operation_id,
            generation.retired_at,
            str(generation.to_dict()["schema_version"]),
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO workspace_generation_records
                (workspace_id, workspace_kind, session_id, owner_member_id,
                 generation, workspace_state_version, status, provider_id,
                 target_id, created_at, updated_at, root_identity_digest,
                 target_qualification_digest, transition_receipt_digest,
                 controlled_operation_id, retired_at, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        current_row = connection.execute(
            """
            SELECT generation
            FROM workspace_generation_records
            WHERE workspace_id = ?
            ORDER BY generation DESC
            LIMIT 1
            """,
            (generation.workspace_id,),
        ).fetchone()
        if current_row is None:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "WorkspaceGeneration disappeared before replacement",
                phase="entity_apply",
            )
        current_generation = int(current_row[0])
        if generation.generation == current_generation + 1:
            cursor = connection.execute(
                """
                INSERT INTO workspace_generation_records
                (workspace_id, workspace_kind, session_id, owner_member_id,
                 generation, workspace_state_version, status, provider_id,
                 target_id, created_at, updated_at, root_identity_digest,
                 target_qualification_digest, transition_receipt_digest,
                 controlled_operation_id, retired_at, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        elif generation.generation == current_generation:
            cursor = connection.execute(
                """
                UPDATE workspace_generation_records
                SET workspace_kind = ?, session_id = ?, owner_member_id = ?,
                    workspace_state_version = ?, status = ?, provider_id = ?,
                    target_id = ?, created_at = ?, updated_at = ?,
                    root_identity_digest = ?, target_qualification_digest = ?,
                    transition_receipt_digest = ?, controlled_operation_id = ?,
                    retired_at = ?, schema_version = ?
                WHERE workspace_id = ? AND generation = ?
                """,
                (
                    *values[1:4],
                    *values[5:],
                    generation.workspace_id,
                    generation.generation,
                ),
            )
        else:
            raise SQLiteControlStoreError(
                "sqlite_workspace_generation_non_monotonic",
                "WorkspaceGeneration replacement must update current state or append one successor",
                phase="entity_apply",
            )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "WorkspaceGeneration disappeared before replacement",
                phase="entity_apply",
            )


class WorkspaceRuntimeBindingSQLiteKernelEntityCodec:
    """Maps the current executable binding derived from a READY generation."""

    entity_type = "workspace_runtime_binding"
    owner_id = "openzyme.kernel"
    table_names = (
        "workspace_runtime_binding_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT w.workspace_id, w.workspace_kind, w.session_id,
                   w.owner_member_id, w.generation, w.workspace_state_version,
                   w.root_identity_digest, w.provider_id, w.target_id,
                   w.target_qualification_digest, w.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM workspace_runtime_binding_records AS w
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'workspace_runtime_binding'
             AND v.entity_id = w.workspace_id
            WHERE w.workspace_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[11] is None or row[13] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "WorkspaceRuntimeBinding lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "workspace_id": row[0],
            "workspace_kind": row[1],
            "session_id": row[2],
            "owner_member_id": row[3],
            "generation": row[4],
            "state_version": row[5],
            "root_identity_digest": row[6],
            "provider_id": row[7],
            "target_id": row[8],
            "target_qualification_digest": row[9],
            "schema_version": row[10],
        }
        try:
            binding = WorkspaceRuntimeBinding.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_runtime_binding_invalid",
                "WorkspaceRuntimeBinding owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[11]),
            payload=binding.to_dict(),
        )
        if snapshot.record_digest != row[12]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "WorkspaceRuntimeBinding differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM workspace_runtime_binding_records WHERE workspace_id = ?",
                (mutation.entity_id,),
            )
            return
        assert mutation.payload is not None
        try:
            binding = WorkspaceRuntimeBinding.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_runtime_binding_invalid",
                "WorkspaceRuntimeBinding mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if binding.workspace_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_workspace_runtime_binding_identity_mismatch",
                "WorkspaceRuntimeBinding payload identity differs from its mutation",
                phase="entity_encode",
            )
        values = (
            binding.workspace_id,
            binding.workspace_kind.value,
            binding.session_id,
            binding.owner_member_id,
            binding.generation,
            binding.state_version,
            binding.root_identity_digest,
            binding.provider_id,
            binding.target_id,
            binding.target_qualification_digest,
            str(binding.to_dict()["schema_version"]),
        )
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                """
                INSERT INTO workspace_runtime_binding_records
                (workspace_id, workspace_kind, session_id, owner_member_id,
                 generation, workspace_state_version, root_identity_digest,
                 provider_id, target_id, target_qualification_digest,
                 schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return
        cursor = connection.execute(
            """
            UPDATE workspace_runtime_binding_records
            SET workspace_kind = ?, session_id = ?, owner_member_id = ?,
                generation = ?, workspace_state_version = ?,
                root_identity_digest = ?, provider_id = ?, target_id = ?,
                target_qualification_digest = ?, schema_version = ?
            WHERE workspace_id = ?
            """,
            (*values[1:], binding.workspace_id),
        )
        if cursor.rowcount != 1:
            raise SQLiteControlStoreError(
                "sqlite_kernel_owner_row_missing",
                "WorkspaceRuntimeBinding disappeared before replacement",
                phase="entity_apply",
            )


class TaskEvidenceSQLiteKernelEntityCodec:
    """Maps immutable evidence registrations without importing Plugin schemas."""

    entity_type = "task_evidence"
    owner_id = "openzyme.kernel"
    table_names = (
        "task_evidence_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)
    _fields = (
        "session_id",
        "task_id",
        "registered_by_actor_id",
        "evidence_digest",
        "evidence_ref",
        "created_at",
        "task_transition_performed",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT e.evidence_id, e.session_id, e.task_id,
                   e.registered_by_actor_id, e.evidence_digest,
                   e.evidence_ref_json, e.created_at,
                   e.task_transition_performed,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM task_evidence_records AS e
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'task_evidence'
             AND v.entity_id = e.evidence_id
            WHERE e.evidence_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[8] is None or row[10] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "Task evidence registration lacks exact target CAS metadata",
                phase="entity_decode",
            )
        evidence_payload = _decode_json(
            row[5],
            code="sqlite_task_evidence_invalid",
            subject="Task evidence reference",
        )
        payload: Mapping[str, JsonValue] = {
            "session_id": row[1],
            "task_id": row[2],
            "registered_by_actor_id": row[3],
            "evidence_digest": row[4],
            "evidence_ref": evidence_payload,
            "created_at": row[6],
            "task_transition_performed": bool(row[7]),
        }
        self._validate(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[8]),
            payload=payload,
        )
        if snapshot.record_digest != row[9]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Task evidence registration differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_immutable",
                "Task evidence registrations are append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        payload = mutation.payload
        evidence = self._validate(payload, entity_id=mutation.entity_id)
        connection.execute(
            """
            INSERT INTO task_evidence_records
            (evidence_id, session_id, task_id, registered_by_actor_id,
             evidence_digest, evidence_ref_json, created_at,
             task_transition_performed, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'task_evidence_registration@1')
            """,
            (
                evidence.evidence_id,
                payload["session_id"],
                payload["task_id"],
                payload["registered_by_actor_id"],
                payload["evidence_digest"],
                _canonical_json(evidence.to_dict()),
                payload["created_at"],
            ),
        )

    @classmethod
    def _validate(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> EvidenceRef:
        if set(payload) != set(cls._fields):
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_invalid",
                "Task evidence registration violates its closed contract",
                phase="entity_encode",
            )
        for field_name in (
            "session_id",
            "task_id",
            "registered_by_actor_id",
            "created_at",
        ):
            value = payload[field_name]
            if not isinstance(value, str):
                raise SQLiteControlStoreError(
                    "sqlite_task_evidence_invalid",
                    f"Task evidence {field_name} must be a string",
                    phase="entity_encode",
                )
            try:
                require_identifier(value, field_name=field_name)
            except (TypeError, ValueError) as exc:
                raise SQLiteControlStoreError(
                    "sqlite_task_evidence_invalid",
                    f"Task evidence {field_name} is invalid",
                    phase="entity_encode",
                ) from exc
        if payload["task_transition_performed"] is not False:
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_transition_forbidden",
                "Task evidence registration cannot transition a Task",
                phase="entity_encode",
            )
        value = payload["evidence_ref"]
        if not isinstance(value, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_invalid",
                "Task evidence_ref must be an object",
                phase="entity_encode",
            )
        expected = {
            "schema_version",
            "evidence_id",
            "evidence_kind",
            "contract_id",
            "owner_component_id",
            "project_id",
            "session_id",
            "task_id",
            "subject_ref",
            "subject_digest",
            "attributes",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != EVIDENCE_REF_SCHEMA_VERSION
        ):
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_invalid",
                "EvidenceRef violates its closed contract",
                phase="entity_encode",
            )
        attributes = value["attributes"]
        if not isinstance(attributes, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_invalid",
                "EvidenceRef attributes must be an object",
                phase="entity_encode",
            )
        try:
            evidence = EvidenceRef(
                evidence_id=str(value["evidence_id"]),
                evidence_kind=EvidenceKind(str(value["evidence_kind"])),
                contract_id=str(value["contract_id"]),
                owner_component_id=str(value["owner_component_id"]),
                project_id=str(value["project_id"]),
                session_id=str(value["session_id"]),
                task_id=str(value["task_id"]),
                subject_ref=str(value["subject_ref"]),
                subject_digest=str(value["subject_digest"]),
                attributes=dict(attributes),
            )
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_invalid",
                "EvidenceRef values violate their contract",
                phase="entity_encode",
            ) from exc
        if (
            evidence.evidence_id != entity_id
            or evidence.session_id != payload["session_id"]
            or evidence.task_id != payload["task_id"]
            or evidence.evidence_digest != payload["evidence_digest"]
        ):
            raise SQLiteControlStoreError(
                "sqlite_task_evidence_identity_mismatch",
                "Task evidence wrapper differs from its EvidenceRef identity",
                phase="entity_encode",
            )
        return evidence


class KernelCommandReceiptSQLiteKernelEntityCodec:
    """Maps Kernel idempotency receipts onto the retained immutable ledger.

    The legacy physical table remains the Kernel-owned storage mechanism, but
    target writers use one closed payload and the generic CAS version ledger.
    Rows without that target version identity are deliberately not adopted by
    this codec.
    """

    entity_type = "kernel_command_receipt"
    owner_id = "openzyme.kernel"
    table_names = (
        "command_receipt_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("ledger",)
    _fields = ("session_id", "command_digest", "receipt", "created_at")
    _receipt_fields = (
        "schema_version",
        "command_id",
        "service_id",
        "operation",
        "mutation_applied",
        "effect_certainty",
        "fallback_performed",
        "entity_refs",
        "event_refs",
        "result",
        "receipt_digest",
    )

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT r.command_receipt_id, r.session_id, r.request_digest,
                   r.response_json, r.created_at, r.status,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM command_receipt_records AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'kernel_command_receipt'
             AND v.entity_id = r.command_receipt_id
            WHERE r.command_receipt_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[5] != "completed" or row[6] is None or row[8] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_unadopted",
                "Command receipt lacks exact immutable target CAS metadata",
                phase="entity_decode",
            )
        payload = _decode_json(
            row[3],
            code="sqlite_kernel_command_receipt_invalid",
            subject="Kernel command receipt",
        )
        if not isinstance(payload, Mapping):
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel command receipt payload must be an object",
                phase="entity_decode",
            )
        self._validate(payload, entity_id=entity_id)
        if payload["session_id"] != row[1] or payload["command_digest"] != row[2]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_identity_mismatch",
                "Kernel command receipt columns differ from its closed payload",
                phase="entity_decode",
            )
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[6]),
            payload=payload,
        )
        if snapshot.record_digest != row[7]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "Kernel command receipt differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_immutable",
                "Kernel command receipts are append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        payload = mutation.payload
        receipt = self._validate(payload, entity_id=mutation.entity_id)
        service_id = str(receipt["service_id"])
        operation = str(receipt["operation"])
        created_at = str(payload["created_at"])
        connection.execute(
            """
            INSERT INTO command_receipt_records
            (command_receipt_id, scope_ref, session_id, command_type,
             idempotency_key, request_digest, status, response_json,
             created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
            """,
            (
                mutation.entity_id,
                payload["session_id"],
                payload["session_id"],
                f"{service_id}.{operation}",
                mutation.entity_id,
                payload["command_digest"],
                _canonical_json(payload),
                created_at,
                created_at,
            ),
        )

    @classmethod
    def _validate(
        cls, payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> Mapping[str, JsonValue]:
        if set(payload) != set(cls._fields):
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel command receipt violates its closed payload contract",
                phase="entity_encode",
            )
        for field_name in ("session_id", "created_at"):
            value = payload[field_name]
            if not isinstance(value, str):
                raise SQLiteControlStoreError(
                    "sqlite_kernel_command_receipt_invalid",
                    f"Kernel command receipt {field_name} must be a string",
                    phase="entity_encode",
                )
            try:
                require_identifier(value, field_name=field_name)
            except (TypeError, ValueError) as exc:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_command_receipt_invalid",
                    f"Kernel command receipt {field_name} is invalid",
                    phase="entity_encode",
                ) from exc
        command_digest = payload["command_digest"]
        try:
            require_digest(command_digest, field_name="command_digest")
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel command receipt command_digest is invalid",
                phase="entity_encode",
            ) from exc
        receipt = payload["receipt"]
        if not isinstance(receipt, Mapping) or set(receipt) != set(cls._receipt_fields):
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel mutation receipt violates its closed contract",
                phase="entity_encode",
            )
        for field_name in ("command_id", "service_id", "operation"):
            value = receipt[field_name]
            if not isinstance(value, str):
                raise SQLiteControlStoreError(
                    "sqlite_kernel_command_receipt_invalid",
                    f"Kernel mutation receipt {field_name} must be a string",
                    phase="entity_encode",
                )
            try:
                require_identifier(value, field_name=field_name)
            except (TypeError, ValueError) as exc:
                raise SQLiteControlStoreError(
                    "sqlite_kernel_command_receipt_invalid",
                    f"Kernel mutation receipt {field_name} is invalid",
                    phase="entity_encode",
                ) from exc
        if receipt["fallback_performed"] is not False:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_fallback_forbidden",
                "Kernel mutation receipt cannot record hidden fallback",
                phase="entity_encode",
            )
        if not isinstance(receipt["mutation_applied"], bool):
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel mutation receipt mutation_applied must be boolean",
                phase="entity_encode",
            )
        if (
            not isinstance(receipt["entity_refs"], (list, tuple))
            or not isinstance(receipt["event_refs"], (list, tuple))
            or not isinstance(receipt["result"], Mapping)
        ):
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel mutation receipt collections violate their contract",
                phase="entity_encode",
            )
        receipt_digest = receipt["receipt_digest"]
        try:
            require_digest(receipt_digest, field_name="receipt_digest")
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel mutation receipt digest is invalid",
                phase="entity_encode",
            ) from exc
        if receipt_digest != canonical_sha256_digest(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        ):
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_digest_mismatch",
                "Kernel mutation receipt digest does not match its payload",
                phase="entity_encode",
            )
        if not entity_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_command_receipt_invalid",
                "Kernel command receipt identity must be non-empty",
                phase="entity_encode",
            )
        return receipt


class VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec:
    """Maps immutable verified checkpoints to the retained structured table."""

    entity_type = "verified_workspace_checkpoint"
    owner_id = "openzyme.kernel"
    table_names = (
        "verified_workspace_checkpoint_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT c.checkpoint_id, c.boundary, c.workspace_id, c.session_id,
                   c.agent_member_id, c.agent_id, c.workspace_generation,
                   c.repository_binding_id, c.repository_binding_version,
                   c.repository_id, c.commit_oid, c.tree_oid, c.private_ref,
                   c.prior_commit_oid, c.advance_kind, c.remote_observed_at,
                   c.verified_at, c.checkpoint_digest, c.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM verified_workspace_checkpoint_records AS c
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'verified_workspace_checkpoint'
             AND v.entity_id = c.checkpoint_id
            WHERE c.checkpoint_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[19] is None or row[21] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "VerifiedWorkspaceCheckpoint lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "checkpoint_id": row[0],
            "boundary": row[1],
            "workspace_id": row[2],
            "session_id": row[3],
            "agent_member_id": row[4],
            "agent_id": row[5],
            "workspace_generation": row[6],
            "repository_binding_id": row[7],
            "repository_binding_version": row[8],
            "repository_id": row[9],
            "commit": row[10],
            "tree": row[11],
            "private_ref": row[12],
            "prior_commit": row[13],
            "advance_kind": row[14],
            "remote_observed_at": row[15],
            "verified_at": row[16],
            "checkpoint_digest": row[17],
            "schema_version": row[18],
        }
        try:
            checkpoint = VerifiedWorkspaceCheckpoint.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_verified_workspace_checkpoint_invalid",
                "VerifiedWorkspaceCheckpoint owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[19]),
            payload=checkpoint.to_dict(),
        )
        if snapshot.record_digest != row[20]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "VerifiedWorkspaceCheckpoint differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_verified_workspace_checkpoint_immutable",
                "VerifiedWorkspaceCheckpoint is append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            checkpoint = VerifiedWorkspaceCheckpoint.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_verified_workspace_checkpoint_invalid",
                "VerifiedWorkspaceCheckpoint mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if checkpoint.checkpoint_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_verified_workspace_checkpoint_identity_mismatch",
                "VerifiedWorkspaceCheckpoint identity differs from its mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO verified_workspace_checkpoint_records
            (checkpoint_id, boundary, workspace_id, session_id,
             agent_member_id, agent_id, workspace_generation,
             repository_binding_id, repository_binding_version,
             repository_id, commit_oid, tree_oid, private_ref,
             prior_commit_oid, advance_kind, remote_observed_at,
             verified_at, checkpoint_digest, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.checkpoint_id,
                checkpoint.boundary.value,
                checkpoint.workspace_id,
                checkpoint.session_id,
                checkpoint.agent_member_id,
                checkpoint.agent_id,
                checkpoint.workspace_generation,
                checkpoint.repository_binding_id,
                checkpoint.repository_binding_version,
                checkpoint.repository_id,
                checkpoint.commit,
                checkpoint.tree,
                checkpoint.private_ref,
                checkpoint.prior_commit,
                checkpoint.advance_kind.value,
                checkpoint.remote_observed_at,
                checkpoint.verified_at,
                checkpoint.checkpoint_digest,
                checkpoint.schema_version,
            ),
        )


class WorkspacePublicationIntentSQLiteKernelEntityCodec:
    """Maps immutable publication intent facts to the retained structured table."""

    entity_type = "workspace_publication_intent"
    owner_id = "openzyme.kernel"
    table_names = (
        "workspace_publication_intents",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT i.intent_id, i.publication_id, i.idempotency_key,
                   i.project_id, i.session_id, i.agent_member_id, i.agent_id,
                   i.workspace_id, i.workspace_generation, i.capability_lease_id,
                   i.repository_binding_id, i.repository_binding_version,
                   i.repository_id, i.expected_head_commit, i.expected_tree,
                   i.git_parent_commits_json, i.declared_base_commit,
                   i.parent_publication_id, i.supersedes_publication_id,
                   i.publication_ref, i.manifest_json,
                   i.repository_policy_version, i.repository_policy_digest,
                   i.checkpoint_id, i.state, i.created_at,
                   i.canonical_digest, i.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM workspace_publication_intents AS i
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'workspace_publication_intent'
             AND v.entity_id = i.publication_id
            WHERE i.publication_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[28] is None or row[30] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "WorkspacePublicationIntent lacks exact target CAS metadata",
                phase="entity_decode",
            )
        parents = _decode_json(
            row[15],
            code="sqlite_workspace_publication_intent_invalid",
            subject="Publication parent list",
        )
        manifest = _decode_json(
            row[20],
            code="sqlite_workspace_publication_intent_invalid",
            subject="Publication manifest",
        )
        payload: dict[str, JsonValue] = {
            "intent_id": row[0],
            "publication_id": row[1],
            "idempotency_key": row[2],
            "project_id": row[3],
            "session_id": row[4],
            "agent_member_id": row[5],
            "agent_id": row[6],
            "workspace_id": row[7],
            "workspace_generation": row[8],
            "capability_lease_id": row[9],
            "repository_binding_id": row[10],
            "repository_binding_version": row[11],
            "repository_id": row[12],
            "expected_head_commit": row[13],
            "expected_tree": row[14],
            "git_parent_commits": parents,
            "declared_base_commit": row[16],
            "parent_publication_id": row[17],
            "supersedes_publication_id": row[18],
            "publication_ref": row[19],
            "manifest": manifest,
            "repository_policy_version": row[21],
            "repository_policy_digest": row[22],
            "checkpoint_id": row[23],
            "state": row[24],
            "created_at": row[25],
            "canonical_digest": row[26],
            "schema_version": row[27],
        }
        try:
            intent = WorkspacePublicationIntent.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_publication_intent_invalid",
                "WorkspacePublicationIntent owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[28]),
            payload=intent.to_dict(),
        )
        if snapshot.record_digest != row[29]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "WorkspacePublicationIntent differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_workspace_publication_intent_immutable",
                "WorkspacePublicationIntent is append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            intent = WorkspacePublicationIntent.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_workspace_publication_intent_invalid",
                "WorkspacePublicationIntent mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if intent.publication_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_workspace_publication_intent_identity_mismatch",
                "WorkspacePublicationIntent publication identity differs from mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO workspace_publication_intents
            (intent_id, publication_id, idempotency_key, project_id,
             session_id, agent_member_id, agent_id, workspace_id,
             workspace_generation, capability_lease_id,
             repository_binding_id, repository_binding_version,
             repository_id, expected_head_commit, expected_tree,
             git_parent_commits_json, declared_base_commit,
             parent_publication_id, supersedes_publication_id,
             publication_ref, manifest_json, manifest_digest,
             repository_policy_version, repository_policy_digest,
             checkpoint_id, state, created_at, canonical_digest, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.intent_id,
                intent.publication_id,
                intent.idempotency_key,
                intent.project_id,
                intent.session_id,
                intent.agent_member_id,
                intent.agent_id,
                intent.workspace_id,
                intent.workspace_generation,
                intent.capability_lease_id,
                intent.repository_binding_id,
                intent.repository_binding_version,
                intent.repository_id,
                intent.expected_head_commit,
                intent.expected_tree,
                _canonical_json(list(intent.git_parent_commits)),
                intent.declared_base_commit,
                intent.parent_publication_id,
                intent.supersedes_publication_id,
                intent.publication_ref,
                _canonical_json(intent.manifest.to_dict()),
                intent.manifest.manifest_digest,
                intent.repository_policy_version,
                intent.repository_policy_digest,
                intent.checkpoint_id,
                intent.state.value,
                intent.created_at,
                intent.canonical_digest,
                intent.schema_version,
            ),
        )


class PublishedRevisionSQLiteKernelEntityCodec:
    """Maps immutable published revisions without owning Git mechanism effects."""

    entity_type = "published_revision"
    owner_id = "openzyme.kernel"
    table_names = (
        "published_revisions",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT r.publication_id, r.intent_id, r.project_id, r.session_id,
                   r.repository_binding_id, r.repository_binding_version,
                   r.repository_id, r.commit_id, r.tree_id,
                   r.git_parent_commits_json, r.declared_base_commit,
                   r.parent_publication_id, r.publisher_agent_member_id,
                   r.publisher_agent_id, r.publisher_workspace_id,
                   r.publisher_workspace_generation, r.publication_ref,
                   r.manifest_json, r.repository_policy_version,
                   r.repository_policy_digest, r.controlled_execution_id,
                   r.remote_receipt_id, r.supersedes_publication_id,
                   r.created_at, r.revision_digest, r.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM published_revisions AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'published_revision'
             AND v.entity_id = r.publication_id
            WHERE r.publication_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[26] is None or row[28] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "PublishedRevision lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: dict[str, JsonValue] = {
            "publication_id": row[0],
            "intent_id": row[1],
            "project_id": row[2],
            "session_id": row[3],
            "repository_binding_id": row[4],
            "repository_binding_version": row[5],
            "repository_id": row[6],
            "commit": row[7],
            "tree": row[8],
            "git_parent_commits": _decode_json(
                row[9],
                code="sqlite_published_revision_invalid",
                subject="Published revision parents",
            ),
            "declared_base_commit": row[10],
            "parent_publication_id": row[11],
            "publisher_agent_member_id": row[12],
            "publisher_agent_id": row[13],
            "publisher_workspace_id": row[14],
            "publisher_workspace_generation": row[15],
            "publication_ref": row[16],
            "manifest": _decode_json(
                row[17],
                code="sqlite_published_revision_invalid",
                subject="Published revision manifest",
            ),
            "repository_policy_version": row[18],
            "repository_policy_digest": row[19],
            "controlled_execution_id": row[20],
            "remote_receipt_id": row[21],
            "supersedes_publication_id": row[22],
            "created_at": row[23],
            "revision_digest": row[24],
            "schema_version": row[25],
        }
        try:
            revision = PublishedRevision.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_published_revision_invalid",
                "PublishedRevision owner row violates its closed contract",
                phase="entity_decode",
            ) from exc
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[26]),
            payload=revision.to_dict(),
        )
        if snapshot.record_digest != row[27]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "PublishedRevision differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_published_revision_immutable",
                "PublishedRevision is append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        try:
            revision = PublishedRevision.from_dict(dict(mutation.payload))
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_published_revision_invalid",
                "PublishedRevision mutation violates its closed contract",
                phase="entity_encode",
            ) from exc
        if revision.publication_id != mutation.entity_id:
            raise SQLiteControlStoreError(
                "sqlite_published_revision_identity_mismatch",
                "PublishedRevision identity differs from its mutation",
                phase="entity_encode",
            )
        connection.execute(
            """
            INSERT INTO published_revisions
            (publication_id, intent_id, project_id, session_id,
             repository_binding_id, repository_binding_version,
             repository_id, commit_id, tree_id, git_parent_commits_json,
             declared_base_commit, parent_publication_id,
             publisher_agent_member_id, publisher_agent_id,
             publisher_workspace_id, publisher_workspace_generation,
             publication_ref, manifest_json, manifest_digest,
             repository_policy_version, repository_policy_digest,
             controlled_execution_id, remote_receipt_id,
             supersedes_publication_id, created_at, revision_digest,
             schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.publication_id,
                revision.intent_id,
                revision.project_id,
                revision.session_id,
                revision.repository_binding_id,
                revision.repository_binding_version,
                revision.repository_id,
                revision.commit,
                revision.tree,
                _canonical_json(list(revision.git_parent_commits)),
                revision.declared_base_commit,
                revision.parent_publication_id,
                revision.publisher_agent_member_id,
                revision.publisher_agent_id,
                revision.publisher_workspace_id,
                revision.publisher_workspace_generation,
                revision.publication_ref,
                _canonical_json(revision.manifest.to_dict()),
                revision.manifest.manifest_digest,
                revision.repository_policy_version,
                revision.repository_policy_digest,
                revision.controlled_execution_id,
                revision.remote_receipt_id,
                revision.supersedes_publication_id,
                revision.created_at,
                revision.revision_digest,
                revision.schema_version,
            ),
        )


class RevisionPathVerificationSQLiteKernelEntityCodec:
    """Maps immutable Adapter path-verification receipts into Kernel truth."""

    entity_type = "revision_path_verification"
    owner_id = "openzyme.kernel"
    table_names = (
        "revision_path_verification_records",
        "openzyme_store_kernel_entity_versions",
    )
    uses_store_version_ledger = True
    mutation_channels = ("canonical_sqlite",)

    def read(
        self, connection: sqlite3.Connection, *, entity_id: str
    ) -> KernelRecordSnapshot | None:
        row = connection.execute(
            """
            SELECT r.ref_id, r.publication_id, r.repository_binding_id,
                   r.repository_binding_version, r.commit_oid, r.tree_oid,
                   r.repository_path, r.object_id, r.actual_size_bytes,
                   r.actual_content_digest, r.lfs_oid, r.lfs_size_bytes,
                   r.verified_at, r.verification_digest, r.schema_version,
                   v.state_version, v.record_digest, v.owner_component_id
            FROM revision_path_verification_records AS r
            LEFT JOIN openzyme_store_kernel_entity_versions AS v
              ON v.entity_type = 'revision_path_verification'
             AND v.entity_id = r.ref_id
            WHERE r.ref_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        if row[15] is None or row[17] != self.owner_id:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_unadopted",
                "RevisionPathVerification lacks exact target CAS metadata",
                phase="entity_decode",
            )
        payload: Mapping[str, JsonValue] = {
            "schema_version": row[14],
            "ref_id": row[0],
            "publication_id": row[1],
            "repository_binding_id": row[2],
            "repository_binding_version": row[3],
            "commit": row[4],
            "tree": row[5],
            "path": row[6],
            "object_id": row[7],
            "actual_size_bytes": row[8],
            "actual_content_digest": row[9],
            "lfs_oid": row[10],
            "lfs_size_bytes": row[11],
            "verified_at": row[12],
            "verification_digest": row[13],
        }
        self._validate(payload, entity_id=entity_id)
        snapshot = KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[15]),
            payload=payload,
        )
        if snapshot.record_digest != row[16]:
            raise SQLiteControlStoreError(
                "sqlite_kernel_entity_digest_mismatch",
                "RevisionPathVerification differs from its target CAS digest",
                phase="entity_decode",
            )
        return snapshot

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        mutation: KernelStateMutation,
        next_state_version: int | None,
    ) -> None:
        if mutation.kind is not KernelMutationKind.CREATE:
            raise SQLiteControlStoreError(
                "sqlite_revision_path_verification_immutable",
                "RevisionPathVerification is append-only",
                phase="entity_apply",
            )
        assert mutation.payload is not None
        receipt = self._validate(mutation.payload, entity_id=mutation.entity_id)
        connection.execute(
            """
            INSERT INTO revision_path_verification_records
            (ref_id, publication_id, repository_binding_id,
             repository_binding_version, commit_oid, tree_oid,
             repository_path, object_id, actual_size_bytes,
             actual_content_digest, lfs_oid, lfs_size_bytes, verified_at,
             verification_digest, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.ref_id,
                receipt.publication_id,
                receipt.repository_binding_id,
                receipt.repository_binding_version,
                receipt.commit,
                receipt.tree,
                receipt.path,
                receipt.object_id,
                receipt.actual_size_bytes,
                receipt.actual_content_digest,
                receipt.lfs_oid,
                receipt.lfs_size_bytes,
                receipt.verified_at,
                receipt.verification_digest,
                REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION,
            ),
        )

    @staticmethod
    def _validate(
        payload: Mapping[str, JsonValue], *, entity_id: str
    ) -> RevisionPathVerificationReceipt:
        expected = {
            "schema_version",
            "ref_id",
            "publication_id",
            "repository_binding_id",
            "repository_binding_version",
            "commit",
            "tree",
            "path",
            "object_id",
            "actual_size_bytes",
            "actual_content_digest",
            "lfs_oid",
            "lfs_size_bytes",
            "verified_at",
            "verification_digest",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version")
            != REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION
            or payload.get("ref_id") != entity_id
        ):
            raise SQLiteControlStoreError(
                "sqlite_revision_path_verification_invalid",
                "RevisionPathVerification violates its closed contract or identity",
                phase="entity_encode",
            )
        try:
            return RevisionPathVerificationReceipt(
                ref_id=str(payload["ref_id"]),
                publication_id=str(payload["publication_id"]),
                repository_binding_id=str(payload["repository_binding_id"]),
                repository_binding_version=int(payload["repository_binding_version"]),
                commit=str(payload["commit"]),
                tree=str(payload["tree"]),
                path=str(payload["path"]),
                object_id=str(payload["object_id"]),
                actual_size_bytes=(
                    None
                    if payload["actual_size_bytes"] is None
                    else int(payload["actual_size_bytes"])
                ),
                actual_content_digest=(
                    None
                    if payload["actual_content_digest"] is None
                    else str(payload["actual_content_digest"])
                ),
                lfs_oid=(
                    None if payload["lfs_oid"] is None else str(payload["lfs_oid"])
                ),
                lfs_size_bytes=(
                    None
                    if payload["lfs_size_bytes"] is None
                    else int(payload["lfs_size_bytes"])
                ),
                verified_at=str(payload["verified_at"]),
                verification_digest=str(payload["verification_digest"]),
            )
        except (TypeError, ValueError) as exc:
            raise SQLiteControlStoreError(
                "sqlite_revision_path_verification_invalid",
                "RevisionPathVerification values violate their contract",
                phase="entity_encode",
            ) from exc


def kernel_entity_codecs() -> tuple[SQLiteKernelEntityCodec, ...]:
    """Return the complete implemented Kernel-to-owner-table codec set.

    The concrete catalog belongs to the SQLite Adapter. Distributions may
    require a narrower or equal closed entity set, but must not copy this
    construction or depend on another Distribution to obtain it.
    """

    return (
        AgentAuthorityLeaseSQLiteKernelEntityCodec(),
        AgentMemberSQLiteKernelEntityCodec(),
        AgentRuntimeSignalSQLiteKernelEntityCodec(),
        ApprovalRequestSQLiteKernelEntityCodec(),
        CommandToolExpansionSQLiteKernelEntityCodec(),
        ConversationMessageSQLiteKernelEntityCodec(),
        ContinuationSQLiteKernelEntityCodec(),
        ControlledOperationSQLiteKernelEntityCodec(),
        FailureObservationSQLiteKernelEntityCodec(),
        PrivateDiagnosticSQLiteKernelEntityCodec(),
        InboxMessageSQLiteKernelEntityCodec(),
        KernelCommandReceiptSQLiteKernelEntityCodec(),
        LaneSQLiteKernelEntityCodec(),
        MemorySQLiteKernelEntityCodec(),
        PublishedRevisionSQLiteKernelEntityCodec(),
        ProjectRepositoryBindingHeadSQLiteKernelEntityCodec(),
        ProjectRepositoryBindingSQLiteKernelEntityCodec(),
        ProtocolRecordSQLiteKernelEntityCodec(),
        RevisionPathVerificationSQLiteKernelEntityCodec(),
        RuntimeContinuationIntentSQLiteKernelEntityCodec(),
        RuntimeCommandSQLiteKernelEntityCodec(),
        RuntimeOutcomeConsumptionSQLiteKernelEntityCodec(),
        RuntimeSignalAuthorityLinkSQLiteKernelEntityCodec(),
        RuntimeSettlementIntentSQLiteKernelEntityCodec(),
        RuntimeTurnCommandSQLiteKernelEntityCodec(),
        RuntimeTurnContextSQLiteKernelEntityCodec(),
        RuntimeTurnOutcomeSQLiteKernelEntityCodec(),
        SessionCapabilityBindingSQLiteKernelEntityCodec(),
        SessionCompositionPinSQLiteKernelEntityCodec(),
        SessionRepositoryBindingPinSQLiteKernelEntityCodec(),
        SessionRuntimeLeaseSQLiteKernelEntityCodec(),
        SessionSQLiteKernelEntityCodec(),
        TaskSQLiteKernelEntityCodec(),
        TaskEvidenceSQLiteKernelEntityCodec(),
        ToolExposureSnapshotSQLiteKernelEntityCodec(),
        VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec(),
        WorkspaceGenerationSQLiteKernelEntityCodec(),
        WorkspaceProvisioningIntentSQLiteKernelEntityCodec(),
        WorkspaceProvisioningReconciliationSQLiteKernelEntityCodec(),
        WorkspaceProvisioningReceiptSQLiteKernelEntityCodec(),
        WorkspacePublicationIntentSQLiteKernelEntityCodec(),
        WorkspaceRuntimeBindingSQLiteKernelEntityCodec(),
        WorkflowAuthorityBindingSQLiteKernelEntityCodec(),
    )


__all__ = [
    "AgentAuthorityLeaseSQLiteKernelEntityCodec",
    "AgentMemberSQLiteKernelEntityCodec",
    "AgentRuntimeSignalSQLiteKernelEntityCodec",
    "ApprovalRequestSQLiteKernelEntityCodec",
    "CommandToolExpansionSQLiteKernelEntityCodec",
    "ConversationMessageSQLiteKernelEntityCodec",
    "ContinuationSQLiteKernelEntityCodec",
    "ControlledOperationSQLiteKernelEntityCodec",
    "FailureObservationSQLiteKernelEntityCodec",
    "PrivateDiagnosticSQLiteKernelEntityCodec",
    "InboxMessageSQLiteKernelEntityCodec",
    "KernelCommandReceiptSQLiteKernelEntityCodec",
    "LaneSQLiteKernelEntityCodec",
    "MemorySQLiteKernelEntityCodec",
    "PublishedRevisionSQLiteKernelEntityCodec",
    "ProjectRepositoryBindingHeadSQLiteKernelEntityCodec",
    "ProjectRepositoryBindingSQLiteKernelEntityCodec",
    "ProtocolRecordSQLiteKernelEntityCodec",
    "RevisionPathVerificationSQLiteKernelEntityCodec",
    "RuntimeContinuationIntentSQLiteKernelEntityCodec",
    "RuntimeCommandSQLiteKernelEntityCodec",
    "RuntimeOutcomeConsumptionSQLiteKernelEntityCodec",
    "RuntimeSignalAuthorityLinkSQLiteKernelEntityCodec",
    "RuntimeSettlementIntentSQLiteKernelEntityCodec",
    "RuntimeTurnCommandSQLiteKernelEntityCodec",
    "RuntimeTurnContextSQLiteKernelEntityCodec",
    "RuntimeTurnOutcomeSQLiteKernelEntityCodec",
    "SessionCapabilityBindingSQLiteKernelEntityCodec",
    "SessionCompositionPinSQLiteKernelEntityCodec",
    "SessionRuntimeLeaseSQLiteKernelEntityCodec",
    "SessionRepositoryBindingPinSQLiteKernelEntityCodec",
    "SessionSQLiteKernelEntityCodec",
    "TaskSQLiteKernelEntityCodec",
    "TaskEvidenceSQLiteKernelEntityCodec",
    "ToolExposureSnapshotSQLiteKernelEntityCodec",
    "VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec",
    "WorkspaceGenerationSQLiteKernelEntityCodec",
    "WorkspaceProvisioningIntentSQLiteKernelEntityCodec",
    "WorkspaceProvisioningReconciliationSQLiteKernelEntityCodec",
    "WorkspaceProvisioningReceiptSQLiteKernelEntityCodec",
    "WorkspaceRuntimeBindingSQLiteKernelEntityCodec",
    "WorkspacePublicationIntentSQLiteKernelEntityCodec",
    "WorkflowAuthorityBindingSQLiteKernelEntityCodec",
    "kernel_entity_codecs",
]
