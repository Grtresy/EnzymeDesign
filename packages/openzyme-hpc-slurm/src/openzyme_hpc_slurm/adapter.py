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
from openzyme_hpc import PrivateSchedulerHandleRecord
from openzyme_hpc import SchedulerOccurrenceIdentity
from openzyme_hpc import SchedulerOccurrenceKind
from openzyme_hpc import SchedulerOccurrenceLedger
from openzyme_hpc import SchedulerOccurrenceRecord
from openzyme_hpc import HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT
from openzyme_hpc import HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT_DIGEST


SLURM_ADAPTER_ID = "openzyme.hpc.slurm"
SLURM_ADAPTER_CONTRACT = "openzyme.hpc.slurm@1"
SLURM_ADAPTER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": SLURM_ADAPTER_CONTRACT,
        "port": "openzyme.hpc.scheduler-port@1",
        "credential": "one_formal_occurrence_only",
        "public_handle": "opaque",
        "occurrence_ledger_contract": HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT,
        "occurrence_ledger_contract_digest": (
            HPC_SCHEDULER_OCCURRENCE_LEDGER_CONTRACT_DIGEST
        ),
        "raw_scheduler_id": "durable_private_ledger_only",
        "reconcile": "same_occurrence_no_resubmit",
        "factory": "explicit_backend_credential_ledger_injection",
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


PrivateSlurmHandleRecord = PrivateSchedulerHandleRecord
SlurmHandleLedger = SchedulerOccurrenceLedger


