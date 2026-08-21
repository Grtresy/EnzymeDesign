from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from typing import Callable
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationApplicationService
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import ExtensionInvocationApplicationCommand
from openzyme_extension_spi import ExtensionInvocationApplicationService
from openzyme_extension_spi import ExtensionInvocationCommandKind
from openzyme_extension_spi import KernelCommandContext

from .contracts import ResearchInvocationRecord
from .contracts import ResearchInvocationStatus
from .contracts import ResearchProviderReceipt
from .contracts import ResearchProviderDescriptor
from .contracts import ResearchProviderRequest
from .contracts import ResearchRequest


RESEARCH_PLUGIN_ID = "openzyme.research"
RESEARCH_PROVIDER_CAPABILITY = "openzyme.research.provider"
RESEARCH_PROVIDER_CONTRACT = "openzyme.research.provider@1"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ResearchProviderPort(Protocol):
    """Provider-neutral external boundary selected by explicit composition."""

    @property
    def provider_id(self) -> str: ...

    @property
    def route_id(self) -> str: ...

    @property
    def descriptor(self) -> ResearchProviderDescriptor: ...

    def dispatch(self, request: ResearchProviderRequest) -> ResearchProviderReceipt: ...

    def reconcile(self, operation_id: str) -> ResearchProviderReceipt: ...


class ResearchRepository(Protocol):
    def get(self, invocation_id: str) -> ResearchInvocationRecord | None: ...

    def save(
        self,
        record: ResearchInvocationRecord,
        *,
        expected_version: int | None,
    ) -> None: ...

    def list_session(self, session_id: str) -> tuple[ResearchInvocationRecord, ...]: ...

    def list_claimable(self, *, limit: int) -> tuple[ResearchInvocationRecord, ...]: ...

    def save_provider_receipt(self, receipt: ResearchProviderReceipt) -> None: ...

    def provider_receipts(
        self,
        operation_ids: tuple[str, ...],
    ) -> tuple[ResearchProviderReceipt, ...]: ...


class ResearchContextFactory(Protocol):
    def create(
        self,
        *,
        request: ResearchRequest,
        command_id: str,
        idempotency_key: str,
        route_id: str,
    ) -> KernelCommandContext: ...


@dataclass(slots=True)
class InMemoryResearchRepository:
    records: dict[str, ResearchInvocationRecord]
    receipts: dict[str, ResearchProviderReceipt]

    def __init__(self) -> None:
        self.records = {}
        self.receipts = {}

    def get(self, invocation_id: str) -> ResearchInvocationRecord | None:
        return self.records.get(invocation_id)

    def save(
        self,
        record: ResearchInvocationRecord,
        *,
        expected_version: int | None,
    ) -> None:
        current = self.records.get(record.invocation_id)
        current_version = None if current is None else current.state_version
        if current_version != expected_version:
            raise RuntimeError("research_state_version_conflict")
        self.records[record.invocation_id] = record

    def list_session(self, session_id: str) -> tuple[ResearchInvocationRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self.records.values()
                    if record.request.session_id == session_id
                ),
                key=lambda record: record.invocation_id,
            )
        )

    def list_claimable(self, *, limit: int) -> tuple[ResearchInvocationRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self.records.values()
                    if record.status
                    in {
                        ResearchInvocationStatus.ADMITTED,
                        ResearchInvocationStatus.DISPATCH_IN_DOUBT,
                    }
                ),
                key=lambda record: record.invocation_id,
            )[:limit]
        )

    def save_provider_receipt(self, receipt: ResearchProviderReceipt) -> None:
        existing = self.receipts.get(receipt.operation_id)
        if existing is not None and existing.request_digest != receipt.request_digest:
            raise RuntimeError("research_provider_receipt_identity_conflict")
        self.receipts[receipt.operation_id] = receipt

    def provider_receipts(
        self,
        operation_ids: tuple[str, ...],
    ) -> tuple[ResearchProviderReceipt, ...]:
        return tuple(
            self.receipts[operation_id]
            for operation_id in operation_ids
            if operation_id in self.receipts
        )


