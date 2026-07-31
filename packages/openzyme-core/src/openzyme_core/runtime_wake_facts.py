from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import RetryEligibility
from openzyme_domain import SandboxRunStatus
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptClosure
from openzyme_domain import ScientificAttemptLifecyclePhase
from openzyme_domain import Task

from .mutation_authority import canonical_digest
from .repositories import CoreRepositories
from .scientific_attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .scientific_attempt_lifecycle import ScientificAttemptLifecycleResolver


class CanonicalWakeFactsReason(StrEnum):
    SIGNAL_NOT_CLAIMED = "signal_not_claimed"
    SOURCE_RECORD_MISSING = "source_record_missing"
    REQUEST_MISSING = "request_missing"
    CONTROL_BINDING_INVALID = "control_binding_invalid"
    LIFECYCLE_INVALID = "lifecycle_invalid"
    TASK_MISSING = "task_missing"
    PROJECTION_BOUND_EXCEEDED = "projection_bound_exceeded"


class CanonicalWakeFactsError(RuntimeError):
    error_code = "canonical_wake_facts_invalid"
    retryable = False

    def __init__(self, reason: CanonicalWakeFactsReason) -> None:
        super().__init__("canonical runtime wake facts are inconsistent")
        self.reason = reason
        self.details: dict[str, Any] = {
            "boundary": "canonical_wake_facts",
            "disposition": "fail_closed",
            "settlement_reason": reason.value,
            "mutation_applied": False,
        }


