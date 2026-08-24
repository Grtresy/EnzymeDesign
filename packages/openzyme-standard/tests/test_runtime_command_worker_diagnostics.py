from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timezone

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeCommandRecord
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import RuntimeCommandType
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel.runtime_command_application import RuntimeCommandClaimCommand
from openzyme_kernel.runtime_command_application import RuntimeCommandSettlementCommand
from openzyme_kernel.testing import DeterministicClock
from openzyme_standard.runtime_command_worker import StandardRuntimeCommandWorker


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _accepted() -> RuntimeCommandRecord:
    return RuntimeCommandRecord(
        command_id="runtime-command-1",
        session_id="session-1",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest=_digest("request"),
        idempotency_key="runtime-command-1",
        status=RuntimeCommandStatus.ACCEPTED,
        max_signals=1,
        max_steps_per_agent=2,
        auto_enqueue_ready_tasks=False,
        state_version=1,
        fencing_token=0,
        accepted_at="2026-08-24T00:00:00+00:00",
    )


@dataclass
class _Records:
    record: RuntimeCommandRecord

    def read(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> KernelRecordSnapshot | None:
        if entity_type != "runtime_command" or entity_id != self.record.command_id:
            return None
        return KernelRecordSnapshot.create(
            entity_type=entity_type,
            entity_id=entity_id,
            state_version=self.record.state_version,
            payload=self.record.to_dict(),
        )


@dataclass
class _Commands:
    records: _Records
    fail_settlement: bool = False
    settlement: RuntimeCommandSettlementCommand | None = None
    settlement_error: RuntimeError | None = None

    def claim(self, command: RuntimeCommandClaimCommand) -> object:
        current = self.records.record
        self.records.record = replace(
            current,
            status=RuntimeCommandStatus.CLAIMED,
            state_version=current.state_version + 1,
            fencing_token=current.fencing_token + 1,
            claim_owner=command.claim_owner,
            lease_token="runtime-command-lease-1",
            lease_expires_at="2026-08-24T00:10:00+00:00",
            started_at="2026-08-24T00:00:01+00:00",
        )
        return object()

    def settle(self, command: RuntimeCommandSettlementCommand) -> object:
        self.settlement = command
        if self.fail_settlement:
            self.settlement_error = RuntimeError("private settlement collision")
            raise self.settlement_error
        records = command.failure_records
        self.records.record = replace(
            self.records.record,
            status=command.status,
            state_version=self.records.record.state_version + 1,
            bounded_outcome_summary=dict(command.bounded_outcome_summary),
            failure_id=None if records is None else records.public.failure_id,
            diagnostic_id=None if records is None else records.public.diagnostic_id,
            error_code=command.error_code,
            safe_error_summary=command.safe_error_summary,
            safe_retry_hint=command.safe_retry_hint,
            completed_at="2026-08-24T00:00:02+00:00",
        )
        return object()


@dataclass
class _Contexts:
    def build(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> KernelCommandContext:
        return KernelCommandContext(
            command_id="claim-command-1",
            session_id=session_id,
            actor_id="member-1",
            owner_plugin_id="openzyme.kernel",
            authority_lease_id="authority-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            extension_bundle_digest=_digest("extensions"),
            capability_binding_digest=_digest("binding"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            workspace_generation=1,
        )

    def derive_settlement(
        self,
        context: KernelCommandContext,
        *,
        idempotency_key: str,
    ) -> KernelCommandContext:
        return replace(
            context,
            command_id="settlement-command-1",
            idempotency_key=idempotency_key,
        )


@dataclass
class _FailingExecutor:
    error: KernelContractError
    calls: int = 0

    def execute(self, record: RuntimeCommandRecord) -> dict[str, object]:
        assert record.status is RuntimeCommandStatus.CLAIMED
        self.calls += 1
        raise self.error


def _worker(*, fail_settlement: bool = False):  # noqa: ANN202
    records = _Records(_accepted())
    commands = _Commands(records=records, fail_settlement=fail_settlement)
    executor = _FailingExecutor(
        KernelContractError(
            "runtime_context_identity_stale",
            "private context identity token=standard-secret",
        )
    )
    worker = StandardRuntimeCommandWorker(
        application=commands,  # type: ignore[arg-type]
        records=records,  # type: ignore[arg-type]
        executor=executor,  # type: ignore[arg-type]
        contexts=_Contexts(),  # type: ignore[arg-type]
        clock=DeterministicClock(datetime(2026, 8, 24, tzinfo=timezone.utc)),
    )
    return worker, commands, records, executor


def test_standard_worker_wires_context_failure_pair_without_provider_fallback() -> None:
    worker, commands, records, executor = _worker()

    worker.run(runtime_command_id="runtime-command-1")

    assert executor.calls == 1
    settlement = commands.settlement
    assert settlement is not None
    assert settlement.status is RuntimeCommandStatus.FAILED
    assert settlement.failure_records is not None
    public = settlement.failure_records.public
    private = settlement.failure_records.private
    assert public.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert public.fallback_performed is False
    assert "standard-secret" not in str(public.to_dict())
    assert "standard-secret" in private.exception_message
    assert records.record.failure_id == public.failure_id
    assert records.record.diagnostic_id == private.diagnostic_id


def test_standard_worker_preserves_claim_and_raise_from_when_settlement_fails() -> None:
    worker, commands, records, _executor = _worker(fail_settlement=True)

    with pytest.raises(KernelContractError) as caught:
        worker.run(runtime_command_id="runtime-command-1")

    assert caught.value.code == "runtime_context_identity_stale"
    assert caught.value.__cause__ is commands.settlement_error
    assert records.record.status is RuntimeCommandStatus.CLAIMED
    assert records.record.failure_id is None
    assert records.record.diagnostic_id is None