@dataclass(slots=True)
class ResearchOrchestrationService:
    repository: ResearchRepository
    provider: ResearchProviderPort
    controlled_operations: ControlledOperationApplicationService
    extension_invocations: ExtensionInvocationApplicationService
    context_factory: ResearchContextFactory
    now: Callable[[], str] = utc_now_iso

    def __post_init__(self) -> None:
        descriptor = self.provider.descriptor
        if descriptor.provider_id != self.provider.provider_id:
            raise ValueError("Research provider descriptor identity mismatch")
        if tuple(descriptor.operations) != ("dispatch", "reconcile"):
            raise ValueError("Research provider must implement dispatch and reconcile")

    def admit(
        self,
        *,
        invocation_id: str,
        request: ResearchRequest,
    ) -> ResearchInvocationRecord:
        existing = self.repository.get(invocation_id)
        if existing is not None:
            if existing.request.request_digest != request.request_digest:
                raise RuntimeError("research_invocation_identity_conflict")
            return existing
        timestamp = self.now()
        context = self.context_factory.create(
            request=request,
            command_id=f"research-start-{invocation_id}",
            idempotency_key=f"research-start-{invocation_id}",
            route_id=self.provider.route_id,
        )
        self.extension_invocations.execute(
            ExtensionInvocationApplicationCommand(
                context=context,
                operation=ExtensionInvocationCommandKind.START,
                invocation_id=invocation_id,
                tool_name="deep_research.start",
                tool_contract_digest=RESEARCH_START_TOOL_CONTRACT_DIGEST,
                payload={
                    "request_id": request.request_id,
                    "request_digest": request.request_digest,
                    "provider_id": self.provider.provider_id,
                    "route_id": self.provider.route_id,
                },
            )
        )
        record = ResearchInvocationRecord(
            invocation_id=invocation_id,
            request=request,
            provider_id=self.provider.provider_id,
            route_id=self.provider.route_id,
            status=ResearchInvocationStatus.ADMITTED,
            operation_ids=tuple(
                f"research-{invocation_id}-{unit.unit_id}" for unit in request.units
            ),
            source_ids=(),
            started_at=timestamp,
            updated_at=timestamp,
        )
        self.repository.save(record, expected_version=None)
        return record

    def run(self, invocation_id: str) -> ResearchInvocationRecord:
        current = self._require(invocation_id)
        if current.status.terminal:
            return current
        if current.status is ResearchInvocationStatus.DISPATCH_IN_DOUBT:
            return self.reconcile(invocation_id)
        running = replace(
            current,
            status=ResearchInvocationStatus.RUNNING,
            updated_at=self.now(),
            state_version=current.state_version + 1,
        )
        self.repository.save(running, expected_version=current.state_version)
        receipts: list[ResearchProviderReceipt] = []
        for unit, operation_id in zip(
            running.request.units, running.operation_ids, strict=True
        ):
            context = self._context(
                running,
                command_id=f"research-admit-{operation_id}",
                idempotency_key=operation_id,
            )
            intent_digest = canonical_sha256_digest(
                {
                    "invocation_id": invocation_id,
                    "request_digest": running.request.request_digest,
                    "unit": unit.to_dict(),
                    "provider_id": running.provider_id,
                    "route_id": running.route_id,
                }
            )
            self.controlled_operations.execute(
                ControlledOperationApplicationCommand(
                    context=context,
                    operation=ControlledOperationCommandKind.ADMIT,
                    operation_id=operation_id,
                    intent_digest=intent_digest,
                    payload={
                        "owner_plugin_id": RESEARCH_PLUGIN_ID,
                        "authority_operation": "ordinary_network",
                        "scope_id": running.route_id,
                        "provider_id": running.provider_id,
                        "unit_id": unit.unit_id,
                    },
                )
            )
            receipt = self.provider.dispatch(
                ResearchProviderRequest(
                    operation_id=operation_id,
                    request_digest=intent_digest,
                    session_id=running.request.session_id,
                    unit=unit,
                    deadline_at=self.now(),
                )
            )
            self._validate_receipt(
                receipt,
                operation_id=operation_id,
                request_digest=intent_digest,
            )
            self.repository.save_provider_receipt(receipt)
            receipts.append(receipt)
            command_kind = (
                ControlledOperationCommandKind.RECONCILE
                if receipt.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else ControlledOperationCommandKind.OBSERVE
            )
            self.controlled_operations.execute(
                ControlledOperationApplicationCommand(
                    context=self._context(
                        running,
                        command_id=f"research-{command_kind.value}-{operation_id}",
                        idempotency_key=f"{operation_id}-{command_kind.value}",
                    ),
                    operation=command_kind,
                    operation_id=operation_id,
                    intent_digest=intent_digest,
                    payload={
                        "provider_id": receipt.provider_id,
                        "provider_operation_id": receipt.provider_operation_id,
                        "result_handle": receipt.provider_operation_id,
                        "effect_certainty": receipt.effect_certainty.value,
                        "mutation_applied": _provider_mutation_fact(receipt),
                        "status": receipt.status,
                        "response_digest": receipt.response_digest,
                        "terminal_receipt_digest": receipt.response_digest,
                        "error_code": receipt.error_code,
                        "fallback_performed": False,
                    },
                )
            )
            if receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
                in_doubt = replace(
                    running,
                    status=ResearchInvocationStatus.DISPATCH_IN_DOUBT,
                    updated_at=self.now(),
                    state_version=running.state_version + 1,
                )
                self.repository.save(in_doubt, expected_version=running.state_version)
                return in_doubt
        return self._settle(running, receipts)

    def reconcile(self, invocation_id: str) -> ResearchInvocationRecord:
        current = self._require(invocation_id)
        if current.status is not ResearchInvocationStatus.DISPATCH_IN_DOUBT:
            return current
        receipts = []
        for operation_id in current.operation_ids:
            receipt = self.provider.reconcile(operation_id)
            previous = self.repository.provider_receipts((operation_id,))
            if not previous:
                raise RuntimeError("research_reconcile_missing_original_receipt")
            self._validate_receipt(
                receipt,
                operation_id=operation_id,
                request_digest=previous[0].request_digest,
            )
            receipts.append(receipt)
        for receipt in receipts:
            self.repository.save_provider_receipt(receipt)
        if any(
            receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            for receipt in receipts
        ):
            return current
        for receipt in receipts:
            self.controlled_operations.execute(
                ControlledOperationApplicationCommand(
                    context=self._context(
                        current,
                        command_id=f"research-reconcile-{receipt.operation_id}",
                        idempotency_key=f"{receipt.operation_id}-reconcile-observed",
                    ),
                    operation=ControlledOperationCommandKind.RECONCILE,
                    operation_id=receipt.operation_id,
                    intent_digest=receipt.request_digest,
                    payload={
                        "provider_id": receipt.provider_id,
                        "result_handle": receipt.provider_operation_id,
                        "effect_certainty": receipt.effect_certainty.value,
                        "mutation_applied": _provider_mutation_fact(receipt),
                        "status": receipt.status,
                        "response_digest": receipt.response_digest,
                        "terminal_receipt_digest": receipt.response_digest,
                        "fallback_performed": False,
                    },
                )
            )
        return self._settle(current, receipts)

    def _validate_receipt(
        self,
        receipt: ResearchProviderReceipt,
        *,
        operation_id: str,
        request_digest: str,
    ) -> None:
        if receipt.operation_id != operation_id:
            raise RuntimeError("research_provider_operation_identity_mismatch")
        if receipt.request_digest != request_digest:
            raise RuntimeError("research_provider_request_identity_mismatch")
        if receipt.provider_id != self.provider.provider_id:
            raise RuntimeError("research_provider_identity_mismatch")

    def link_publication(
        self,
        *,
        invocation_id: str,
        publication_ref: RevisionPathRef,
    ) -> ResearchInvocationRecord:
        current = self._require(invocation_id)
        if publication_ref.session_id != current.request.session_id:
            raise ValueError("Research publication belongs to another Session")
        updated = replace(
            current,
            publication_ref=publication_ref,
            updated_at=self.now(),
            state_version=current.state_version + 1,
        )
        self.repository.save(updated, expected_version=current.state_version)
        return updated

    def _settle(
        self,
        current: ResearchInvocationRecord,
        receipts: Iterable[ResearchProviderReceipt],
    ) -> ResearchInvocationRecord:
        material = tuple(receipts)
        source_ids = tuple(
            sorted({source.source_id for receipt in material for source in receipt.sources})
        )
        if any(receipt.status == "failed" for receipt in material):
            status = ResearchInvocationStatus.FAILED
        elif any(receipt.status in {"partial", "empty"} for receipt in material):
            status = ResearchInvocationStatus.PARTIAL
        else:
            status = ResearchInvocationStatus.COMPLETED
        updated = replace(
            current,
            status=status,
            source_ids=source_ids,
            updated_at=self.now(),
            state_version=current.state_version + 1,
        )
        self.repository.save(updated, expected_version=current.state_version)
        self.extension_invocations.execute(
            ExtensionInvocationApplicationCommand(
                context=self._context(
                    updated,
                    command_id=f"research-settle-{updated.invocation_id}",
                    idempotency_key=f"research-settle-{updated.invocation_id}-{updated.state_version}",
                ),
                operation=ExtensionInvocationCommandKind.SETTLE,
                invocation_id=updated.invocation_id,
                tool_name="deep_research.start",
                tool_contract_digest=RESEARCH_START_TOOL_CONTRACT_DIGEST,
                payload={
                    "status": updated.status.value,
                    "source_ids": list(updated.source_ids),
                    "publication_ref": None,
                    "task_evidence_created": False,
                    "task_finished": False,
                },
            )
        )
        return updated

    def _context(
        self,
        record: ResearchInvocationRecord,
        *,
        command_id: str,
        idempotency_key: str,
    ) -> KernelCommandContext:
        return self.context_factory.create(
            request=record.request,
            command_id=command_id,
            idempotency_key=idempotency_key,
            route_id=record.route_id,
        )

    def _require(self, invocation_id: str) -> ResearchInvocationRecord:
        record = self.repository.get(invocation_id)
        if record is None:
            raise KeyError(invocation_id)
        return record


RESEARCH_START_TOOL_CONTRACT_DIGEST = (
    "sha256:6fe5f211ac558f96ef66fa2df032ee545425457c341b98ad872763805c096c5d"
)


def _provider_mutation_fact(receipt: ResearchProviderReceipt) -> bool | None:
    if receipt.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
        return False
    if receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
        return None
    return True


__all__ = [
    "InMemoryResearchRepository",
    "RESEARCH_PLUGIN_ID",
    "RESEARCH_PROVIDER_CAPABILITY",
    "RESEARCH_PROVIDER_CONTRACT",
    "ResearchContextFactory",
    "ResearchOrchestrationService",
    "ResearchProviderPort",
    "ResearchRepository",
    "utc_now_iso",
]