@dataclass(frozen=True, slots=True)
class CanonicalWakeFacts:
    MAX_FACTS_JSON_CHARS = 3_200
    MAX_TASK_CONTEXT_CHARS = 512

    source_kind: str
    task: Task
    facts: dict[str, Any]

    def __post_init__(self) -> None:
        if len(self._facts_json()) > self.MAX_FACTS_JSON_CHARS:
            raise CanonicalWakeFactsError(
                CanonicalWakeFactsReason.PROJECTION_BOUND_EXCEEDED
            )

    def _facts_json(self) -> str:
        return json.dumps(
            self.facts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def render_instructions(self) -> str:
        lines = [
            "Canonical wake facts: " + self._facts_json(),
        ]
        if self.source_kind == "scientific_attempt_admitted":
            lines.append(
                "The Host already finalized this attempt admission. Do not call "
                "attempt.create again for this transition; continue from the exact "
                "attempt and lifecycle facts above."
            )
        elif self.source_kind == "scientific_attempt_closed":
            lines.append(
                "The Host already finalized this attempt closure. The immutable "
                "closure does not finish the business task; decide the task outcome "
                "explicitly from current evidence."
            )
        else:
            lines.append(
                "This is typed causal failure evidence. Do not automatically replay "
                "an effect. Choose a repair, replan, reconciliation, authorization "
                "request, or explicit task outcome from the stated recoverability, "
                "effect certainty, and retry eligibility."
            )
        task_context = str(self.task.description or self.task.subject)
        if len(task_context) > self.MAX_TASK_CONTEXT_CHARS:
            task_context = task_context[: self.MAX_TASK_CONTEXT_CHARS] + "…"
        lines.append(f"Task {self.task.task_id}: {task_context}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class CanonicalWakeFactsProjector:
    repositories: CoreRepositories

    def project(
        self,
        signal: AgentRuntimeSignal,
    ) -> CanonicalWakeFacts | None:
        if signal.reason is AgentRuntimeSignalReason.ENGINE_COMPLETED:
            return self._sandbox_run_failure_facts(signal)
        if signal.reason is not AgentRuntimeSignalReason.MANUAL_RESUME:
            return None
        source_ref = str(signal.source_ref or "").strip()
        if not source_ref:
            return None

        closure = self.repositories.scientific_attempt_closures.get(source_ref)
        if closure is not None:
            return self._closure_facts(signal, closure)

        attempt = self.repositories.scientific_attempts.get(source_ref)
        if attempt is not None:
            return self._attempt_facts(signal, attempt)

        failure = self.repositories.failure_observations.get(source_ref)
        if failure is not None:
            return self._failure_facts(signal, failure)

        if self._has_orphan_transition_event(signal.session_id, source_ref):
            self._invalid(CanonicalWakeFactsReason.SOURCE_RECORD_MISSING)
        return None

    def _sandbox_run_failure_facts(
        self,
        signal: AgentRuntimeSignal,
    ) -> CanonicalWakeFacts | None:
        source_ref = str(signal.source_ref or "").strip()
        if not source_ref:
            return None
        continuation = self.repositories.continuation_states.get(source_ref)
        if continuation is None:
            return None
        wrappers = self.repositories.failure_observations.list_by_source(
            session_id=signal.session_id,
            source_kind="sandbox_run",
            source_ref=continuation.sandbox_run_id,
        )
        if not wrappers:
            return None
        self._require_claimed(signal)
        if len(wrappers) != 1:
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        wrapper = wrappers[0]
        run = self.repositories.sandbox_runs.get(continuation.sandbox_run_id)
        if run is None:
            self._invalid(CanonicalWakeFactsReason.SOURCE_RECORD_MISSING)
        assert run is not None
        wrapper_facts = dict(wrapper.facts)
        cause_id = str(wrapper_facts.get("causal_failure_id") or "")
        if not cause_id:
            if wrapper_facts.get("local_cause_count") in {None, 0}:
                # A generic terminal sandbox wrapper is not a local validation
                # projection.  Preserve the existing continuation failure path
                # for controlled-operation outcomes on the same run.
                return None
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        cause = (
            None
            if not cause_id
            else self.repositories.failure_observations.get(cause_id)
        )
        local_causes = self.repositories.failure_observations.list_by_source(
            session_id=signal.session_id,
            source_kind="sandbox_control_request",
            source_ref=run.sandbox_run_id,
        )
        if (
            cause is None
            or len(local_causes) != 1
            or local_causes[0] != cause
        ):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        assert cause is not None
        cause_facts = dict(cause.facts)
        owner_wakes = wrapper_facts.get("owner_wake_continuation_ids")
        if not isinstance(owner_wakes, list):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        if (
            signal.source_ref != continuation.continuation_id
            or run.task_id is None
            or continuation.originating_agent_id is None
            or continuation.originating_task_id is None
            or signal.correlation_id != continuation.continuation_id
            or signal.session_id != continuation.session_id
            or signal.agent_id != continuation.originating_agent_id
            or signal.task_id != continuation.originating_task_id
            or signal.lane_id != continuation.originating_lane_id
            or continuation.status is not ContinuationStateStatus.COMPLETED
            or continuation.sandbox_run_id != run.sandbox_run_id
            or continuation.session_id != run.session_id
            or continuation.sandbox_workspace_id != run.sandbox_workspace_id
            or continuation.originating_agent_id != run.agent_id
            or continuation.originating_task_id != run.task_id
            or continuation.originating_lane_id != run.lane_id
            or continuation.continuation_id not in owner_wakes
            or run.status is not SandboxRunStatus.FAILED
            or run.error_code != "sandbox_exec_nonzero"
            or wrapper.source_kind != "sandbox_run"
            or wrapper.source_ref != run.sandbox_run_id
            or wrapper.task_id != run.task_id
            or wrapper.lane_id != run.lane_id
            or wrapper.agent_id != run.agent_id
            or wrapper.failure_class is not FailureClass.RUNTIME
            or wrapper.recoverability
            is not FailureRecoverability.AGENT_CAN_REPLAN
            or wrapper.effect_certainty
            is not ExternalEffectCertainty.TERMINAL_KNOWN
            or wrapper.retry_eligibility is not RetryEligibility.TERMINAL
            or wrapper.error_code != run.error_code
            or wrapper_facts.get("schema_version") != "sandbox_run_failure@1"
            or wrapper_facts.get("sandbox_run_id") != run.sandbox_run_id
            or wrapper_facts.get("sandbox_workspace_id")
            != run.sandbox_workspace_id
            or wrapper_facts.get("source_snapshot_artifact_id")
            != run.source_snapshot_artifact_id
            or wrapper_facts.get("source_tree_digest")
            != run.source_tree_digest
            or wrapper_facts.get("local_cause_count") != 1
            or wrapper_facts.get("causal_error_code")
            != "hpc_stage_ref_required"
            or wrapper_facts.get("causal_source_version")
            != cause.source_version
            or cause.source_kind != "sandbox_control_request"
            or cause.source_ref != run.sandbox_run_id
            or cause.task_id != run.task_id
            or cause.lane_id != run.lane_id
            or cause.agent_id != run.agent_id
            or cause.failure_class is not FailureClass.VALIDATION
            or cause.recoverability
            is not FailureRecoverability.AGENT_CAN_REPLAN
            or cause.effect_certainty is not ExternalEffectCertainty.NO_EFFECT
            or cause.retry_eligibility is not RetryEligibility.SAME_PHASE_SAFE
            or cause.error_code != "hpc_stage_ref_required"
            or cause_facts.get("schema_version")
            != "sandbox_control_failure@1"
            or cause_facts.get("sandbox_run_id") != run.sandbox_run_id
            or cause_facts.get("sandbox_workspace_id")
            != run.sandbox_workspace_id
            or cause_facts.get("source_snapshot_artifact_id")
            != run.source_snapshot_artifact_id
            or cause_facts.get("source_tree_digest")
            != run.source_tree_digest
            or cause_facts.get("operation_admitted") is not False
            or cause_facts.get("external_dispatch_started") is not False
        ):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        task = self._task(
            signal,
            session_id=run.session_id,
            task_id=run.task_id,
            lane_id=run.lane_id,
            actor_ref=run.agent_id,
        )
        return CanonicalWakeFacts(
            source_kind="sandbox_run_failure",
            task=task,
            facts={
                "schema_version": "canonical_wake_facts@1",
                "source_kind": "sandbox_run_failure",
                "session_id": run.session_id,
                "task_id": run.task_id,
                "lane_id": run.lane_id,
                "agent_id": run.agent_id,
                "continuation_id": continuation.continuation_id,
                "operation_id": continuation.operation_id,
                "sandbox_run_id": run.sandbox_run_id,
                "sandbox_workspace_id": run.sandbox_workspace_id,
                "attempt_id": wrapper_facts.get("attempt_id"),
                "source_snapshot_artifact_id": (
                    run.source_snapshot_artifact_id
                ),
                "source_tree_digest": run.source_tree_digest,
                "wrapper_failure_id": wrapper.failure_id,
                "wrapper_error_code": wrapper.error_code,
                "wrapper_recoverability": wrapper.recoverability.value,
                "wrapper_effect_certainty": wrapper.effect_certainty.value,
                "wrapper_retry_eligibility": (
                    wrapper.retry_eligibility.value
                ),
                "causal_failure_id": cause.failure_id,
                "error_code": cause.error_code,
                "failure_class": cause.failure_class.value,
                "recoverability": cause.recoverability.value,
                "effect_certainty": cause.effect_certainty.value,
                "retry_eligibility": cause.retry_eligibility.value,
                "operation_admitted": False,
                "external_dispatch_started": False,
                "created_at": wrapper.created_at,
            },
        )

    def _attempt_facts(
        self,
        signal: AgentRuntimeSignal,
        attempt: ScientificAttempt,
    ) -> CanonicalWakeFacts:
        self._require_claimed(signal)
        request = self.repositories.scientific_attempt_admission_requests.get(
            attempt.admission_request_id
        )
        if request is None:
            self._invalid(CanonicalWakeFactsReason.REQUEST_MISSING)
        assert request is not None
        if (
            signal.source_ref != attempt.attempt_id
            or signal.correlation_id != attempt.attempt_id
            or signal.session_id != attempt.session_id
            or signal.task_id != attempt.task_id
            or signal.lane_id != attempt.lane_id
            or signal.agent_id != request.actor_ref
            or attempt.admission_request_id != request.admission_request_id
            or attempt.envelope_id != request.envelope_id
            or attempt.session_id != request.session_id
            or attempt.task_id != request.task_id
            or attempt.lane_id != request.lane_id
            or attempt.campaign_id != request.campaign_id
            or attempt.workflow_id != request.workflow_id
            or attempt.scope is not request.scope
            or attempt.workflow_contract_digest
            != request.workflow_contract_digest
            or attempt.requested_effect_classes
            != request.requested_effect_classes
            or attempt.provider != request.provider
            or attempt.hpc_target != request.hpc_target
            or attempt.reserved_micu != request.reserved_micu
            or attempt.reserved_cost_microunits
            != request.reserved_cost_microunits
            or attempt.reserved_wall_time_seconds
            != request.reserved_wall_time_seconds
            or attempt.created_by != request.actor_ref
            or attempt.idempotency_key != request.idempotency_key
            or attempt.request_digest != request.request_digest
        ):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        lifecycle = self._lifecycle(attempt)
        task = self._task(
            signal,
            session_id=attempt.session_id,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            actor_ref=request.actor_ref,
        )
        return CanonicalWakeFacts(
            source_kind="scientific_attempt_admitted",
            task=task,
            facts={
                "schema_version": "canonical_wake_facts@1",
                "source_kind": "scientific_attempt_admitted",
                "attempt_id": attempt.attempt_id,
                "admission_request_id": request.admission_request_id,
                "envelope_id": attempt.envelope_id,
                "session_id": attempt.session_id,
                "task_id": attempt.task_id,
                "lane_id": attempt.lane_id,
                "campaign_id": attempt.campaign_id,
                "workflow_id": attempt.workflow_id,
                "scope": attempt.scope.value,
                "ordinal": attempt.ordinal,
                "record_status": attempt.status.value,
                "lifecycle_phase": lifecycle.phase.value,
                "workflow_contract_digest": attempt.workflow_contract_digest,
                "requested_effect_classes": list(
                    attempt.requested_effect_classes
                ),
                "provider": attempt.provider,
                "hpc_target": attempt.hpc_target,
                "reserved_micu": attempt.reserved_micu,
                "reserved_cost_microunits": (
                    attempt.reserved_cost_microunits
                ),
                "reserved_wall_time_seconds": (
                    attempt.reserved_wall_time_seconds
                ),
                "request_digest": attempt.request_digest,
                "actor_ref": request.actor_ref,
                "created_at": attempt.created_at,
            },
        )

    def _closure_facts(
        self,
        signal: AgentRuntimeSignal,
        closure: ScientificAttemptClosure,
    ) -> CanonicalWakeFacts:
        self._require_claimed(signal)
        attempt = self.repositories.scientific_attempts.get(closure.attempt_id)
        if attempt is None:
            self._invalid(CanonicalWakeFactsReason.SOURCE_RECORD_MISSING)
        request = self.repositories.scientific_attempt_closure_requests.get(
            closure.closure_request_id
        )
        if request is None:
            self._invalid(CanonicalWakeFactsReason.REQUEST_MISSING)
        assert attempt is not None and request is not None
        if (
            signal.source_ref != closure.closure_id
            or signal.correlation_id != closure.closure_id
            or signal.session_id != attempt.session_id
            or signal.task_id != attempt.task_id
            or signal.lane_id != attempt.lane_id
            or signal.agent_id != request.actor_ref
            or closure.actor_ref != request.actor_ref
            or closure.attempt_id != request.attempt_id
            or closure.selection_id != request.selection_id
            or closure.closure_request_id != request.closure_request_id
            or closure.idempotency_key != request.idempotency_key
        ):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        lifecycle = self._lifecycle(attempt)
        if (
            lifecycle.phase is not ScientificAttemptLifecyclePhase.CLOSED
            or lifecycle.closure != closure
            or lifecycle.closure_request != request
        ):
            self._invalid(CanonicalWakeFactsReason.LIFECYCLE_INVALID)
        task = self._task(
            signal,
            session_id=attempt.session_id,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            actor_ref=request.actor_ref,
        )
        return CanonicalWakeFacts(
            source_kind="scientific_attempt_closed",
            task=task,
            facts={
                "schema_version": "canonical_wake_facts@1",
                "source_kind": "scientific_attempt_closed",
                "closure_id": closure.closure_id,
                "closure_request_id": request.closure_request_id,
                "attempt_id": attempt.attempt_id,
                "selection_id": closure.selection_id,
                "session_id": attempt.session_id,
                "task_id": attempt.task_id,
                "lane_id": attempt.lane_id,
                "campaign_id": attempt.campaign_id,
                "workflow_id": attempt.workflow_id,
                "lifecycle_phase": lifecycle.phase.value,
                "closure_digest": closure.closure_digest,
                "operation_universe_digest": (
                    closure.operation_universe_digest
                ),
                "disposition_digest": closure.disposition_digest,
                "adoption_digest": closure.adoption_digest,
                "materialization_digest": closure.materialization_digest,
                "authority_consumption_digest": (
                    closure.authority_consumption_digest
                ),
                "quiescence_receipt_id": closure.quiescence_receipt_id,
                "quiescence_receipt_digest": (
                    closure.quiescence_receipt_digest
                ),
                "actor_ref": request.actor_ref,
                "created_at": closure.created_at,
            },
        )

    def _failure_facts(
        self,
        signal: AgentRuntimeSignal,
        failure: FailureObservation,
    ) -> CanonicalWakeFacts:
        self._require_claimed(signal)
        if (
            signal.source_ref != failure.failure_id
            or signal.correlation_id != failure.failure_id
            or signal.session_id != failure.session_id
            or signal.task_id != failure.task_id
            or signal.lane_id != failure.lane_id
            or signal.agent_id != failure.agent_id
            or failure.task_id is None
            or failure.agent_id is None
        ):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        task = self._task(
            signal,
            session_id=failure.session_id,
            task_id=failure.task_id,
            lane_id=failure.lane_id,
            actor_ref=failure.agent_id,
        )
        return CanonicalWakeFacts(
            source_kind="failure_observation",
            task=task,
            facts=_bounded_failure_wake_facts(failure),
        )

    def _task(
        self,
        signal: AgentRuntimeSignal,
        *,
        session_id: str,
        task_id: str,
        lane_id: str | None,
        actor_ref: str,
    ) -> Task:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            self._invalid(CanonicalWakeFactsReason.TASK_MISSING)
        assert task is not None
        if (
            task.session_id != session_id
            or task.task_id != signal.task_id
            or task.lane_id != lane_id
            or task.assigned_ref != actor_ref
        ):
            self._invalid(CanonicalWakeFactsReason.CONTROL_BINDING_INVALID)
        return task

    def _lifecycle(self, attempt: ScientificAttempt):
        try:
            return ScientificAttemptLifecycleResolver(self.repositories).resolve(
                attempt
            )
        except ScientificAttemptLifecycleIntegrityError as exc:
            raise CanonicalWakeFactsError(
                CanonicalWakeFactsReason.LIFECYCLE_INVALID
            ) from exc

    def _has_orphan_transition_event(
        self,
        session_id: str,
        source_ref: str,
    ) -> bool:
        for event_type in (
            "scientific.attempt.admitted",
            "scientific.attempt.closed",
        ):
            if self.repositories.durable_events.list_scientific_transition_events(
                session_id=session_id,
                event_type=event_type,
                record_id=source_ref,
            ):
                return True
        return any(
            event.event_type == "scientific.transition.failed"
            and event.payload.get("failure_id") == source_ref
            for event in self.repositories.durable_events.list_by_session(
                session_id,
                visibilities=("public", "audit", "internal"),
            )
        )

    @staticmethod
    def _require_claimed(signal: AgentRuntimeSignal) -> None:
        if signal.status is not AgentRuntimeSignalStatus.CLAIMED:
            raise CanonicalWakeFactsError(
                CanonicalWakeFactsReason.SIGNAL_NOT_CLAIMED
            )

    @staticmethod
    def _invalid(reason: CanonicalWakeFactsReason) -> None:
        raise CanonicalWakeFactsError(reason)


def _bounded_failure_wake_facts(
    failure: FailureObservation,
) -> dict[str, Any]:
    evidence_refs = [str(item) for item in failure.evidence_refs]
    projected_refs: list[str] = []
    projected_ref_chars = 0
    for evidence_ref in evidence_refs:
        if len(projected_refs) >= 8:
            break
        if len(evidence_ref) > 256:
            break
        next_chars = projected_ref_chars + len(evidence_ref)
        if next_chars > 768:
            break
        projected_refs.append(evidence_ref)
        projected_ref_chars = next_chars

    safe_summary = str(failure.safe_summary)
    if len(safe_summary) > 256:
        safe_summary = safe_summary[:256] + "…"
    safe_hint = None if failure.safe_hint is None else str(failure.safe_hint)
    if safe_hint is not None and len(safe_hint) > 256:
        safe_hint = safe_hint[:256] + "…"

    return {
        "schema_version": "canonical_wake_facts@1",
        "source_kind": "failure_observation",
        "failure_id": failure.failure_id,
        "session_id": failure.session_id,
        "task_id": failure.task_id,
        "lane_id": failure.lane_id,
        "agent_id": failure.agent_id,
        "failure_source_kind": failure.source_kind,
        "source_ref": failure.source_ref,
        "source_version": failure.source_version,
        "phase": failure.phase,
        "failure_class": failure.failure_class.value,
        "recoverability": failure.recoverability.value,
        "effect_certainty": failure.effect_certainty.value,
        "retry_eligibility": failure.retry_eligibility.value,
        "actor_kind": failure.actor_kind.value,
        "error_code": failure.error_code,
        "safe_summary": safe_summary,
        "safe_hint": safe_hint,
        "evidence_refs": projected_refs,
        "evidence_ref_count": len(evidence_refs),
        "evidence_refs_digest": canonical_digest(evidence_refs),
        "evidence_refs_truncated": projected_refs != evidence_refs,
        "facts_key_count": len(failure.facts),
        "facts_digest": canonical_digest(failure.facts),
        "created_at": failure.created_at,
    }


__all__ = [
    "CanonicalWakeFacts",
    "CanonicalWakeFactsError",
    "CanonicalWakeFactsProjector",
    "CanonicalWakeFactsReason",
]
