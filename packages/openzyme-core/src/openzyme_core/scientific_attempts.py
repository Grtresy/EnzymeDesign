from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriterKind
from openzyme_domain import ScientificArtifactMaterialization
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptAdmissionRequest
from openzyme_domain import ScientificAttemptAuthorization
from openzyme_domain import ScientificAttemptAuthorityStatus
from openzyme_domain import ScientificAttemptClosure
from openzyme_domain import ScientificAttemptClosureRequest
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificChainSelection
from openzyme_domain import ScientificEffectAdoption
from openzyme_domain import ScientificOperationDisposition
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import ScientificSelectionState

from .mutation_authority import canonical_digest
from .mutation_authority import current_mutation_write_authority
from .mutation_quiescence import build_quiescence_evidence_envelope
from .mutation_quiescence import MutationScopeService
from .mutation_quiescence import verify_quiescence_evidence
from .artifact_boundary import ArtifactBoundaryError
from .repositories import CoreRepositories
from .reliability_repositories import ImmutableIdentityConflictError
from .scientific_attempt_repositories import (
    ScientificAttemptIdentityConflictError,
)
from .scientific_attempt_repositories import ResolvedScientificSelectionHead
from .scientific_attempt_repositories import ScientificOccurrenceSnapshot
from .scientific_attempt_repositories import ScientificSelectionIntegrityError
from .scientific_attempt_lifecycle import ResolvedScientificAttemptLifecycle
from .scientific_attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .scientific_attempt_lifecycle import ScientificAttemptLifecycleResolver
from .scientific_attempt_rollover import scientific_attempt_post_scope_id
from .scientific_attempt_rollover import scientific_attempt_post_scope_ref
from .scientific_selection_evaluation import ScientificSelectionEvaluation
from .scientific_selection_evaluation import ScientificSelectionEvaluator
from .scientific_workflow_contracts import (
    SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC,
)
from .scientific_workflow_contracts import HistoricalScientificWorkflowContract
from .scientific_workflow_contracts import ScientificWorkflowContract
from .scientific_workflow_contracts import ScientificWorkflowContractError
from .scientific_workflow_contracts import ScientificWorkflowContractRegistry


SCIENTIFIC_ATTEMPT_AUTHORIZATION_POLICY_ID = "scientific_attempt_authorization_policy@1"
EMPTY_DISPOSITION_DIGEST = canonical_digest([])
EMPTY_ADOPTION_DIGEST = canonical_digest([])
SCIENTIFIC_SELECTION_INSPECTION_MAX_LIMIT = 50
SCIENTIFIC_SELECTION_INSPECTION_DEFAULT_LIMIT = 20


class ScientificAttemptError(RuntimeError):
    retryable = False

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.hint = hint
        self.details = {
            "boundary": "scientific_attempt_control_plane",
            "disposition": "fail_closed",
            **({} if details is None else details),
        }
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ScientificOperationUniverse:
    attempt_id: str
    run_ids: tuple[str, ...]
    occurrences: tuple[dict[str, Any], ...]
    universe_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "run_ids": list(self.run_ids),
            "operation_count": len(self.occurrences),
            "operation_universe_digest": self.universe_digest,
            "occurrences": [dict(item) for item in self.occurrences],
        }


