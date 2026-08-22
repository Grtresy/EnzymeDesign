from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_contracts import ExternalEffectCertainty
from openzyme_hpc import SchedulerDispatchRequest
from openzyme_hpc import SchedulerCancelRequest
from openzyme_hpc import SchedulerJobState
from openzyme_hpc import SQLiteSchedulerOccurrenceLedger
from openzyme_hpc import install_hpc_inventory_schema_for_offline_migration
from openzyme_hpc_slurm import InMemorySlurmHandleLedger
from openzyme_hpc_slurm import PrivateSchedulerOccurrenceCredential
from openzyme_hpc_slurm import SlurmBackendOutcome
from openzyme_hpc_slurm import SlurmSchedulerAdapter
from openzyme_hpc_slurm import SlurmSchedulerAdapterFactory


DIGEST = "sha256:" + "a" * 64


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-22T12:00:00+00:00"


def _request() -> SchedulerDispatchRequest:
    return SchedulerDispatchRequest.create(
        operation_id="operation_1",
        dispatch_id="dispatch_1",
        execution_id="execution_1",
        route_id="hpc:primary/slurm",
        target_id="hpc:primary",
        target_inventory_generation=7,
        target_inventory_digest=DIGEST,
        qualification_digest=DIGEST,
        workload_digest=DIGEST,
        credential_occurrence_id="credential_1",
        credential_digest=DIGEST,
        absolute_deadline="2026-09-01T00:00:00+00:00",
    )


@dataclass
class _Resolver:
    credential: object | None

    def resolve(self, _: str) -> object | None:
        return self.credential


class _Backend:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.reconcile_calls = 0
        self.submit_outcome: SlurmBackendOutcome | None = None
        self.reconcile_outcome: SlurmBackendOutcome | None = None
        self.cancel_calls = 0
        self.reconcile_cancel_calls = 0
        self.cancel_outcome: SlurmBackendOutcome | None = None
        self.reconcile_cancel_outcome: SlurmBackendOutcome | None = None

    def submit(self, *_: object) -> SlurmBackendOutcome:
        self.submit_calls += 1
        assert self.submit_outcome is not None
        return self.submit_outcome

    def reconcile_submit(self, *_: object) -> SlurmBackendOutcome:
        self.reconcile_calls += 1
        assert self.reconcile_outcome is not None
        return self.reconcile_outcome

    def observe(self, **values: object) -> SlurmBackendOutcome:
        return SlurmBackendOutcome(
            operation_id=str(values["operation_id"]),
            request_digest=str(values["request_digest"]),
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            accepted=True,
            raw_scheduler_id=str(values["raw_scheduler_id"]),
            state=SchedulerJobState.SUCCEEDED,
            result_digest=DIGEST,
        )

    def cancel(self, *_: object, **__: object) -> SlurmBackendOutcome:
        self.cancel_calls += 1
        assert self.cancel_outcome is not None
        return self.cancel_outcome

    def reconcile_cancel(self, *_: object, **__: object) -> SlurmBackendOutcome:
        self.reconcile_cancel_calls += 1
        assert self.reconcile_cancel_outcome is not None
        return self.reconcile_cancel_outcome


def _credential() -> PrivateSchedulerOccurrenceCredential:
    return PrivateSchedulerOccurrenceCredential(
        occurrence_id="credential_1",
        credential_digest=DIGEST,
        opaque_token="private-token",
    )


def test_missing_or_login_credential_cannot_submit_scheduler_work() -> None:
    backend = _Backend()
    request = _request()
    for credential in (None, object()):
        adapter = SlurmSchedulerAdapter(
            backend=backend,
            credential_resolver=_Resolver(credential),  # type: ignore[arg-type]
            ledger=InMemorySlurmHandleLedger(),
        )
        receipt = adapter.submit(request)
        assert receipt.effect_certainty is ExternalEffectCertainty.NO_EFFECT
        assert receipt.accepted is False
    assert backend.submit_calls == 0


def test_lost_submit_response_reconciles_without_resubmit_and_hides_raw_id() -> None:
    request = _request()
    backend = _Backend()
    backend.submit_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        accepted=None,
        diagnostic_id="diagnostic_1",
    )
    backend.reconcile_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
        accepted=True,
        raw_scheduler_id="slurm-job-12345",
        state=SchedulerJobState.QUEUED,
    )
    adapter = SlurmSchedulerAdapter(
        backend=backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=InMemorySlurmHandleLedger(),
    )

    uncertain = adapter.submit(request)
    settled = adapter.reconcile_submit(request)

    assert uncertain.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert settled.opaque_handle_id is not None
    assert settled.opaque_handle_id != "slurm-job-12345"
    assert "slurm-job-12345" not in repr(settled)
    assert backend.submit_calls == 1
    assert backend.reconcile_calls == 1

    observation = adapter.observe(settled.opaque_handle_id, observation_index=1)
    assert observation.state is SchedulerJobState.SUCCEEDED
    assert "slurm-job-12345" not in repr(observation)


