from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol

from .identity import JsonValue
from .identity import canonical_sha256_digest
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_digest
from .identity import require_identifier
from .reliability import ControlledOperationDispatchRequest
from .reliability import ControlledOperationProviderDispatchReceipt
from .reliability import ControlledOperationProviderObservationReceipt


KERNEL_RECORD_SNAPSHOT_SCHEMA_VERSION = "kernel_record_snapshot@1"
KERNEL_STATE_MUTATION_SCHEMA_VERSION = "kernel_state_mutation@1"
UNIT_OF_WORK_REQUEST_SCHEMA_VERSION = "kernel_unit_of_work_request@1"
UNIT_OF_WORK_RECEIPT_SCHEMA_VERSION = "kernel_unit_of_work_receipt@1"
DURABLE_EVENT_RECORD_SCHEMA_VERSION = "durable_event_record@1"
OUTBOX_RECORD_SCHEMA_VERSION = "outbox_record@1"
CREDENTIAL_MATERIAL_REQUEST_SCHEMA_VERSION = "credential_material_request@1"
CREDENTIAL_MATERIAL_RECEIPT_SCHEMA_VERSION = "credential_material_receipt@1"
CONTROLLED_EFFECT_OBSERVATION_REQUEST_SCHEMA_VERSION = (
    "controlled_effect_observation_request@1"
)
CONTROLLED_EFFECT_CANCELLATION_REQUEST_SCHEMA_VERSION = (
    "controlled_effect_cancellation_request@1"
)


class KernelMutationKind(StrEnum):
    CREATE = "create"
    REPLACE = "replace"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class KernelRecordSnapshot:
    entity_type: str
    entity_id: str
    state_version: int
    payload: Mapping[str, JsonValue]
    record_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.entity_type, field_name="entity_type")
        require_identifier(self.entity_id, field_name="entity_id")
        if self.state_version < 1:
            raise ValueError("state_version must be positive")
        frozen = freeze_json(self.payload, field_name="payload")
        if not isinstance(frozen, Mapping):
            raise ValueError("payload must be a JSON object")
        object.__setattr__(self, "payload", frozen)
        require_digest(self.record_digest, field_name="record_digest")
        if self.record_digest != canonical_sha256_digest(self.canonical_payload):
            raise ValueError("record_digest does not match the record payload")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": KERNEL_RECORD_SNAPSHOT_SCHEMA_VERSION,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "state_version": self.state_version,
            "payload": json_compatible(self.payload),
        }

    @classmethod
    def create(
        cls,
        *,
        entity_type: str,
        entity_id: str,
        state_version: int,
        payload: Mapping[str, JsonValue],
    ) -> KernelRecordSnapshot:
        frozen = freeze_json(payload, field_name="payload")
        if not isinstance(frozen, Mapping):
            raise ValueError("payload must be a JSON object")
        canonical_payload = {
            "schema_version": KERNEL_RECORD_SNAPSHOT_SCHEMA_VERSION,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "state_version": state_version,
            "payload": json_compatible(frozen),
        }
        return cls(
            entity_type=entity_type,
            entity_id=entity_id,
            state_version=state_version,
            payload=frozen,
            record_digest=canonical_sha256_digest(canonical_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload, "record_digest": self.record_digest}


@dataclass(frozen=True, slots=True)
class KernelStateMutation:
    mutation_id: str
    kind: KernelMutationKind
    entity_type: str
    entity_id: str
    expected_state_version: int | None
    payload: Mapping[str, JsonValue] | None
    mutation_digest: str

    def __post_init__(self) -> None:
        for field_name in ("mutation_id", "entity_type", "entity_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.expected_state_version is not None and self.expected_state_version < 1:
            raise ValueError("expected_state_version must be positive when present")
        if self.kind is KernelMutationKind.CREATE and self.expected_state_version is not None:
            raise ValueError("create must not claim an existing state version")
        if self.kind in {KernelMutationKind.REPLACE, KernelMutationKind.DELETE} and (
            self.expected_state_version is None
        ):
            raise ValueError("replace/delete requires expected_state_version")
        if self.kind is KernelMutationKind.DELETE:
            if self.payload is not None:
                raise ValueError("delete mutation must not carry payload")
        elif self.payload is None:
            raise ValueError("create/replace mutation requires payload")
        if self.payload is not None:
            frozen = freeze_json(self.payload, field_name="payload")
            if not isinstance(frozen, Mapping):
                raise ValueError("payload must be a JSON object")
            object.__setattr__(self, "payload", frozen)
        require_digest(self.mutation_digest, field_name="mutation_digest")
        if self.mutation_digest != canonical_sha256_digest(self.canonical_payload):
            raise ValueError("mutation_digest does not match mutation payload")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": KERNEL_STATE_MUTATION_SCHEMA_VERSION,
            "mutation_id": self.mutation_id,
            "kind": self.kind.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "expected_state_version": self.expected_state_version,
            "payload": None if self.payload is None else json_compatible(self.payload),
        }

    @classmethod
    def create(
        cls,
        *,
        mutation_id: str,
        kind: KernelMutationKind,
        entity_type: str,
        entity_id: str,
        expected_state_version: int | None,
        payload: Mapping[str, JsonValue] | None,
    ) -> KernelStateMutation:
        frozen = None if payload is None else freeze_json(payload, field_name="payload")
        if frozen is not None and not isinstance(frozen, Mapping):
            raise ValueError("payload must be a JSON object")
        canonical_payload = {
            "schema_version": KERNEL_STATE_MUTATION_SCHEMA_VERSION,
            "mutation_id": mutation_id,
            "kind": kind.value,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "expected_state_version": expected_state_version,
            "payload": None if frozen is None else json_compatible(frozen),
        }
        return cls(
            mutation_id=mutation_id,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state_version=expected_state_version,
            payload=frozen,
            mutation_digest=canonical_sha256_digest(canonical_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload, "mutation_digest": self.mutation_digest}


@dataclass(frozen=True, slots=True)
class DurableEventRecord:
    event_id: str
    session_id: str
    event_type: str
    source_entity_type: str
    source_entity_id: str
    source_state_version: int
    command_id: str
    payload: Mapping[str, JsonValue]
    event_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "session_id",
            "event_type",
            "source_entity_type",
            "source_entity_id",
            "command_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.source_state_version < 1:
            raise ValueError("source_state_version must be positive")
        frozen = freeze_json(self.payload, field_name="payload")
        if not isinstance(frozen, Mapping):
            raise ValueError("event payload must be a JSON object")
        object.__setattr__(self, "payload", frozen)
        require_digest(self.event_digest, field_name="event_digest")
        if self.event_digest != canonical_sha256_digest(self.canonical_payload):
            raise ValueError("event_digest does not match event payload")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": DURABLE_EVENT_RECORD_SCHEMA_VERSION,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "source_entity_type": self.source_entity_type,
            "source_entity_id": self.source_entity_id,
            "source_state_version": self.source_state_version,
            "command_id": self.command_id,
            "payload": json_compatible(self.payload),
        }

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        session_id: str,
        event_type: str,
        source_entity_type: str,
        source_entity_id: str,
        source_state_version: int,
        command_id: str,
        payload: Mapping[str, JsonValue],
    ) -> DurableEventRecord:
        frozen = freeze_json(payload, field_name="payload")
        if not isinstance(frozen, Mapping):
            raise ValueError("event payload must be a JSON object")
        canonical_payload = {
            "schema_version": DURABLE_EVENT_RECORD_SCHEMA_VERSION,
            "event_id": event_id,
            "session_id": session_id,
            "event_type": event_type,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
            "source_state_version": source_state_version,
            "command_id": command_id,
            "payload": json_compatible(frozen),
        }
        return cls(
            event_id=event_id,
            session_id=session_id,
            event_type=event_type,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            source_state_version=source_state_version,
            command_id=command_id,
            payload=frozen,
            event_digest=canonical_sha256_digest(canonical_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload, "event_digest": self.event_digest}


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    outbox_id: str
    session_id: str
    topic: str
    occurrence_id: str
    payload: Mapping[str, JsonValue]
    payload_digest: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("outbox_id", "session_id", "topic", "occurrence_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        frozen = freeze_json(self.payload, field_name="payload")
        if not isinstance(frozen, Mapping):
            raise ValueError("outbox payload must be a JSON object")
        object.__setattr__(self, "payload", frozen)
        require_digest(self.payload_digest, field_name="payload_digest")
        if self.payload_digest != canonical_sha256_digest(json_compatible(frozen)):
            raise ValueError("outbox payload_digest does not match payload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OUTBOX_RECORD_SCHEMA_VERSION,
            "outbox_id": self.outbox_id,
            "session_id": self.session_id,
            "topic": self.topic,
            "occurrence_id": self.occurrence_id,
            "payload": json_compatible(self.payload),
            "payload_digest": self.payload_digest,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class UnitOfWorkRequest:
    unit_of_work_id: str
    command_id: str
    session_id: str
    actor_id: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    expected_session_version: int
    idempotency_key: str
    command_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "unit_of_work_id",
            "command_id",
            "session_id",
            "actor_id",
            "authority_lease_id",
            "idempotency_key",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "authority_generation",
            "authority_fence",
            "expected_session_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        require_digest(self.command_digest, field_name="command_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": UNIT_OF_WORK_REQUEST_SCHEMA_VERSION,
            "unit_of_work_id": self.unit_of_work_id,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
            "expected_session_version": self.expected_session_version,
            "idempotency_key": self.idempotency_key,
            "command_digest": self.command_digest,
        }


@dataclass(frozen=True, slots=True)
class UnitOfWorkReceipt:
    unit_of_work_id: str
    command_id: str
    committed: bool
    mutation_digests: tuple[str, ...]
    event_digests: tuple[str, ...]
    outbox_payload_digests: tuple[str, ...]
    resulting_session_version: int | None
    receipt_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.unit_of_work_id, field_name="unit_of_work_id")
        require_identifier(self.command_id, field_name="command_id")
        for field_name in (
            "mutation_digests",
            "event_digests",
            "outbox_payload_digests",
        ):
            values = getattr(self, field_name)
            for value in values:
                require_digest(value, field_name=field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
        if self.committed != (self.resulting_session_version is not None):
            raise ValueError("commit fact and resulting_session_version must agree")
        if self.resulting_session_version is not None and self.resulting_session_version < 1:
            raise ValueError("resulting_session_version must be positive")
        require_digest(self.receipt_digest, field_name="receipt_digest")
        if self.receipt_digest != canonical_sha256_digest(self.canonical_payload):
            raise ValueError("receipt_digest does not match Unit of Work payload")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": UNIT_OF_WORK_RECEIPT_SCHEMA_VERSION,
            "unit_of_work_id": self.unit_of_work_id,
            "command_id": self.command_id,
            "committed": self.committed,
            "mutation_digests": list(self.mutation_digests),
            "event_digests": list(self.event_digests),
            "outbox_payload_digests": list(self.outbox_payload_digests),
            "resulting_session_version": self.resulting_session_version,
        }

    @classmethod
    def create(
        cls,
        *,
        unit_of_work_id: str,
        command_id: str,
        committed: bool,
        mutation_digests: tuple[str, ...],
        event_digests: tuple[str, ...],
        outbox_payload_digests: tuple[str, ...],
        resulting_session_version: int | None,
    ) -> UnitOfWorkReceipt:
        canonical_payload = {
            "schema_version": UNIT_OF_WORK_RECEIPT_SCHEMA_VERSION,
            "unit_of_work_id": unit_of_work_id,
            "command_id": command_id,
            "committed": committed,
            "mutation_digests": list(mutation_digests),
            "event_digests": list(event_digests),
            "outbox_payload_digests": list(outbox_payload_digests),
            "resulting_session_version": resulting_session_version,
        }
        return cls(
            unit_of_work_id=unit_of_work_id,
            command_id=command_id,
            committed=committed,
            mutation_digests=mutation_digests,
            event_digests=event_digests,
            outbox_payload_digests=outbox_payload_digests,
            resulting_session_version=resulting_session_version,
            receipt_digest=canonical_sha256_digest(canonical_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload, "receipt_digest": self.receipt_digest}


class ClockPort(Protocol):
    def now_iso(self) -> str: ...


class IdGeneratorPort(Protocol):
    def new_id(self, *, namespace: str) -> str: ...


class KernelUnitOfWork(Protocol):
    request: UnitOfWorkRequest

    def read(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> KernelRecordSnapshot | None: ...

    def stage(self, mutation: KernelStateMutation) -> None: ...

    def append_event(self, event: DurableEventRecord) -> None: ...

    def append_outbox(self, record: OutboxRecord) -> None: ...

    def commit(self) -> UnitOfWorkReceipt: ...

    def rollback(self) -> None: ...


class ControlStorePort(Protocol):
    provider_id: str
    provider_contract_digest: str

    def begin(self, request: UnitOfWorkRequest) -> KernelUnitOfWork: ...


class KernelRecordReaderPort(Protocol):
    """Read-only record view; implementations must not open a writer transaction."""

    def read(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> KernelRecordSnapshot | None: ...


class KernelRecordQueryPort(KernelRecordReaderPort, Protocol):
    """Bounded read model over canonical Kernel records.

    Projection code may enumerate records only within one exact Session.  The
    implementation must read through the same closed entity codecs used by the
    canonical store; this Port is not a raw-SQL or generic JSON escape hatch.
    """

    def list_for_session(
        self,
        *,
        entity_type: str,
        session_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]: ...


class OutboxDeliveryPort(Protocol):
    provider_id: str

    def deliver(self, record: OutboxRecord) -> str: ...


@dataclass(frozen=True, slots=True)
class CredentialMaterialRequest:
    request_id: str
    session_id: str
    actor_id: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    service_id: str
    target_id: str
    protocol_id: str
    audience: str
    expires_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "session_id",
            "actor_id",
            "authority_lease_id",
            "service_id",
            "target_id",
            "protocol_id",
            "audience",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.authority_generation < 1 or self.authority_fence < 1:
            raise ValueError("credential request authority identity must be positive")


@dataclass(frozen=True, slots=True)
class CredentialMaterialReceipt:
    receipt_id: str
    request_id: str
    credential_handle: str
    provider_id: str
    issued_at: str
    expires_at: str
    revocation_handle: str
    receipt_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "request_id",
            "credential_handle",
            "provider_id",
            "revocation_handle",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.receipt_digest, field_name="receipt_digest")


class CredentialMaterialPort(Protocol):
    provider_id: str

    def issue(self, request: CredentialMaterialRequest) -> CredentialMaterialReceipt: ...

    def revoke(self, *, revocation_handle: str) -> CredentialMaterialReceipt: ...


@dataclass(frozen=True, slots=True)
class ControlledEffectObservationRequest:
    observation_id: str
    execution_id: str
    operation_id: str
    route_id: str
    dispatch_generation: int
    provider_request_identity: str
    authority_fence: int

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "execution_id",
            "operation_id",
            "route_id",
            "provider_request_identity",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.dispatch_generation < 1 or self.authority_fence < 1:
            raise ValueError("observation generation/fence must be positive")


@dataclass(frozen=True, slots=True)
class ControlledEffectCancellationRequest:
    cancellation_id: str
    execution_id: str
    operation_id: str
    route_id: str
    dispatch_generation: int
    provider_request_identity: str
    authority_fence: int
    cancellation_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "cancellation_id",
            "execution_id",
            "operation_id",
            "route_id",
            "provider_request_identity",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.dispatch_generation < 1 or self.authority_fence < 1:
            raise ValueError("cancellation generation/fence must be positive")
        require_digest(self.cancellation_digest, field_name="cancellation_digest")


class ControlledEffectAdapterPort(Protocol):
    provider_id: str
    provider_contract_digest: str

    def dispatch(
        self,
        request: ControlledOperationDispatchRequest,
    ) -> ControlledOperationProviderDispatchReceipt: ...

    def observe(
        self,
        request: ControlledEffectObservationRequest,
    ) -> ControlledOperationProviderObservationReceipt: ...

    def cancel(
        self,
        request: ControlledEffectCancellationRequest,
    ) -> ControlledOperationProviderObservationReceipt: ...


__all__ = [
    "CONTROLLED_EFFECT_CANCELLATION_REQUEST_SCHEMA_VERSION",
    "CONTROLLED_EFFECT_OBSERVATION_REQUEST_SCHEMA_VERSION",
    "CREDENTIAL_MATERIAL_RECEIPT_SCHEMA_VERSION",
    "CREDENTIAL_MATERIAL_REQUEST_SCHEMA_VERSION",
    "ClockPort",
    "ControlStorePort",
    "ControlledEffectAdapterPort",
    "ControlledEffectCancellationRequest",
    "ControlledEffectObservationRequest",
    "CredentialMaterialPort",
    "CredentialMaterialReceipt",
    "CredentialMaterialRequest",
    "DURABLE_EVENT_RECORD_SCHEMA_VERSION",
    "DurableEventRecord",
    "IdGeneratorPort",
    "KERNEL_RECORD_SNAPSHOT_SCHEMA_VERSION",
    "KERNEL_STATE_MUTATION_SCHEMA_VERSION",
    "KernelMutationKind",
    "KernelRecordSnapshot",
    "KernelRecordReaderPort",
    "KernelRecordQueryPort",
    "KernelStateMutation",
    "KernelUnitOfWork",
    "OUTBOX_RECORD_SCHEMA_VERSION",
    "OutboxDeliveryPort",
    "OutboxRecord",
    "UNIT_OF_WORK_RECEIPT_SCHEMA_VERSION",
    "UNIT_OF_WORK_REQUEST_SCHEMA_VERSION",
    "UnitOfWorkReceipt",
    "UnitOfWorkRequest",
]
