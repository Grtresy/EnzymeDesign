from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_hpc import SchedulerCancelRequest
from openzyme_hpc import SchedulerDispatchReceipt
from openzyme_hpc import SchedulerDispatchRequest
from openzyme_hpc import SchedulerJobState
from openzyme_hpc import SchedulerObservation


SLURM_ADAPTER_ID = "openzyme.hpc.slurm"
SLURM_ADAPTER_CONTRACT = "openzyme.hpc.slurm@1"
SLURM_ADAPTER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": SLURM_ADAPTER_CONTRACT,
        "port": "openzyme.hpc.scheduler-port@1",
        "credential": "one_formal_occurrence_only",
        "public_handle": "opaque",
        "raw_scheduler_id": "private_ledger_only",
        "reconcile": "same_occurrence_no_resubmit",
        "fallback": False,
    }
)


@dataclass(frozen=True, slots=True)
class PrivateSchedulerOccurrenceCredential:
    occurrence_id: str
    credential_digest: str
    opaque_token: str = field(repr=False)

    def __post_init__(self) -> None:
        require_identifier(self.occurrence_id, field_name="occurrence_id")
        require_digest(self.credential_digest, field_name="credential_digest")
        if not self.opaque_token or self.opaque_token != self.opaque_token.strip():
            raise ValueError("scheduler credential token must be bounded and exact")


class SchedulerOccurrenceCredentialResolver(Protocol):
    def resolve(
        self,
        occurrence_id: str,
    ) -> PrivateSchedulerOccurrenceCredential | None: ...


@dataclass(frozen=True, slots=True)
class SlurmBackendOutcome:
    operation_id: str
    request_digest: str
    effect_certainty: ExternalEffectCertainty
    accepted: bool | None
    raw_scheduler_id: str | None = field(default=None, repr=False)
    state: SchedulerJobState | None = None
    result_digest: str | None = None
    diagnostic_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.request_digest, field_name="request_digest")
        if self.raw_scheduler_id is not None:
            require_identifier(self.raw_scheduler_id, field_name="raw_scheduler_id")
        if self.result_digest is not None:
            require_digest(self.result_digest, field_name="result_digest")
        if self.diagnostic_id is not None:
            require_identifier(self.diagnostic_id, field_name="diagnostic_id")
        if self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.accepted is not None or self.raw_scheduler_id is not None:
                raise ValueError("uncertain Slurm outcome cannot claim acceptance")
        if self.accepted is True and self.raw_scheduler_id is None:
            raise ValueError("accepted Slurm outcome requires a private scheduler id")


class SlurmBackend(Protocol):
    def submit(
        self,
        request: SchedulerDispatchRequest,
        credential: PrivateSchedulerOccurrenceCredential,
    ) -> SlurmBackendOutcome: ...

    def reconcile_submit(
        self,
        request: SchedulerDispatchRequest,
        credential: PrivateSchedulerOccurrenceCredential,
    ) -> SlurmBackendOutcome: ...

    def observe(
        self,
        *,
        operation_id: str,
        request_digest: str,
        raw_scheduler_id: str,
        observation_index: int,
    ) -> SlurmBackendOutcome: ...

    def cancel(
        self,
        request: SchedulerCancelRequest,
        credential: PrivateSchedulerOccurrenceCredential,
        *,
        raw_scheduler_id: str,
    ) -> SlurmBackendOutcome: ...

    def reconcile_cancel(
        self,
        request: SchedulerCancelRequest,
        credential: PrivateSchedulerOccurrenceCredential,
        *,
        raw_scheduler_id: str,
    ) -> SlurmBackendOutcome: ...


@dataclass(frozen=True, slots=True)
class PrivateSlurmHandleRecord:
    opaque_handle_id: str
    operation_id: str
    request_digest: str
    raw_scheduler_id: str = field(repr=False)


class SlurmHandleLedger(Protocol):
    def get_by_operation(self, operation_id: str) -> PrivateSlurmHandleRecord | None: ...

    def get(self, opaque_handle_id: str) -> PrivateSlurmHandleRecord | None: ...

    def add(self, record: PrivateSlurmHandleRecord) -> PrivateSlurmHandleRecord: ...