def test_sqlite_ledger_recovers_submit_handle_and_cancel_after_host_restart() -> None:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    request = _request()
    first_backend = _Backend()
    first_backend.submit_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        accepted=None,
        diagnostic_id="diagnostic_1",
    )
    factory = SlurmSchedulerAdapterFactory()
    first = factory.build(
        backend=first_backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    )
    uncertain = first.submit(request)
    assert uncertain.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT

    reconcile_backend = _Backend()
    reconcile_backend.reconcile_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
        accepted=True,
        raw_scheduler_id="slurm-job-12345",
        state=SchedulerJobState.QUEUED,
    )
    restarted = factory.build(
        backend=reconcile_backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    )
    duplicate = restarted.submit(request)
    settled = restarted.reconcile_submit(request)

    assert duplicate == uncertain
    assert settled.opaque_handle_id is not None
    assert first_backend.submit_calls == 1
    assert reconcile_backend.submit_calls == 0
    assert reconcile_backend.reconcile_calls == 1

    cancel_request = SchedulerCancelRequest.create(
        operation_id="cancel_operation_restart_1",
        opaque_handle_id=settled.opaque_handle_id,
        reason="operator requested cancellation",
        credential_occurrence_id="credential_1",
        credential_digest=DIGEST,
    )
    reconcile_backend.cancel_outcome = SlurmBackendOutcome(
        operation_id=cancel_request.operation_id,
        request_digest=cancel_request.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        accepted=None,
        diagnostic_id="diagnostic_cancel_1",
    )
    cancel_uncertain = restarted.cancel(cancel_request)

    final_backend = _Backend()
    final_backend.reconcile_cancel_outcome = SlurmBackendOutcome(
        operation_id=cancel_request.operation_id,
        request_digest=cancel_request.request_digest,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        accepted=True,
        raw_scheduler_id="slurm-job-12345",
        state=SchedulerJobState.CANCELLED,
    )
    final = factory.build(
        backend=final_backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    )
    cancel_duplicate = final.cancel(cancel_request)
    cancel_settled = final.reconcile_cancel(cancel_request)

    assert cancel_duplicate == cancel_uncertain
    assert cancel_settled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert final_backend.cancel_calls == 0
    assert final_backend.reconcile_cancel_calls == 1


def test_reconcile_submit_missing_credential_preserves_uncertain_occurrence() -> None:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    request = _request()
    first_backend = _Backend()
    first_backend.submit_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        accepted=None,
        diagnostic_id="diagnostic_1",
    )
    uncertain = SlurmSchedulerAdapter(
        backend=first_backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    ).submit(request)
    restarted_backend = _Backend()
    restarted = SlurmSchedulerAdapter(
        backend=restarted_backend,
        credential_resolver=_Resolver(None),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    )

    reconciled = restarted.reconcile_submit(request)

    assert reconciled == uncertain
    assert reconciled.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert reconciled.accepted is None
    assert restarted_backend.submit_calls == 0
    assert restarted_backend.reconcile_calls == 0


def test_reconcile_cancel_missing_credential_preserves_uncertain_occurrence() -> None:
    connection = sqlite3.connect(":memory:")
    install_hpc_inventory_schema_for_offline_migration(connection)
    request = _request()
    first_backend = _Backend()
    first_backend.submit_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
        accepted=True,
        raw_scheduler_id="slurm-job-12345",
        state=SchedulerJobState.QUEUED,
    )
    first = SlurmSchedulerAdapter(
        backend=first_backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    )
    submitted = first.submit(request)
    assert submitted.opaque_handle_id is not None
    cancel_request = SchedulerCancelRequest.create(
        operation_id="cancel_operation_missing_credential_1",
        opaque_handle_id=submitted.opaque_handle_id,
        reason="operator requested cancellation",
        credential_occurrence_id="credential_1",
        credential_digest=DIGEST,
    )
    first_backend.cancel_outcome = SlurmBackendOutcome(
        operation_id=cancel_request.operation_id,
        request_digest=cancel_request.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        accepted=None,
        diagnostic_id="diagnostic_cancel_1",
    )
    uncertain = first.cancel(cancel_request)
    restarted_backend = _Backend()
    restarted = SlurmSchedulerAdapter(
        backend=restarted_backend,
        credential_resolver=_Resolver(None),  # type: ignore[arg-type]
        ledger=SQLiteSchedulerOccurrenceLedger(connection, _Clock()),
    )

    reconciled = restarted.reconcile_cancel(cancel_request)

    assert reconciled == uncertain
    assert reconciled.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert reconciled.accepted is None
    assert restarted_backend.cancel_calls == 0
    assert restarted_backend.reconcile_cancel_calls == 0


def test_lost_cancel_response_reconciles_without_second_cancel() -> None:
    request = _request()
    backend = _Backend()
    backend.submit_outcome = SlurmBackendOutcome(
        operation_id=request.operation_id,
        request_digest=request.request_digest,
        effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
        accepted=True,
        raw_scheduler_id="slurm-job-12345",
        state=SchedulerJobState.QUEUED,
    )
    adapter = SlurmSchedulerAdapter(
        backend=backend,
        credential_resolver=_Resolver(_credential()),  # type: ignore[arg-type]
        ledger=InMemorySlurmHandleLedger(),
    )
    submit_receipt = adapter.submit(request)
    assert submit_receipt.opaque_handle_id is not None
    cancel_request = SchedulerCancelRequest.create(
        operation_id="cancel_operation_1",
        opaque_handle_id=submit_receipt.opaque_handle_id,
        reason="operator requested cancellation",
        credential_occurrence_id="credential_1",
        credential_digest=DIGEST,
    )
    backend.cancel_outcome = SlurmBackendOutcome(
        operation_id=cancel_request.operation_id,
        request_digest=cancel_request.request_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        accepted=None,
        diagnostic_id="diagnostic_cancel_1",
    )
    backend.reconcile_cancel_outcome = SlurmBackendOutcome(
        operation_id=cancel_request.operation_id,
        request_digest=cancel_request.request_digest,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        accepted=True,
        raw_scheduler_id="slurm-job-12345",
        state=SchedulerJobState.CANCELLED,
    )

    uncertain = adapter.cancel(cancel_request)
    settled = adapter.reconcile_cancel(cancel_request)

    assert uncertain.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert settled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert settled.opaque_handle_id == submit_receipt.opaque_handle_id
    assert "slurm-job-12345" not in repr(settled)
    assert backend.cancel_calls == 1
    assert backend.reconcile_cancel_calls == 1