@dataclass(frozen=True, slots=True)
class ScientificOperationAdoptionResult:
    disposition: ScientificOperationDisposition
    adoption: ScientificEffectAdoption

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "scientific_operation_adoption_result@1",
            "attempt_id": self.disposition.attempt_id,
            "selection_id": self.disposition.selection_id,
            "operation_id": self.disposition.operation_id,
            "workflow_role": self.adoption.workflow_role,
            "reason_code": self.disposition.reason_code,
            "disposition_id": self.disposition.disposition_id,
            "adoption_id": self.adoption.adoption_id,
            "request_digest": self.disposition.request_digest,
            "created_at": self.disposition.created_at,
        }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScientificAttemptError(
            "authorization_timestamp_invalid",
            f"{field_name} is not a valid ISO-8601 timestamp",
        ) from exc
    if parsed.tzinfo is None:
        raise ScientificAttemptError(
            "authorization_timestamp_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed.astimezone(UTC)


def _normalized_unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(
        sorted({str(value).strip() for value in values if str(value).strip()})
    )
    return normalized


def _stable_id(prefix: str, request_digest: str) -> str:
    suffix = request_digest.removeprefix("sha256:")[:24]
    return f"{prefix}_{suffix}"


def scientific_attempt_authorization_request(
    *,
    session_id: str,
    task_id: str,
    campaign_id: str,
    workflow_id: str,
    root_ref: str,
    grantor_kind: str,
    grantor_ref: str,
    allowed_scopes: tuple[ScientificAttemptScope | str, ...],
    allowed_effect_classes: tuple[str, ...],
    allowed_providers: tuple[str, ...] = (),
    allowed_hpc_targets: tuple[str, ...] = (),
    max_attempts: int,
    max_micu: int,
    max_cost_microunits: int,
    max_wall_time_seconds: int,
    expires_at: str,
    idempotency_key: str,
    policy_digest: str | None = None,
) -> dict[str, Any]:
    """Return the canonical grant preimage used by Host and operator plans."""

    normalized_scopes = tuple(
        item
        if isinstance(item, ScientificAttemptScope)
        else ScientificAttemptScope(item)
        for item in allowed_scopes
    )
    effective_policy_digest = policy_digest or canonical_digest(
        {"policy_id": SCIENTIFIC_ATTEMPT_AUTHORIZATION_POLICY_ID}
    )
    return {
        "command": "scientific.attempt.authorization.grant",
        "session_id": session_id,
        "task_id": task_id,
        "campaign_id": campaign_id,
        "workflow_id": workflow_id,
        "root_ref": root_ref,
        "grantor_kind": grantor_kind,
        "grantor_ref": grantor_ref,
        "allowed_scopes": sorted(scope.value for scope in normalized_scopes),
        "allowed_effect_classes": list(_normalized_unique(allowed_effect_classes)),
        "allowed_providers": list(_normalized_unique(allowed_providers)),
        "allowed_hpc_targets": list(_normalized_unique(allowed_hpc_targets)),
        "max_attempts": max_attempts,
        "max_micu": max_micu,
        "max_cost_microunits": max_cost_microunits,
        "max_wall_time_seconds": max_wall_time_seconds,
        "expires_at": expires_at,
        "policy_digest": effective_policy_digest,
        "idempotency_key": idempotency_key,
    }


def scientific_attempt_authorization_identity(
    **arguments: Any,
) -> tuple[str, str, dict[str, Any]]:
    """Return stable envelope id, request digest, and canonical grant preimage."""

    request = scientific_attempt_authorization_request(**arguments)
    request_digest = canonical_digest(request)
    return (
        _stable_id("attempt_authority", request_digest),
        request_digest,
        request,
    )


@dataclass(slots=True)
class ScientificAttemptService:
    repositories: CoreRepositories
    now: Callable[[], str] = _utc_now_iso
    id_factory: Callable[[], str] = lambda: uuid4().hex
    workflow_contract_registry: ScientificWorkflowContractRegistry | None = None
    artifact_boundary: Any | None = None

    @property
    def mutation_scopes(self) -> MutationScopeService:
        return MutationScopeService(
            self.repositories,
            now=self.now,
            id_factory=self.id_factory,
        )

    @property
    def attempt_lifecycles(self) -> ScientificAttemptLifecycleResolver:
        return ScientificAttemptLifecycleResolver(self.repositories)

    def grant_authorization(
        self,
        *,
        session_id: str,
        task_id: str,
        campaign_id: str,
        workflow_id: str,
        root_ref: str,
        grantor_kind: str,
        grantor_ref: str,
        allowed_scopes: tuple[ScientificAttemptScope | str, ...],
        allowed_effect_classes: tuple[str, ...],
        allowed_providers: tuple[str, ...] = (),
        allowed_hpc_targets: tuple[str, ...] = (),
        max_attempts: int,
        max_micu: int,
        max_cost_microunits: int,
        max_wall_time_seconds: int,
        expires_at: str,
        idempotency_key: str,
        policy_digest: str | None = None,
    ) -> ScientificAttemptAuthorization:
        actor = self._require_actor(grantor_ref)
        resource_values = (
            max_attempts,
            max_micu,
            max_cost_microunits,
            max_wall_time_seconds,
        )
        if (
            type(max_attempts) is not int
            or max_attempts < 1
            or any(type(value) is not int or value < 0 for value in resource_values[1:])
        ):
            raise ScientificAttemptError(
                "authorization_resource_invalid",
                "attempt authorization resources must be exact non-negative integers with a positive attempt count",
            )
        normalized_scopes = tuple(
            item
            if isinstance(item, ScientificAttemptScope)
            else ScientificAttemptScope(item)
            for item in allowed_scopes
        )
        normalized_effects = _normalized_unique(allowed_effect_classes)
        normalized_providers = _normalized_unique(allowed_providers)
        normalized_targets = _normalized_unique(allowed_hpc_targets)
        envelope_id, request_digest, request = (
            scientific_attempt_authorization_identity(
                session_id=session_id,
                task_id=task_id,
                campaign_id=campaign_id,
                workflow_id=workflow_id,
                root_ref=root_ref,
                grantor_kind=grantor_kind,
                grantor_ref=actor,
                allowed_scopes=normalized_scopes,
                allowed_effect_classes=normalized_effects,
                allowed_providers=normalized_providers,
                allowed_hpc_targets=normalized_targets,
                max_attempts=max_attempts,
                max_micu=max_micu,
                max_cost_microunits=max_cost_microunits,
                max_wall_time_seconds=max_wall_time_seconds,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                policy_digest=policy_digest,
            )
        )
        effective_policy_digest = str(request["policy_digest"])
        existing = (
            self.repositories.scientific_attempt_authorizations.get_by_idempotency(
                session_id=session_id,
                grantor_ref=actor,
                idempotency_key=idempotency_key,
            )
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        now = self.now()
        if _parse_timestamp(expires_at, field_name="expires_at") <= _parse_timestamp(
            now, field_name="now"
        ):
            raise ScientificAttemptError(
                "authorization_expired",
                "attempt authorization expiry must be in the future",
                details={"expires_at": expires_at},
            )
        task = self.repositories.tasks.get(task_id)
        if task is None or task.session_id != session_id:
            raise ScientificAttemptError(
                "authorization_task_scope_invalid",
                "attempt authorization task does not belong to the session",
            )
        record = ScientificAttemptAuthorization(
            envelope_id=envelope_id,
            session_id=session_id,
            task_id=task_id,
            campaign_id=self._require_text("campaign_id", campaign_id),
            workflow_id=self._require_text("workflow_id", workflow_id),
            root_ref=self._require_text("root_ref", root_ref),
            grantor_kind=self._require_text("grantor_kind", grantor_kind),
            grantor_ref=actor,
            allowed_scopes=normalized_scopes,
            allowed_effect_classes=normalized_effects,
            allowed_providers=normalized_providers,
            allowed_hpc_targets=normalized_targets,
            max_attempts=max_attempts,
            max_micu=max_micu,
            max_cost_microunits=max_cost_microunits,
            max_wall_time_seconds=max_wall_time_seconds,
            consumed_attempts=0,
            reserved_micu=0,
            reserved_cost_microunits=0,
            reserved_wall_time_seconds=0,
            expires_at=expires_at,
            policy_digest=effective_policy_digest,
            idempotency_key=self._require_text("idempotency_key", idempotency_key),
            request_digest=request_digest,
            status=ScientificAttemptAuthorityStatus.ACTIVE,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        with self.mutation_scopes.writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"authorization:{record.envelope_id}",
        ):
            return self.repositories.scientific_attempt_authorizations.add(record)

    def create_attempt(
        self,
        *,
        envelope_id: str,
        session_id: str,
        task_id: str,
        lane_id: str,
        campaign_id: str,
        workflow_id: str,
        scope: ScientificAttemptScope | str,
        workflow_contract_digest: str,
        requested_effect_classes: tuple[str, ...],
        reserved_micu: int,
        reserved_cost_microunits: int,
        reserved_wall_time_seconds: int,
        actor_ref: str,
        idempotency_key: str,
        provider: str | None = None,
        hpc_target: str | None = None,
    ) -> ScientificAttempt:
        """Compatibility Host entrypoint for callers outside a mutation writer.

        Agent tools use ``request_attempt_admission``.  A Host caller with no
        active writer may use this convenience method, which persists the same
        immutable request and immediately runs the post-writer finalizer.
        """

        if current_mutation_write_authority() is not None:
            raise ScientificAttemptError(
                "attempt_admission_writer_still_active",
                "attempt admission must be finalized after the requesting writer retires",
                hint="Record an attempt admission request and let the Host finalize it.",
                retryable=True,
            )
        request = self.request_attempt_admission(
            envelope_id=envelope_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=lane_id,
            campaign_id=campaign_id,
            workflow_id=workflow_id,
            scope=scope,
            workflow_contract_digest=workflow_contract_digest,
            requested_effect_classes=requested_effect_classes,
            reserved_micu=reserved_micu,
            reserved_cost_microunits=reserved_cost_microunits,
            reserved_wall_time_seconds=reserved_wall_time_seconds,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
            provider=provider,
            hpc_target=hpc_target,
        )
        return self.finalize_attempt_admission(
            admission_request_id=request.admission_request_id
        )

    def request_attempt_admission(
        self,
        *,
        envelope_id: str,
        session_id: str,
        task_id: str,
        lane_id: str,
        campaign_id: str,
        workflow_id: str,
        scope: ScientificAttemptScope | str,
        workflow_contract_digest: str,
        requested_effect_classes: tuple[str, ...],
        reserved_micu: int,
        reserved_cost_microunits: int,
        reserved_wall_time_seconds: int,
        actor_ref: str,
        idempotency_key: str,
        provider: str | None = None,
        hpc_target: str | None = None,
    ) -> ScientificAttemptAdmissionRequest:
        normalized_scope = (
            scope
            if isinstance(scope, ScientificAttemptScope)
            else ScientificAttemptScope(scope)
        )
        normalized_effects = _normalized_unique(requested_effect_classes)
        actor = self._require_actor(actor_ref)
        request = {
            "command": "attempt.create",
            "envelope_id": envelope_id,
            "session_id": session_id,
            "task_id": task_id,
            "lane_id": lane_id,
            "campaign_id": campaign_id,
            "workflow_id": workflow_id,
            "scope": normalized_scope.value,
            "workflow_contract_digest": workflow_contract_digest,
            "requested_effect_classes": list(normalized_effects),
            "reserved_micu": reserved_micu,
            "reserved_cost_microunits": reserved_cost_microunits,
            "reserved_wall_time_seconds": reserved_wall_time_seconds,
            "provider": provider,
            "hpc_target": hpc_target,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_digest(request)
        existing = (
            self.repositories.scientific_attempt_admission_requests.get_by_idempotency(
                envelope_id=envelope_id,
                idempotency_key=idempotency_key,
            )
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        authority = self.repositories.scientific_attempt_authorizations.get(envelope_id)
        self._validate_admission(
            authority=authority,
            session_id=session_id,
            task_id=task_id,
            campaign_id=campaign_id,
            workflow_id=workflow_id,
            scope=normalized_scope,
            effect_classes=normalized_effects,
            provider=provider,
            hpc_target=hpc_target,
            reserved_micu=reserved_micu,
            reserved_cost_microunits=reserved_cost_microunits,
            reserved_wall_time_seconds=reserved_wall_time_seconds,
        )
        self._resolve_new_workflow_contract(
            workflow_id=workflow_id,
            workflow_contract_digest=workflow_contract_digest,
            scope=normalized_scope,
        )
        lane = self.repositories.lanes.get(lane_id)
        task = self.repositories.tasks.get(task_id)
        if (
            lane is None
            or lane.session_id != session_id
            or task is None
            or task.session_id != session_id
            or task.lane_id != lane_id
        ):
            raise ScientificAttemptError(
                "attempt_lane_scope_invalid",
                "scientific attempt lane does not belong to the exact task",
            )
        self._assert_no_campaign_unknown_effect(
            session_id=session_id,
            task_id=task_id,
            campaign_id=campaign_id,
        )
        record = ScientificAttemptAdmissionRequest(
            admission_request_id=_stable_id(
                "attempt_admission_request", request_digest
            ),
            envelope_id=envelope_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=lane_id,
            campaign_id=campaign_id,
            workflow_id=workflow_id,
            scope=normalized_scope,
            workflow_contract_digest=self._require_text(
                "workflow_contract_digest", workflow_contract_digest
            ),
            requested_effect_classes=normalized_effects,
            provider=provider,
            hpc_target=hpc_target,
            reserved_micu=reserved_micu,
            reserved_cost_microunits=reserved_cost_microunits,
            reserved_wall_time_seconds=reserved_wall_time_seconds,
            actor_ref=actor,
            idempotency_key=self._require_text("idempotency_key", idempotency_key),
            request_digest=request_digest,
            created_at=self.now(),
        )
        with self.mutation_scopes.writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"attempt.admission.request:{record.admission_request_id}",
        ):
            return self.repositories.scientific_attempt_admission_requests.add(record)

    def finalize_attempt_admission(
        self,
        *,
        admission_request_id: str,
    ) -> ScientificAttempt:
        """Host-only scope rollover and atomic envelope consumption."""

        if current_mutation_write_authority() is not None:
            raise ScientificAttemptError(
                "attempt_admission_writer_still_active",
                "Host attempt admission must run after the requesting writer retires",
                hint="Return from the bounded agent turn, then run the Host finalizer.",
                retryable=True,
            )
        admission = self.repositories.scientific_attempt_admission_requests.get(
            admission_request_id
        )
        if admission is None:
            raise ScientificAttemptError(
                "attempt_admission_request_missing",
                "scientific attempt admission request does not exist",
            )
        existing = self.repositories.scientific_attempts.get_by_admission_request(
            admission_request_id
        )
        if existing is not None:
            return existing

        with self.repositories.atomic(prefix="scientific_attempt_admit"):
            existing = self.repositories.scientific_attempts.get_by_admission_request(
                admission_request_id
            )
            if existing is not None:
                return existing
            authority = self.repositories.scientific_attempt_authorizations.get(
                admission.envelope_id
            )
            self._validate_admission(
                authority=authority,
                session_id=admission.session_id,
                task_id=admission.task_id,
                campaign_id=admission.campaign_id,
                workflow_id=admission.workflow_id,
                scope=admission.scope,
                effect_classes=admission.requested_effect_classes,
                provider=admission.provider,
                hpc_target=admission.hpc_target,
                reserved_micu=admission.reserved_micu,
                reserved_cost_microunits=admission.reserved_cost_microunits,
                reserved_wall_time_seconds=admission.reserved_wall_time_seconds,
            )
            self._resolve_new_workflow_contract(
                workflow_id=admission.workflow_id,
                workflow_contract_digest=(admission.workflow_contract_digest),
                scope=admission.scope,
            )
            assert authority is not None
            lane = self.repositories.lanes.get(admission.lane_id)
            task = self.repositories.tasks.get(admission.task_id)
            if (
                lane is None
                or lane.session_id != admission.session_id
                or task is None
                or task.session_id != admission.session_id
                or task.lane_id != admission.lane_id
            ):
                raise ScientificAttemptError(
                    "attempt_lane_scope_invalid",
                    "scientific attempt lane does not belong to the exact task",
                )
            self._assert_no_campaign_unknown_effect(
                session_id=admission.session_id,
                task_id=admission.task_id,
                campaign_id=admission.campaign_id,
            )
            unclosed = [
                item
                for item in self.repositories.scientific_attempts.list_by_campaign(
                    session_id=admission.session_id,
                    task_id=admission.task_id,
                    campaign_id=admission.campaign_id,
                )
                if not self._resolve_attempt_lifecycle(item).is_closed
            ]
            if unclosed:
                raise ScientificAttemptError(
                    "attempt_admission_prior_attempt_unclosed",
                    "a prior scientific attempt must close before another is admitted",
                    details={"attempt_ids": [item.attempt_id for item in unclosed]},
                )
            parent_scope_id = self._seal_pre_attempt_scope(admission.session_id)
            ordinal = authority.consumed_attempts + 1
            attempt_id = _stable_id("attempt", admission.request_digest)
            mutation_scope = self.mutation_scopes.open_scope(
                session_id=admission.session_id,
                scope_kind=MutationScopeKind.ATTEMPT,
                scope_ref=attempt_id,
                scope_id=f"mutation_scope_{attempt_id}",
                parent_scope_id=parent_scope_id,
            )
            now = self.now()
            attempt = ScientificAttempt(
                attempt_id=attempt_id,
                admission_request_id=admission.admission_request_id,
                envelope_id=admission.envelope_id,
                session_id=admission.session_id,
                task_id=admission.task_id,
                lane_id=admission.lane_id,
                campaign_id=admission.campaign_id,
                workflow_id=admission.workflow_id,
                scope=admission.scope,
                root_ref=authority.root_ref,
                mutation_scope_id=mutation_scope.scope_id,
                ordinal=ordinal,
                request_digest=admission.request_digest,
                idempotency_key=admission.idempotency_key,
                workflow_contract_digest=admission.workflow_contract_digest,
                requested_effect_classes=admission.requested_effect_classes,
                provider=admission.provider,
                hpc_target=admission.hpc_target,
                reserved_micu=admission.reserved_micu,
                reserved_cost_microunits=admission.reserved_cost_microunits,
                reserved_wall_time_seconds=admission.reserved_wall_time_seconds,
                status=ScientificAttemptStatus.ACTIVE,
                state_version=1,
                created_by=admission.actor_ref,
                created_at=now,
                updated_at=now,
            )
            with self.mutation_scopes.writer_turn(
                session_id=admission.session_id,
                owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                owner_ref=f"attempt.create:{attempt_id}",
            ):
                consumed = replace(
                    authority,
                    consumed_attempts=ordinal,
                    reserved_micu=(authority.reserved_micu + admission.reserved_micu),
                    reserved_cost_microunits=(
                        authority.reserved_cost_microunits
                        + admission.reserved_cost_microunits
                    ),
                    reserved_wall_time_seconds=(
                        authority.reserved_wall_time_seconds
                        + admission.reserved_wall_time_seconds
                    ),
                    status=(
                        ScientificAttemptAuthorityStatus.EXHAUSTED
                        if ordinal == authority.max_attempts
                        else ScientificAttemptAuthorityStatus.ACTIVE
                    ),
                    state_version=authority.state_version + 1,
                    updated_at=now,
                )
                self.repositories.scientific_attempt_authorizations.replace_consumption(
                    consumed,
                    expected_state_version=authority.state_version,
                )
                return self.repositories.scientific_attempts.add(attempt)

    def bind_run(
        self,
        *,
        attempt_id: str,
        sandbox_run_id: str,
        actor_ref: str,
    ) -> None:
        attempt = self._require_mutation_admissible_attempt(attempt_id)
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"attempt.bind_run:{attempt_id}:{sandbox_run_id}",
        ):
            self.repositories.scientific_attempt_bindings.bind_run(
                attempt_id=attempt_id,
                sandbox_run_id=sandbox_run_id,
                session_id=attempt.session_id,
                bound_by=self._require_actor(actor_ref),
                created_at=self.now(),
            )

    def bind_operation(
        self,
        *,
        attempt_id: str,
        operation_id: str,
        actor_ref: str,
    ) -> None:
        attempt = self._require_mutation_admissible_attempt(attempt_id)
        operation = self.repositories.controlled_operations.get(operation_id)
        if operation is None:
            raise ScientificAttemptError(
                "attempt_operation_missing",
                "controlled operation does not exist",
            )
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"attempt.bind_operation:{attempt_id}:{operation_id}",
        ):
            self.repositories.scientific_attempt_bindings.bind_operation(
                attempt_id=attempt_id,
                operation_id=operation_id,
                sandbox_run_id=operation.sandbox_run_id,
                session_id=attempt.session_id,
                bound_by=self._require_actor(actor_ref),
                created_at=self.now(),
            )

    def operation_universe(self, attempt_id: str) -> ScientificOperationUniverse:
        attempt = self._require_attempt(attempt_id)
        run_ids = self.repositories.scientific_attempt_bindings.list_runs(attempt_id)
        occurrences: list[dict[str, Any]] = []
        for binding in self.repositories.scientific_attempt_bindings.list_operations(
            attempt_id
        ):
            operation_id = binding["operation_id"]
            operation = self.repositories.controlled_operations.get(operation_id)
            if operation is None:
                raise ScientificAttemptError(
                    "attempt_operation_identity_missing",
                    "attempt operation binding points to a missing operation",
                    details={"operation_id": operation_id},
                )
            execution = (
                self.repositories.controlled_operation_executions.get_by_operation_id(
                    operation_id
                )
            )
            result = (
                None
                if execution is None or execution.result_handle_ref is None
                else self.repositories.controlled_operation_results.get(
                    execution.result_handle_ref
                )
            )
            occurrence = {
                "attempt_id": attempt_id,
                "operation_id": operation.operation_id,
                "sandbox_run_id": operation.sandbox_run_id,
                "logical_operation_key": operation.logical_operation_key,
                "operation_digest": operation.operation_digest,
                "backend_category": operation.backend_category,
                "sdk_module": operation.sdk_module,
                "function_name": operation.function_name,
                "operation_status": operation.status.value,
                "approval_id": operation.approval_id,
                "approval_state": operation.approval_state,
                "owner_mode": operation.owner_mode.value,
                "execution": (
                    None
                    if execution is None
                    else {
                        "execution_id": execution.execution_id,
                        "lifecycle_state": execution.lifecycle_state.value,
                        "terminal_outcome": (
                            None
                            if execution.terminal_outcome is None
                            else execution.terminal_outcome.value
                        ),
                        "effect_certainty": execution.effect_certainty.value,
                        "retry_eligibility": execution.retry_eligibility.value,
                        "state_version": execution.state_version,
                        "dispatch_generation": execution.dispatch_generation,
                        "result_handle_ref": execution.result_handle_ref,
                        "result_digest": execution.result_digest,
                        "artifact_set_digest": execution.artifact_set_digest,
                        "approval_digest": execution.approval_digest,
                    }
                ),
                "result": (
                    None
                    if result is None
                    else {
                        "result_handle_id": result.result_handle_id,
                        "terminal_outcome": result.terminal_outcome.value,
                        "result_digest": result.result_digest,
                        "artifact_set_digest": result.artifact_set_digest,
                        "origin": result.origin,
                    }
                ),
            }
            occurrences.append(
                {
                    **occurrence,
                    "occurrence_digest": canonical_digest(occurrence),
                }
            )
        occurrences.sort(key=lambda item: str(item["operation_id"]))
        payload = {
            "attempt_id": attempt.attempt_id,
            "session_id": attempt.session_id,
            "task_id": attempt.task_id,
            "lane_id": attempt.lane_id,
            "campaign_id": attempt.campaign_id,
            "workflow_id": attempt.workflow_id,
            "scope": attempt.scope.value,
            "run_ids": list(run_ids),
            "occurrences": occurrences,
        }
        return ScientificOperationUniverse(
            attempt_id=attempt_id,
            run_ids=run_ids,
            occurrences=tuple(occurrences),
            universe_digest=canonical_digest(payload),
        )

    def evaluate_selection(
        self,
        *,
        attempt_id: str,
        selection_id: str | None = None,
    ) -> ScientificSelectionEvaluation:
        """Evaluate the exact current scientific-selection head without mutation."""

        attempt = self._require_attempt(attempt_id)
        resolved_head = self._resolve_selection_head(attempt_id)
        if resolved_head is None:
            raise ScientificAttemptError(
                "selection_head_missing",
                "scientific attempt has no current selection head",
                details={"attempt_id": attempt_id, "mutation_applied": False},
            )
        if selection_id is not None and resolved_head.head.selection_id != selection_id:
            raise ScientificAttemptError(
                "selection_not_current_head",
                "requested scientific selection is not the current CAS head",
                details={
                    "attempt_id": attempt_id,
                    "selection_id": selection_id,
                    "current_selection_id": resolved_head.head.selection_id,
                    "head_state_version": resolved_head.head.state_version,
                    "mutation_applied": False,
                },
                retryable=True,
            )
        return self._selection_evaluator().evaluate(
            attempt=attempt,
            resolved_head=resolved_head,
            universe=self.operation_universe(attempt_id),
        )

    def inspect_selection(
        self,
        *,
        session_id: str,
        attempt_id: str,
        selection_id: str,
        task_id: str | None = None,
        limit: int = SCIENTIFIC_SELECTION_INSPECTION_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Project one exact, bounded page from the current selection head."""

        attempt = self.repositories.scientific_attempts.get(attempt_id)
        if (
            attempt is None
            or attempt.session_id != session_id
            or (task_id is not None and attempt.task_id != task_id)
        ):
            raise ScientificAttemptError(
                "scientific_inspection_scope_mismatch",
                "scientific attempt is outside the current inspection authority",
                details={"mutation_applied": False},
            )
        resolved_head = self._resolve_selection_head(attempt_id)
        if resolved_head is None or resolved_head.head.selection_id != selection_id:
            raise ScientificAttemptError(
                "scientific_inspection_selection_not_current",
                "requested selection is not the exact current attempt head",
                details={
                    "attempt_id": attempt_id,
                    "mutation_applied": False,
                },
            )
        effective_limit = self._inspection_limit(limit)
        evaluation = self._selection_evaluator().evaluate(
            attempt=attempt,
            resolved_head=resolved_head,
            universe=self.operation_universe(attempt_id),
        )
        offset = self._decode_inspection_cursor(
            cursor,
            attempt_id=attempt_id,
            selection_id=selection_id,
            head_state_version=resolved_head.head.state_version,
            operation_universe_digest=evaluation.operation_universe_digest,
            occurrence_count=len(evaluation.occurrences),
        )
        page_occurrences = evaluation.occurrences[offset : offset + effective_limit]
        next_offset = offset + len(page_occurrences)
        next_cursor = (
            None
            if next_offset >= len(evaluation.occurrences)
            else self._encode_inspection_cursor(
                attempt_id=attempt_id,
                selection_id=selection_id,
                head_state_version=resolved_head.head.state_version,
                operation_universe_digest=evaluation.operation_universe_digest,
                offset=next_offset,
            )
        )
        page_operation_ids = {
            occurrence.operation_id for occurrence in page_occurrences
        }
        relevant_issues = tuple(
            issue
            for issue in evaluation.issues
            if not issue.operation_ids
            or page_operation_ids.intersection(issue.operation_ids)
        )
        issue_limit = min(max(effective_limit * 4, 20), 200)
        contract = self._resolve_readable_workflow_contract(attempt)
        lifecycle = self._resolve_attempt_lifecycle(attempt)
        return {
            "schema_id": "scientific_selection_inspection@1",
            "mode": "facts_only",
            "strategy_policy": {
                "harness_recommends_actions": False,
                "selection_decider": "agent",
                "readiness_is_intent": False,
            },
            "attempt": {
                "attempt_id": attempt.attempt_id,
                "task_id": attempt.task_id,
                "lane_id": attempt.lane_id,
                "campaign_id": attempt.campaign_id,
                "workflow_id": attempt.workflow_id,
                "scope": attempt.scope.value,
                "status": lifecycle.projected_status.value,
                "record_status": lifecycle.record_status.value,
                "effective_status": lifecycle.effective_status.value,
                "lifecycle_phase": lifecycle.phase.value,
                "closure_requested": lifecycle.closure_requested,
                "closure_request_id": lifecycle.closure_request_id,
                "closure_id": lifecycle.closure_id,
                "accepts_scientific_mutation": (lifecycle.accepts_scientific_mutation),
            },
            "head": {
                "selection_id": resolved_head.head.selection_id,
                "revision": resolved_head.head.revision,
                "state_version": resolved_head.head.state_version,
                "selection_state": resolved_head.selection.state.value,
            },
            "selection": {
                "selection_id": resolved_head.selection.selection_id,
                "revision": resolved_head.selection.revision,
                "state": resolved_head.selection.state.value,
                "operation_universe_digest": (
                    resolved_head.selection.operation_universe_digest
                ),
                "operation_count": resolved_head.selection.operation_count,
                "workflow_contract_digest": (
                    resolved_head.selection.workflow_contract_digest
                ),
            },
            "contract": contract.project(attempt.scope),
            "page": {
                "schema_id": "scientific_selection_occurrence_page@1",
                "order": "operation_id_asc",
                "offset": offset,
                "limit": effective_limit,
                "returned_count": len(page_occurrences),
                "total_count": len(evaluation.occurrences),
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
                "head_state_version": resolved_head.head.state_version,
                "operation_universe_digest": (evaluation.operation_universe_digest),
            },
            "occurrences": [occurrence.to_dict() for occurrence in page_occurrences],
            "issues": [
                {
                    **issue.to_dict(),
                    "operation_ids": [
                        operation_id
                        for operation_id in issue.operation_ids
                        if operation_id in page_operation_ids
                    ][:effective_limit],
                }
                for issue in relevant_issues[:issue_limit]
            ],
            "issue_page": {
                "matching_count": len(relevant_issues),
                "returned_count": min(
                    len(relevant_issues),
                    issue_limit,
                ),
                "truncated": len(relevant_issues) > issue_limit,
            },
            "readiness": evaluation.summary(),
        }

    def project_session_readiness_summary(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        limit: int = SCIENTIFIC_SELECTION_INSPECTION_DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Project only bounded attempt/head/readiness facts for shared surfaces."""

        effective_limit = self._inspection_limit(limit)
        attempts = [
            attempt
            for attempt in self.repositories.scientific_attempts.list_by_session(
                session_id
            )
            if task_id is None or attempt.task_id == task_id
        ]
        projected: list[dict[str, Any]] = []
        for attempt in attempts[:effective_limit]:
            lifecycle = self._resolve_attempt_lifecycle(attempt)
            resolved_head = self._resolve_selection_head(attempt.attempt_id)
            if resolved_head is None:
                head = None
                readiness = {
                    "attempt_id": attempt.attempt_id,
                    "selection_id": None,
                    "gap_counts": {"selection_head_missing": 1},
                    "bounded_operation_ids": {},
                    "blocker_codes": ["selection_head_missing"],
                    "seal_ready": False,
                    "closure_ready": False,
                    "closure_ready_phase": "host_finalization_after_request",
                    "closure_request_ready": False,
                    "closure_finalization_ready": False,
                }
            else:
                evaluation = self._selection_evaluator().evaluate(
                    attempt=attempt,
                    resolved_head=resolved_head,
                    universe=self.operation_universe(attempt.attempt_id),
                )
                head = {
                    "selection_id": resolved_head.head.selection_id,
                    "revision": resolved_head.head.revision,
                    "state_version": resolved_head.head.state_version,
                    "selection_state": resolved_head.selection.state.value,
                    "operation_universe_digest": (
                        resolved_head.selection.operation_universe_digest
                    ),
                    "operation_count": resolved_head.selection.operation_count,
                }
                readiness = evaluation.summary(max_ids=10)
            projected.append(
                {
                    "attempt_id": attempt.attempt_id,
                    "task_id": attempt.task_id,
                    "lane_id": attempt.lane_id,
                    "campaign_id": attempt.campaign_id,
                    "workflow_id": attempt.workflow_id,
                    "scope": attempt.scope.value,
                    "status": lifecycle.projected_status.value,
                    "record_status": lifecycle.record_status.value,
                    "effective_status": lifecycle.effective_status.value,
                    "lifecycle_phase": lifecycle.phase.value,
                    "accepts_scientific_mutation": (
                        lifecycle.accepts_scientific_mutation
                    ),
                    "workflow_contract_digest": (attempt.workflow_contract_digest),
                    "selection_head": head,
                    "readiness": readiness,
                    "closure_requested": lifecycle.closure_requested,
                    "closure_request_id": lifecycle.closure_request_id,
                    "closure_id": lifecycle.closure_id,
                }
            )
        return {
            "schema_id": "scientific_attempt_readiness_summary@1",
            "mode": "bounded_summary",
            "attempt_count": len(attempts),
            "returned_count": len(projected),
            "truncated": len(projected) < len(attempts),
            "attempts": projected,
        }

    def begin_selection(
        self,
        *,
        attempt_id: str,
        actor_ref: str,
        idempotency_key: str,
        expected_head_state_version: int | None = None,
        parent_selection_id: str | None = None,
    ) -> ScientificChainSelection:
        attempt = self._require_active_attempt(attempt_id)
        self._resolve_mutable_workflow_contract(attempt)
        actor = self._require_actor(actor_ref)
        request = {
            "command": "scientific.selection.begin",
            "attempt_id": attempt_id,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
            "expected_head_state_version": expected_head_state_version,
            "parent_selection_id": parent_selection_id,
        }
        request_digest = canonical_digest(request)
        existing = self.repositories.scientific_selections.get_by_idempotency(
            attempt_id=attempt_id,
            actor_ref=actor,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        self._require_closure_not_requested(attempt_id)
        with self.repositories.atomic(prefix="scientific_selection_begin"):
            resolved_head = self._resolve_selection_head(attempt_id)
            head = None if resolved_head is None else resolved_head.head
            if head is None:
                if expected_head_state_version not in {None, 0}:
                    raise ScientificAttemptError(
                        "selection_version_conflict",
                        "scientific selection has no current head",
                        retryable=True,
                    )
                if parent_selection_id is not None:
                    raise ScientificAttemptError(
                        "selection_parent_invalid",
                        "first scientific selection cannot name a parent",
                    )
                revision = 1
                expected_version = None
            else:
                if expected_head_state_version != head.state_version:
                    raise ScientificAttemptError(
                        "selection_version_conflict",
                        "scientific selection head changed",
                        details={
                            "current_head_selection_id": head.selection_id,
                            "current_head_state_version": head.state_version,
                        },
                        retryable=True,
                    )
                if parent_selection_id != head.selection_id:
                    raise ScientificAttemptError(
                        "selection_parent_invalid",
                        "selection revision must name the exact current head",
                    )
                revision = head.revision + 1
                expected_version = head.state_version
            universe = self.operation_universe(attempt_id)
            now = self.now()
            selection = ScientificChainSelection(
                selection_id=_stable_id("selection", request_digest),
                attempt_id=attempt_id,
                revision=revision,
                parent_selection_id=parent_selection_id,
                state=ScientificSelectionState.DRAFT,
                operation_universe_digest=universe.universe_digest,
                operation_count=len(universe.occurrences),
                disposition_digest=EMPTY_DISPOSITION_DIGEST,
                adoption_digest=EMPTY_ADOPTION_DIGEST,
                workflow_contract_digest=attempt.workflow_contract_digest,
                actor_ref=actor,
                idempotency_key=self._require_text("idempotency_key", idempotency_key),
                request_digest=request_digest,
                created_at=now,
            )
            snapshots = tuple(
                ScientificOccurrenceSnapshot(
                    selection_id=selection.selection_id,
                    attempt_id=attempt_id,
                    operation_id=str(item["operation_id"]),
                    sandbox_run_id=str(item["sandbox_run_id"]),
                    occurrence_digest=str(item["occurrence_digest"]),
                    created_at=now,
                )
                for item in universe.occurrences
            )
            with self.mutation_scopes.writer_turn(
                session_id=attempt.session_id,
                owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                owner_ref=f"selection.begin:{selection.selection_id}",
            ):
                return self.repositories.scientific_selections.add(
                    selection,
                    snapshots,
                    expected_head_state_version=expected_version,
                )

    def disposition_operation(
        self,
        *,
        selection_id: str,
        operation_id: str,
        kind: ScientificOperationDispositionKind | str,
        reason_code: str,
        actor_ref: str,
        idempotency_key: str,
        workflow_role: str | None = None,
        replacement_operation_id: str | None = None,
    ) -> ScientificOperationDisposition:
        selection, attempt = self._require_draft_head(selection_id)
        normalized_kind = (
            kind
            if isinstance(kind, ScientificOperationDispositionKind)
            else ScientificOperationDispositionKind(kind)
        )
        contract = self._resolve_mutable_workflow_contract(attempt)
        if (
            normalized_kind is ScientificOperationDispositionKind.ADOPTED
            and contract.effect_adoption_policy
            == SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
        ):
            raise ScientificAttemptError(
                "scientific_atomic_adoption_required",
                "adopted disposition must be created by scientific.operation.adopt",
                details=self._operation_adoption_error_details(
                    attempt=attempt,
                    selection=selection,
                    operation_id=operation_id,
                    requested_role=workflow_role,
                    error_code="scientific_atomic_adoption_required",
                ),
            )
        actor = self._require_actor(actor_ref)
        request = {
            "command": "scientific.operation.disposition",
            "selection_id": selection_id,
            "operation_id": operation_id,
            "kind": normalized_kind.value,
            "reason_code": reason_code,
            "workflow_role": workflow_role,
            "replacement_operation_id": replacement_operation_id,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_digest(request)
        existing = self.repositories.scientific_dispositions.get_by_idempotency(
            selection_id=selection_id,
            actor_ref=actor,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        occurrence_ids = {
            item.operation_id
            for item in self.repositories.scientific_selections.list_occurrences(
                selection_id
            )
        }
        if operation_id not in occurrence_ids:
            raise ScientificAttemptError(
                "selection_operation_out_of_universe",
                "operation is not in the Host-derived selection universe",
            )
        if (
            replacement_operation_id is not None
            and replacement_operation_id not in occurrence_ids
        ):
            raise ScientificAttemptError(
                "selection_replacement_out_of_universe",
                "replacement operation is not in the same selection universe",
            )
        record = ScientificOperationDisposition(
            disposition_id=_stable_id("disposition", request_digest),
            selection_id=selection_id,
            attempt_id=attempt.attempt_id,
            operation_id=operation_id,
            kind=normalized_kind,
            workflow_role=workflow_role,
            reason_code=self._require_text("reason_code", reason_code),
            replacement_operation_id=replacement_operation_id,
            actor_ref=actor,
            idempotency_key=self._require_text("idempotency_key", idempotency_key),
            request_digest=request_digest,
            created_at=self.now(),
        )
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"selection.disposition:{record.disposition_id}",
        ):
            return self.repositories.scientific_dispositions.add(record)

    def adopt_operation(
        self,
        *,
        selection_id: str,
        operation_id: str,
        workflow_role: str,
        reason_code: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificOperationAdoptionResult:
        selection_ref = self._require_text("selection_id", selection_id)
        operation_ref = self._require_text("operation_id", operation_id)
        actor = self._require_actor(actor_ref)
        role = self._require_text("workflow_role", workflow_role)
        reason = self._require_text("reason_code", reason_code)
        idempotency = self._require_text(
            "idempotency_key",
            idempotency_key,
        )
        candidate_selection = self.repositories.scientific_selections.get(selection_ref)
        try:
            selection, attempt = self._require_draft_head(selection_ref)
            contract = self._resolve_mutable_workflow_contract(attempt)
            if (
                contract.effect_adoption_policy
                != SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
            ):
                raise ScientificAttemptError(
                    "scientific_atomic_adoption_unsupported",
                    "workflow contract does not authorize atomic operation adoption",
                    details={"mutation_applied": False},
                )
        except ScientificAttemptError as exc:
            candidate_attempt = (
                None
                if candidate_selection is None
                else self.repositories.scientific_attempts.get(
                    candidate_selection.attempt_id
                )
            )
            if candidate_selection is not None and candidate_attempt is not None:
                raise self._enrich_operation_adoption_error(
                    exc,
                    attempt=candidate_attempt,
                    selection=candidate_selection,
                    operation_id=operation_ref,
                    requested_role=role,
                ) from exc
            details = dict(exc.details)
            details.update(
                {
                    "selection_id": selection_ref,
                    "operation_id": operation_ref,
                    "requested_role": role,
                    "head_state_version": None,
                    "current_disposition": None,
                    "current_adoption": None,
                    "mutation_applied": False,
                }
            )
            raise ScientificAttemptError(
                exc.error_code,
                str(exc),
                hint=exc.hint,
                details=details,
                retryable=exc.retryable,
            ) from exc
        request = {
            "command": "scientific.operation.adopt",
            "selection_id": selection_ref,
            "operation_id": operation_ref,
            "workflow_role": role,
            "reason_code": reason,
            "actor_ref": actor,
            "idempotency_key": idempotency,
        }
        request_digest = canonical_digest(request)
        replay = self._resolve_operation_adoption_replay(
            selection=selection,
            attempt=attempt,
            operation_id=operation_ref,
            workflow_role=role,
            reason_code=reason,
            actor_ref=actor,
            idempotency_key=idempotency,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        try:
            with self.mutation_scopes.writer_turn(
                session_id=attempt.session_id,
                owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                owner_ref=(
                    "selection.operation.adopt:"
                    + _stable_id("disposition", request_digest)
                ),
            ):
                with self.repositories.atomic(prefix="scientific_operation_adopt"):
                    current_selection, current_attempt = self._require_draft_head(
                        selection_ref
                    )
                    current_universe = self.operation_universe(
                        current_attempt.attempt_id
                    )
                    if (
                        current_selection != selection
                        or current_universe.universe_digest
                        != selection.operation_universe_digest
                    ):
                        raise ScientificAttemptError(
                            "selection_universe_changed",
                            "selection head or operation universe changed before adoption",
                            details=self._operation_adoption_error_details(
                                attempt=current_attempt,
                                selection=current_selection,
                                operation_id=operation_ref,
                                requested_role=role,
                                error_code="selection_universe_changed",
                            ),
                            retryable=True,
                        )
                    if operation_ref not in {
                        str(occurrence["operation_id"])
                        for occurrence in current_universe.occurrences
                    }:
                        raise ScientificAttemptError(
                            "selection_operation_out_of_universe",
                            "operation is not in the exact current selection universe",
                            details=self._operation_adoption_error_details(
                                attempt=current_attempt,
                                selection=current_selection,
                                operation_id=operation_ref,
                                requested_role=role,
                                error_code=("selection_operation_out_of_universe"),
                            ),
                        )
                    replay = self._resolve_operation_adoption_replay(
                        selection=current_selection,
                        attempt=current_attempt,
                        operation_id=operation_ref,
                        workflow_role=role,
                        reason_code=reason,
                        actor_ref=actor,
                        idempotency_key=idempotency,
                        request_digest=request_digest,
                    )
                    if replay is not None:
                        return replay
                    operation, execution, result = self._require_adoptable_execution(
                        attempt=current_attempt,
                        operation_id=operation_ref,
                    )
                    self._validate_workflow_role(
                        attempt=current_attempt,
                        selection=current_selection,
                        workflow_role=role,
                        operation=operation,
                        execution=execution,
                    )
                    self._require_operation_adoption_slot_available(
                        selection_id=selection_ref,
                        operation_id=operation_ref,
                        workflow_role=role,
                    )
                    created_at = self.now()
                    disposition = ScientificOperationDisposition(
                        disposition_id=_stable_id(
                            "disposition",
                            request_digest,
                        ),
                        selection_id=selection_ref,
                        attempt_id=current_attempt.attempt_id,
                        operation_id=operation_ref,
                        kind=ScientificOperationDispositionKind.ADOPTED,
                        workflow_role=role,
                        reason_code=reason,
                        replacement_operation_id=None,
                        actor_ref=actor,
                        idempotency_key=idempotency,
                        request_digest=request_digest,
                        created_at=created_at,
                    )
                    adoption = ScientificEffectAdoption(
                        adoption_id=_stable_id(
                            "adoption",
                            request_digest,
                        ),
                        selection_id=selection_ref,
                        attempt_id=current_attempt.attempt_id,
                        workflow_role=role,
                        operation_id=operation_ref,
                        execution_id=execution.execution_id,
                        result_handle_id=result.result_handle_id,
                        result_digest=result.result_digest,
                        artifact_set_digest=result.artifact_set_digest,
                        source_sandbox_run_id=operation.sandbox_run_id,
                        effect_certainty=execution.effect_certainty.value,
                        approval_digest=execution.approval_digest,
                        actor_ref=actor,
                        idempotency_key=idempotency,
                        request_digest=request_digest,
                        created_at=created_at,
                    )
                    stored_disposition = self.repositories.scientific_dispositions.add(
                        disposition
                    )
                    stored_adoption = self.repositories.scientific_effect_adoptions.add(
                        adoption
                    )
                    return ScientificOperationAdoptionResult(
                        disposition=stored_disposition,
                        adoption=stored_adoption,
                    )
        except ScientificAttemptError as exc:
            raise self._enrich_operation_adoption_error(
                exc,
                attempt=attempt,
                selection=selection,
                operation_id=operation_ref,
                requested_role=role,
            ) from exc
        except ScientificAttemptIdentityConflictError as exc:
            raise ScientificAttemptError(
                "scientific_operation_adoption_integrity_conflict",
                "atomic scientific adoption conflicts with existing canonical facts",
                details=self._operation_adoption_error_details(
                    attempt=attempt,
                    selection=selection,
                    operation_id=operation_ref,
                    requested_role=role,
                    error_code=("scientific_operation_adoption_integrity_conflict"),
                ),
            ) from exc

    def adopt_effect(
        self,
        *,
        selection_id: str,
        operation_id: str,
        workflow_role: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificEffectAdoption:
        selection, attempt = self._require_draft_head(selection_id)
        contract = self._resolve_mutable_workflow_contract(attempt)
        if contract.effect_adoption_policy == SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC:
            raise ScientificAttemptError(
                "scientific_legacy_adoption_disabled",
                "legacy effect adoption is disabled for this workflow contract",
                details=self._operation_adoption_error_details(
                    attempt=attempt,
                    selection=selection,
                    operation_id=operation_id,
                    requested_role=workflow_role,
                    error_code="scientific_legacy_adoption_disabled",
                ),
            )
        actor = self._require_actor(actor_ref)
        request = {
            "command": "scientific.effect.adopt",
            "selection_id": selection_id,
            "operation_id": operation_id,
            "workflow_role": workflow_role,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_digest(request)
        existing = self.repositories.scientific_effect_adoptions.get_by_idempotency(
            selection_id=selection_id,
            actor_ref=actor,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        disposition = next(
            (
                item
                for item in self.repositories.scientific_dispositions.list_by_selection(
                    selection_id
                )
                if item.operation_id == operation_id
            ),
            None,
        )
        if (
            disposition is None
            or disposition.kind is not ScientificOperationDispositionKind.ADOPTED
            or disposition.workflow_role != workflow_role
        ):
            raise ScientificAttemptError(
                "effect_adoption_disposition_missing",
                "effect adoption requires an exact adopted disposition and role",
            )
        operation, execution, result = self._require_adoptable_execution(
            attempt=attempt,
            operation_id=operation_id,
        )
        self._validate_workflow_role(
            attempt=attempt,
            selection=selection,
            workflow_role=workflow_role,
            operation=operation,
            execution=execution,
        )
        record = ScientificEffectAdoption(
            adoption_id=_stable_id("adoption", request_digest),
            selection_id=selection_id,
            attempt_id=attempt.attempt_id,
            workflow_role=self._require_text("workflow_role", workflow_role),
            operation_id=operation_id,
            execution_id=execution.execution_id,
            result_handle_id=result.result_handle_id,
            result_digest=result.result_digest,
            artifact_set_digest=result.artifact_set_digest,
            source_sandbox_run_id=operation.sandbox_run_id,
            effect_certainty=execution.effect_certainty.value,
            approval_digest=execution.approval_digest,
            actor_ref=actor,
            idempotency_key=self._require_text("idempotency_key", idempotency_key),
            request_digest=request_digest,
            created_at=self.now(),
        )
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"selection.adopt:{record.adoption_id}",
        ):
            return self.repositories.scientific_effect_adoptions.add(record)

    def materialize_adopted_artifact(
        self,
        *,
        selection_id: str,
        adoption_id: str,
        source_artifact_id: str,
        target_sandbox_run_id: str,
        target: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificArtifactMaterialization:
        selection, attempt = self._require_draft_head(selection_id)
        actor = self._require_actor(actor_ref)
        request = {
            "command": "scientific.artifact.materialize",
            "selection_id": selection_id,
            "adoption_id": adoption_id,
            "source_artifact_id": source_artifact_id,
            "target_sandbox_run_id": target_sandbox_run_id,
            "target": target,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_digest(request)
        existing = (
            self.repositories.scientific_artifact_materializations.get_by_idempotency(
                selection_id=selection_id,
                actor_ref=actor,
                idempotency_key=idempotency_key,
            )
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        adoption = self.repositories.scientific_effect_adoptions.get(adoption_id)
        if (
            adoption is None
            or adoption.selection_id != selection_id
            or adoption.attempt_id != attempt.attempt_id
        ):
            raise ScientificAttemptError(
                "materialization_adoption_scope_invalid",
                "artifact adoption does not belong to the exact selection",
            )
        result_refs = self.repositories.controlled_operation_result_artifacts.list_by_result_handle(
            adoption.result_handle_id
        )
        source_ref = next(
            (ref for ref in result_refs if ref.artifact_id == source_artifact_id),
            None,
        )
        if source_ref is None:
            raise ScientificAttemptError(
                "materialization_artifact_not_adopted",
                "artifact is not in the immutable adopted result set",
            )
        if (
            self.repositories.scientific_attempt_bindings.attempt_for_run(
                target_sandbox_run_id
            )
            != attempt.attempt_id
        ):
            raise ScientificAttemptError(
                "materialization_target_cross_attempt",
                "target sandbox run is not bound to the same scientific attempt",
            )
        target_run = self.repositories.sandbox_runs.get(target_sandbox_run_id)
        if target_run is None or target_run.session_id != attempt.session_id:
            raise ScientificAttemptError(
                "materialization_target_missing",
                "target sandbox run does not exist in the attempt session",
            )
        if self.artifact_boundary is None:
            raise ScientificAttemptError(
                "materialization_boundary_unavailable",
                "Host artifact materialization boundary is not configured",
            )
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
            owner_ref=f"selection.materialize:{selection_id}:{source_artifact_id}",
        ):
            try:
                materialized = self.artifact_boundary.materialize(
                    session_id=attempt.session_id,
                    sandbox_workspace_id=target_run.sandbox_workspace_id,
                    artifact_id=source_artifact_id,
                    target=target,
                    mode="readonly",
                )
            except ArtifactBoundaryError as exc:
                raise ScientificAttemptError(
                    exc.error_code,
                    str(exc),
                    hint=exc.hint,
                    details=exc.details,
                    retryable=exc.retryable,
                ) from exc
            if materialized.artifact_digest != source_ref.artifact_digest:
                raise ScientificAttemptError(
                    "materialization_digest_mismatch",
                    "Host materialization digest does not match adopted result bytes",
                )
            receipt = ScientificArtifactMaterialization(
                receipt_id=_stable_id("scientific_materialization", request_digest),
                selection_id=selection_id,
                attempt_id=attempt.attempt_id,
                adoption_id=adoption_id,
                source_artifact_id=source_artifact_id,
                source_artifact_digest=source_ref.artifact_digest,
                source_sandbox_run_id=adoption.source_sandbox_run_id,
                target_sandbox_workspace_id=target_run.sandbox_workspace_id,
                target_sandbox_run_id=target_sandbox_run_id,
                target_path=materialized.path,
                boundary_materialization_id=materialized.materialization_id,
                actor_ref=actor,
                idempotency_key=self._require_text("idempotency_key", idempotency_key),
                request_digest=request_digest,
                created_at=self.now(),
            )
            return self.repositories.scientific_artifact_materializations.add(receipt)

    def seal_selection(
        self,
        *,
        selection_id: str,
        actor_ref: str,
        idempotency_key: str,
        expected_universe_digest: str,
    ) -> ScientificChainSelection:
        actor = self._require_actor(actor_ref)
        selection = self.repositories.scientific_selections.get(selection_id)
        if selection is None:
            raise ScientificAttemptError(
                "selection_missing",
                "scientific selection does not exist",
            )
        attempt = self._require_attempt(selection.attempt_id)
        self._resolve_mutable_workflow_contract(attempt)
        resolved_head = self._resolve_selection_head(selection.attempt_id)
        if resolved_head is None or resolved_head.head.selection_id != selection_id:
            raise ScientificAttemptError(
                "selection_not_current_head",
                "scientific selection is not the current CAS head",
                retryable=True,
            )
        selection = resolved_head.selection
        if selection.state is ScientificSelectionState.SEALED:
            if expected_universe_digest != selection.operation_universe_digest:
                raise ScientificAttemptError(
                    "selection_universe_expectation_mismatch",
                    "requested universe digest is not the sealed selection snapshot",
                )
            return selection
        if selection.state is not ScientificSelectionState.DRAFT:
            raise ScientificAttemptError(
                "selection_not_draft",
                "invalidated scientific selection cannot be sealed",
            )
        attempt = self._require_mutation_admissible_attempt(selection.attempt_id)
        request_digest = canonical_digest(
            {
                "command": "scientific.selection.seal",
                "selection_id": selection_id,
                "actor_ref": actor,
                "idempotency_key": idempotency_key,
                "expected_universe_digest": expected_universe_digest,
            }
        )
        if expected_universe_digest != selection.operation_universe_digest:
            raise ScientificAttemptError(
                "selection_universe_expectation_mismatch",
                "requested universe digest is not the selection snapshot",
            )
        universe = self.operation_universe(attempt.attempt_id)
        if universe.universe_digest != selection.operation_universe_digest:
            raise ScientificAttemptError(
                "selection_universe_changed",
                "attempt operation universe changed after selection began",
                details={
                    "selection_universe_digest": selection.operation_universe_digest,
                    "current_universe_digest": universe.universe_digest,
                },
                retryable=True,
            )
        dispositions = self.repositories.scientific_dispositions.list_by_selection(
            selection_id
        )
        adoptions = self.repositories.scientific_effect_adoptions.list_by_selection(
            selection_id
        )
        evaluation = self._selection_evaluator().evaluate(
            attempt=attempt,
            resolved_head=resolved_head,
            universe=universe,
        )
        self._raise_selection_evaluation(evaluation, for_closure=False)
        disposition_digest = canonical_digest([item.to_dict() for item in dispositions])
        adoption_digest = canonical_digest([item.to_dict() for item in adoptions])
        sealed = replace(
            selection,
            state=ScientificSelectionState.SEALED,
            disposition_digest=disposition_digest,
            adoption_digest=adoption_digest,
            sealed_at=self.now(),
        )
        # Idempotency is represented by the sealed revision itself.  A replay with
        # the same selection and universe digest returns it; a different command
        # cannot edit a sealed revision.
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"selection.seal:{selection_id}:{actor}:{idempotency_key}",
        ):
            stored = self.repositories.scientific_selections.seal(
                sealed,
                expected_state=ScientificSelectionState.DRAFT,
            )
        _ = request_digest
        return stored

    def request_attempt_closure(
        self,
        *,
        attempt_id: str,
        selection_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificAttemptClosureRequest:
        """Persist agent closure intent while its writer still has authority.

        The Host must finalize this request after the requesting turn retires;
        attempting to establish quiescence from inside that turn would make the
        caller part of the active writer set it is trying to seal.
        """

        attempt = self._require_active_attempt(attempt_id)
        self._resolve_mutable_workflow_contract(attempt)
        actor = self._require_actor(actor_ref)
        self._require_attempt_task_owner(attempt, actor_ref=actor)
        request = {
            "command": "scientific.attempt.close",
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_digest(request)
        existing = self.repositories.scientific_attempt_closure_requests.get_by_attempt(
            attempt_id
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            return existing
        resolved_head = self._resolve_selection_head(attempt_id)
        selection = (
            None
            if resolved_head is None or resolved_head.head.selection_id != selection_id
            else resolved_head.selection
        )
        if (
            selection is None
            or selection.attempt_id != attempt_id
            or selection.state is not ScientificSelectionState.SEALED
        ):
            raise ScientificAttemptError(
                "attempt_closure_selection_invalid",
                "closure request requires the exact sealed current selection",
            )
        universe = self.operation_universe(attempt_id)
        if universe.universe_digest != selection.operation_universe_digest:
            raise ScientificAttemptError(
                "attempt_closure_universe_changed",
                "operation universe changed after selection sealing",
            )
        assert resolved_head is not None
        evaluation = self._selection_evaluator().evaluate(
            attempt=attempt,
            resolved_head=resolved_head,
            universe=universe,
        )
        self._raise_selection_evaluation(evaluation, for_closure=False)
        self._assert_attempt_quiescent(attempt)
        record = ScientificAttemptClosureRequest(
            closure_request_id=_stable_id("attempt_closure_request", request_digest),
            attempt_id=attempt_id,
            selection_id=selection_id,
            actor_ref=actor,
            idempotency_key=self._require_text("idempotency_key", idempotency_key),
            request_digest=request_digest,
            created_at=self.now(),
        )
        with self.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref=f"attempt.close.request:{record.closure_request_id}",
        ):
            stored = self.repositories.scientific_attempt_closure_requests.add(record)
            return stored

    def finalize_closure_request(
        self,
        *,
        closure_request_id: str,
    ) -> ScientificAttemptClosure:
        """Atomically seal, close, and roll one immutable agent request."""

        if current_mutation_write_authority() is not None:
            raise ScientificAttemptError(
                "attempt_closure_writer_still_active",
                "Host closure finalization must run after the requesting writer retires",
                hint="Return from the bounded agent turn, then run the Host finalizer.",
                retryable=True,
            )
        with self.repositories.atomic(prefix="scientific_attempt_close"):
            return self._finalize_closure_request_in_transaction(
                closure_request_id=closure_request_id
            )

    def _finalize_closure_request_in_transaction(
        self,
        *,
        closure_request_id: str,
    ) -> ScientificAttemptClosure:
        """Finalize one closure while the caller owns the short write transaction."""

        request = self.repositories.scientific_attempt_closure_requests.get(
            closure_request_id
        )
        if request is None:
            raise ScientificAttemptError(
                "attempt_closure_request_missing",
                "scientific attempt closure request does not exist",
            )
        attempt = self._require_attempt(request.attempt_id)
        existing = self.repositories.scientific_attempt_closures.get_by_attempt(
            attempt.attempt_id
        )
        if existing is not None:
            if existing.closure_request_id != closure_request_id:
                raise ScientificAttemptError(
                    "attempt_closure_request_conflict",
                    "attempt was closed from a different immutable request",
                )
            lifecycle = self._resolve_attempt_lifecycle(attempt)
            if lifecycle.closure != existing:
                raise ScientificAttemptError(
                    "scientific_attempt_lifecycle_invalid",
                    "scientific attempt closure does not resolve canonically",
                    details={
                        "attempt_id": attempt.attempt_id,
                        "mutation_applied": False,
                    },
                )
            self._ensure_post_closure_scope(attempt)
            return existing
        self._require_attempt_task_owner(
            attempt,
            actor_ref=request.actor_ref,
        )
        self._assert_attempt_quiescent(attempt)
        active_writers = self.repositories.mutation_writers.list_active(
            attempt.mutation_scope_id
        )
        if active_writers:
            raise ScientificAttemptError(
                "attempt_closure_writers_active",
                "attempt still has active mutation writers",
                details={"writer_ids": [writer.writer_id for writer in active_writers]},
                retryable=True,
            )
        scope = self.repositories.mutation_scopes.get(attempt.mutation_scope_id)
        if scope is None:
            raise ScientificAttemptError(
                "attempt_closure_scope_missing",
                "attempt mutation scope does not exist",
            )
        if scope.state is MutationScopeState.OPEN:
            scope = self.mutation_scopes.begin_freeze(scope.scope_id)
        if scope.state is MutationScopeState.FREEZING:
            issued = self.mutation_scopes.issue_quiescence_receipt(scope.scope_id)
            scope = self.mutation_scopes.seal_scope(
                scope.scope_id,
                receipt_id=issued.receipt.receipt_id,
            )
            receipt = issued.receipt
        elif scope.state is MutationScopeState.QUIESCENT:
            receipt = self.repositories.quiescence_receipts.get_by_scope(
                scope_id=scope.scope_id,
                seal_generation=scope.generation,
            )
            if receipt is None:
                raise ScientificAttemptError(
                    "attempt_closure_quiescence_missing",
                    "quiescent scope has no exact receipt",
                )
            scope = self.mutation_scopes.seal_scope(
                scope.scope_id,
                receipt_id=receipt.receipt_id,
            )
        elif scope.state is MutationScopeState.SEALED:
            receipt = self.repositories.quiescence_receipts.get_by_scope(
                scope_id=scope.scope_id,
                seal_generation=scope.generation,
            )
            if receipt is None:
                raise ScientificAttemptError(
                    "attempt_closure_quiescence_missing",
                    "sealed scope has no exact receipt",
                )
        else:
            raise ScientificAttemptError(
                "attempt_closure_scope_invalid",
                "attempt mutation scope cannot be finalized from its current state",
                details={"scope_state": scope.state.value},
            )
        if scope.state is not MutationScopeState.SEALED:
            raise ScientificAttemptError(
                "attempt_closure_scope_not_sealed",
                "attempt mutation scope did not reach its sealed state",
            )
        closure = self.close_attempt(
            attempt_id=attempt.attempt_id,
            selection_id=request.selection_id,
            closure_request_id=request.closure_request_id,
            quiescence_receipt_id=receipt.receipt_id,
            actor_ref=request.actor_ref,
            idempotency_key=request.idempotency_key,
        )
        self._ensure_post_closure_scope(attempt)
        return closure

    def close_attempt(
        self,
        *,
        attempt_id: str,
        selection_id: str,
        closure_request_id: str,
        quiescence_receipt_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificAttemptClosure:
        attempt = self._require_attempt(attempt_id)
        self._resolve_mutable_workflow_contract(attempt)
        actor = self._require_actor(actor_ref)
        request = {
            "command": "scientific.attempt.close",
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "closure_request_id": closure_request_id,
            "quiescence_receipt_id": quiescence_receipt_id,
            "actor_ref": actor,
            "idempotency_key": idempotency_key,
        }
        request_digest = canonical_digest(request)
        existing = self.repositories.scientific_attempt_closures.get_by_attempt(
            attempt_id
        )
        if existing is not None:
            self._require_replay_digest(existing.request_digest, request_digest)
            lifecycle = self._resolve_attempt_lifecycle(attempt)
            if lifecycle.closure != existing:
                raise ScientificAttemptError(
                    "scientific_attempt_lifecycle_invalid",
                    "scientific attempt closure does not resolve canonically",
                    details={
                        "attempt_id": attempt.attempt_id,
                        "mutation_applied": False,
                    },
                )
            return existing
        self._require_attempt_task_owner(attempt, actor_ref=actor)
        closure_request = self.repositories.scientific_attempt_closure_requests.get(
            closure_request_id
        )
        resolved_head = self._resolve_selection_head(attempt_id)
        selection = (
            None
            if resolved_head is None or resolved_head.head.selection_id != selection_id
            else resolved_head.selection
        )
        if (
            selection is None
            or selection.attempt_id != attempt_id
            or selection.state is not ScientificSelectionState.SEALED
            or closure_request is None
            or closure_request.attempt_id != attempt_id
            or closure_request.selection_id != selection_id
            or closure_request.actor_ref != actor
        ):
            raise ScientificAttemptError(
                "attempt_closure_selection_invalid",
                "attempt closure requires the exact agent request and sealed current selection",
            )
        universe = self.operation_universe(attempt_id)
        if universe.universe_digest != selection.operation_universe_digest:
            raise ScientificAttemptError(
                "attempt_closure_universe_changed",
                "operation universe changed after selection sealing",
            )
        dispositions = self.repositories.scientific_dispositions.list_by_selection(
            selection_id
        )
        adoptions = self.repositories.scientific_effect_adoptions.list_by_selection(
            selection_id
        )
        assert resolved_head is not None
        evaluation = self._selection_evaluator().evaluate(
            attempt=attempt,
            resolved_head=resolved_head,
            universe=universe,
        )
        self._raise_selection_evaluation(evaluation, for_closure=True)
        if canonical_digest([item.to_dict() for item in dispositions]) != (
            selection.disposition_digest
        ):
            raise ScientificAttemptError(
                "attempt_closure_disposition_digest_mismatch",
                "sealed disposition digest no longer reproduces",
            )
        if canonical_digest([item.to_dict() for item in adoptions]) != (
            selection.adoption_digest
        ):
            raise ScientificAttemptError(
                "attempt_closure_adoption_digest_mismatch",
                "sealed adoption digest no longer reproduces",
            )
        self._assert_attempt_quiescent(attempt)
        scope = self.repositories.mutation_scopes.get(attempt.mutation_scope_id)
        receipt = self.repositories.quiescence_receipts.get(quiescence_receipt_id)
        snapshot = self.repositories.quiescence_snapshots.get_by_receipt(
            quiescence_receipt_id
        )
        if (
            scope is None
            or receipt is None
            or snapshot is None
            or scope.state is not MutationScopeState.SEALED
            or receipt.scope_id != attempt.mutation_scope_id
            or receipt.seal_generation != scope.generation
            or scope.sealed_receipt_digest != receipt.receipt_digest
        ):
            raise ScientificAttemptError(
                "attempt_closure_quiescence_not_exact",
                "closure does not consume the exact sealed attempt scope receipt",
            )
        verify_quiescence_evidence(receipt=receipt, snapshot=snapshot)
        materializations = (
            self.repositories.scientific_artifact_materializations.list_by_selection(
                selection_id
            )
        )
        materialization_digest = canonical_digest(
            [item.to_dict() for item in materializations]
        )
        authority = self.repositories.scientific_attempt_authorizations.get(
            attempt.envelope_id
        )
        if authority is None:
            raise ScientificAttemptError(
                "attempt_closure_authority_missing",
                "attempt authorization envelope is missing",
            )
        authority_consumption_digest = canonical_digest(
            {
                "envelope_id": authority.envelope_id,
                "attempt_id": attempt.attempt_id,
                "ordinal": attempt.ordinal,
                "consumed_attempts": authority.consumed_attempts,
                "reserved_micu": authority.reserved_micu,
                "reserved_cost_microunits": authority.reserved_cost_microunits,
                "reserved_wall_time_seconds": authority.reserved_wall_time_seconds,
                "state_version": authority.state_version,
            }
        )
        closure_payload = {
            "closure_request_id": closure_request_id,
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "operation_universe_digest": universe.universe_digest,
            "disposition_digest": selection.disposition_digest,
            "adoption_digest": selection.adoption_digest,
            "materialization_digest": materialization_digest,
            "authority_consumption_digest": authority_consumption_digest,
            "quiescence_receipt_id": receipt.receipt_id,
            "quiescence_receipt_digest": receipt.receipt_digest,
        }
        closure = ScientificAttemptClosure(
            closure_id=_stable_id("attempt_closure", request_digest),
            closure_request_id=closure_request_id,
            attempt_id=attempt_id,
            selection_id=selection_id,
            operation_universe_digest=universe.universe_digest,
            disposition_digest=selection.disposition_digest,
            adoption_digest=selection.adoption_digest,
            materialization_digest=materialization_digest,
            authority_consumption_digest=authority_consumption_digest,
            quiescence_receipt_id=receipt.receipt_id,
            quiescence_receipt_digest=receipt.receipt_digest,
            closure_digest=canonical_digest(closure_payload),
            actor_ref=actor,
            idempotency_key=self._require_text("idempotency_key", idempotency_key),
            request_digest=request_digest,
            created_at=self.now(),
        )
        # Closure is an immutable post-quiescence seal derived from the exact
        # receipt.  It deliberately does not mutate Task or the sealed attempt
        # snapshot.
        return self.repositories.scientific_attempt_closures.add(closure)

    def project_session(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        limit: int = SCIENTIFIC_SELECTION_INSPECTION_MAX_LIMIT,
    ) -> dict[str, Any]:
        effective_limit = self._inspection_limit(limit)
        authorities = tuple(
            authority
            for authority in self.repositories.scientific_attempt_authorizations.list_by_session(
                session_id
            )
            if task_id is None or authority.task_id == task_id
        )
        admission_requests = tuple(
            request
            for request in self.repositories.scientific_attempt_admission_requests.list_by_session(
                session_id
            )
            if task_id is None or request.task_id == task_id
        )
        readiness = self.project_session_readiness_summary(
            session_id,
            task_id=task_id,
            limit=effective_limit,
        )
        return {
            "schema_id": "scientific_attempt_workspace@2",
            "mode": "bounded_session_summary",
            "limits": {
                "requested": limit,
                "effective": effective_limit,
            },
            "authorization_count": len(authorities),
            "authorizations": [
                {
                    "envelope_id": authority.envelope_id,
                    "task_id": authority.task_id,
                    "campaign_id": authority.campaign_id,
                    "workflow_id": authority.workflow_id,
                    "allowed_scopes": [
                        scope.value for scope in authority.allowed_scopes
                    ],
                    "allowed_effect_classes": list(authority.allowed_effect_classes),
                    "allowed_provider_count": len(authority.allowed_providers),
                    "allowed_hpc_target_count": len(authority.allowed_hpc_targets),
                    "status": authority.status.value,
                    "attempts": {
                        "consumed": authority.consumed_attempts,
                        "max": authority.max_attempts,
                        "remaining": (
                            authority.max_attempts - authority.consumed_attempts
                        ),
                    },
                    "resources": {
                        "micu": {
                            "reserved": authority.reserved_micu,
                            "max": authority.max_micu,
                        },
                        "cost_microunits": {
                            "reserved": authority.reserved_cost_microunits,
                            "max": authority.max_cost_microunits,
                        },
                        "wall_time_seconds": {
                            "reserved": authority.reserved_wall_time_seconds,
                            "max": authority.max_wall_time_seconds,
                        },
                    },
                    "expires_at": authority.expires_at,
                    "policy_digest": authority.policy_digest,
                    "state_version": authority.state_version,
                }
                for authority in authorities[:effective_limit]
            ],
            "admission_request_count": len(admission_requests),
            "admission_requests": [
                {
                    "admission_request_id": request.admission_request_id,
                    "envelope_id": request.envelope_id,
                    "task_id": request.task_id,
                    "lane_id": request.lane_id,
                    "campaign_id": request.campaign_id,
                    "workflow_id": request.workflow_id,
                    "scope": request.scope.value,
                    "workflow_contract_digest": (request.workflow_contract_digest),
                    "requested_effect_classes": list(request.requested_effect_classes),
                    "provider_authorized": request.provider is not None,
                    "hpc_target_authorized": request.hpc_target is not None,
                    "reserved": {
                        "micu": request.reserved_micu,
                        "cost_microunits": request.reserved_cost_microunits,
                        "wall_time_seconds": request.reserved_wall_time_seconds,
                    },
                    "actor_ref": request.actor_ref,
                    "finalized_attempt_id": (
                        None
                        if (
                            attempt
                            := self.repositories.scientific_attempts.get_by_admission_request(
                                request.admission_request_id
                            )
                        )
                        is None
                        else attempt.attempt_id
                    ),
                    "created_at": request.created_at,
                }
                for request in admission_requests[:effective_limit]
            ],
            "attempt_count": readiness["attempt_count"],
            "attempts": readiness["attempts"],
            "truncated": (
                len(authorities) > effective_limit
                or len(admission_requests) > effective_limit
                or bool(readiness["truncated"])
            ),
        }

    def export_closed_attempt_evidence(
        self,
        attempt_id: str,
        *,
        session_id: str,
        selection_id: str,
    ) -> dict[str, Any]:
        """Export one exact session-bound closed selection without private targets."""

        attempt = self._require_attempt(attempt_id)
        if attempt.session_id != session_id:
            raise ScientificAttemptError(
                "attempt_evidence_session_mismatch",
                "scientific attempt evidence is not bound to this session",
            )
        lifecycle = self._resolve_attempt_lifecycle(attempt)
        authority = self.repositories.scientific_attempt_authorizations.get(
            attempt.envelope_id
        )
        admission = self.repositories.scientific_attempt_admission_requests.get(
            attempt.admission_request_id
        )
        closure = lifecycle.closure
        closure_request = lifecycle.closure_request
        resolved_head = self._resolve_selection_head(attempt_id)
        selection = None if resolved_head is None else resolved_head.selection
        if (
            authority is None
            or admission is None
            or not lifecycle.is_closed
            or closure is None
            or closure_request is None
            or selection is None
            or selection.state is not ScientificSelectionState.SEALED
            or selection.selection_id != selection_id
            or closure.selection_id != selection.selection_id
        ):
            raise ScientificAttemptError(
                "attempt_evidence_not_closed",
                "scientific attempt evidence requires the exact closed selection",
            )
        receipt = self.repositories.quiescence_receipts.get(
            closure.quiescence_receipt_id
        )
        snapshot = self.repositories.quiescence_snapshots.get_by_receipt(
            closure.quiescence_receipt_id
        )
        if receipt is None or snapshot is None:
            raise ScientificAttemptError(
                "attempt_evidence_quiescence_missing",
                "scientific attempt closure has no exact quiescence evidence",
            )
        verify_quiescence_evidence(receipt=receipt, snapshot=snapshot)
        universe = self.operation_universe(attempt_id)
        dispositions = self.repositories.scientific_dispositions.list_by_selection(
            selection.selection_id
        )
        adoptions = self.repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        materializations = (
            self.repositories.scientific_artifact_materializations.list_by_selection(
                selection.selection_id
            )
        )
        authorization_payload = authority.to_dict()
        authorization_payload["allowed_provider_digests"] = [
            self._private_identity_digest(item) for item in authority.allowed_providers
        ]
        authorization_payload["allowed_hpc_target_digests"] = [
            self._private_identity_digest(item)
            for item in authority.allowed_hpc_targets
        ]
        authorization_payload.pop("allowed_providers")
        authorization_payload.pop("allowed_hpc_targets")
        admission_payload = admission.to_dict()
        admission_payload["provider_digest"] = self._private_identity_digest(
            admission.provider
        )
        admission_payload["hpc_target_digest"] = self._private_identity_digest(
            admission.hpc_target
        )
        admission_payload.pop("provider")
        admission_payload.pop("hpc_target")
        attempt_payload = attempt.to_dict()
        # The immutable closure row is the business truth for closure.  The
        # base attempt row remains append-only, so evidence must project the
        # derived terminal state just like the workspace projection does.
        attempt_payload["status"] = lifecycle.projected_status.value
        attempt_payload["provider_digest"] = self._private_identity_digest(
            attempt.provider
        )
        attempt_payload["hpc_target_digest"] = self._private_identity_digest(
            attempt.hpc_target
        )
        attempt_payload.pop("provider")
        attempt_payload.pop("hpc_target")
        universe_payload = {
            "schema_id": "scientific_operation_universe@2",
            **universe.to_dict(),
        }
        payload: dict[str, Any] = {
            "schema_id": "scientific_attempt_evidence@1",
            "attempt_authority": authorization_payload,
            "admission_request": admission_payload,
            "attempt": attempt_payload,
            "operation_universe": universe_payload,
            "selection": selection.to_dict(),
            "dispositions": [item.to_dict() for item in dispositions],
            "adoptions": [item.to_dict() for item in adoptions],
            "materializations": [item.to_dict() for item in materializations],
            "closure_request": closure_request.to_dict(),
            "quiescence": build_quiescence_evidence_envelope(
                receipt=receipt,
                snapshot=snapshot,
            ),
            "closure": closure.to_dict(),
        }
        return {
            **payload,
            "evidence_digest": canonical_digest(payload),
        }

    @staticmethod
    def _private_identity_digest(value: str | None) -> str | None:
        if value is None:
            return None
        return canonical_digest({"private_identity": value})

    def _validate_admission(
        self,
        *,
        authority: ScientificAttemptAuthorization | None,
        session_id: str,
        task_id: str,
        campaign_id: str,
        workflow_id: str,
        scope: ScientificAttemptScope,
        effect_classes: tuple[str, ...],
        provider: str | None,
        hpc_target: str | None,
        reserved_micu: int,
        reserved_cost_microunits: int,
        reserved_wall_time_seconds: int,
    ) -> None:
        if authority is None:
            raise ScientificAttemptError(
                "authorization_required",
                "a durable attempt authorization envelope is required",
                hint="Ask the user or operator for an exact attempt authorization.",
            )
        if (
            authority.session_id != session_id
            or authority.task_id != task_id
            or authority.campaign_id != campaign_id
            or authority.workflow_id != workflow_id
        ):
            raise ScientificAttemptError(
                "authorization_scope_mismatch",
                "attempt request does not match the authorization scope",
            )
        if authority.status is not ScientificAttemptAuthorityStatus.ACTIVE:
            raise ScientificAttemptError(
                "authorization_exhausted",
                "attempt authorization is not active",
                details={"status": authority.status.value},
            )
        if _parse_timestamp(authority.expires_at, field_name="expires_at") <= (
            _parse_timestamp(self.now(), field_name="now")
        ):
            raise ScientificAttemptError(
                "authorization_expired",
                "attempt authorization has expired",
                details={"expires_at": authority.expires_at},
            )
        if scope not in authority.allowed_scopes:
            raise ScientificAttemptError(
                "authorization_scope_forbidden",
                "requested scientific scope is not authorized",
                details={"requested_scope": scope.value},
            )
        forbidden_effects = sorted(
            set(effect_classes) - set(authority.allowed_effect_classes)
        )
        if forbidden_effects:
            raise ScientificAttemptError(
                "authorization_effect_forbidden",
                "one or more requested effect classes are not authorized",
                details={"forbidden_effect_classes": forbidden_effects},
            )
        if provider is not None and provider not in authority.allowed_providers:
            raise ScientificAttemptError(
                "authorization_provider_forbidden",
                "requested provider is not authorized",
                details={"provider": provider},
            )
        if hpc_target is not None and hpc_target not in authority.allowed_hpc_targets:
            raise ScientificAttemptError(
                "authorization_hpc_target_forbidden",
                "requested HPC target is not authorized",
                details={"hpc_target_authorized": False},
            )
        requested = (
            reserved_micu,
            reserved_cost_microunits,
            reserved_wall_time_seconds,
        )
        if any(type(value) is not int or value < 0 for value in requested):
            raise ScientificAttemptError(
                "authorization_resource_invalid",
                "attempt resource reservations must be non-negative",
            )
        blockers: dict[str, dict[str, int]] = {}
        for name, current, requested_value, maximum in (
            (
                "micu",
                authority.reserved_micu,
                reserved_micu,
                authority.max_micu,
            ),
            (
                "cost_microunits",
                authority.reserved_cost_microunits,
                reserved_cost_microunits,
                authority.max_cost_microunits,
            ),
            (
                "wall_time_seconds",
                authority.reserved_wall_time_seconds,
                reserved_wall_time_seconds,
                authority.max_wall_time_seconds,
            ),
        ):
            if current + requested_value > maximum:
                blockers[name] = {
                    "reserved": current,
                    "requested": requested_value,
                    "maximum": maximum,
                }
        if authority.consumed_attempts >= authority.max_attempts:
            blockers["attempts"] = {
                "reserved": authority.consumed_attempts,
                "requested": 1,
                "maximum": authority.max_attempts,
            }
        if blockers:
            raise ScientificAttemptError(
                "authorization_resource_exceeded",
                "attempt request exceeds its durable authorization envelope",
                details={"resource_blockers": blockers},
            )

    def _assert_no_campaign_unknown_effect(
        self,
        *,
        session_id: str,
        task_id: str,
        campaign_id: str,
    ) -> None:
        rows = self.repositories.tasks.connection.execute(
            """
            SELECT
                execution.operation_id,
                execution.execution_id,
                execution.lifecycle_state,
                execution.effect_certainty
            FROM controlled_operation_execution_records AS execution
            JOIN scientific_attempt_operation_bindings AS binding
              ON binding.operation_id = execution.operation_id
            JOIN scientific_attempt_records AS attempt
              ON attempt.attempt_id = binding.attempt_id
            WHERE attempt.session_id = ?
              AND attempt.task_id = ?
              AND attempt.campaign_id = ?
              AND (
                  execution.effect_certainty = 'dispatch_in_doubt'
                  OR execution.lifecycle_state = 'reconcile_required'
              )
            ORDER BY execution.operation_id
            """,
            (session_id, task_id, campaign_id),
        ).fetchall()
        if rows:
            raise ScientificAttemptError(
                "attempt_unknown_effect_blocker",
                "an earlier campaign occurrence still has an unknown external effect",
                hint="Reconcile the exact controlled operation before creating another attempt.",
                details={
                    "operation_ids": [str(row["operation_id"]) for row in rows],
                    "reconciliation_required": True,
                },
            )

    def _seal_pre_attempt_scope(self, session_id: str) -> str | None:
        active = [
            scope
            for scope in self.repositories.mutation_scopes.list_by_session(session_id)
            if scope.state
            in {
                MutationScopeState.OPEN,
                MutationScopeState.FREEZING,
                MutationScopeState.QUIESCENT,
            }
        ]
        if not active:
            return None
        if len(active) != 1:
            raise ScientificAttemptError(
                "attempt_admission_scope_ambiguous",
                "session has more than one active mutation scope",
            )
        scope = active[0]
        if scope.scope_kind is MutationScopeKind.ATTEMPT:
            raise ScientificAttemptError(
                "attempt_admission_prior_attempt_unclosed",
                "an existing attempt mutation scope is still active",
                details={"scope_ref": scope.scope_ref},
            )
        active_writers = self.repositories.mutation_writers.list_active(scope.scope_id)
        if active_writers:
            raise ScientificAttemptError(
                "attempt_admission_writers_active",
                "pre-attempt session scope still has active writers",
                details={"writer_ids": [writer.writer_id for writer in active_writers]},
                retryable=True,
            )
        if scope.state is MutationScopeState.OPEN:
            scope = self.mutation_scopes.begin_freeze(scope.scope_id)
        if scope.state is MutationScopeState.FREEZING:
            issued = self.mutation_scopes.issue_quiescence_receipt(scope.scope_id)
            scope = self.mutation_scopes.seal_scope(
                scope.scope_id,
                receipt_id=issued.receipt.receipt_id,
            )
        elif scope.state is MutationScopeState.QUIESCENT:
            receipt = self.repositories.quiescence_receipts.get_by_scope(
                scope_id=scope.scope_id,
                seal_generation=scope.generation,
            )
            if receipt is None:
                raise ScientificAttemptError(
                    "attempt_admission_quiescence_missing",
                    "quiescent pre-attempt scope has no exact receipt",
                )
            scope = self.mutation_scopes.seal_scope(
                scope.scope_id,
                receipt_id=receipt.receipt_id,
            )
        if scope.state is not MutationScopeState.SEALED:
            raise ScientificAttemptError(
                "attempt_admission_scope_not_sealed",
                "pre-attempt session scope did not reach its sealed state",
            )
        return scope.scope_id

    def _ensure_post_closure_scope(self, attempt: ScientificAttempt) -> None:
        scopes = self.repositories.mutation_scopes.list_by_session(attempt.session_id)
        children = [
            scope
            for scope in scopes
            if scope.parent_scope_id == attempt.mutation_scope_id
        ]
        if children:
            if len(children) != 1:
                raise ScientificAttemptError(
                    "attempt_post_closure_scope_ambiguous",
                    "attempt closure has more than one follow-up mutation scope",
                    details={"scope_ids": sorted(scope.scope_id for scope in children)},
                )
            child = children[0]
            expected_scope_id = scientific_attempt_post_scope_id(attempt.attempt_id)
            expected_scope_ref = scientific_attempt_post_scope_ref(attempt.attempt_id)
            if (
                child.scope_id != expected_scope_id
                or child.session_id != attempt.session_id
                or child.scope_kind is not MutationScopeKind.SESSION
                or child.scope_ref != expected_scope_ref
            ):
                raise ScientificAttemptError(
                    "attempt_post_closure_scope_identity_invalid",
                    "attempt closure follow-up mutation scope has drifted identity",
                    details={"scope_id": child.scope_id},
                )
            return
        active = [
            scope
            for scope in scopes
            if scope.state
            in {
                MutationScopeState.OPEN,
                MutationScopeState.FREEZING,
                MutationScopeState.QUIESCENT,
            }
        ]
        if active:
            raise ScientificAttemptError(
                "attempt_post_closure_scope_conflict",
                "session has an unrelated active scope after attempt closure",
                details={"scope_ids": [scope.scope_id for scope in active]},
            )
        self.mutation_scopes.open_scope(
            session_id=attempt.session_id,
            scope_kind=MutationScopeKind.SESSION,
            scope_ref=scientific_attempt_post_scope_ref(attempt.attempt_id),
            parent_scope_id=attempt.mutation_scope_id,
            scope_id=scientific_attempt_post_scope_id(attempt.attempt_id),
        )

    def _resolve_operation_adoption_replay(
        self,
        *,
        selection: ScientificChainSelection,
        attempt: ScientificAttempt,
        operation_id: str,
        workflow_role: str,
        reason_code: str,
        actor_ref: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ScientificOperationAdoptionResult | None:
        disposition = self.repositories.scientific_dispositions.get_by_idempotency(
            selection_id=selection.selection_id,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
        )
        adoption = self.repositories.scientific_effect_adoptions.get_by_idempotency(
            selection_id=selection.selection_id,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
        )
        if disposition is None and adoption is None:
            return None
        if (
            disposition is None
            or adoption is None
            or disposition.disposition_id != _stable_id("disposition", request_digest)
            or adoption.adoption_id != _stable_id("adoption", request_digest)
            or disposition.selection_id != selection.selection_id
            or adoption.selection_id != selection.selection_id
            or disposition.attempt_id != attempt.attempt_id
            or adoption.attempt_id != attempt.attempt_id
            or disposition.operation_id != operation_id
            or adoption.operation_id != operation_id
            or disposition.kind is not ScientificOperationDispositionKind.ADOPTED
            or disposition.workflow_role != workflow_role
            or adoption.workflow_role != workflow_role
            or disposition.reason_code != reason_code
            or disposition.replacement_operation_id is not None
            or disposition.actor_ref != actor_ref
            or adoption.actor_ref != actor_ref
            or disposition.idempotency_key != idempotency_key
            or adoption.idempotency_key != idempotency_key
            or disposition.request_digest != request_digest
            or adoption.request_digest != request_digest
            or disposition.created_at != adoption.created_at
        ):
            raise ScientificAttemptError(
                "scientific_operation_adoption_integrity_conflict",
                "atomic scientific adoption replay is partial or mismatched",
                details=self._operation_adoption_error_details(
                    attempt=attempt,
                    selection=selection,
                    operation_id=operation_id,
                    requested_role=workflow_role,
                    error_code=("scientific_operation_adoption_integrity_conflict"),
                ),
            )
        return ScientificOperationAdoptionResult(
            disposition=disposition,
            adoption=adoption,
        )

    def _require_operation_adoption_slot_available(
        self,
        *,
        selection_id: str,
        operation_id: str,
        workflow_role: str,
    ) -> None:
        dispositions = self.repositories.scientific_dispositions.list_by_selection(
            selection_id
        )
        adoptions = self.repositories.scientific_effect_adoptions.list_by_selection(
            selection_id
        )
        conflicting_dispositions = tuple(
            disposition
            for disposition in dispositions
            if disposition.operation_id == operation_id
            or (
                disposition.kind is ScientificOperationDispositionKind.ADOPTED
                and disposition.workflow_role == workflow_role
            )
        )
        conflicting_adoptions = tuple(
            adoption
            for adoption in adoptions
            if adoption.operation_id == operation_id
            or adoption.workflow_role == workflow_role
        )
        if conflicting_dispositions or conflicting_adoptions:
            raise ScientificAttemptError(
                "scientific_operation_adoption_conflict",
                "operation or workflow role already has different selection facts",
                details={
                    "current_disposition_ids": [
                        item.disposition_id for item in conflicting_dispositions[:4]
                    ],
                    "current_adoption_ids": [
                        item.adoption_id for item in conflicting_adoptions[:4]
                    ],
                    "mutation_applied": False,
                },
            )

    def _enrich_operation_adoption_error(
        self,
        error: ScientificAttemptError,
        *,
        attempt: ScientificAttempt,
        selection: ScientificChainSelection,
        operation_id: str,
        requested_role: str | None,
    ) -> ScientificAttemptError:
        details = self._operation_adoption_error_details(
            attempt=attempt,
            selection=selection,
            operation_id=operation_id,
            requested_role=requested_role,
            error_code=error.error_code,
        )
        details.update(
            {
                key: value
                for key, value in error.details.items()
                if key not in {"boundary", "disposition"}
            }
        )
        details["mutation_applied"] = False
        return ScientificAttemptError(
            error.error_code,
            str(error),
            hint=error.hint,
            details=details,
            retryable=error.retryable,
        )

    def _operation_adoption_error_details(
        self,
        *,
        attempt: ScientificAttempt,
        selection: ScientificChainSelection,
        operation_id: str,
        requested_role: str | None,
        error_code: str,
    ) -> dict[str, Any]:
        resolved_head = self._resolve_selection_head(attempt.attempt_id)
        head = None if resolved_head is None else resolved_head.head
        occurrence_ids = {
            item.operation_id
            for item in self.repositories.scientific_selections.list_occurrences(
                selection.selection_id
            )
        }
        operation = (
            None
            if operation_id not in occurrence_ids
            else self.repositories.controlled_operations.get(operation_id)
        )
        dispositions = self.repositories.scientific_dispositions.list_by_selection(
            selection.selection_id
        )
        adoptions = self.repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        current_disposition = next(
            (item for item in dispositions if item.operation_id == operation_id),
            None,
        )
        current_adoption = next(
            (item for item in adoptions if item.operation_id == operation_id),
            None,
        )
        contract = self._resolve_readable_workflow_contract(attempt)
        if isinstance(contract, HistoricalScientificWorkflowContract):
            allowed_roles = tuple(
                role["role_id"] for role in contract.project(attempt.scope)["roles"]
            )
            compatible_roles: tuple[str, ...] = ()
        else:
            allowed_roles = contract.allowed_roles(attempt.scope)
            compatible_roles = (
                ()
                if operation is None
                else contract.compatible_roles(attempt.scope, operation)
            )
        evaluation = (
            None
            if resolved_head is None
            else self._selection_evaluator().evaluate(
                attempt=attempt,
                resolved_head=resolved_head,
                universe=self.operation_universe(attempt.attempt_id),
            )
        )
        retry_boundary = (
            "refresh_exact_selection"
            if error_code
            in {
                "selection_not_current_head",
                "selection_universe_changed",
                "selection_operation_out_of_universe",
            }
            else "reconcile_external_effect"
            if error_code
            in {
                "selection_unknown_effect",
                "effect_adoption_not_terminal_known",
            }
            else "none"
            if "integrity_conflict" in error_code
            else "agent_replan"
        )
        return {
            "attempt_id": attempt.attempt_id,
            "selection_id": selection.selection_id,
            "selection_revision": selection.revision,
            "selection_state": selection.state.value,
            "current_selection_id": (None if head is None else head.selection_id),
            "current_selection_revision": (None if head is None else head.revision),
            "head_state_version": (None if head is None else head.state_version),
            "operation_id": operation_id,
            "operation_signature": (
                None
                if operation is None
                else {
                    "sdk_module": operation.sdk_module,
                    "function_name": operation.function_name,
                }
            ),
            "required_disposition_kind": "adopted",
            "requested_role": requested_role,
            "allowed_roles": list(allowed_roles),
            "compatible_roles": list(compatible_roles),
            "current_disposition": (
                None
                if current_disposition is None
                else {
                    "disposition_id": current_disposition.disposition_id,
                    "kind": current_disposition.kind.value,
                    "workflow_role": current_disposition.workflow_role,
                }
            ),
            "current_adoption": (
                None
                if current_adoption is None
                else {
                    "adoption_id": current_adoption.adoption_id,
                    "workflow_role": current_adoption.workflow_role,
                }
            ),
            "blocker_codes": (
                ["selection_head_missing"]
                if evaluation is None
                else list(evaluation.blocker_codes)
            ),
            "bounded_operation_ids": (
                {}
                if evaluation is None
                else evaluation.summary()["bounded_operation_ids"]
            ),
            "retry_boundary": retry_boundary,
            "mutation_applied": False,
        }

    def _require_adoptable_execution(
        self,
        *,
        attempt: ScientificAttempt,
        operation_id: str,
    ) -> tuple[ControlledOperation, ControlledOperationExecution, Any]:
        if (
            self.repositories.scientific_attempt_bindings.attempt_for_operation(
                operation_id
            )
            != attempt.attempt_id
        ):
            raise ScientificAttemptError(
                "effect_adoption_cross_attempt",
                "effect adoption crossed its formal attempt boundary",
            )
        operation = self.repositories.controlled_operations.get(operation_id)
        execution = (
            self.repositories.controlled_operation_executions.get_by_operation_id(
                operation_id
            )
        )
        if operation is None or execution is None:
            raise ScientificAttemptError(
                "effect_adoption_execution_missing",
                "effect adoption requires a canonical durable execution",
            )
        if (
            execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.TERMINAL
            or execution.terminal_outcome
            is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            or execution.effect_certainty
            not in {
                ExternalEffectCertainty.EFFECT_KNOWN,
                ExternalEffectCertainty.TERMINAL_KNOWN,
            }
            or execution.result_handle_ref is None
        ):
            raise ScientificAttemptError(
                "effect_adoption_not_terminal_known",
                "effect adoption requires a successful terminal known execution",
                details={
                    "operation_id": operation_id,
                    "lifecycle_state": execution.lifecycle_state.value,
                    "effect_certainty": execution.effect_certainty.value,
                },
            )
        result = self.repositories.controlled_operation_results.get(
            execution.result_handle_ref
        )
        if (
            result is None
            or result.operation_id != operation_id
            or result.execution_id != execution.execution_id
            or result.terminal_outcome
            is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            or result.result_digest != execution.result_digest
            or result.artifact_set_digest != execution.artifact_set_digest
        ):
            raise ScientificAttemptError(
                "effect_adoption_result_invalid",
                "immutable controlled-operation result is missing or inconsistent",
            )
        try:
            self.repositories.controlled_operation_result_artifacts.assert_exact(result)
        except ImmutableIdentityConflictError as exc:
            raise ScientificAttemptError(
                "effect_adoption_result_invalid",
                "immutable controlled-operation artifact set is inconsistent",
            ) from exc
        if operation.approval_id is not None and (
            operation.approval_state != "approved" or execution.approval_digest is None
        ):
            raise ScientificAttemptError(
                "effect_adoption_approval_invalid",
                "controlled effect lacks exact approved authority",
            )
        return operation, execution, result

    def _validate_workflow_role(
        self,
        *,
        attempt: ScientificAttempt,
        selection: ScientificChainSelection,
        workflow_role: str,
        operation: ControlledOperation,
        execution: ControlledOperationExecution,
    ) -> None:
        if selection.workflow_contract_digest != attempt.workflow_contract_digest:
            raise ScientificAttemptError(
                "workflow_contract_digest_mismatch",
                "selection does not bind the attempt workflow contract",
            )
        if self.workflow_contract_registry is None:
            raise ScientificAttemptError(
                "workflow_contract_registry_missing",
                "Host has no registry for the bound scientific workflow contract",
            )
        try:
            self.workflow_contract_registry.validate_role(
                attempt=attempt,
                selection=selection,
                workflow_role=workflow_role,
                operation=operation,
                execution=execution,
            )
        except ScientificWorkflowContractError as exc:
            raise ScientificAttemptError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc

    def _assert_attempt_quiescent(self, attempt: ScientificAttempt) -> None:
        operation_ids = [
            item["operation_id"]
            for item in self.repositories.scientific_attempt_bindings.list_operations(
                attempt.attempt_id
            )
        ]
        for operation_id in operation_ids:
            execution = (
                self.repositories.controlled_operation_executions.get_by_operation_id(
                    operation_id
                )
            )
            if execution is not None and (
                execution.lifecycle_state
                is not ControlledOperationExecutionLifecycle.TERMINAL
                or execution.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ):
                raise ScientificAttemptError(
                    "attempt_closure_effect_unresolved",
                    "attempt has an active or unknown-effect controlled operation",
                    details={"operation_id": operation_id},
                )
        for run_id in self.repositories.scientific_attempt_bindings.list_runs(
            attempt.attempt_id
        ):
            run = self.repositories.sandbox_runs.get(run_id)
            if run is None or not run.status.is_terminal:
                raise ScientificAttemptError(
                    "attempt_closure_process_active",
                    "attempt has a missing or nonterminal sandbox run",
                    details={"sandbox_run_id": run_id},
                )

    def _require_draft_head(
        self,
        selection_id: str,
    ) -> tuple[ScientificChainSelection, ScientificAttempt]:
        selection = self.repositories.scientific_selections.get(selection_id)
        if selection is None:
            raise ScientificAttemptError(
                "selection_missing",
                "scientific selection does not exist",
            )
        attempt = self._require_mutation_admissible_attempt(selection.attempt_id)
        self._resolve_mutable_workflow_contract(attempt)
        resolved_head = self._resolve_selection_head(selection.attempt_id)
        if resolved_head is None or resolved_head.head.selection_id != selection_id:
            raise ScientificAttemptError(
                "selection_not_current_head",
                "scientific selection is not the current CAS head",
                retryable=True,
            )
        selection = resolved_head.selection
        if selection.state is not ScientificSelectionState.DRAFT:
            raise ScientificAttemptError(
                "selection_not_draft",
                "scientific selection revision is immutable after sealing",
            )
        return selection, attempt

    def _selection_evaluator(self) -> ScientificSelectionEvaluator:
        if self.workflow_contract_registry is None:
            raise ScientificAttemptError(
                "workflow_contract_registry_missing",
                "Host has no scientific workflow contract registry",
                details={"mutation_applied": False},
            )
        return ScientificSelectionEvaluator(
            repositories=self.repositories,
            workflow_contract_registry=self.workflow_contract_registry,
        )

    @staticmethod
    def _raise_selection_evaluation(
        evaluation: ScientificSelectionEvaluation,
        *,
        for_closure: bool,
    ) -> None:
        blockers = tuple(
            issue
            for issue in evaluation.issues
            if (issue.blocks_closure if for_closure else issue.blocks_seal)
        )
        if not blockers:
            return
        details = evaluation.summary()
        details.update(
            {
                "mutation_applied": False,
                "validation_boundary": (
                    "attempt_closure" if for_closure else "selection_seal"
                ),
            }
        )
        raise ScientificAttemptError(
            blockers[0].code,
            "scientific selection is not ready for the requested transition",
            details=details,
            retryable=blockers[0].code
            in {
                "selection_not_current_head",
                "selection_universe_changed",
                "selection_active_writers",
                "selection_process_active",
                "selection_continuation_active",
            },
        )

    def _resolve_readable_workflow_contract(
        self,
        attempt: ScientificAttempt,
    ) -> ScientificWorkflowContract | HistoricalScientificWorkflowContract:
        if self.workflow_contract_registry is None:
            raise ScientificAttemptError(
                "workflow_contract_registry_missing",
                "Host has no scientific workflow contract registry",
                details={"mutation_applied": False},
            )
        try:
            return self.workflow_contract_registry.resolve_attempt(attempt)
        except ScientificWorkflowContractError as exc:
            raise ScientificAttemptError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc

    @staticmethod
    def _inspection_limit(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > SCIENTIFIC_SELECTION_INSPECTION_MAX_LIMIT
        ):
            raise ScientificAttemptError(
                "scientific_inspection_limit_invalid",
                "scientific selection inspection limit is outside the bounded range",
                details={
                    "minimum": 1,
                    "maximum": SCIENTIFIC_SELECTION_INSPECTION_MAX_LIMIT,
                    "mutation_applied": False,
                },
            )
        return value

    @staticmethod
    def _encode_inspection_cursor(
        *,
        attempt_id: str,
        selection_id: str,
        head_state_version: int,
        operation_universe_digest: str,
        offset: int,
    ) -> str:
        payload = json.dumps(
            {
                "schema_id": "scientific_selection_cursor@1",
                "attempt_id": attempt_id,
                "selection_id": selection_id,
                "head_state_version": head_state_version,
                "operation_universe_digest": operation_universe_digest,
                "offset": offset,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii")

    @staticmethod
    def _decode_inspection_cursor(
        cursor: str | None,
        *,
        attempt_id: str,
        selection_id: str,
        head_state_version: int,
        operation_universe_digest: str,
        occurrence_count: int,
    ) -> int:
        if cursor is None:
            return 0
        if not isinstance(cursor, str) or not cursor or len(cursor) > 2048:
            raise ScientificAttemptError(
                "scientific_inspection_cursor_invalid",
                "scientific selection inspection cursor is invalid",
                details={"mutation_applied": False},
            )
        try:
            decoded = base64.b64decode(
                cursor.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            payload = json.loads(decoded.decode("utf-8"))
        except (
            UnicodeError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ScientificAttemptError(
                "scientific_inspection_cursor_invalid",
                "scientific selection inspection cursor is invalid",
                details={"mutation_applied": False},
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_id") != "scientific_selection_cursor@1"
            or payload.get("attempt_id") != attempt_id
            or payload.get("selection_id") != selection_id
            or payload.get("head_state_version") != head_state_version
            or payload.get("operation_universe_digest") != operation_universe_digest
            or isinstance(payload.get("offset"), bool)
            or not isinstance(payload.get("offset"), int)
            or payload["offset"] < 0
            or payload["offset"] >= occurrence_count
        ):
            raise ScientificAttemptError(
                "scientific_inspection_cursor_invalid",
                "scientific selection inspection cursor is stale or mismatched",
                details={"mutation_applied": False},
            )
        return int(payload["offset"])

    def _resolve_new_workflow_contract(
        self,
        *,
        workflow_id: str,
        workflow_contract_digest: str,
        scope: ScientificAttemptScope,
    ) -> ScientificWorkflowContract:
        if self.workflow_contract_registry is None:
            raise ScientificAttemptError(
                "workflow_contract_registry_missing",
                "Host has no scientific workflow contract registry",
                details={"mutation_applied": False},
            )
        try:
            contract = self.workflow_contract_registry.resolve(
                workflow_id=workflow_id,
                workflow_contract_digest=workflow_contract_digest,
                for_new_attempt=True,
            )
            assert isinstance(contract, ScientificWorkflowContract)
            contract.scope_policy(scope)
            return contract
        except ScientificWorkflowContractError as exc:
            raise ScientificAttemptError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc

    def _resolve_mutable_workflow_contract(
        self,
        attempt: ScientificAttempt,
    ) -> ScientificWorkflowContract:
        if self.workflow_contract_registry is None:
            raise ScientificAttemptError(
                "workflow_contract_registry_missing",
                "Host has no scientific workflow contract registry",
                details={"mutation_applied": False},
            )
        try:
            contract = self.workflow_contract_registry.resolve_attempt(attempt)
            if isinstance(contract, HistoricalScientificWorkflowContract):
                raise ScientificWorkflowContractError(
                    "workflow_contract_historical_read_only",
                    "historical workflow contract cannot authorize selection mutation",
                    details={
                        "contract_id": contract.contract_id,
                        "workflow_contract_digest": contract.digest,
                    },
                )
            contract.scope_policy(attempt.scope)
            return contract
        except ScientificWorkflowContractError as exc:
            raise ScientificAttemptError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc

    def _resolve_selection_head(
        self,
        attempt_id: str,
    ) -> ResolvedScientificSelectionHead | None:
        try:
            return self.repositories.scientific_selections.resolve_head(attempt_id)
        except ScientificSelectionIntegrityError as exc:
            raise ScientificAttemptError(
                exc.error_code,
                "scientific selection head does not resolve to canonical state",
                details={
                    "attempt_id": attempt_id,
                    "integrity_reason": exc.reason_code,
                    "mutation_applied": False,
                },
            ) from exc

    def _require_attempt(self, attempt_id: str) -> ScientificAttempt:
        attempt = self.repositories.scientific_attempts.get(attempt_id)
        if attempt is None:
            raise ScientificAttemptError(
                "attempt_missing",
                "scientific attempt does not exist",
            )
        return attempt

    def _require_attempt_task_owner(
        self,
        attempt: ScientificAttempt,
        *,
        actor_ref: str,
    ) -> None:
        task = self.repositories.tasks.get(attempt.task_id)
        if (
            task is None
            or task.session_id != attempt.session_id
            or task.assigned_ref != actor_ref
        ):
            raise ScientificAttemptError(
                "attempt_closure_actor_not_owner",
                (
                    "scientific attempt closure can be requested only by the "
                    "current assignee of its canonical task"
                ),
                hint=(
                    "Inspect the task assignment and let its canonical assignee "
                    "request closure."
                ),
                details={
                    "attempt_id": attempt.attempt_id,
                    "task_id": attempt.task_id,
                    "assigned_ref": None if task is None else task.assigned_ref,
                    "actor_ref": actor_ref,
                    "mutation_applied": False,
                },
                retryable=True,
            )

    def resolve_attempt_lifecycle(
        self,
        attempt_id: str,
    ) -> ResolvedScientificAttemptLifecycle:
        """Resolve one attempt lifecycle and sanitize private integrity errors."""

        return self._resolve_attempt_lifecycle(self._require_attempt(attempt_id))

    def _resolve_attempt_lifecycle(
        self,
        attempt: ScientificAttempt,
    ) -> ResolvedScientificAttemptLifecycle:
        try:
            return self.attempt_lifecycles.resolve(attempt)
        except ScientificAttemptLifecycleIntegrityError as exc:
            raise ScientificAttemptError(
                exc.error_code,
                "scientific attempt lifecycle evidence is inconsistent",
                details=exc.details,
            ) from exc

    def _require_active_attempt(self, attempt_id: str) -> ScientificAttempt:
        """Require an active record while allowing exact closure-request replay."""

        attempt = self._require_attempt(attempt_id)
        lifecycle = self._resolve_attempt_lifecycle(attempt)
        if lifecycle.is_closed:
            raise ScientificAttemptError(
                "attempt_already_closed",
                "scientific attempt already has an immutable closure",
            )
        if lifecycle.record_status is not ScientificAttemptStatus.ACTIVE:
            raise ScientificAttemptError(
                "attempt_not_active",
                "scientific attempt does not accept further mutation",
                details={
                    "status": lifecycle.projected_status.value,
                    "lifecycle_phase": lifecycle.phase.value,
                },
            )
        return attempt

    def _require_mutation_admissible_attempt(
        self,
        attempt_id: str,
    ) -> ScientificAttempt:
        attempt = self._require_attempt(attempt_id)
        lifecycle = self._resolve_attempt_lifecycle(attempt)
        if lifecycle.accepts_scientific_mutation:
            return attempt
        if lifecycle.is_closed:
            raise ScientificAttemptError(
                "attempt_already_closed",
                "scientific attempt already has an immutable closure",
            )
        if lifecycle.closure_requested:
            raise ScientificAttemptError(
                "attempt_closure_already_requested",
                "no new scientific occurrence or selection revision is allowed after closure intent",
                details={
                    "closure_request_id": lifecycle.closure_request_id,
                },
            )
        raise ScientificAttemptError(
            "attempt_not_active",
            "scientific attempt does not accept further mutation",
            details={
                "status": lifecycle.projected_status.value,
                "lifecycle_phase": lifecycle.phase.value,
            },
        )

    def _require_closure_not_requested(self, attempt_id: str) -> None:
        lifecycle = self.resolve_attempt_lifecycle(attempt_id)
        if lifecycle.is_closed:
            raise ScientificAttemptError(
                "attempt_already_closed",
                "scientific attempt already has an immutable closure",
            )
        if lifecycle.closure_requested:
            raise ScientificAttemptError(
                "attempt_closure_already_requested",
                "no new scientific occurrence or selection revision is allowed after closure intent",
                details={
                    "closure_request_id": lifecycle.closure_request_id,
                },
            )

    @staticmethod
    def _require_actor(actor_ref: str) -> str:
        return ScientificAttemptService._require_text("actor_ref", actor_ref)

    @staticmethod
    def _require_text(field_name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ScientificAttemptError(
                "scientific_command_invalid",
                f"{field_name} must be non-empty",
            )
        return value.strip()

    @staticmethod
    def _require_replay_digest(existing: str, requested: str) -> None:
        if existing != requested:
            raise ScientificAttemptIdentityConflictError(
                "idempotency key was reused with a different scientific command"
            )


__all__ = [
    "EMPTY_ADOPTION_DIGEST",
    "EMPTY_DISPOSITION_DIGEST",
    "SCIENTIFIC_ATTEMPT_AUTHORIZATION_POLICY_ID",
    "ScientificAttemptError",
    "ScientificAttemptService",
    "ScientificOperationUniverse",
]