@dataclass(slots=True)
class InMemorySlurmHandleLedger:
    _by_handle: dict[str, PrivateSlurmHandleRecord] = field(default_factory=dict)
    _by_operation: dict[str, PrivateSlurmHandleRecord] = field(default_factory=dict)

    def get_by_operation(self, operation_id: str) -> PrivateSlurmHandleRecord | None:
        return self._by_operation.get(operation_id)

    def get(self, opaque_handle_id: str) -> PrivateSlurmHandleRecord | None:
        return self._by_handle.get(opaque_handle_id)

    def add(self, record: PrivateSlurmHandleRecord) -> PrivateSlurmHandleRecord:
        existing = self._by_operation.get(record.operation_id)
        if existing is not None:
            if existing != record:
                raise ValueError("Slurm operation identity collided")
            return existing
        if record.opaque_handle_id in self._by_handle:
            raise ValueError("opaque Slurm handle identity collided")
        self._by_operation[record.operation_id] = record
        self._by_handle[record.opaque_handle_id] = record
        return record


@dataclass(slots=True)
class SlurmSchedulerAdapter:
    backend: SlurmBackend
    credential_resolver: SchedulerOccurrenceCredentialResolver
    ledger: SlurmHandleLedger

    def submit(self, request: SchedulerDispatchRequest) -> SchedulerDispatchReceipt:
        credential = self._credential(
            request.credential_occurrence_id,
            request.credential_digest,
        )
        if credential is None:
            return self._no_effect(request.operation_id, request.request_digest)
        prior = self.ledger.get_by_operation(request.operation_id)
        if prior is not None:
            if prior.request_digest != request.request_digest:
                return self._no_effect(request.operation_id, request.request_digest)
            return self._accepted(prior)
        return self._settle_dispatch(
            request,
            self.backend.submit(request, credential),
        )

    def reconcile_submit(
        self,
        request: SchedulerDispatchRequest,
    ) -> SchedulerDispatchReceipt:
        credential = self._credential(
            request.credential_occurrence_id,
            request.credential_digest,
        )
        if credential is None:
            return self._no_effect(request.operation_id, request.request_digest)
        prior = self.ledger.get_by_operation(request.operation_id)
        if prior is not None:
            return self._accepted(prior)
        return self._settle_dispatch(
            request,
            self.backend.reconcile_submit(request, credential),
        )

    def observe(
        self,
        opaque_handle_id: str,
        *,
        observation_index: int,
    ) -> SchedulerObservation:
        record = self._record(opaque_handle_id)
        outcome = self.backend.observe(
            operation_id=record.operation_id,
            request_digest=record.request_digest,
            raw_scheduler_id=record.raw_scheduler_id,
            observation_index=observation_index,
        )
        self._require_identity(outcome, record.operation_id, record.request_digest)
        if (
            outcome.effect_certainty
            not in {
                ExternalEffectCertainty.EFFECT_KNOWN,
                ExternalEffectCertainty.TERMINAL_KNOWN,
            }
            or outcome.state is None
        ):
            raise RuntimeError("Slurm observation is not settled")
        return SchedulerObservation.create(
            opaque_handle_id=opaque_handle_id,
            state=outcome.state,
            observation_index=observation_index,
            result_digest=outcome.result_digest,
        )

    def cancel(self, request: SchedulerCancelRequest) -> SchedulerDispatchReceipt:
        return self._cancel(request, reconcile=False)

    def reconcile_cancel(
        self,
        request: SchedulerCancelRequest,
    ) -> SchedulerDispatchReceipt:
        return self._cancel(request, reconcile=True)

    def _cancel(
        self,
        request: SchedulerCancelRequest,
        *,
        reconcile: bool,
    ) -> SchedulerDispatchReceipt:
        record = self._record(request.opaque_handle_id)
        credential = self._credential(
            request.credential_occurrence_id,
            request.credential_digest,
        )
        if credential is None:
            return self._no_effect(request.operation_id, request.request_digest)
        outcome = (
            self.backend.reconcile_cancel(
                request,
                credential,
                raw_scheduler_id=record.raw_scheduler_id,
            )
            if reconcile
            else self.backend.cancel(
                request,
                credential,
                raw_scheduler_id=record.raw_scheduler_id,
            )
        )
        self._require_identity(outcome, request.operation_id, request.request_digest)
        return SchedulerDispatchReceipt.create(
            operation_id=request.operation_id,
            request_digest=request.request_digest,
            effect_certainty=outcome.effect_certainty,
            opaque_handle_id=(
                request.opaque_handle_id
                if outcome.effect_certainty
                in {
                    ExternalEffectCertainty.EFFECT_KNOWN,
                    ExternalEffectCertainty.TERMINAL_KNOWN,
                }
                else None
            ),
            accepted=outcome.accepted,
            fallback_performed=False,
            diagnostic_id=outcome.diagnostic_id,
        )

    def _settle_dispatch(
        self,
        request: SchedulerDispatchRequest,
        outcome: SlurmBackendOutcome,
    ) -> SchedulerDispatchReceipt:
        self._require_identity(outcome, request.operation_id, request.request_digest)
        if (
            outcome.effect_certainty
            in {
                ExternalEffectCertainty.EFFECT_KNOWN,
                ExternalEffectCertainty.TERMINAL_KNOWN,
            }
            and outcome.accepted is True
            and outcome.raw_scheduler_id is not None
        ):
            record = self.ledger.add(
                PrivateSlurmHandleRecord(
                    opaque_handle_id=(
                        "slurmh-"
                        + canonical_sha256_digest(
                            {
                                "operation_id": request.operation_id,
                                "request_digest": request.request_digest,
                                "raw_scheduler_id": outcome.raw_scheduler_id,
                            }
                        ).removeprefix("sha256:")[:32]
                    ),
                    operation_id=request.operation_id,
                    request_digest=request.request_digest,
                    raw_scheduler_id=outcome.raw_scheduler_id,
                )
            )
            return self._accepted(record)
        return SchedulerDispatchReceipt.create(
            operation_id=request.operation_id,
            request_digest=request.request_digest,
            effect_certainty=outcome.effect_certainty,
            opaque_handle_id=None,
            accepted=outcome.accepted,
            fallback_performed=False,
            diagnostic_id=outcome.diagnostic_id,
        )

    def _credential(
        self,
        occurrence_id: str,
        credential_digest: str,
    ) -> PrivateSchedulerOccurrenceCredential | None:
        credential = self.credential_resolver.resolve(occurrence_id)
        if (
            not isinstance(credential, PrivateSchedulerOccurrenceCredential)
            or credential.occurrence_id != occurrence_id
            or credential.credential_digest != credential_digest
        ):
            return None
        return credential

    def _record(self, opaque_handle_id: str) -> PrivateSlurmHandleRecord:
        require_identifier(opaque_handle_id, field_name="opaque_handle_id")
        record = self.ledger.get(opaque_handle_id)
        if record is None:
            raise ValueError("opaque Slurm handle is unknown")
        return record

    @staticmethod
    def _require_identity(
        outcome: SlurmBackendOutcome,
        operation_id: str,
        request_digest: str,
    ) -> None:
        if (
            outcome.operation_id != operation_id
            or outcome.request_digest != request_digest
        ):
            raise RuntimeError("Slurm backend response identity drifted")

    @staticmethod
    def _accepted(record: PrivateSlurmHandleRecord) -> SchedulerDispatchReceipt:
        return SchedulerDispatchReceipt.create(
            operation_id=record.operation_id,
            request_digest=record.request_digest,
            effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
            opaque_handle_id=record.opaque_handle_id,
            accepted=True,
            fallback_performed=False,
            diagnostic_id=None,
        )

    @staticmethod
    def _no_effect(
        operation_id: str,
        request_digest: str,
    ) -> SchedulerDispatchReceipt:
        return SchedulerDispatchReceipt.create(
            operation_id=operation_id,
            request_digest=request_digest,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            opaque_handle_id=None,
            accepted=False,
            fallback_performed=False,
            diagnostic_id=None,
        )


__all__ = [
    "InMemorySlurmHandleLedger",
    "PrivateSchedulerOccurrenceCredential",
    "PrivateSlurmHandleRecord",
    "SLURM_ADAPTER_CONTRACT",
    "SLURM_ADAPTER_CONTRACT_DIGEST",
    "SLURM_ADAPTER_ID",
    "SchedulerOccurrenceCredentialResolver",
    "SlurmBackend",
    "SlurmBackendOutcome",
    "SlurmHandleLedger",
    "SlurmSchedulerAdapter",
]
