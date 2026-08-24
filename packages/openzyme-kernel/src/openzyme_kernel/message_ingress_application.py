from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import RetryEligibility
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowSelectionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import parse_failure_observation
from openzyme_contracts import validate_failure_diagnostic_pair
from openzyme_extension_spi import FailureRecordCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import WorkflowRegistryResolutionError
from openzyme_extension_spi import WorkflowRegistryResolverPort
from openzyme_extension_spi import validate_workflow_registry_resolver_identity

from .authority_application import evaluate_authority_payload
from .coordination_application import FailureKernelApplicationService
from .errors import KernelContractError
from .runtime_coordination_application import build_runtime_signal_payload
from .workflow_authority_application import RootWorkflowAuthorityRequest
from .workflow_authority_application import WorkflowAuthorityUnitOfWorkOwner


@dataclass(frozen=True, slots=True)
class MessageIngressCommand:
    context: KernelCommandContext
    message_id: str
    source_actor_id: str
    content: str
    distribution_id: str
    request_lineage_id: str
    task_id: str | None = None
    lane_id: str | None = None
    workflow_refs: tuple[str, ...] = ()
    skill_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.message_id,
                self.source_actor_id,
                self.distribution_id,
                self.request_lineage_id,
            )
        ):
            raise ValueError(
                "message, source, Distribution and lineage identities are required"
            )
        if not self.content or self.content != self.content.strip():
            raise ValueError(
                "message content must be non-empty without surrounding whitespace"
            )
        for field_name in ("workflow_refs", "skill_keys"):
            values = getattr(self, field_name)
            normalized = tuple(sorted(set(values)))
            if normalized != values or any(not item for item in normalized):
                raise ValueError(f"{field_name} must be sorted, unique and non-empty")
        if self.workflow_refs and self.skill_keys:
            raise ValueError("workflow_refs and compatibility skill_keys are exclusive")


