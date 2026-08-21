from __future__ import annotations

from dataclasses import dataclass
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
    "HPC_SCHEDULER_PORT_CONTRACT",
    "HPC_SCHEDULER_PORT_CONTRACT_DIGEST",
    "HpcSchedulerPort",
    "SchedulerCancelRequest",
    "SchedulerDispatchReceipt",
    "SchedulerDispatchRequest",
    "SchedulerJobState",
    "SchedulerObservation",
]