@dataclass(slots=True)
class InMemorySlurmHandleLedger:
    _records: dict[tuple[str, str], SchedulerOccurrenceRecord] = field(
        default_factory=dict
    )

    def read(
        self,
        identity: SchedulerOccurrenceIdentity,
    ) -> SchedulerOccurrenceRecord | None:
        record = self._records.get((identity.provider_id, identity.operation_id))
        if record is not None and record.identity != identity:
            raise ValueError("Slurm operation identity collided")
        return record

    def reserve(self, identity: SchedulerOccurrenceIdentity) -> bool:
        if self.read(identity) is not None:
            return False
        self._records[(identity.provider_id, identity.operation_id)] = (
            SchedulerOccurrenceRecord(identity=identity, receipt=None)
        )
        return True

    def settle(
        self,
        identity: SchedulerOccurrenceIdentity,
        receipt: SchedulerDispatchReceipt,
        *,
        raw_scheduler_id: str | None = None,
    ) -> SchedulerOccurrenceRecord:
        current = self.read(identity)
        if current is None:
            raise ValueError("Slurm occurrence must be reserved")
        if current.receipt == receipt and current.raw_scheduler_id == raw_scheduler_id:
            return current
        if current.receipt is not None and (
            current.receipt.effect_certainty
            is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            raise ValueError("terminal Slurm occurrence cannot be replaced")
        if (
            current.receipt is not None
            and receipt.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return current
        updated = SchedulerOccurrenceRecord(
            identity=identity,
            receipt=receipt,
            raw_scheduler_id=raw_scheduler_id,
            ledger_version=current.ledger_version + 1,
        )
        self._records[(identity.provider_id, identity.operation_id)] = updated
        return updated

    def get_handle(
        self,
        provider_id: str,
        opaque_handle_id: str,
    ) -> PrivateSchedulerHandleRecord | None:
        for record in self._records.values():
            if record.identity.provider_id != provider_id:
                continue
            handle = record.private_handle()
            if handle is not None and handle.opaque_handle_id == opaque_handle_id:
                return handle
        return None


@dataclass(slots=True)
class SlurmSchedulerAdapter:
    backend: SlurmBackend
    credential_resolver: SchedulerOccurrenceCredentialResolver
    ledger: SlurmHandleLedger
    provider_id: str = SLURM_ADAPTER_ID

    def submit(self, request: SchedulerDispatchRequest) -> SchedulerDispatchReceipt:
        credential = self._credential(
            request.credential_occurrence_id,
            request.credential_digest,
        )
        if credential is None:
            return self._no_effect(request.operation_id, request.request_digest)
        identity = self._identity(
            SchedulerOccurrenceKind.SUBMIT,
            request.operation_id,
            request.request_digest,
        )
        prior = self.ledger.read(identity)
        if prior is not None:
            return self._recorded_or_pending(identity, prior)
        if not self.ledger.reserve(identity):
            concurrent = self.ledger.read(identity)
            if concurrent is None:
                raise RuntimeError("reserved Slurm submit occurrence disappeared")
            return self._recorded_or_pending(identity, concurrent)
        return self._settle_dispatch(
            identity,
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
        identity = self._identity(
            SchedulerOccurrenceKind.SUBMIT,
            request.operation_id,
            request.request_digest,
        )
        prior = self.ledger.read(identity)
        if prior is None:
            return self._no_effect(request.operation_id, request.request_digest)
        if prior.receipt is not None and (
            prior.receipt.effect_certainty
            is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return prior.receipt
        return self._settle_dispatch(
            identity,
            request,
            self.backend.reconcile_submit(request, credential),
            prior=prior,
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
        identity = self._identity(
            SchedulerOccurrenceKind.CANCEL,
            request.operation_id,
            request.request_digest,
        )
        prior = self.ledger.read(identity)
        if reconcile:
            if prior is None:
                return self._no_effect(request.operation_id, request.request_digest)
            if prior.receipt is not None and (
                prior.receipt.effect_certainty
                is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ):
                return prior.receipt
        elif prior is not None:
            return self._recorded_or_pending(identity, prior)
        elif not self.ledger.reserve(identity):
            concurrent = self.ledger.read(identity)
            if concurrent is None:
                raise RuntimeError("reserved Slurm cancel occurrence disappeared")
            return self._recorded_or_pending(identity, concurrent)
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
        receipt = SchedulerDispatchReceipt.create(
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
        if (
            prior is not None
            and prior.receipt is not None
            and prior.receipt.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and receipt.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return prior.receipt
        return self.ledger.settle(identity, receipt).receipt or receipt

    def _settle_dispatch(
        self,
        identity: SchedulerOccurrenceIdentity,
        request: SchedulerDispatchRequest,
        outcome: SlurmBackendOutcome,
        *,
        prior: SchedulerOccurrenceRecord | None = None,
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
            receipt = SchedulerDispatchReceipt.create(
                operation_id=request.operation_id,
                request_digest=request.request_digest,
                effect_certainty=outcome.effect_certainty,
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
                accepted=True,
                fallback_performed=False,
                diagnostic_id=outcome.diagnostic_id,
            )
            return self.ledger.settle(
                identity,
                receipt,
                raw_scheduler_id=outcome.raw_scheduler_id,
            ).receipt or receipt
        receipt = SchedulerDispatchReceipt.create(
            operation_id=request.operation_id,
            request_digest=request.request_digest,
            effect_certainty=outcome.effect_certainty,
            opaque_handle_id=None,
            accepted=outcome.accepted,
            fallback_performed=False,
            diagnostic_id=outcome.diagnostic_id,
        )
        if (
            prior is not None
            and prior.receipt is not None
            and prior.receipt.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and receipt.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return prior.receipt
        return self.ledger.settle(identity, receipt).receipt or receipt

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
        record = self.ledger.get_handle(self.provider_id, opaque_handle_id)
        if record is None:
            raise ValueError("opaque Slurm handle is unknown")
        return record

    def _identity(
        self,
        operation_kind: SchedulerOccurrenceKind,
        operation_id: str,
        request_digest: str,
    ) -> SchedulerOccurrenceIdentity:
        return SchedulerOccurrenceIdentity(
            provider_id=self.provider_id,
            operation_kind=operation_kind,
            operation_id=operation_id,
            request_digest=request_digest,
        )

    def _recorded_or_pending(
        self,
        identity: SchedulerOccurrenceIdentity,
        record: SchedulerOccurrenceRecord,
    ) -> SchedulerDispatchReceipt:
        if record.receipt is not None:
            return record.receipt
        pending = SchedulerDispatchReceipt.create(
            operation_id=identity.operation_id,
            request_digest=identity.request_digest,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            opaque_handle_id=None,
            accepted=None,
            fallback_performed=False,
            diagnostic_id="diagnostic-slurm-reconciliation-pending",
        )
        return self.ledger.settle(identity, pending).receipt or pending

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


@dataclass(frozen=True, slots=True)
class SlurmSchedulerAdapterFactory:
    """Construct one selected scheduler Port from explicit injected mechanisms."""

    provider_id: str = SLURM_ADAPTER_ID

    def __post_init__(self) -> None:
        if self.provider_id != SLURM_ADAPTER_ID:
            raise ValueError("Slurm Adapter factory provider identity is closed")

    def build(
        self,
        *,
        backend: SlurmBackend,
        credential_resolver: SchedulerOccurrenceCredentialResolver,
        ledger: SchedulerOccurrenceLedger,
    ) -> SlurmSchedulerAdapter:
        return SlurmSchedulerAdapter(
            backend=backend,
            credential_resolver=credential_resolver,
            ledger=ledger,
            provider_id=self.provider_id,
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
    "SlurmSchedulerAdapterFactory",
]
