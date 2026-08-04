from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from contextlib import contextmanager
import base64
import json
from pathlib import Path
import threading
from typing import Any
from typing import Callable
from typing import ContextManager
from uuid import uuid4

from openzyme_core import CoreRepositories
from openzyme_core import ControlledOperationExecutionTransitionService
from openzyme_core import build_controlled_operation_result_handle
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import current_mutation_write_authority
from openzyme_core import DurableEventRecord
from openzyme_core import EngineRegistry
from openzyme_core import HarnessEvent
from openzyme_core import HarnessStatus
from openzyme_core import LaneManager
from openzyme_core import MutationScopeService
from openzyme_core import RestoreFocus
from openzyme_core import CommandIdempotencyConflictError
from openzyme_core import runtime_command_request_digest
from openzyme_core import RuntimeWriteFencingError
from openzyme_core import SandboxHostBinding
from openzyme_core import SandboxMutationWriterScopeFactory
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import TaskBoardService
from openzyme_core import TaskMutation
from openzyme_core import ToolRegistry
from openzyme_core import AgentRuntimeOutcome
from openzyme_core import AgentRuntimeService
from openzyme_core import AgentRuntimeScheduler
from openzyme_core import AgentRuntimeSettlementDisposition
from openzyme_core import ArtifactBoundaryService
from openzyme_core import canonical_digest
from openzyme_core import persist_conversation_message
from openzyme_core import RuntimeDrainCoreReceipt
from openzyme_core import RuntimeDrainProjectionOutcome
from openzyme_core import ScientificAttemptError
from openzyme_core import ScientificAttemptService
from openzyme_core import ScientificWorkflowContractRegistry
from openzyme_core import SessionRuntimeLeaseLockedError
from openzyme_domain import SessionRuntimeLease
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureRecoverability
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import MutationWriterKind
from openzyme_domain import SandboxRunStatus
from openzyme_domain import RetryEligibility
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import record_failure_observation
from openzyme_runtime import sanitize_public_diagnostic_text

from .aox_bundle_finalizer import validate_persisted_aox_finalization_receipt
from .aox_fault_injection import inject_authority_bound_aox_reference_byte_flip
from .aox_public_product_closure import AoxPublicProductClosureError
from .aox_public_product_closure import build_aox_public_product_closure


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _event(event_type: str, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": _new_id("evt"),
        "session_id": session_id,
        "event_type": event_type,
        "created_at": utc_now_iso(),
        "payload": payload,
    }


def _scientific_transition_event(
    *,
    event_type: str,
    session_id: str,
    record_id: str,
    actor_ref: str,
    task_id: str | None,
    lane_id: str | None,
    created_at: str,
) -> dict[str, Any]:
    identity_digest = canonical_digest(
        {
            "event_type": event_type,
            "session_id": session_id,
            "record_id": record_id,
        }
    ).removeprefix("sha256:")
    return {
        "event_id": f"evt_scientific_transition_{identity_digest[:24]}",
        "session_id": session_id,
        "event_type": event_type,
        "created_at": created_at,
        "payload": {
            "record_id": record_id,
            "actor_ref": actor_ref,
            "task_id": task_id,
            "lane_id": lane_id,
        },
    }


def _event_fingerprint(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(event["event_type"]),
        str(event["created_at"]),
        json.dumps(event.get("payload", {}), sort_keys=True, separators=(",", ":")),
    )


@dataclass(slots=True)
class V3EventStore:
    repositories: CoreRepositories | None
    _lock: threading.RLock

    def __init__(self, repositories: CoreRepositories | None = None) -> None:
        self.repositories = repositories
        self._lock = threading.RLock()

    def bind(self, repositories: CoreRepositories) -> None:
        if self.repositories is not None and self.repositories is not repositories:
            raise RuntimeError(
                "V3EventStore is already bound to another repository scope"
            )
        self.repositories = repositories

    def _repository(self):  # type: ignore[no-untyped-def]
        repositories = self.repositories
        if repositories is None:
            raise RuntimeError("V3EventStore must be bound to CoreRepositories")
        return repositories.durable_events

    @contextmanager
    def _mutation_writer_scope(self, session_id: str):  # type: ignore[no-untyped-def]
        repositories = self.repositories
        authority = current_mutation_write_authority()
        if (
            repositories is None
            or authority is None
            or authority.owner_kind is MutationWriterKind.EVENT_OUTBOX_PUBLISHER
        ):
            yield
            return
        with MutationScopeService(repositories).writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.EVENT_OUTBOX_PUBLISHER,
            owner_ref=f"v3-event-store:{session_id}",
        ):
            yield

    def append(
        self,
        session_id: str,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stored_events: list[dict[str, Any]] = []
        with self._lock:
            with self._mutation_writer_scope(session_id):
                for event in events:
                    if str(event.get("session_id")) != session_id:
                        raise ValueError(
                            "durable event session_id does not match append scope"
                        )
                    payload = event.get("payload", {})
                    if not isinstance(payload, dict):
                        raise ValueError("durable event payload must be an object")
                    visibility = str(event.get("visibility") or "public")
                    stored = (
                        self._repository()
                        .append(
                            DurableEventRecord(
                                event_id=str(event["event_id"]),
                                session_id=session_id,
                                event_type=str(event["event_type"]),
                                schema_version=str(
                                    event.get("schema_version")
                                    or "openzyme.v3.event.v1"
                                ),
                                visibility=visibility,
                                payload=payload,
                                command_id=event.get("command_id"),
                                correlation_id=event.get("correlation_id"),
                                causation_id=event.get("causation_id"),
                                actor_ref=event.get("actor_ref"),
                                created_at=str(event["created_at"]),
                            )
                        )
                        .to_dict()
                    )
                    event.clear()
                    event.update(stored)
                    stored_events.append(event)
                events.sort(key=lambda item: int(item["cursor"]))
        return stored_events

    def list(
        self,
        session_id: str,
        *,
        after_cursor: int = 0,
        limit: int = 1_000,
    ) -> list[dict[str, Any]]:
        with self._lock:
            records = self._repository().list_by_session(
                session_id,
                after_cursor=after_cursor,
                limit=limit,
                # Audit/internal events require a separate authorized surface.
                visibilities=("public",),
            )
            if any(record.visibility != "public" for record in records):
                raise RuntimeError(
                    "public durable event read returned a non-public record"
                )
            return [record.to_dict() for record in records]

    def latest_cursor(self, session_id: str) -> int:
        with self._lock:
            return self._repository().latest_cursor(session_id)


@dataclass(slots=True)
class V3EventStoreSink:
    event_store: V3EventStore
    events: list[HarnessEvent]

    def __init__(
        self,
        event_store: V3EventStore,
        *,
        events: list[HarnessEvent] | None = None,
    ) -> None:
        self.event_store = event_store
        self.events = [] if events is None else events

    def for_repositories(self, repositories: CoreRepositories) -> "V3EventStoreSink":
        return V3EventStoreSink(
            V3EventStore(repositories),
            events=self.events,
        )

    def emit(self, event: HarnessEvent) -> None:
        self.events.append(event)
        try:
            self.event_store.append(event.session_id, [event.to_dict()])
        except RuntimeWriteFencingError:
            # The coordinator persists the shared collector after the stale
            # worker returns. A stale worker must never bypass its write fence
            # merely to publish the rejection diagnostic itself.
            return


@dataclass(frozen=True, slots=True)
class V3CommandResult:
    session_id: str
    status: str
    outputs: tuple[str, ...]
    events: list[dict[str, Any]]
    workspace: dict[str, Any]
    processed_signal_count: int = 0
    suspended: bool = False
    safe_retry_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "outputs": list(self.outputs),
            "events": self.events,
            "workspace": self.workspace,
        }


@dataclass(frozen=True, slots=True)
class V3RuntimeDrainResult:
    session_id: str
    core_receipt: RuntimeDrainCoreReceipt
    projection_outcome: RuntimeDrainProjectionOutcome
    outputs: tuple[str, ...]
    events: list[dict[str, Any]]
    workspace: dict[str, Any]
    safe_retry_hint: str | None = None

    @property
    def status(self) -> str:
        if self.projection_outcome.status == "failed":
            return RuntimeCommandStatus.FAILED.value
        return self.core_receipt.scheduler_status

    @property
    def processed_signal_count(self) -> int:
        return self.core_receipt.processed_signal_count

    @property
    def suspended(self) -> bool:
        return self.core_receipt.suspended

    @property
    def bounded_outcome_summary(self) -> dict[str, Any]:
        return self.core_receipt.bounded_outcome_summary(self.projection_outcome)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "outputs": list(self.outputs),
            "events": self.events,
            "workspace": self.workspace,
        }