class MessageIngressKernelApplicationService:
    """Atomically records user input and wakes the resident target Agent."""

    service_id = "openzyme.kernel.message-ingress"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: KernelRecordReaderPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        workflow_registry: WorkflowRegistryResolverPort,
    ) -> None:
        validate_workflow_registry_resolver_identity(workflow_registry)
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids
        self._workflow_registry = workflow_registry
        self._failures = FailureKernelApplicationService(
            store=store,
            clock=clock,
            ids=ids,
        )
        self._workflow_authority = WorkflowAuthorityUnitOfWorkOwner(
            clock=clock,
            ids=ids,
        )

    @property
    def workflow_registry(self) -> WorkflowRegistryResolverPort:
        """Return the exact resolver used by message admission for identity checks."""

        return self._workflow_registry

    def execute(self, command: MessageIngressCommand) -> KernelMutationReceipt:
        context = command.context
        selection_request = WorkflowSelectionRequest(
            request_id=command.message_id,
            distribution_id=command.distribution_id,
            requested_workflow_refs=command.workflow_refs,
            compatibility_skill_keys=command.skill_keys,
        )
        try:
            if command.distribution_id != self._workflow_registry.distribution_id:
                raise KernelContractError(
                    "workflow_registry_distribution_mismatch",
                    "Message selection names another Distribution registry",
                )
            selection = self._workflow_registry.resolve(selection_request)
            if (
                selection.request_id != selection_request.request_id
                or selection.request_digest != selection_request.request_digest
                or selection.distribution_id != self._workflow_registry.distribution_id
                or selection.registry_id != self._workflow_registry.registry_id
                or selection.registry_snapshot_digest
                != self._workflow_registry.registry_snapshot_digest
            ):
                raise KernelContractError(
                    "workflow_registry_resolution_identity_stale",
                    "Workflow resolver returned a drifted registry or request identity",
                )
        except WorkflowRegistryResolutionError as exc:
            self._raise_recorded_resolution_failure(
                command=command,
                request=selection_request,
                error=exc,
                error_code=exc.code,
                failure_class=FailureClass.VALIDATION,
                next_action="correct_workflow_selection",
            )
        except KernelContractError as exc:
            self._raise_recorded_resolution_failure(
                command=command,
                request=selection_request,
                error=exc,
                error_code=exc.code,
                failure_class=FailureClass.VALIDATION,
                next_action="refresh_workflow_registry_identity",
            )
        except Exception as exc:
            self._raise_recorded_resolution_failure(
                command=command,
                request=selection_request,
                error=exc,
                error_code="workflow_registry_resolution_failed",
                failure_class=FailureClass.SYSTEM,
                next_action="inspect_workflow_registry_diagnostic",
            )
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=canonical_sha256_digest(
                {
                    "service_id": self.service_id,
                    "context": context.to_dict(),
                    "message_id": command.message_id,
                    "source_actor_id": command.source_actor_id,
                    "content": command.content,
                    "task_id": command.task_id,
                    "lane_id": command.lane_id,
                    "workflow_selection_request": selection_request.to_dict(),
                    "resolved_workflow_selection": selection.to_dict(),
                    "skill_keys": list(command.skill_keys),
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(entity_type="session", entity_id=context.session_id)
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "Message ingress requires a canonical Session",
                )
            if session.state_version != context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before message ingress",
                )
            if (
                unit.read(
                    entity_type="conversation_message",
                    entity_id=command.message_id,
                )
                is not None
            ):
                raise KernelContractError(
                    "message_identity_conflict",
                    "Message identity already exists",
                )
            self._validate_optional_scope(
                unit,
                entity_type="task",
                entity_id=command.task_id,
                session_id=context.session_id,
            )
            self._validate_optional_scope(
                unit,
                entity_type="lane",
                entity_id=command.lane_id,
                session_id=context.session_id,
            )
            member = unit.read(entity_type="agent_member", entity_id=context.actor_id)
            if (
                member is None
                or member.payload.get("session_id") != context.session_id
                or member.payload.get("status") != "active"
            ):
                raise KernelContractError(
                    "message_target_agent_unavailable",
                    "Message target Agent is absent, retired or belongs elsewhere",
                )
            lease = unit.read(
                entity_type="agent_authority_lease",
                entity_id=context.authority_lease_id,
            )
            if lease is None:
                raise KernelContractError(
                    "authority_lease_not_found",
                    "Message ingress authority lease is absent",
                )
            decision = evaluate_authority_payload(
                payload=lease.payload,
                session_id=context.session_id,
                actor_id=context.actor_id,
                authority_lease_id=context.authority_lease_id,
                operation="conversation.message.ingress",
                scope_id=context.session_id,
                expected_generation=context.authority_generation,
                expected_fence=context.authority_fence,
                now_iso=self._clock.now_iso(),
            )
            if not decision.allowed:
                raise KernelContractError(
                    decision.denial_code or "authority_operation_denied",
                    "AgentAuthorityLease denies message ingress",
                )
            workspace_generation = member.payload.get("workspace_generation")
            process_epoch = member.payload.get("process_epoch")
            agent_id = member.payload.get("agent_id")
            if (
                not isinstance(workspace_generation, int)
                or isinstance(workspace_generation, bool)
                or workspace_generation < 1
                or context.workspace_generation != workspace_generation
                or not isinstance(process_epoch, int)
                or isinstance(process_epoch, bool)
                or process_epoch < 1
                or not isinstance(agent_id, str)
                or not agent_id
                or lease.payload.get("workspace_generation") != workspace_generation
            ):
                raise KernelContractError(
                    "message_target_runtime_binding_missing",
                    "Message target lacks an exact ready workspace/runtime binding",
                )
            now = self._clock.now_iso()
            signal_id = self._ids.new_id(namespace="runtime-signal")
            inbox_id = self._ids.new_id(namespace="inbox")
            message_payload = {
                "message_id": command.message_id,
                "session_id": context.session_id,
                "sender_actor_id": command.source_actor_id,
                "admitted_by_actor_id": context.actor_id,
                "sender_kind": "user",
                "content": command.content,
                "message_type": "user_message",
                "correlation_id": context.correlation_id,
                "task_id": command.task_id,
                "lane_id": command.lane_id,
                "request_lineage_id": command.request_lineage_id,
                "workflow_refs": list(selection.selected_workflow_refs),
                "skill_keys": list(command.skill_keys),
                "created_at": now,
            }
            inbox_payload = {
                "message_id": inbox_id,
                "session_id": context.session_id,
                "sender_actor_id": command.source_actor_id,
                "sender_kind": "user",
                "recipient_actor_id": context.actor_id,
                "protocol_ref": command.message_id,
                "message_type": "user_message",
                "correlation_id": context.correlation_id,
                "status": "unread",
                "created_at": now,
            }
            signal_payload = build_runtime_signal_payload(
                signal_id=signal_id,
                session_id=context.session_id,
                agent_id=agent_id,
                agent_member_id=context.actor_id,
                reason=AgentRuntimeSignalReason.INBOX_UNREAD,
                target_authority_lease_id=context.authority_lease_id,
                target_authority_lease_digest=str(lease.payload["lease_digest"]),
                workspace_generation=workspace_generation,
                process_epoch=process_epoch,
                correlation_id=context.correlation_id,
                source_ref=command.message_id,
                task_id=command.task_id,
                lane_id=command.lane_id,
                created_at=now,
                enqueue_command_digest=request.command_digest,
            )
            project_id = session.payload.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise KernelContractError(
                    "workflow_authority_project_missing",
                    "Session lacks the exact project identity required by workflow authority",
                )
            workflow_binding, signal_link = self._workflow_authority.create_root(
                unit,
                RootWorkflowAuthorityRequest(
                    session_id=context.session_id,
                    project_id=project_id,
                    request_lineage_id=command.request_lineage_id,
                    source_message_id=command.message_id,
                    source_principal_id=command.source_actor_id,
                    authorized_actor_id=context.actor_id,
                    task_id=command.task_id,
                    lane_id=command.lane_id,
                    selection=selection,
                    signal_id=signal_id,
                ),
            )
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            mutations = (
                ("conversation_message", command.message_id, message_payload, None),
                ("inbox_message", inbox_id, inbox_payload, None),
            )
            for entity_type, entity_id, payload, expected in mutations:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=(
                            KernelMutationKind.CREATE
                            if expected is None
                            else KernelMutationKind.REPLACE
                        ),
                        entity_type=entity_type,
                        entity_id=entity_id,
                        expected_state_version=expected,
                        payload=payload,
                    )
                )
            self._workflow_authority.stage_runtime_signal_with_link(
                unit,
                signal_mutation=KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="agent_runtime_signal",
                    entity_id=signal_id,
                    expected_state_version=None,
                    payload=signal_payload,
                ),
                link=signal_link,
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="session",
                    entity_id=context.session_id,
                    expected_state_version=session.state_version,
                    payload=session_payload,
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=context.session_id,
                event_type="conversation.user_message",
                source_entity_type="conversation_message",
                source_entity_id=command.message_id,
                source_state_version=1,
                command_id=context.command_id,
                payload={
                    "message_id": command.message_id,
                    "inbox_message_id": inbox_id,
                    "runtime_signal_id": signal_id,
                    "workflow_authority_id": workflow_binding.authority_id,
                    "workflow_authority_epoch": workflow_binding.epoch,
                    "workflow_authority_digest": workflow_binding.binding_digest,
                    "runtime_signal_authority_link_digest": signal_link.link_digest,
                    "runtime_executed": False,
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "runtime_signal_id": signal_id,
                "workflow_authority_id": workflow_binding.authority_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=context.session_id,
                    topic="openzyme.kernel.message-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=now,
                )
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        message_snapshot = KernelRecordSnapshot.create(
            entity_type="conversation_message",
            entity_id=command.message_id,
            state_version=1,
            payload=message_payload,
        )
        workflow_snapshot = KernelRecordSnapshot.create(
            entity_type="workflow_authority_binding",
            entity_id=workflow_binding.authority_id,
            state_version=1,
            payload=workflow_binding.to_dict(),
        )
        link_snapshot = KernelRecordSnapshot.create(
            entity_type="runtime_signal_authority_link",
            entity_id=signal_link.signal_id,
            state_version=1,
            payload=signal_link.to_dict(),
        )
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation="message.ingress",
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=message_snapshot.entity_type,
                    entity_id=message_snapshot.entity_id,
                    state_version=message_snapshot.state_version,
                    entity_digest=message_snapshot.record_digest,
                ),
                KernelEntityRef(
                    entity_kind=workflow_snapshot.entity_type,
                    entity_id=workflow_snapshot.entity_id,
                    state_version=workflow_snapshot.state_version,
                    entity_digest=workflow_snapshot.record_digest,
                ),
                KernelEntityRef(
                    entity_kind=link_snapshot.entity_type,
                    entity_id=link_snapshot.entity_id,
                    state_version=link_snapshot.state_version,
                    entity_digest=link_snapshot.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "message_id": command.message_id,
                "inbox_message_id": inbox_id,
                "runtime_signal_id": signal_id,
                "workflow_authority_id": workflow_binding.authority_id,
                "workflow_authority_epoch": workflow_binding.epoch,
                "workflow_authority_digest": workflow_binding.binding_digest,
                "runtime_signal_authority_link_digest": signal_link.link_digest,
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )

    def _raise_recorded_resolution_failure(
        self,
        *,
        command: MessageIngressCommand,
        request: WorkflowSelectionRequest,
        error: BaseException,
        error_code: str,
        failure_class: FailureClass,
        next_action: str,
    ) -> None:
        """Persist one diagnostic occurrence while leaving message admission empty."""

        context = command.context
        source_version = canonical_sha256_digest(
            {
                "schema_version": "workflow_resolution_occurrence@1",
                "command_id": context.command_id,
                "message_id": command.message_id,
                "request_digest": request.request_digest,
                "distribution_id": command.distribution_id,
                "registry_id": self._workflow_registry.registry_id,
                "registry_snapshot_digest": (
                    self._workflow_registry.registry_snapshot_digest
                ),
                "error_code": error_code,
            }
        )
        suffix = source_version.removeprefix("sha256:")[:24]
        failure_id = f"failure-workflow-{suffix}"
        diagnostic_id = f"diagnostic-workflow-{suffix}"
        try:
            if not self._has_exact_resolution_diagnostic(
                failure_id=failure_id,
                diagnostic_id=diagnostic_id,
                session_id=context.session_id,
                source_ref=command.message_id,
                source_version=source_version,
                error_code=error_code,
            ):
                records = observe_structured_failure(
                    error,
                    context=StructuredFailureContext(
                        failure_id=failure_id,
                        diagnostic_id=diagnostic_id,
                        session_id=context.session_id,
                        component="openzyme.kernel.message-ingress",
                        operation="resolve_workflow_selection",
                        phase="workflow_resolution",
                        source_kind="workflow_registry",
                        source_ref=command.message_id,
                        source_version=source_version,
                        created_at=self._clock.now_iso(),
                        task_id=command.task_id,
                        lane_id=command.lane_id,
                        agent_id=context.actor_id,
                        correlation_id=context.correlation_id,
                    ),
                    failure_class=failure_class,
                    recoverability=FailureRecoverability.AUTHORIZATION_REQUIRED,
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    retry_eligibility=RetryEligibility.TERMINAL,
                    actor_kind=FailureActorKind.HARNESS,
                    error_code=error_code,
                    safe_summary=(
                        "Workflow selection resolution failed before message, "
                        "authority, inbox, or runtime-signal admission."
                    ),
                    safe_hint=(
                        "Inspect the exact registry snapshot and submit a corrected "
                        "workflow selection as a new request."
                    ),
                    next_action=next_action,
                    mutation_applied=False,
                    fallback_performed=False,
                    reconcile_required=False,
                    public_facts={
                        "distribution_id": command.distribution_id,
                        "observed_manifest_digest": (
                            self._workflow_registry.registry_snapshot_digest
                        ),
                    },
                    identities={
                        "distribution_id": command.distribution_id,
                    },
                    evidence_refs=(
                        request.request_digest,
                        self._workflow_registry.registry_snapshot_digest,
                    ),
                    likely_causes=(
                        "The requested selection or exact registry identity was rejected.",
                    ),
                    private_context={
                        "selection_request": request.to_dict(),
                        "registry_id": self._workflow_registry.registry_id,
                        "registry_snapshot_digest": (
                            self._workflow_registry.registry_snapshot_digest
                        ),
                        "resolver_diagnostic_id": getattr(
                            error,
                            "diagnostic_id",
                            None,
                        ),
                    },
                )
                diagnostic_context = replace(
                    context,
                    command_id=f"workflow-diagnostic-{suffix}",
                    idempotency_key=f"workflow-diagnostic-{suffix}",
                )
                self._failures.record(
                    FailureRecordCommand(
                        context=diagnostic_context,
                        observation=records.public,
                    ),
                    private_diagnostic=records.private,
                    authorization_operation="conversation.message.ingress",
                )
        except Exception as persistence_error:
            rejected = KernelContractError(
                "workflow_resolution_diagnostic_persistence_failed",
                "Workflow resolution failed and its diagnostic could not be persisted",
                details={
                    "source_error_code": error_code,
                    "failure_id": failure_id,
                    "diagnostic_id": diagnostic_id,
                    "diagnostic_recorded": False,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
            rejected.add_note(
                f"diagnostic persistence failed with {type(persistence_error).__name__}"
            )
            raise rejected from error
        raise KernelContractError(
            error_code,
            "Workflow selection resolution failed closed before admission",
            details={
                "failure_id": failure_id,
                "diagnostic_id": diagnostic_id,
                "diagnostic_recorded": True,
                "message_admitted": False,
                "authority_created": False,
                "runtime_signal_created": False,
                "mutation_applied": False,
                "fallback_performed": False,
            },
        ) from error

    def _has_exact_resolution_diagnostic(
        self,
        *,
        failure_id: str,
        diagnostic_id: str,
        session_id: str,
        source_ref: str,
        source_version: str,
        error_code: str,
    ) -> bool:
        failure_record = self._reader.read(
            entity_type="failure_observation",
            entity_id=failure_id,
        )
        private_record = self._reader.read(
            entity_type="private_diagnostic",
            entity_id=diagnostic_id,
        )
        if failure_record is None and private_record is None:
            return False
        try:
            if failure_record is None or private_record is None:
                raise ValueError("workflow diagnostic pair is incomplete")
            observation = parse_failure_observation(failure_record.payload)
            diagnostic = PrivateDiagnosticRecord.from_dict(private_record.payload)
            if not isinstance(observation, FailureObservation):
                raise ValueError("workflow diagnostic uses a legacy public record")
            validate_failure_diagnostic_pair(observation, diagnostic)
            if (
                observation.failure_id != failure_id
                or observation.diagnostic_id != diagnostic_id
                or observation.session_id != session_id
                or observation.source_kind != "workflow_registry"
                or observation.source_ref != source_ref
                or observation.source_version != source_version
                or observation.error_code != error_code
                or observation.component != "openzyme.kernel.message-ingress"
                or observation.operation != "resolve_workflow_selection"
                or observation.mutation_applied is not False
                or observation.fallback_performed is not False
            ):
                raise ValueError("workflow diagnostic occurrence identity drifted")
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workflow_resolution_diagnostic_collision",
                "Workflow resolution diagnostic identity already names another pair",
                details={
                    "failure_id": failure_id,
                    "diagnostic_id": diagnostic_id,
                    "diagnostic_recorded": False,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            ) from exc
        return True

    @staticmethod
    def _validate_optional_scope(
        unit,  # noqa: ANN001 - UnitOfWorkPort is intentionally structural
        *,
        entity_type: str,
        entity_id: str | None,
        session_id: str,
    ) -> None:
        if entity_id is None:
            return
        record = unit.read(entity_type=entity_type, entity_id=entity_id)
        if record is None or record.payload.get("session_id") != session_id:
            raise KernelContractError(
                f"message_{entity_type}_scope_invalid",
                f"Message {entity_type} is absent or belongs to another Session",
            )


__all__ = ["MessageIngressCommand", "MessageIngressKernelApplicationService"]
