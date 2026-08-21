from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


HPC_SCHEDULER_PORT_CONTRACT = "openzyme.hpc.scheduler-port@1"
HPC_SCHEDULER_PORT_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": HPC_SCHEDULER_PORT_CONTRACT,
        "methods": [
            "submit",
            "reconcile_submit",
            "observe",
            "cancel",
            "reconcile_cancel",
        ],
        "credential": "one_formal_occurrence_only",
        "public_handle": "opaque_no_raw_scheduler_id",
        "fallback": False,
    }
)

HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT = (
    "openzyme.hpc.scheduler-occurrence-ledger@1"
)
HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT,
        "identity": [
            "provider_id",
            "operation_kind",
            "operation_id",
            "request_digest",
        ],
        "operations": ["read", "reserve", "settle", "get_handle"],
        "private_fields": ["raw_scheduler_id"],
        "restart_reconciliation": "same_occurrence_only",
        "redispatch": False,
        "fallback": False,
    }
)


class SchedulerJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True, slots=True)
class SchedulerDispatchRequest:
    operation_id: str
    dispatch_id: str
    execution_id: str
    route_id: str
    target_id: str
    target_inventory_generation: int
    target_inventory_digest: str
    qualification_digest: str
    workload_digest: str
    credential_occurrence_id: str
    credential_digest: str
    absolute_deadline: str
    request_digest: str

    @classmethod
    def create(cls, **values: object) -> "SchedulerDispatchRequest":
        return cls(
            **values,
            request_digest=canonical_sha256_digest(
                {"schema_version": "scheduler_dispatch_request@1", **values}
            ),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "operation_id",
            "dispatch_id",
            "execution_id",
            "route_id",
            "target_id",
            "credential_occurrence_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.target_inventory_generation < 1:
            raise ValueError("target_inventory_generation must be positive")
        for field_name in (
            "target_inventory_digest",
            "qualification_digest",
            "workload_digest",
            "credential_digest",
            "request_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        try:
            deadline = datetime.fromisoformat(self.absolute_deadline)
        except ValueError as exc:
            raise ValueError("absolute_deadline must be ISO-8601") from exc
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError("absolute_deadline must include timezone")
        expected = canonical_sha256_digest(self.identity_payload)
        if self.request_digest != expected:
            raise ValueError("scheduler dispatch request digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "scheduler_dispatch_request@1",
            "operation_id": self.operation_id,
            "dispatch_id": self.dispatch_id,
            "execution_id": self.execution_id,
            "route_id": self.route_id,
            "target_id": self.target_id,
            "target_inventory_generation": self.target_inventory_generation,
            "target_inventory_digest": self.target_inventory_digest,
            "qualification_digest": self.qualification_digest,
            "workload_digest": self.workload_digest,
            "credential_occurrence_id": self.credential_occurrence_id,
            "credential_digest": self.credential_digest,
            "absolute_deadline": self.absolute_deadline,
        }


@dataclass(frozen=True, slots=True)
class SchedulerDispatchReceipt:
    operation_id: str
    request_digest: str
    effect_certainty: ExternalEffectCertainty
    opaque_handle_id: str | None
    accepted: bool | None
    fallback_performed: bool
    receipt_digest: str
    diagnostic_id: str | None = None

    @classmethod
    def create(cls, **values: object) -> "SchedulerDispatchReceipt":
        payload = {"schema_version": "scheduler_dispatch_receipt@1", **values}
        return cls(**values, receipt_digest=canonical_sha256_digest(payload))

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.request_digest, field_name="request_digest")
        require_digest(self.receipt_digest, field_name="receipt_digest")
        if self.opaque_handle_id is not None:
            require_identifier(self.opaque_handle_id, field_name="opaque_handle_id")
        if self.diagnostic_id is not None:
            require_identifier(self.diagnostic_id, field_name="diagnostic_id")
        if self.fallback_performed:
            raise ValueError("scheduler Adapter must not perform fallback")
        if self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.opaque_handle_id is not None or self.accepted is not None:
                raise ValueError("uncertain scheduler receipt cannot claim a handle")
        elif self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if self.opaque_handle_id is not None or self.accepted is not False:
                raise ValueError("no_effect scheduler receipt must report rejected")
        elif self.accepted is True and self.opaque_handle_id is None:
            raise ValueError("accepted scheduler receipt requires opaque handle")
        expected = canonical_sha256_digest(self.identity_payload)
        if self.receipt_digest != expected:
            raise ValueError("scheduler dispatch receipt digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "scheduler_dispatch_receipt@1",
            "operation_id": self.operation_id,
            "request_digest": self.request_digest,
            "effect_certainty": self.effect_certainty.value,
            "opaque_handle_id": self.opaque_handle_id,
            "accepted": self.accepted,
            "fallback_performed": self.fallback_performed,
            "diagnostic_id": self.diagnostic_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: object) -> SchedulerDispatchReceipt:
        fields = {
            "schema_version",
            "operation_id",
            "request_digest",
            "effect_certainty",
            "opaque_handle_id",
            "accepted",
            "fallback_performed",
            "diagnostic_id",
            "receipt_digest",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("scheduler receipt fields are closed")
        if value["schema_version"] != "scheduler_dispatch_receipt@1":
            raise ValueError("scheduler receipt schema drifted")
        return cls(
            operation_id=str(value["operation_id"]),
            request_digest=str(value["request_digest"]),
            effect_certainty=ExternalEffectCertainty(str(value["effect_certainty"])),
            opaque_handle_id=(
                None
                if value["opaque_handle_id"] is None
                else str(value["opaque_handle_id"])
            ),
            accepted=value["accepted"],
            fallback_performed=value["fallback_performed"] is True,
            receipt_digest=str(value["receipt_digest"]),
            diagnostic_id=(
                None
                if value["diagnostic_id"] is None
                else str(value["diagnostic_id"])
            ),
        )


@dataclass(frozen=True, slots=True)
class SchedulerObservation:
    opaque_handle_id: str
    state: SchedulerJobState
    observation_index: int
    result_digest: str | None
    observation_digest: str

    @classmethod
    def create(cls, **values: object) -> "SchedulerObservation":
        payload = {"schema_version": "scheduler_observation@1", **values}
        return cls(**values, observation_digest=canonical_sha256_digest(payload))

    def __post_init__(self) -> None:
        require_identifier(self.opaque_handle_id, field_name="opaque_handle_id")
        if self.observation_index < 1:
            raise ValueError("observation_index must be positive")
        if self.result_digest is not None:
            require_digest(self.result_digest, field_name="result_digest")
        require_digest(self.observation_digest, field_name="observation_digest")
        if self.observation_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("scheduler observation digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "scheduler_observation@1",
            "opaque_handle_id": self.opaque_handle_id,
            "state": self.state.value,
            "observation_index": self.observation_index,
            "result_digest": self.result_digest,
        }


@dataclass(frozen=True, slots=True)
class SchedulerCancelRequest:
    operation_id: str
    opaque_handle_id: str
    reason: str
    credential_occurrence_id: str
    credential_digest: str
    request_digest: str

    @classmethod
    def create(cls, **values: object) -> "SchedulerCancelRequest":
        return cls(
            **values,
            request_digest=canonical_sha256_digest(
                {"schema_version": "scheduler_cancel_request@1", **values}
            ),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "operation_id",
            "opaque_handle_id",
            "credential_occurrence_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.credential_digest, field_name="credential_digest")
        require_digest(self.request_digest, field_name="request_digest")
        if not self.reason or self.reason != self.reason.strip():
            raise ValueError("cancel reason must be explicit")
        if self.request_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("scheduler cancel request digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "scheduler_cancel_request@1",
            "operation_id": self.operation_id,
            "opaque_handle_id": self.opaque_handle_id,
            "reason": self.reason,
            "credential_occurrence_id": self.credential_occurrence_id,
            "credential_digest": self.credential_digest,
        }


class SchedulerOccurrenceKind(StrEnum):
    SUBMIT = "submit"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class SchedulerOccurrenceIdentity:
    provider_id: str
    operation_kind: SchedulerOccurrenceKind
    operation_id: str
    request_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.provider_id, field_name="provider_id")
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.request_digest, field_name="request_digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "scheduler_occurrence_identity@1",
            "provider_id": self.provider_id,
            "operation_kind": self.operation_kind.value,
            "operation_id": self.operation_id,
            "request_digest": self.request_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> SchedulerOccurrenceIdentity:
        fields = {
            "schema_version",
            "provider_id",
            "operation_kind",
            "operation_id",
            "request_digest",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("scheduler occurrence identity fields are closed")
        if value["schema_version"] != "scheduler_occurrence_identity@1":
            raise ValueError("scheduler occurrence identity schema drifted")
        return cls(
            provider_id=str(value["provider_id"]),
            operation_kind=SchedulerOccurrenceKind(str(value["operation_kind"])),
            operation_id=str(value["operation_id"]),
            request_digest=str(value["request_digest"]),
        )


@dataclass(frozen=True, slots=True)
class PrivateSchedulerHandleRecord:
    opaque_handle_id: str
    operation_id: str
    request_digest: str
    raw_scheduler_id: str = field(repr=False)

    def __post_init__(self) -> None:
        require_identifier(self.opaque_handle_id, field_name="opaque_handle_id")
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.request_digest, field_name="request_digest")
        require_identifier(self.raw_scheduler_id, field_name="raw_scheduler_id")


@dataclass(frozen=True, slots=True)
class SchedulerOccurrenceRecord:
    identity: SchedulerOccurrenceIdentity
    receipt: SchedulerDispatchReceipt | None
    raw_scheduler_id: str | None = field(default=None, repr=False)
    ledger_version: int = 1

    def __post_init__(self) -> None:
        if self.ledger_version < 1:
            raise ValueError("scheduler ledger version must be positive")
        if self.receipt is not None and (
            self.receipt.operation_id != self.identity.operation_id
            or self.receipt.request_digest != self.identity.request_digest
        ):
            raise ValueError("scheduler receipt crossed its occurrence identity")
        if self.raw_scheduler_id is not None:
            require_identifier(self.raw_scheduler_id, field_name="raw_scheduler_id")
            if (
                self.identity.operation_kind is not SchedulerOccurrenceKind.SUBMIT
                or self.receipt is None
                or self.receipt.accepted is not True
                or self.receipt.opaque_handle_id is None
            ):
                raise ValueError("private scheduler handle requires an accepted submit")

    @property
    def record_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "scheduler_occurrence_record@1",
            "identity": self.identity.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "raw_scheduler_id": self.raw_scheduler_id,
            "ledger_version": self.ledger_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> SchedulerOccurrenceRecord:
        fields = {
            "schema_version",
            "identity",
            "receipt",
            "raw_scheduler_id",
            "ledger_version",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("scheduler occurrence fields are closed")
        if value["schema_version"] != "scheduler_occurrence_record@1":
            raise ValueError("scheduler occurrence schema drifted")
        return cls(
            identity=SchedulerOccurrenceIdentity.from_dict(value["identity"]),
            receipt=(
                None
                if value["receipt"] is None
                else SchedulerDispatchReceipt.from_dict(value["receipt"])
            ),
            raw_scheduler_id=(
                None
                if value["raw_scheduler_id"] is None
                else str(value["raw_scheduler_id"])
            ),
            ledger_version=int(value["ledger_version"]),
        )

    def private_handle(self) -> PrivateSchedulerHandleRecord | None:
        if self.raw_scheduler_id is None or self.receipt is None:
            return None
        assert self.receipt.opaque_handle_id is not None
        return PrivateSchedulerHandleRecord(
            opaque_handle_id=self.receipt.opaque_handle_id,
            operation_id=self.identity.operation_id,
            request_digest=self.identity.request_digest,
            raw_scheduler_id=self.raw_scheduler_id,
        )


class SchedulerOccurrenceLedger(Protocol):
    def read(
        self,
        identity: SchedulerOccurrenceIdentity,
    ) -> SchedulerOccurrenceRecord | None: ...

    def reserve(self, identity: SchedulerOccurrenceIdentity) -> bool: ...

    def settle(
        self,
        identity: SchedulerOccurrenceIdentity,
        receipt: SchedulerDispatchReceipt,
        *,
        raw_scheduler_id: str | None = None,
    ) -> SchedulerOccurrenceRecord: ...

    def get_handle(
        self,
        provider_id: str,
        opaque_handle_id: str,
    ) -> PrivateSchedulerHandleRecord | None: ...


class HpcSchedulerPort(Protocol):
    def submit(self, request: SchedulerDispatchRequest) -> SchedulerDispatchReceipt: ...

    def reconcile_submit(
        self,
        request: SchedulerDispatchRequest,
    ) -> SchedulerDispatchReceipt: ...

    def observe(
        self,
        opaque_handle_id: str,
        *,
        observation_index: int,
    ) -> SchedulerObservation: ...

    def cancel(self, request: SchedulerCancelRequest) -> SchedulerDispatchReceipt: ...

    def reconcile_cancel(
        self,
        request: SchedulerCancelRequest,
    ) -> SchedulerDispatchReceipt: ...


__all__ = [
    "HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT",
    "HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT_DIGEST",
    "HPC_SCHEDULER_PORT_CONTRACT",
    "HPC_SCHEDULER_PORT_CONTRACT_DIGEST",
    "HpcSchedulerPort",
    "SchedulerCancelRequest",
    "SchedulerDispatchReceipt",
    "SchedulerDispatchRequest",
    "SchedulerJobState",
    "SchedulerObservation",
    "PrivateSchedulerHandleRecord",
    "SchedulerOccurrenceIdentity",
    "SchedulerOccurrenceKind",
    "SchedulerOccurrenceLedger",
    "SchedulerOccurrenceRecord",
]