@dataclass(slots=True)
class V3HostApiService:
    repositories: CoreRepositories
    event_store: V3EventStore
    engine_registry: EngineRegistry | None = None
    model_factory: Any | None = None
    bio_research_service: Any | None = None
    research_adapter: Any | None = None
    scientific_workflow_contract_registry: ScientificWorkflowContractRegistry | None = (
        None
    )
    sandbox_workspace_root: Path | None = None
    artifact_blob_root: Path | None = None
    artifact_bundle_finalizer: Callable[..., dict[str, Any]] | None = None
    scheduler_limits: dict[str, int] = field(default_factory=dict)
    signal_notifier: Any | None = None
    durable_work_notifier: Any | None = None
    reliability_shadow_observer: Any | None = None
    reliability_settings: Any | None = None
    durable_route_adapter_policy_ids: dict[str, str] = field(default_factory=dict)
    tool_dispatch_precondition: Callable[..., Any] | None = None
    runtime_repository_scope_factory: (
        Callable[[], ContextManager[CoreRepositories]] | None
    ) = None
    engine_registry_factory: (
        Callable[
            [CoreRepositories, SessionRuntimeLease | None],
            EngineRegistry,
        ]
        | None
    ) = None
    mutation_writer_scope_factory: SandboxMutationWriterScopeFactory | None = None
    sandbox_host_binding_factory: (
        Callable[
            [EngineRegistry, SessionRuntimeLease | None],
            SandboxHostBinding,
        ]
        | None
    ) = None
    operation_lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self.event_store.bind(self.repositories)

    def _event_sink(self) -> V3EventStoreSink:
        return V3EventStoreSink(self.event_store)

    def admit_runtime_command(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        max_signals: int,
        max_steps_per_agent: int,
        auto_enqueue_ready_tasks: bool,
    ) -> tuple[RuntimeCommandRecord, bool]:
        if self.repositories.sessions.get(session_id) is None:
            raise KeyError(f"session {session_id!r} does not exist")
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > 256:
            raise ValueError("Idempotency-Key must contain 1 to 256 characters")
        if max_signals <= 0 or max_signals > 100:
            raise ValueError("max_signals must be between 1 and 100")
        if max_steps_per_agent <= 0 or max_steps_per_agent > 100:
            raise ValueError("max_steps_per_agent must be between 1 and 100")
        if not isinstance(auto_enqueue_ready_tasks, bool):
            raise ValueError("auto_enqueue_ready_tasks must be boolean")
        request_digest = runtime_command_request_digest(
            session_id=session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            max_signals=max_signals,
            max_steps_per_agent=max_steps_per_agent,
            auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
        )
        existing = self.repositories.runtime_commands.find_by_idempotency_key(
            session_id=session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            idempotency_key=normalized_key,
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise CommandIdempotencyConflictError(
                    "runtime command idempotency key was reused with a different request"
                )
            return existing, False
        accepted_at = utc_now_iso()
        command = RuntimeCommandRecord(
            command_id=_new_id("runtime_command"),
            session_id=session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            request_digest=request_digest,
            idempotency_key=normalized_key,
            status=RuntimeCommandStatus.ACCEPTED,
            max_signals=max_signals,
            max_steps_per_agent=max_steps_per_agent,
            auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
            state_version=1,
            fencing_token=0,
            accepted_at=accepted_at,
        )
        stored = self.repositories.runtime_commands.add(command)
        event = _event(
            "runtime.command.accepted",
            session_id,
            {
                "command_id": stored.command_id,
                "command_type": stored.command_type.value,
                "status": stored.status.value,
                "accepted_at": stored.accepted_at,
            },
        )
        event["command_id"] = stored.command_id
        self.event_store.append(session_id, [event])
        self._touch_session(session_id)
        return stored, True

    def _record_events(
        self,
        session_id: str,
        target: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> None:
        target.extend(events)
        self.event_store.append(session_id, events)

    def create_session(
        self,
        *,
        project_id: str,
        objective: str,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        with self.operation_lock:
            return self._create_session_locked(
                project_id=project_id,
                objective=objective,
                title=title,
                session_id=session_id,
            )

    def _create_session_locked(
        self,
        *,
        project_id: str,
        objective: str,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_session_id = session_id or _new_id("sess")
        if self.repositories.sessions.get(resolved_session_id) is not None:
            raise ValueError(f"session {resolved_session_id!r} already exists")
        session = Session.create(
            session_id=resolved_session_id,
            project_id=project_id,
            title=title or objective,
            objective=objective,
            status=SessionStatus.ACTIVE,
        )
        self.repositories.sessions.save(session)
        self._ensure_master_agent(session.session_id)
        events = [
            _event(
                "session.created",
                session.session_id,
                {"session": session.to_dict()},
            )
        ]
        self.event_store.append(session.session_id, events)
        return {
            "session_id": session.session_id,
            "workspace": self.workspace(session.session_id),
            "events": events,
        }

    def recover_abandoned_sdk_continuations(
        self,
        *,
        actor_ref: str = "host_startup",
    ) -> list[dict[str, Any]]:
        with self.operation_lock:
            return self._recover_abandoned_sdk_continuations_locked(
                actor_ref=actor_ref,
            )

    def _recover_abandoned_sdk_continuations_locked(
        self,
        *,
        actor_ref: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for continuation in self.repositories.continuation_states.list_recoverable():
            operation = self.repositories.controlled_operations.get(
                continuation.operation_id
            )
            if (
                operation is not None
                and operation.owner_mode
                is ControlledOperationOwnerMode.DURABLE_ASYNC_V1
            ):
                # Durable execution and continuation delivery are recovered by
                # their own fenced workers.  The legacy startup sweep must not
                # relabel their operation or infer external-effect failure.
                continue
            with self._startup_continuation_writer_scope(continuation):
                failed_continuation = self.repositories.continuation_states.fail(
                    continuation.continuation_id,
                    error_code="operation_recovery_failed",
                    error_message=(
                        "Host restarted before the SDK continuation could be resumed."
                    ),
                    recovery_failed=True,
                )
                if operation is not None and not operation.status.is_terminal:
                    operation = replace(
                        operation,
                        status=ControlledOperationStatus.RECOVERY_FAILED,
                        error_code="operation_recovery_failed",
                        error_summary=(
                            "Host restarted before the SDK continuation could be resumed."
                        ),
                        updated_at=utc_now_iso(),
                    )
                    self.repositories.controlled_operations.save(operation)
                run = self.repositories.sandbox_runs.get(continuation.sandbox_run_id)
                if run is not None and not run.status.is_terminal:
                    now = utc_now_iso()
                    self.repositories.sandbox_runs.save(
                        replace(
                            run,
                            status=SandboxRunStatus.FAILED,
                            stderr_summary=(
                                "operation_recovery_failed: Host restarted before the "
                                "SDK continuation could be resumed."
                            ),
                            error_code="operation_recovery_failed",
                            ended_at=now,
                            updated_at=now,
                        )
                    )
                event = _event(
                    "sdk_controlled_operation.recovery_failed",
                    continuation.session_id,
                    {
                        "actor_ref": actor_ref,
                        "approval_id": continuation.approval_id,
                        "continuation_id": continuation.continuation_id,
                        "operation_id": continuation.operation_id,
                        "sandbox_run_id": continuation.sandbox_run_id,
                        "status": None
                        if failed_continuation is None
                        else failed_continuation.status.value,
                        "error_code": "operation_recovery_failed",
                    },
                )
                self._record_events(continuation.session_id, events, [event])
                self._touch_session(continuation.session_id)
        return events

    @contextmanager
    def _startup_continuation_writer_scope(self, continuation: Any):  # type: ignore[no-untyped-def]
        if self.mutation_writer_scope_factory is None:
            yield
            return
        with MutationScopeService(self.repositories).writer_turn(
            session_id=continuation.session_id,
            owner_kind=MutationWriterKind.CONTINUATION_DELIVERY,
            owner_ref=f"legacy-continuation-startup:{continuation.continuation_id}",
            process_epoch=continuation.process_epoch,
        ):
            yield

    def _ensure_master_agent(self, session_id: str) -> AgentMember:
        existing = self.repositories.agents.get(session_id, "agent:master")
        if existing is not None:
            return existing
        now = utc_now_iso()
        master = AgentMember(
            agent_id="agent:master",
            session_id=session_id,
            lane_id=None,
            task_id=None,
            name="OpenZyme",
            role="master",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            runtime_state="idle",
            idle_since=now,
            nickname="OpenZyme",
            display_name="OpenZyme",
            handle="@openzyme",
        )
        self.repositories.agents.save(master)
        return master

    def workspace(self, session_id: str) -> dict[str, Any]:
        with self.operation_lock:
            return (
                SessionProjectionBuilder(
                    self.repositories,
                    scientific_workflow_contract_registry=(
                        self.scientific_workflow_contract_registry
                    ),
                )
                .build_session_workspace(session_id)
                .to_dict()
            )

    def scientific_attempt_control(self) -> ScientificAttemptService:
        return ScientificAttemptService(
            self.repositories,
            workflow_contract_registry=(self.scientific_workflow_contract_registry),
            artifact_boundary=ArtifactBoundaryService(
                self.repositories,
                workspace_root=self.sandbox_workspace_root,
                blob_store_root=self.artifact_blob_root,
            ),
        )

    def export_closed_aox_attempt_evidence(
        self,
        *,
        session_id: str,
        attempt_id: str,
        selection_id: str,
    ) -> dict[str, Any]:
        """Project the complete source-bound AOX closure through the Host API."""

        control = self.scientific_attempt_control().export_closed_attempt_evidence(
            attempt_id,
            session_id=session_id,
            selection_id=selection_id,
        )
        attempt = dict(control["attempt"])
        events: list[dict[str, Any]] = []
        after_cursor = 0
        while True:
            page = self.event_store.list(
                session_id,
                after_cursor=after_cursor,
                limit=1_000,
            )
            events.extend(page)
            if len(events) > 100_000:
                raise ScientificAttemptError(
                    "attempt_evidence_event_export_too_large",
                    "closed AOX public event export exceeds its bounded limit",
                )
            if len(page) < 1_000:
                break
            after_cursor = int(page[-1]["cursor"])
        try:
            product_closure = build_aox_public_product_closure(
                self.repositories,
                session_id=session_id,
                attempt_id=attempt_id,
                attempt_kind=(
                    "fault"
                    if attempt.get("scope") == ScientificAttemptScope.FAULT.value
                    else "positive"
                ),
                execution_task_id=str(attempt["task_id"]),
                events=events,
                latest_event_cursor=(0 if not events else int(events[-1]["cursor"])),
            )
        except AoxPublicProductClosureError as exc:
            raise ScientificAttemptError(exc.error_code, str(exc)) from exc
        finalization: dict[str, object] | None = None
        deliverables: list[dict[str, object]] = []
        if attempt.get("scope") == ScientificAttemptScope.FORMAL.value:
            finalization = validate_persisted_aox_finalization_receipt(
                self.repositories,
                session_id=session_id,
                execution_task_id=str(attempt["task_id"]),
                attempt_id=attempt_id,
                selection_id=selection_id,
            )
            boundary = ArtifactBoundaryService(
                self.repositories,
                workspace_root=self.sandbox_workspace_root,
                blob_store_root=self.artifact_blob_root,
            )
            total_size = 0
            for raw_ref in sorted(
                finalization["artifacts"],
                key=lambda item: str(item["relative_path"]),
            ):
                ref = dict(raw_ref)
                content, content_digest = boundary.read_sealed_file(
                    session_id=session_id,
                    artifact_id=str(ref["artifact_id"]),
                )
                total_size += len(content)
                if total_size > 256 * 1024 * 1024:
                    raise ScientificAttemptError(
                        "attempt_evidence_export_too_large",
                        "closed AOX deliverables exceed the public export bound",
                    )
                if content_digest != ref.get("content_digest"):
                    raise ScientificAttemptError(
                        "attempt_evidence_artifact_digest_mismatch",
                        "closed AOX artifact differs from its finalization receipt",
                    )
                deliverables.append(
                    {
                        "artifact_id": ref["artifact_id"],
                        "relative_path": ref["relative_path"],
                        "content_digest": content_digest,
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                )
        payload: dict[str, Any] = {
            "schema_id": "aox_closed_attempt_evidence@2",
            "session_id": session_id,
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "scientific_attempt_control": control,
            "finalization_receipt": finalization,
            "deliverables": deliverables,
            "product_closure": product_closure,
        }
        return {**payload, "export_digest": canonical_digest(payload)}

    def inject_aox_reference_fault(
        self,
        *,
        session_id: str,
        attempt_id: str,
        artifact_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self.operation_lock:
            with MutationScopeService(self.repositories).writer_turn(
                session_id=session_id,
                owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
                owner_ref=f"aox-fault-capability:{attempt_id}",
            ):
                return inject_authority_bound_aox_reference_byte_flip(
                    self.repositories,
                    session_id=session_id,
                    attempt_id=attempt_id,
                    artifact_id=artifact_id,
                    actor_ref=actor_ref,
                    idempotency_key=idempotency_key,
                    blob_root=self.artifact_blob_root,
                )

    def grant_scientific_attempt_authorization(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        grantor_ref: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        record = self.scientific_attempt_control().grant_authorization(
            session_id=session_id,
            task_id=str(payload["task_id"]),
            campaign_id=str(payload["campaign_id"]),
            workflow_id=str(payload["workflow_id"]),
            root_ref=str(payload["root_ref"]),
            grantor_kind=str(payload.get("grantor_kind") or "user"),
            grantor_ref=grantor_ref,
            allowed_scopes=tuple(
                ScientificAttemptScope(str(item)) for item in payload["allowed_scopes"]
            ),
            allowed_effect_classes=tuple(
                str(item) for item in payload["allowed_effect_classes"]
            ),
            allowed_providers=tuple(
                str(item) for item in payload.get("allowed_providers", ())
            ),
            allowed_hpc_targets=tuple(
                str(item) for item in payload.get("allowed_hpc_targets", ())
            ),
            max_attempts=payload["max_attempts"],
            max_micu=payload["max_micu"],
            max_cost_microunits=payload["max_cost_microunits"],
            max_wall_time_seconds=payload["max_wall_time_seconds"],
            expires_at=str(payload["expires_at"]),
            idempotency_key=idempotency_key,
            policy_digest=(
                None
                if payload.get("policy_digest") is None
                else str(payload["policy_digest"])
            ),
        )
        return {
            "session_id": session_id,
            "record": record.to_dict(),
            "scientific_attempts": self.scientific_attempt_control().project_session(
                session_id
            ),
        }

    def _finalize_scientific_transition_with_delivery(
        self,
        *,
        transition_kind: str,
        session_id: str,
        request_id: str,
    ) -> tuple[Any, list[dict[str, Any]]]:
        """Commit one transition, its event, and its durable wakeup together."""

        if transition_kind not in {"admission", "closure"}:
            raise ValueError("unsupported scientific transition kind")
        if current_mutation_write_authority() is not None:
            raise RuntimeError(
                "scientific transition finalization requires no active writer"
            )

        signal = None
        with self.repositories.atomic(
            prefix=f"scientific_transition_{transition_kind}"
        ):
            control = self.scientific_attempt_control()
            if transition_kind == "admission":
                request = self.repositories.scientific_attempt_admission_requests.get(
                    request_id
                )
                if request is None or request.session_id != session_id:
                    raise ValueError("admission request does not belong to the session")
                record = control.finalize_attempt_admission(
                    admission_request_id=request_id
                )
                attempt = record
                event_type = "scientific.attempt.admitted"
            else:
                request = self.repositories.scientific_attempt_closure_requests.get(
                    request_id
                )
                attempt = (
                    None
                    if request is None
                    else self.repositories.scientific_attempts.get(request.attempt_id)
                )
                if (
                    request is None
                    or attempt is None
                    or attempt.session_id != session_id
                ):
                    raise ValueError("closure request does not belong to the session")
                record = control.finalize_closure_request(closure_request_id=request_id)
                event_type = "scientific.attempt.closed"

            transition_record_id = (
                record.attempt_id
                if transition_kind == "admission"
                else record.closure_id
            )
            expected_event = _scientific_transition_event(
                event_type=event_type,
                session_id=session_id,
                record_id=transition_record_id,
                actor_ref=request.actor_ref,
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
                created_at=record.created_at,
            )
            deterministic_event = self.repositories.durable_events.get(
                str(expected_event["event_id"])
            )
            transition_events = (
                self.repositories.durable_events.list_scientific_transition_events(
                    session_id=session_id,
                    event_type=event_type,
                    record_id=transition_record_id,
                )
            )
            if len(transition_events) > 1:
                raise RuntimeError("scientific transition has ambiguous durable events")
            existing_event = (
                deterministic_event
                if deterministic_event is not None
                else (transition_events[0] if transition_events else None)
            )
            if existing_event is not None and (
                existing_event.session_id != session_id
                or existing_event.event_type != event_type
                or existing_event.payload != expected_event["payload"]
                or existing_event.schema_version != "openzyme.v3.event.v1"
                or existing_event.visibility != "public"
                or (
                    deterministic_event is not None
                    and existing_event.created_at != record.created_at
                )
            ):
                raise RuntimeError(
                    "scientific transition event identity conflicts with durable state"
                )

            agent = self.repositories.agents.get(
                session_id,
                request.actor_ref,
            )
            existing_signal = (
                None
                if agent is None
                else self.repositories.runtime_signals.find_source_signal(
                    session_id=session_id,
                    agent_id=request.actor_ref,
                    reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                    source_ref=transition_record_id,
                )
            )
            signal = existing_signal
            events: list[dict[str, Any]] = []
            if existing_event is None or (
                agent is not None and existing_signal is None
            ):
                with MutationScopeService(self.repositories).writer_turn(
                    session_id=session_id,
                    owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                    owner_ref="host:scientific-transition-finalizer",
                ):
                    if existing_event is None:
                        events.append(expected_event)
                    if agent is not None and existing_signal is None:
                        context = self._build_runtime_context(
                            session_id,
                            task_id=attempt.task_id,
                            lane_id=attempt.lane_id,
                        )
                        signal = AgentRuntimeService(context).enqueue_signal(
                            session_id=session_id,
                            agent_id=request.actor_ref,
                            task_id=attempt.task_id,
                            lane_id=attempt.lane_id,
                            correlation_id=transition_record_id,
                            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                            source_ref=transition_record_id,
                            notify=False,
                        )
                        events.extend(
                            event.to_dict() for event in context.event_sink.events
                        )
                    if events:
                        self.event_store.append(session_id, events)

        if (
            signal is not None
            and not signal.status.is_terminal
            and self.signal_notifier is not None
            and hasattr(self.signal_notifier, "notify")
        ):
            self.signal_notifier.notify(session_id)
        return record, events

    def finalize_pending_scientific_transitions(
        self,
        *,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Finalize agent requests only after their bounded writer has retired."""

        if current_mutation_write_authority() is not None:
            raise RuntimeError(
                "scientific transition finalization requires no active writer"
            )
        events: list[dict[str, Any]] = []
        failures: list[
            tuple[
                str,
                str,
                str,
                str,
                str,
                str | None,
                str | None,
                ScientificAttemptError,
            ]
        ] = []

        # Closure first permits a same-turn request for a subsequent authorized
        # attempt to roll the newly opened follow-up session scope.
        for (
            request
        ) in self.repositories.scientific_attempt_closure_requests.list_by_session(
            session_id
        ):
            try:
                _, transition_events = (
                    self._finalize_scientific_transition_with_delivery(
                        transition_kind="closure",
                        session_id=session_id,
                        request_id=request.closure_request_id,
                    )
                )
            except ScientificAttemptError as exc:
                if not exc.retryable:
                    attempt = self.repositories.scientific_attempts.get(
                        request.attempt_id
                    )
                    failures.append(
                        (
                            "closure",
                            request.closure_request_id,
                            request.request_digest,
                            request.actor_ref,
                            request.attempt_id,
                            None if attempt is None else attempt.task_id,
                            None if attempt is None else attempt.lane_id,
                            exc,
                        )
                    )
                continue
            events.extend(transition_events)

        for (
            request
        ) in self.repositories.scientific_attempt_admission_requests.list_by_session(
            session_id
        ):
            try:
                _, transition_events = (
                    self._finalize_scientific_transition_with_delivery(
                        transition_kind="admission",
                        session_id=session_id,
                        request_id=request.admission_request_id,
                    )
                )
            except ScientificAttemptError as exc:
                if not exc.retryable:
                    failures.append(
                        (
                            "admission",
                            request.admission_request_id,
                            request.request_digest,
                            request.actor_ref,
                            request.envelope_id,
                            request.task_id,
                            request.lane_id,
                            exc,
                        )
                    )
                continue
            events.extend(transition_events)

        pending_failures = [
            failure
            for failure in failures
            if self.repositories.failure_observations.get_by_source(
                session_id=session_id,
                source_kind="scientific_transition",
                source_ref=failure[1],
                source_version=failure[2],
                phase=f"{failure[0]}_finalization",
                error_code=failure[7].error_code,
            )
            is None
        ]
        if not pending_failures:
            return events
        failure_events: list[dict[str, Any]] = []
        with MutationScopeService(self.repositories).writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref="host:scientific-transition-finalizer",
        ):
            for (
                transition_kind,
                request_id,
                request_digest,
                actor_ref,
                authority_ref,
                task_id,
                lane_id,
                exc,
            ) in pending_failures:
                authorization_failure = exc.error_code.startswith("authorization_")
                agent = (
                    self.repositories.agents.get(session_id, actor_ref)
                    if actor_ref.startswith("agent:")
                    else None
                )
                observation = record_failure_observation(
                    self.repositories,
                    session_id=session_id,
                    task_id=task_id,
                    lane_id=lane_id,
                    agent_id=None if agent is None else actor_ref,
                    source_kind="scientific_transition",
                    source_ref=request_id,
                    source_version=request_digest,
                    phase=f"{transition_kind}_finalization",
                    failure_class=FailureClass.SYSTEM,
                    recoverability=(
                        FailureRecoverability.AUTHORIZATION_REQUIRED
                        if authorization_failure
                        else FailureRecoverability.AGENT_CAN_REPLAN
                    ),
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    retry_eligibility=RetryEligibility.TERMINAL,
                    actor_kind=FailureActorKind.SYSTEM,
                    error_code=exc.error_code,
                    safe_summary=str(exc),
                    safe_hint=exc.hint,
                    facts={
                        "transition_kind": transition_kind,
                        "request_id": request_id,
                        "authority_ref": authority_ref,
                        **exc.details,
                    },
                    evidence_refs=(
                        f"scientific_{transition_kind}_request:{request_id}",
                    ),
                    private_diagnostic={
                        "failure_type": type(exc).__name__,
                        "error_code": exc.error_code,
                    },
                )
                failure_events.append(
                    _event(
                        "scientific.transition.failed",
                        session_id,
                        {
                            "failure_id": observation.failure_id,
                            "transition_kind": transition_kind,
                            "request_id": request_id,
                            "error_code": observation.error_code,
                            "actor_ref": actor_ref,
                            "task_id": task_id,
                            "lane_id": lane_id,
                        },
                    )
                )
                if agent is not None:
                    context = self._build_runtime_context(
                        session_id,
                        task_id=task_id,
                        lane_id=lane_id,
                    )
                    AgentRuntimeService(context).enqueue_signal(
                        session_id=session_id,
                        agent_id=actor_ref,
                        task_id=task_id,
                        lane_id=lane_id,
                        correlation_id=observation.failure_id,
                        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                        source_ref=observation.failure_id,
                    )
                    failure_events.extend(
                        event.to_dict() for event in context.event_sink.events
                    )
            self.event_store.append(session_id, failure_events)
        events.extend(failure_events)
        return events

    def pending_approvals(self, session_id: str) -> list[dict[str, Any]]:
        """Return only the durable approval-control projection for a session."""

        with self.operation_lock:
            if self.repositories.sessions.get(session_id) is None:
                raise ValueError(f"session {session_id!r} does not exist")
            return list(
                SessionProjectionBuilder(self.repositories).build_pending_approvals(
                    session_id
                )
            )

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for session in self.repositories.sessions.list_by_project(project_id):
            messages = self.repositories.inbox.list_by_session(session.session_id)
            approvals = self.repositories.approvals.list_by_session(session.session_id)
            latest_preview = ""
            for message in reversed(messages):
                if (
                    message.message_type not in {"user_message", "assistant_message"}
                    or not message.payload_ref
                ):
                    continue
                payload = self.repositories.engine_documents.get(message.payload_ref)
                if payload is None:
                    continue
                content = str(payload.payload.get("content") or "").strip()
                if content:
                    latest_preview = content
                    break
            summaries.append(
                {
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "title": session.title,
                    "objective": session.objective,
                    "status": session.status.value,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "latest_message_preview": latest_preview,
                    "pending_approval_count": sum(
                        1
                        for approval in approvals
                        if approval.status is ApprovalRequestStatus.PENDING
                    ),
                }
            )
        summaries.sort(
            key=lambda item: (item["updated_at"], item["session_id"]), reverse=True
        )
        return summaries

    def events(
        self,
        session_id: str,
        *,
        after_cursor: int = 0,
        limit: int = 1_000,
    ) -> list[dict[str, Any]]:
        return self.event_store.list(
            session_id,
            after_cursor=after_cursor,
            limit=limit,
        )

    def _touch_session(self, session_id: str) -> None:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            return
        next_updated_at = utc_now_iso()
        latest_project_updated_at = max(
            (
                candidate.updated_at
                for candidate in self.repositories.sessions.list_by_project(
                    session.project_id
                )
            ),
            default=session.updated_at,
        )
        if next_updated_at <= latest_project_updated_at:
            next_updated_at = (
                datetime.fromisoformat(latest_project_updated_at) + timedelta(seconds=1)
            ).isoformat()
        self.repositories.sessions.save(replace(session, updated_at=next_updated_at))

    def _extend_with_activity_events(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        existing = {
            _event_fingerprint(event) for event in self.events(session_id, limit=10_000)
        }
        current = {_event_fingerprint(event) for event in events}
        # Activity-event backfill needs only the activity projection.  Building
        # the composite workspace here used to project the complete artifact
        # catalog while a mutation still owned its SQLite write transaction.
        # That coupled approval latency to unrelated scientific metadata size.
        for item in SessionProjectionBuilder(
            self.repositories
        ).build_public_activity_feed(session_id):
            event = {
                "event_id": _new_id("evt"),
                "session_id": session_id,
                "event_type": item["event_type"],
                "created_at": item["created_at"],
                "payload": item["payload"],
            }
            fingerprint = _event_fingerprint(event)
            if fingerprint in existing or fingerprint in current:
                continue
            events.append(event)
            current.add(fingerprint)

    def _extend_with_trace_events(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        seen_trace_ids = {
            event.get("payload", {}).get("trace_id")
            for event in [*self.events(session_id, limit=10_000), *events]
            if event.get("event_type") == "llm.response.created"
            and isinstance(event.get("payload"), dict)
            and event.get("payload", {}).get("trace_id")
        }
        traces = self.workspace(session_id).get("agent_traces", {})
        for entries in traces.values():
            for payload in entries:
                trace_id = payload.get("trace_id")
                if trace_id in seen_trace_ids:
                    continue
                event = {
                    "event_id": _new_id("evt"),
                    "session_id": session_id,
                    "event_type": "llm.response.created",
                    "created_at": payload.get("created_at") or utc_now_iso(),
                    "payload": payload,
                }
                events.append(event)
                seen_trace_ids.add(trace_id)

    def _build_runtime_context(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
    ) -> SessionRuntimeContext:
        return SessionRuntimeContext(
            repositories=self.repositories,
            event_sink=self._event_sink(),
            snapshot=SessionRuntimeSnapshot.load(self.repositories, session_id),
            tool_registry=ToolRegistry(),
            restore_focus=RestoreFocus(
                task_id=task_id, lane_id=lane_id, skill_keys=skill_keys
            ),
            model_factory=self.model_factory,
            engine_registry=self.engine_registry,
            bio_research_service=self.bio_research_service,
            research_adapter=self.research_adapter,
            scientific_workflow_contract_registry=(
                self.scientific_workflow_contract_registry
            ),
            sandbox_workspace_root=self.sandbox_workspace_root,
            artifact_blob_root=self.artifact_blob_root,
            artifact_bundle_finalizer=self.artifact_bundle_finalizer,
            signal_notifier=self.signal_notifier,
            reliability_shadow_observer=self.reliability_shadow_observer,
            reliability_settings=self.reliability_settings,
            durable_route_adapter_policy_ids=dict(
                self.durable_route_adapter_policy_ids
            ),
            tool_dispatch_precondition=self.tool_dispatch_precondition,
            mutation_writer_scope_factory=self.mutation_writer_scope_factory,
            sandbox_host_binding_factory=self.sandbox_host_binding_factory,
        )

    async def run_background_runtime_once(
        self,
        *,
        session_id: str,
        worker_id: str = "host-api:background-runtime",
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
    ) -> list[dict[str, Any]]:
        with self.operation_lock:
            if self.repositories.sessions.get(session_id) is None:
                raise KeyError(f"session {session_id!r} does not exist")
            context = self._build_runtime_context(session_id)
            scheduler = self._build_scheduler(
                context, worker_id=worker_id, runtime_mode="background"
            )
        try:
            outcomes = await scheduler.run_once(
                session_id,
                max_signals=max_signals,
                max_steps_per_agent=max_steps_per_agent,
            )
        except SessionRuntimeLeaseLockedError as exc:
            event = self._runtime_locked_event(session_id, exc)
            with self.operation_lock:
                self.event_store.append(session_id, [event])
            return []
        events = [event.to_dict() for event in context.event_sink.events]
        if current_mutation_write_authority() is None:
            self.finalize_pending_scientific_transitions(session_id=session_id)
        with self.operation_lock:
            self._touch_session(session_id)
            self._extend_with_trace_events(session_id, events)
            self._extend_with_activity_events(session_id, events)
            self.event_store.append(session_id, events)
        return [outcome.to_dict() for outcome in outcomes]

    def _build_scheduler(
        self,
        context: SessionRuntimeContext,
        *,
        worker_id: str,
        runtime_mode: str = "manual_drain",
    ) -> AgentRuntimeScheduler:
        return AgentRuntimeScheduler(
            context,
            worker_id=worker_id,
            runtime_mode=runtime_mode,
            max_global_concurrency=int(self.scheduler_limits.get("global", 1)),
            max_session_concurrency=int(self.scheduler_limits.get("session", 1)),
            max_agent_concurrency=int(self.scheduler_limits.get("agent", 1)),
            repository_scope_factory=self.runtime_repository_scope_factory,
            engine_registry_factory=self.engine_registry_factory,
            mutation_writer_scope_factory=self.mutation_writer_scope_factory,
        )

    def _runtime_locked_event(
        self, session_id: str, exc: SessionRuntimeLeaseLockedError
    ) -> dict[str, Any]:
        return _event(
            "runtime.session_locked",
            session_id,
            {
                "status": "locked",
                "retry_after_seconds": exc.retry_after_seconds,
                "safe_retry_hint": (
                    "Retry after the current bounded session runtime owner releases "
                    "its authority."
                ),
            },
        )

    def _drain_pending_agent_signals(
        self,
        session_id: str,
        events: list[dict[str, Any]],
        *,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        auto_enqueue_ready_tasks: bool = False,
        worker_id: str = "host-api:runtime-drain",
    ) -> list[AgentRuntimeOutcome]:
        context = self._build_runtime_context(session_id)
        scheduler = self._build_scheduler(
            context, worker_id=worker_id, runtime_mode="manual_drain"
        )
        outcomes = scheduler.run_once_sync(
            session_id,
            max_signals=max_signals,
            max_steps_per_agent=max_steps_per_agent,
            auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
        )
        events.extend(event.to_dict() for event in context.event_sink.events)
        return list(outcomes)

    def _runtime_drain_core_receipt(
        self,
        *,
        session_id: str,
        outcomes: list[AgentRuntimeOutcome],
        events: list[dict[str, Any]],
    ) -> tuple[RuntimeDrainCoreReceipt, tuple[str, ...]]:
        has_pending_approval = bool(
            self.repositories.approvals.list_pending_by_session(session_id)
        )
        waiting = has_pending_approval or self._outcomes_include_waiting_approval(
            outcomes
        )
        if waiting:
            scheduler_status = HarnessStatus.WAITING_APPROVAL.value
        elif self._outcomes_include_scheduler_failure(outcomes):
            scheduler_status = HarnessStatus.FAILED.value
        else:
            scheduler_status = HarnessStatus.COMPLETED.value
        master_outputs = tuple(
            output
            for outcome in outcomes
            if outcome.agent is not None and outcome.agent.agent_id == "agent:master"
            for output in outcome.outputs
        )
        response_outputs = () if has_pending_approval else master_outputs
        output_ids = tuple(
            canonical_digest(
                {
                    "schema_version": "runtime_drain_output_identity@1",
                    "ordinal": ordinal,
                    "output": output,
                }
            )
            for ordinal, output in enumerate(response_outputs)
        )
        event_ids = tuple(
            event_id
            for event in events
            if isinstance((event_id := event.get("event_id")), str) and event_id
        )
        return (
            RuntimeDrainCoreReceipt(
                scheduler_status=scheduler_status,
                processed_signal_count=len(outcomes),
                suspended=waiting,
                output_ids=output_ids,
                event_ids=event_ids,
            ),
            response_outputs,
        )

    def _runtime_drain_projection_failure(
        self,
        *,
        session_id: str,
        core_receipt: RuntimeDrainCoreReceipt,
        outputs: tuple[str, ...],
        events: list[dict[str, Any]],
        failed_stage: str,
        error: Exception,
    ) -> V3RuntimeDrainResult:
        safe_summary = sanitize_public_diagnostic_text(str(error)).strip()
        projection = RuntimeDrainProjectionOutcome.failed(
            safe_summary=(
                safe_summary[:2_000] or "Runtime projection settlement failed."
            ),
            failed_stage=failed_stage,
        )
        return V3RuntimeDrainResult(
            session_id=session_id,
            core_receipt=core_receipt,
            projection_outcome=projection,
            outputs=outputs,
            events=events,
            workspace={},
            safe_retry_hint=(
                "Do not blindly replay this command. Inspect the current "
                "canonical session, signal, task, and scientific selection state "
                "before deciding whether to submit another drain."
            ),
        )

    def _settle_runtime_drain_projection(
        self,
        *,
        session_id: str,
        core_receipt: RuntimeDrainCoreReceipt,
        outputs: tuple[str, ...],
        events: list[dict[str, Any]],
        source_ref: str,
    ) -> V3RuntimeDrainResult:
        stage = "scientific_transitions"
        try:
            with self.operation_lock:
                if current_mutation_write_authority() is None:
                    self.finalize_pending_scientific_transitions(session_id=session_id)
                with self._runtime_projection_writer_scope(
                    session_id=session_id,
                    source_ref=source_ref,
                ):
                    stage = "session_touch"
                    self._touch_session(session_id)
                    stage = "trace_events"
                    self._extend_with_trace_events(session_id, events)
                    stage = "activity_events"
                    self._extend_with_activity_events(session_id, events)
                    stage = "event_append"
                    self.event_store.append(session_id, events)
                    stage = "workspace"
                    workspace = self.workspace(session_id)
        except Exception as exc:
            return self._runtime_drain_projection_failure(
                session_id=session_id,
                core_receipt=core_receipt,
                outputs=outputs,
                events=events,
                failed_stage=stage,
                error=exc,
            )
        return V3RuntimeDrainResult(
            session_id=session_id,
            core_receipt=core_receipt,
            projection_outcome=RuntimeDrainProjectionOutcome.complete(),
            outputs=outputs,
            events=events,
            workspace=workspace,
        )

    def drain_runtime(
        self,
        *,
        session_id: str,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        auto_enqueue_ready_tasks: bool = False,
        worker_id: str = "host-api:runtime-drain",
        source_command_id: str | None = None,
    ) -> V3RuntimeDrainResult:
        source_ref = (
            f"runtime-command:{source_command_id}"
            if source_command_id is not None
            else f"runtime-drain:{worker_id}"
        )
        with self.operation_lock:
            if self.repositories.sessions.get(session_id) is None:
                raise KeyError(f"session {session_id!r} does not exist")
        events: list[dict[str, Any]] = []
        try:
            outcomes = self._drain_pending_agent_signals(
                session_id,
                events,
                max_signals=max_signals,
                max_steps_per_agent=max_steps_per_agent,
                auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
                worker_id=worker_id,
            )
        except SessionRuntimeLeaseLockedError as exc:
            locked_event = self._runtime_locked_event(session_id, exc)
            events.append(locked_event)
            core_receipt = RuntimeDrainCoreReceipt(
                scheduler_status=RuntimeCommandStatus.LOCKED.value,
                processed_signal_count=0,
                suspended=False,
                event_ids=(str(locked_event["event_id"]),),
            )
            settled = self._settle_runtime_drain_projection(
                session_id=session_id,
                outputs=(),
                events=events,
                core_receipt=core_receipt,
                source_ref=source_ref,
            )
            if settled.projection_outcome.status == "failed":
                return settled
            return replace(
                settled,
                safe_retry_hint=(
                    "Submit a new drain command after the active session runtime "
                    "lease has been released."
                ),
            )
        try:
            core_receipt, response_outputs = self._runtime_drain_core_receipt(
                session_id=session_id,
                outcomes=outcomes,
                events=events,
            )
        except Exception as exc:
            core_receipt = RuntimeDrainCoreReceipt(
                scheduler_status=HarnessStatus.FAILED.value,
                processed_signal_count=len(outcomes),
                suspended=False,
                event_ids=tuple(
                    event_id
                    for event in events
                    if isinstance(
                        (event_id := event.get("event_id")),
                        str,
                    )
                    and event_id
                ),
            )
            return self._runtime_drain_projection_failure(
                session_id=session_id,
                core_receipt=core_receipt,
                outputs=(),
                events=events,
                failed_stage="core_receipt_assembly",
                error=exc,
            )
        return self._settle_runtime_drain_projection(
            session_id=session_id,
            core_receipt=core_receipt,
            outputs=response_outputs,
            events=events,
            source_ref=source_ref,
        )

    @contextmanager
    def _runtime_projection_writer_scope(
        self,
        *,
        session_id: str,
        source_ref: str,
    ):  # type: ignore[no-untyped-def]
        """Bind projection writes to the scope visible after a bounded drain."""

        if self.mutation_writer_scope_factory is None:
            yield
            return
        with self.mutation_writer_scope_factory(
            session_id=session_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref=f"{source_ref}:post-transition-projection",
        ) as authority:
            if authority is None:
                yield
            else:
                with self.repositories.mutation_write_authority(authority):
                    yield

    @staticmethod
    def _outcomes_include_scheduler_failure(
        outcomes: list[AgentRuntimeOutcome],
    ) -> bool:
        for outcome in outcomes:
            if not isinstance(outcome, AgentRuntimeOutcome):
                return True
            settlement = outcome.settlement
            if settlement is None:
                return True
            disposition = settlement.disposition
            if disposition is (AgentRuntimeSettlementDisposition.BUDGET_REPLAN_HANDOFF):
                if outcome.ok or not settlement.batch_barrier:
                    return True
                continue
            if disposition is (AgentRuntimeSettlementDisposition.SIGNAL_FAILED):
                return True
            if disposition is (AgentRuntimeSettlementDisposition.WAITING_APPROVAL):
                if not outcome.ok or not outcome.waiting_approval_id:
                    return True
                continue
            if disposition is (AgentRuntimeSettlementDisposition.SIGNAL_COMPLETED):
                if not outcome.ok:
                    return True
                continue
            return True
        return False

    def _outcomes_include_waiting_approval(
        self, outcomes: list[AgentRuntimeOutcome]
    ) -> bool:
        return any(outcome.waiting_approval_id for outcome in outcomes)

    def post_message(
        self,
        *,
        session_id: str,
        message: str | None,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
    ) -> V3CommandResult:
        with self.operation_lock:
            return self._post_message_locked(
                session_id=session_id,
                message=message,
                task_id=task_id,
                lane_id=lane_id,
                skill_keys=skill_keys,
            )

    def _post_message_locked(
        self,
        *,
        session_id: str,
        message: str | None,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
    ) -> V3CommandResult:
        if self.repositories.sessions.get(session_id) is None:
            raise KeyError(f"session {session_id!r} does not exist")
        self._ensure_master_agent(session_id)
        events: list[dict[str, Any]] = []
        message_id = None
        normalized_focus = RestoreFocus(
            task_id=task_id,
            lane_id=lane_id,
            skill_keys=skill_keys,
        ).normalized()
        if message:
            message_id = _new_id("msg")
            created_at = utc_now_iso()
            payload_ref = persist_conversation_message(
                self.repositories,
                session_id=session_id,
                message_id=message_id,
                role="user",
                content=message,
                created_at=created_at,
                skill_keys=normalized_focus.skill_keys,
            )
            self.repositories.inbox.save(
                InboxMessage(
                    message_id=message_id,
                    session_id=session_id,
                    sender="user",
                    sender_kind=InboxParticipantKind.USER,
                    recipient="harness",
                    recipient_kind=InboxParticipantKind.HARNESS,
                    message_type="user_message",
                    correlation_id=None,
                    payload_ref=payload_ref,
                    status=InboxStatus.DELIVERED,
                    created_at=created_at,
                )
            )
            self._record_events(
                session_id,
                events,
                [_event("conversation.user_message", session_id, {"content": message})],
            )
        # Workflow authority remains solely in the canonical source document;
        # this admission-only context carries scheduling focus, not skill focus.
        context = self._build_runtime_context(
            session_id,
            task_id=normalized_focus.task_id,
            lane_id=normalized_focus.lane_id,
        )
        AgentRuntimeService(context).enqueue_signal(
            session_id=session_id,
            agent_id="agent:master",
            task_id=task_id,
            lane_id=lane_id,
            correlation_id=None,
            reason=AgentRuntimeSignalReason.INBOX_UNREAD,
            source_ref=message_id,
        )
        events.extend(event.to_dict() for event in context.event_sink.events)
        has_pending_approval = bool(
            self.repositories.approvals.list_pending_by_session(session_id)
        )
        response_status = (
            HarnessStatus.WAITING_APPROVAL
            if has_pending_approval
            else HarnessStatus.COMPLETED
        )
        response_outputs = ()
        self._touch_session(session_id)
        self._extend_with_trace_events(session_id, events)
        self._extend_with_activity_events(session_id, events)
        self.event_store.append(session_id, events)
        return V3CommandResult(
            session_id=session_id,
            status=response_status.value,
            outputs=response_outputs,
            events=events,
            workspace=self.workspace(session_id),
        )

    def resolve_approval(
        self, approval_id: str, *, decision: str, actor_ref: str = "user"
    ) -> V3CommandResult:
        with self.operation_lock:
            return self._resolve_approval_locked(
                approval_id, decision=decision, actor_ref=actor_ref
            )

    def _resolve_approval_locked(
        self, approval_id: str, *, decision: str, actor_ref: str = "user"
    ) -> V3CommandResult:
        approval = self.repositories.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"approval {approval_id!r} does not exist")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        if approval.status is not ApprovalRequestStatus.PENDING:
            if approval.kind == "sdk_controlled_operation":
                return self._resolve_existing_sdk_controlled_operation(
                    approval,
                    decision=decision,
                )
            raise ValueError(f"approval {approval_id!r} is not pending")
        events: list[dict[str, Any]] = []
        resolved_event = _event(
            "approval.resolved",
            approval.session_id,
            {
                "approval_id": approval_id,
                "decision": decision,
                "actor_ref": actor_ref,
            },
        )
        resolved_event["actor_ref"] = actor_ref
        if approval.kind == "sdk_controlled_operation":
            with self.repositories.atomic(prefix="sdk_controlled_operation_approval"):
                self._record_events(
                    approval.session_id,
                    events,
                    [resolved_event],
                )
                resolved = self._resolve_approval_record(
                    approval,
                    decision=decision,
                    actor_ref=actor_ref,
                )
                self._resolve_sdk_controlled_operation(
                    resolved,
                    decision=decision,
                    events=events,
                )
        else:
            self._record_events(
                approval.session_id,
                events,
                [resolved_event],
            )
            resolved = self._resolve_approval_record(
                approval,
                decision=decision,
                actor_ref=actor_ref,
            )
            assigned_agent_id = self._approval_assigned_agent_id(approval)
            if assigned_agent_id is not None:
                self._enqueue_approval_resolved_signal(
                    approval, agent_id=assigned_agent_id, events=events
                )
            else:
                self._ensure_master_agent(approval.session_id)
                self._enqueue_approval_resolved_signal(
                    approval, agent_id="agent:master", events=events
                )
        self._touch_session(approval.session_id)
        self._extend_with_trace_events(approval.session_id, events)
        self._extend_with_activity_events(approval.session_id, events)
        self.event_store.append(approval.session_id, events)
        return V3CommandResult(
            session_id=approval.session_id,
            status=HarnessStatus.COMPLETED.value,
            outputs=(),
            events=events,
            workspace=self.workspace(approval.session_id),
        )

    def _resolve_existing_sdk_controlled_operation(
        self,
        approval: ApprovalRequest,
        *,
        decision: str,
    ) -> V3CommandResult:
        expected_status = (
            ApprovalRequestStatus.APPROVED
            if decision == "approved"
            else ApprovalRequestStatus.REJECTED
        )
        if approval.status is not expected_status:
            raise ValueError(
                f"approval_state_conflict: approval {approval.approval_id!r} "
                f"is already {approval.status.value}"
            )
        events: list[dict[str, Any]] = []
        self._resolve_sdk_controlled_operation(
            approval,
            decision=decision,
            events=events,
        )
        self._extend_with_trace_events(approval.session_id, events)
        self._extend_with_activity_events(approval.session_id, events)
        self.event_store.append(approval.session_id, events)
        return V3CommandResult(
            session_id=approval.session_id,
            status=HarnessStatus.COMPLETED.value,
            outputs=(),
            events=events,
            workspace=self.workspace(approval.session_id),
        )

    def _resolve_sdk_controlled_operation(
        self,
        approval: ApprovalRequest,
        *,
        decision: str,
        events: list[dict[str, Any]],
    ) -> None:
        existing_continuation = (
            self.repositories.continuation_states.get_by_approval_id(
                approval.approval_id
            )
        )
        if (
            decision == "approved"
            and existing_continuation is not None
            and existing_continuation.delivery_state
            is ContinuationDeliveryState.RECOVERY_FAILED
        ):
            raise ValueError(
                "continuation_recovery_failed: the exact attached process is no "
                "longer resumable; approval cannot authorize dispatch"
            )
        continuation = self.repositories.continuation_states.resolve_for_approval(
            approval.approval_id,
            decision=decision,
        )
        operation = self.repositories.controlled_operations.get_by_approval_id(
            approval.approval_id
        )
        if operation is not None:
            if operation.owner_mode is ControlledOperationOwnerMode.DURABLE_ASYNC_V1:
                self._resolve_durable_sdk_controlled_operation(
                    operation_id=operation.operation_id,
                    decision=decision,
                )
                self._record_events(
                    approval.session_id,
                    events,
                    [
                        _event(
                            "sdk_controlled_operation.approval_resolved",
                            approval.session_id,
                            {
                                "approval_id": approval.approval_id,
                                "operation_id": operation.operation_id,
                                "operation_digest": operation.operation_digest,
                                "continuation_id": (
                                    None
                                    if continuation is None
                                    else continuation.continuation_id
                                ),
                                "decision": decision,
                            },
                        )
                    ],
                )
                return
            status = operation.status
            error_code = operation.error_code
            error_summary = operation.error_summary
            if decision == "rejected":
                status = ControlledOperationStatus.FAILED
                error_code = "approval_rejected"
                error_summary = "User rejected supervised SDK operation."
            updated = replace(
                operation,
                approval_state=approval.status.value,
                status=status,
                error_code=error_code,
                error_summary=error_summary,
                updated_at=utc_now_iso(),
            )
            self.repositories.controlled_operations.save(updated)
        self._record_events(
            approval.session_id,
            events,
            [
                _event(
                    "sdk_controlled_operation.approval_resolved",
                    approval.session_id,
                    {
                        "approval_id": approval.approval_id,
                        "operation_id": None
                        if operation is None
                        else operation.operation_id,
                        "operation_digest": (
                            None if operation is None else operation.operation_digest
                        ),
                        "continuation_id": None
                        if continuation is None
                        else continuation.continuation_id,
                        "decision": decision,
                    },
                )
            ],
        )

    def _resolve_durable_sdk_controlled_operation(
        self,
        *,
        operation_id: str,
        decision: str,
    ) -> None:
        execution = (
            self.repositories.controlled_operation_executions.get_by_operation_id(
                operation_id
            )
        )
        if execution is None:
            raise RuntimeError(
                "durable controlled operation has no canonical execution owner"
            )
        target_lifecycle = (
            ControlledOperationExecutionLifecycle.READY
            if decision == "approved"
            else ControlledOperationExecutionLifecycle.TERMINAL
        )
        if execution.lifecycle_state is target_lifecycle:
            return
        if execution.lifecycle_state is not (
            ControlledOperationExecutionLifecycle.AWAITING_APPROVAL
        ):
            raise ValueError(
                "durable controlled operation approval conflicts with execution state"
            )
        now = utc_now_iso()
        updated = replace(
            execution,
            lifecycle_state=target_lifecycle,
            terminal_outcome=(
                None
                if decision == "approved"
                else ControlledOperationExecutionTerminalOutcome.CANCELLED
            ),
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=(
                RetryEligibility.SAME_PHASE_SAFE
                if decision == "approved"
                else RetryEligibility.TERMINAL
            ),
            state_version=execution.state_version + 1,
            error_code=None if decision == "approved" else "approval_rejected",
            safe_error_summary=(
                None
                if decision == "approved"
                else "User rejected supervised SDK operation."
            ),
            updated_at=now,
            terminal_at=None if decision == "approved" else now,
        )
        result_handle = None
        if decision == "rejected":
            result_handle = build_controlled_operation_result_handle(
                execution,
                terminal_outcome=(
                    ControlledOperationExecutionTerminalOutcome.CANCELLED
                ),
                bounded_result_envelope={
                    "status": "cancelled",
                    "error_code": "approval_rejected",
                    "safe_error_summary": ("User rejected supervised SDK operation."),
                    "output_artifact_ids": [],
                },
                artifact_set_digest=controlled_operation_artifact_set_digest(()),
                origin="host_approval_gate",
                created_at=now,
            )
            updated = replace(
                updated,
                result_handle_ref=result_handle.result_handle_id,
                result_digest=result_handle.result_digest,
                artifact_set_digest=result_handle.artifact_set_digest,
            )
        ControlledOperationExecutionTransitionService(self.repositories).transition(
            execution=updated,
            event=ControlledOperationExecutionEvent(
                event_id=_new_id("exec_evt"),
                execution_id=updated.execution_id,
                operation_id=updated.operation_id,
                session_id=updated.session_id,
                state_version=updated.state_version,
                dispatch_generation=updated.dispatch_generation,
                phase=ControlledOperationExecutionPhase.APPROVAL,
                previous_lifecycle_state=execution.lifecycle_state,
                lifecycle_state=updated.lifecycle_state,
                terminal_outcome=updated.terminal_outcome,
                effect_certainty=updated.effect_certainty,
                retry_eligibility=updated.retry_eligibility,
                fencing_token=updated.fencing_token,
                safe_summary=(
                    "durable operation approved"
                    if decision == "approved"
                    else "durable operation rejected before dispatch"
                ),
                created_at=now,
            ),
            expected_state_version=execution.state_version,
            result_handle=result_handle,
        )
        if decision == "approved" and self.durable_work_notifier is not None:
            self.durable_work_notifier.notify(execution.session_id)

    def _enqueue_approval_resolved_signal(
        self,
        approval: ApprovalRequest,
        *,
        agent_id: str | None,
        events: list[dict[str, Any]],
    ) -> None:
        if agent_id is None:
            return
        if approval.task_id is None and agent_id != "agent:master":
            return
        context = self._build_runtime_context(
            approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
        )
        AgentRuntimeService(context).enqueue_signal(
            session_id=approval.session_id,
            agent_id=agent_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            correlation_id=approval.approval_id,
            reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED,
            source_ref=approval.approval_id,
        )
        events.extend(event.to_dict() for event in context.event_sink.events)

    def _approval_assigned_agent_id(self, approval: ApprovalRequest) -> str | None:
        if approval.task_id is None:
            return None
        task = self.repositories.tasks.get(approval.task_id)
        if (
            task is not None
            and task.assigned_ref
            and task.assigned_ref.startswith("agent:")
        ):
            return task.assigned_ref
        agent = next(
            (
                candidate
                for candidate in self.repositories.agents.list_by_session(
                    approval.session_id
                )
                if (
                    candidate.task_id == approval.task_id
                    or (
                        approval.lane_id is not None
                        and candidate.lane_id == approval.lane_id
                    )
                )
            ),
            None,
        )
        return None if agent is None else agent.agent_id

    def _resolve_approval_record(
        self, approval: ApprovalRequest, *, decision: str, actor_ref: str
    ) -> ApprovalRequest:
        del actor_ref
        status = (
            ApprovalRequestStatus.APPROVED
            if decision == "approved"
            else ApprovalRequestStatus.REJECTED
        )
        resolved = ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=status,
            request_ref=approval.request_ref,
            resolution_ref=approval.resolution_ref,
            created_at=approval.created_at,
            resolved_at=utc_now_iso(),
        )
        self.repositories.approvals.save(resolved)
        return resolved

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.operation_lock:
            return self._create_task_locked(payload)

    def _create_task_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = TaskBoardService(self.repositories).create_task(
            session_id=str(payload["session_id"]),
            task_id=str(payload.get("task_id") or _new_id("task")),
            subject=str(payload["subject"]),
            description=str(payload.get("description") or ""),
            priority=TaskPriority(
                str(payload.get("priority") or TaskPriority.NORMAL.value)
            ),
            kind=str(payload.get("kind") or "general"),
            status=TaskStatus(str(payload.get("status") or TaskStatus.TODO.value)),
            assigned_ref=payload.get("assigned_ref"),
            lane_id=payload.get("lane_id"),
            blocked_by=tuple(payload.get("blocked_by") or ()),
            failure_summary=payload.get("failure_summary"),
            failure_ref=payload.get("failure_ref"),
        )
        events = [_event("task.created", task.session_id, {"task": task.to_dict()})]
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {
            "task": task.to_dict(),
            "workspace": self.workspace(task.session_id),
            "events": events,
        }

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.operation_lock:
            return self._update_task_locked(task_id, payload)

    def _update_task_locked(
        self, task_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        mutation_kwargs: dict[str, Any] = {}
        if "subject" in payload:
            mutation_kwargs["subject"] = payload["subject"]
        if "description" in payload:
            mutation_kwargs["description"] = payload["description"]
        if "status" in payload:
            mutation_kwargs["status"] = TaskStatus(payload["status"])
        if "priority" in payload:
            mutation_kwargs["priority"] = TaskPriority(payload["priority"])
        if "kind" in payload:
            mutation_kwargs["kind"] = payload["kind"]
        if "assigned_ref" in payload:
            mutation_kwargs["assigned_ref"] = payload["assigned_ref"]
        if "lane_id" in payload:
            mutation_kwargs["lane_id"] = payload["lane_id"]
        if "blocked_by" in payload:
            mutation_kwargs["blocked_by"] = tuple(payload["blocked_by"])
        if "failure_summary" in payload:
            mutation_kwargs["failure_summary"] = payload["failure_summary"]
        if "failure_ref" in payload:
            mutation_kwargs["failure_ref"] = payload["failure_ref"]
        mutation = TaskMutation(**mutation_kwargs)
        task = TaskBoardService(self.repositories).edit_task(task_id, mutation)
        events = [_event("task.updated", task.session_id, {"task": task.to_dict()})]
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {
            "task": task.to_dict(),
            "workspace": self.workspace(task.session_id),
            "events": events,
        }

    def create_lane(self, payload: dict[str, Any]) -> dict[str, Any]:
        lane = LaneManager(self.repositories).create_lane(
            session_id=str(payload["session_id"]),
            lane_id=str(payload.get("lane_id") or _new_id("lane")),
            name=str(payload["name"]),
            cwd=str(payload.get("cwd") or "."),
            branch_name=payload.get("branch_name"),
        )
        events = [_event("lane.created", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }

    def claim_lane(self, lane_id: str, *, claimed_ref: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).claim_lane(
            lane_id, claimed_ref=claimed_ref
        )
        events = [_event("lane.claimed", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }

    def keep_lane(self, lane_id: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).keep_lane(lane_id)
        events = [_event("lane.released", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }

    def remove_lane(self, lane_id: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).remove_lane(lane_id)
        events = [_event("lane.removed", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }
