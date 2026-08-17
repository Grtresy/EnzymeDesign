from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptAuthorityStatus
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import ScientificSelectionState

from .repositories import CoreRepositories
from .scientific_attempt_repositories import ResolvedScientificSelectionHead
from .scientific_workflow_contracts import HistoricalScientificWorkflowContract
from .scientific_workflow_contracts import ScientificWorkflowContract
from .scientific_workflow_contracts import ScientificWorkflowContractError
from .scientific_workflow_contracts import ScientificWorkflowContractRegistry

if TYPE_CHECKING:
    from .scientific_attempts import ScientificOperationUniverse


_ISSUE_PRIORITY = {
    "selection_disposition_incomplete": 10,
    "selection_universe_changed": 20,
    "selection_state_not_sealable": 21,
    "selection_attempt_authority_missing": 22,
    "selection_attempt_authority_mismatch": 23,
    "selection_attempt_authority_invalid": 24,
    "selection_operation_missing": 30,
    "selection_unknown_effect": 40,
    "selection_occurrence_not_closed": 50,
    "selection_adoption_incomplete": 60,
    "selection_adoption_unexpected": 70,
    "selection_workflow_role_duplicated": 80,
    "workflow_role_invalid": 90,
    "workflow_role_operation_kind_invalid": 91,
    "workflow_role_operation_scope_invalid": 92,
    "workflow_contract_digest_mismatch": 93,
    "workflow_contract_digest_unsupported": 94,
    "workflow_contract_historical_read_only": 95,
    "selection_adopted_chain_empty": 100,
}


@dataclass(frozen=True, slots=True)
class ScientificSelectionIssue:
    code: str
    operation_ids: tuple[str, ...] = ()
    workflow_roles: tuple[str, ...] = ()
    facts: tuple[tuple[str, str | int | bool | None], ...] = ()
    blocks_seal: bool = True
    blocks_closure: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "operation_ids": list(self.operation_ids),
            "workflow_roles": list(self.workflow_roles),
            "facts": dict(self.facts),
            "blocks_seal": self.blocks_seal,
            "blocks_closure": self.blocks_closure,
        }


@dataclass(frozen=True, slots=True)
class ScientificSelectionOccurrenceEvaluation:
    operation_id: str
    sandbox_run_id: str
    sdk_module: str | None
    function_name: str | None
    operation_status: str
    execution_id: str | None
    lifecycle_state: str | None
    terminal_outcome: str | None
    effect_certainty: str | None
    disposition_id: str | None
    disposition_kind: str | None
    disposition_role: str | None
    adoption_id: str | None
    adoption_role: str | None
    allowed_roles: tuple[str, ...]
    compatible_roles: tuple[str, ...]
    issue_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "sandbox_run_id": self.sandbox_run_id,
            "operation_signature": {
                "sdk_module": self.sdk_module,
                "function_name": self.function_name,
            },
            "operation_status": self.operation_status,
            "execution": {
                "execution_id": self.execution_id,
                "lifecycle_state": self.lifecycle_state,
                "terminal_outcome": self.terminal_outcome,
                "effect_certainty": self.effect_certainty,
            },
            "disposition": {
                "disposition_id": self.disposition_id,
                "kind": self.disposition_kind,
                "workflow_role": self.disposition_role,
            },
            "adoption": {
                "adoption_id": self.adoption_id,
                "workflow_role": self.adoption_role,
            },
            "allowed_roles": list(self.allowed_roles),
            "compatible_roles": list(self.compatible_roles),
            "issue_codes": list(self.issue_codes),
        }


@dataclass(frozen=True, slots=True)
class ScientificSelectionEvaluation:
    attempt_id: str
    selection_id: str
    selection_revision: int
    selection_state: str
    head_state_version: int
    operation_universe_digest: str
    operation_count: int
    workflow_contract_digest: str
    contract_id: str | None
    contract_schema_id: str | None
    occurrences: tuple[ScientificSelectionOccurrenceEvaluation, ...]
    issues: tuple[ScientificSelectionIssue, ...]

    @property
    def seal_ready(self) -> bool:
        return not any(issue.blocks_seal for issue in self.issues)

    @property
    def closure_ready(self) -> bool:
        """Return legacy Host-finalization readiness.

        The field predates the request/finalization split and remains in the
        projection for compatibility. It now includes the sealed-state
        precondition so a draft selection cannot look closure-ready.
        """

        return (
            self.selection_state == ScientificSelectionState.SEALED.value
            and not any(issue.blocks_closure for issue in self.issues)
        )

    @property
    def closure_request_ready(self) -> bool:
        """Return whether the sealed selection can support closure intent.

        A requesting agent turn is itself an active mutation writer. Closure
        intent is therefore validated against the same evidence boundary as
        selection sealing; writer retirement is a Host-finalization concern.
        """

        return (
            self.selection_state == ScientificSelectionState.SEALED.value
            and self.seal_ready
        )

    @property
    def closure_finalization_ready(self) -> bool:
        """Return whether the selection side is ready for Host finalization."""

        return self.closure_ready

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(issue.code for issue in self.issues))

    @property
    def gap_counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for issue in self.issues:
            counts[issue.code] += max(len(issue.operation_ids), 1)
        return dict(counts)

    def summary(self, *, max_ids: int = 20) -> dict[str, Any]:
        bounded_ids: dict[str, list[str]] = {}
        for issue in self.issues:
            if not issue.operation_ids:
                continue
            bucket = bounded_ids.setdefault(issue.code, [])
            for operation_id in issue.operation_ids:
                if operation_id not in bucket and len(bucket) < max_ids:
                    bucket.append(operation_id)
        return {
            "attempt_id": self.attempt_id,
            "selection_id": self.selection_id,
            "selection_revision": self.selection_revision,
            "selection_state": self.selection_state,
            "head_state_version": self.head_state_version,
            "operation_universe_digest": self.operation_universe_digest,
            "operation_count": self.operation_count,
            "workflow_contract_digest": self.workflow_contract_digest,
            "contract_id": self.contract_id,
            "contract_schema_id": self.contract_schema_id,
            "gap_counts": self.gap_counts,
            "bounded_operation_ids": bounded_ids,
            "blocker_codes": list(self.blocker_codes),
            "seal_ready": self.seal_ready,
            "closure_ready": self.closure_ready,
            "closure_ready_phase": "host_finalization_after_request",
            "closure_request_ready": self.closure_request_ready,
            "closure_finalization_ready": self.closure_finalization_ready,
        }


@dataclass(slots=True)
class ScientificSelectionEvaluator:
    repositories: CoreRepositories
    workflow_contract_registry: ScientificWorkflowContractRegistry

    def evaluate(
        self,
        *,
        attempt: ScientificAttempt,
        resolved_head: ResolvedScientificSelectionHead,
        universe: ScientificOperationUniverse,
    ) -> ScientificSelectionEvaluation:
        selection = resolved_head.selection
        issues: list[ScientificSelectionIssue] = []
        contract: ScientificWorkflowContract | None = None
        contract_id: str | None = None
        contract_schema_id: str | None = None
        allowed_roles: tuple[str, ...] = ()
        try:
            resolved_contract = self.workflow_contract_registry.resolve_attempt(
                attempt
            )
            contract_id = resolved_contract.contract_id
            contract_schema_id = resolved_contract.schema_id
            if isinstance(
                resolved_contract,
                HistoricalScientificWorkflowContract,
            ):
                issues.append(
                    ScientificSelectionIssue(
                        code="workflow_contract_historical_read_only",
                    )
                )
            else:
                contract = resolved_contract
                allowed_roles = contract.allowed_roles(attempt.scope)
        except ScientificWorkflowContractError as exc:
            issues.append(ScientificSelectionIssue(code=exc.error_code))

        if (
            selection.attempt_id != attempt.attempt_id
            or selection.workflow_contract_digest
            != attempt.workflow_contract_digest
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="workflow_contract_digest_mismatch",
                )
            )
        if selection.state is ScientificSelectionState.INVALIDATED:
            issues.append(
                ScientificSelectionIssue(
                    code="selection_state_not_sealable",
                )
            )
        issues.extend(self._attempt_authority_issues(attempt))
        if (
            selection.operation_universe_digest != universe.universe_digest
            or selection.operation_count != len(universe.occurrences)
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="selection_universe_changed",
                    facts=(
                        (
                            "selection_operation_count",
                            selection.operation_count,
                        ),
                        (
                            "current_operation_count",
                            len(universe.occurrences),
                        ),
                    ),
                )
            )

        occurrence_by_id = {
            str(item["operation_id"]): item for item in universe.occurrences
        }
        dispositions = (
            self.repositories.scientific_dispositions.list_by_selection(
                selection.selection_id
            )
        )
        adoptions = (
            self.repositories.scientific_effect_adoptions.list_by_selection(
                selection.selection_id
            )
        )
        dispositions_by_operation: dict[str, list[Any]] = {}
        for disposition in dispositions:
            dispositions_by_operation.setdefault(
                disposition.operation_id,
                [],
            ).append(disposition)
        adoptions_by_operation: dict[str, list[Any]] = {}
        for adoption in adoptions:
            adoptions_by_operation.setdefault(adoption.operation_id, []).append(
                adoption
            )

        universe_ids = set(occurrence_by_id)
        disposition_ids = set(dispositions_by_operation)
        missing_dispositions = tuple(sorted(universe_ids - disposition_ids))
        unexpected_dispositions = tuple(
            sorted(disposition_ids - universe_ids)
        )
        duplicate_dispositions = tuple(
            sorted(
                operation_id
                for operation_id, records in dispositions_by_operation.items()
                if len(records) != 1
            )
        )
        if (
            missing_dispositions
            or unexpected_dispositions
            or duplicate_dispositions
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="selection_disposition_incomplete",
                    operation_ids=tuple(
                        dict.fromkeys(
                            (
                                *missing_dispositions,
                                *unexpected_dispositions,
                                *duplicate_dispositions,
                            )
                        )
                    ),
                    facts=(
                        ("missing_count", len(missing_dispositions)),
                        (
                            "unexpected_count",
                            len(unexpected_dispositions),
                        ),
                        (
                            "duplicate_count",
                            len(duplicate_dispositions),
                        ),
                    ),
                )
            )

        adopted_roles: dict[str, list[str]] = {}
        occurrence_evaluations: list[
            ScientificSelectionOccurrenceEvaluation
        ] = []
        for operation_id in sorted(universe_ids):
            occurrence = occurrence_by_id[operation_id]
            operation_issues: list[ScientificSelectionIssue] = []
            operation = self.repositories.controlled_operations.get(operation_id)
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
            disposition_records = dispositions_by_operation.get(
                operation_id,
                [],
            )
            adoption_records = adoptions_by_operation.get(operation_id, [])
            disposition = (
                disposition_records[0]
                if len(disposition_records) == 1
                else None
            )
            adoption = (
                adoption_records[0] if len(adoption_records) == 1 else None
            )

            if operation is None:
                operation_issues.append(
                    ScientificSelectionIssue(
                        code="selection_operation_missing",
                        operation_ids=(operation_id,),
                    )
                )
                compatible_roles: tuple[str, ...] = ()
            else:
                compatible_roles = (
                    ()
                    if contract is None
                    else contract.compatible_roles(attempt.scope, operation)
                )
                if (
                    execution is not None
                    and execution.effect_certainty
                    is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                ):
                    operation_issues.append(
                        ScientificSelectionIssue(
                            code="selection_unknown_effect",
                            operation_ids=(operation_id,),
                        )
                    )
                elif (
                    execution is not None
                    and execution.lifecycle_state
                    is not ControlledOperationExecutionLifecycle.TERMINAL
                ):
                    operation_issues.append(
                        ScientificSelectionIssue(
                            code="selection_occurrence_not_closed",
                            operation_ids=(operation_id,),
                        )
                    )
                run = self.repositories.sandbox_runs.get(
                    str(occurrence["sandbox_run_id"])
                )
                if run is None or not run.status.is_terminal:
                    operation_issues.append(
                        ScientificSelectionIssue(
                            code="selection_process_active",
                            operation_ids=(operation_id,),
                        )
                    )
                continuation = (
                    self.repositories.continuation_states.get_by_operation_id(
                        operation_id
                    )
                )
                if continuation is not None and not continuation.status.is_terminal:
                    operation_issues.append(
                        ScientificSelectionIssue(
                            code="selection_continuation_active",
                            operation_ids=(operation_id,),
                        )
                    )

            if disposition is not None:
                if (
                    disposition.selection_id != selection.selection_id
                    or disposition.attempt_id != attempt.attempt_id
                ):
                    operation_issues.append(
                        ScientificSelectionIssue(
                            code="selection_disposition_scope_invalid",
                            operation_ids=(operation_id,),
                        )
                    )
                if (
                    disposition.kind
                    is ScientificOperationDispositionKind.ADOPTED
                ):
                    if disposition.workflow_role:
                        adopted_roles.setdefault(
                            disposition.workflow_role,
                            [],
                        ).append(operation_id)
                    if (
                        adoption is None
                        or adoption.workflow_role
                        != disposition.workflow_role
                    ):
                        operation_issues.append(
                            ScientificSelectionIssue(
                                code="selection_adoption_incomplete",
                                operation_ids=(operation_id,),
                                workflow_roles=(
                                    ()
                                    if disposition.workflow_role is None
                                    else (disposition.workflow_role,)
                                ),
                            )
                        )
                    if (
                        operation is not None
                        and execution is not None
                        and contract is not None
                        and disposition.workflow_role is not None
                    ):
                        try:
                            self.workflow_contract_registry.validate_role(
                                attempt=attempt,
                                selection=selection,
                                workflow_role=disposition.workflow_role,
                                operation=operation,
                                execution=execution,
                            )
                        except ScientificWorkflowContractError as exc:
                            operation_issues.append(
                                ScientificSelectionIssue(
                                    code=exc.error_code,
                                    operation_ids=(operation_id,),
                                    workflow_roles=(
                                        disposition.workflow_role,
                                    ),
                                )
                            )
                    operation_issues.extend(
                        self._adopted_execution_issues(
                            attempt=attempt,
                            operation_id=operation_id,
                            operation=operation,
                            execution=execution,
                            result=result,
                            adoption=adoption,
                            selection_id=selection.selection_id,
                        )
                    )
                elif (
                    disposition.kind
                    is ScientificOperationDispositionKind.SUPERSEDED
                ):
                    replacement = disposition.replacement_operation_id
                    replacement_records = dispositions_by_operation.get(
                        replacement or "",
                        [],
                    )
                    if (
                        replacement is None
                        or len(replacement_records) != 1
                        or replacement_records[0].kind
                        is not ScientificOperationDispositionKind.ADOPTED
                    ):
                        operation_issues.append(
                            ScientificSelectionIssue(
                                code="selection_supersession_invalid",
                                operation_ids=(operation_id,),
                            )
                        )
                    operation_issues.extend(
                        self._terminal_occurrence_issues(
                            operation_id=operation_id,
                            operation=operation,
                            execution=execution,
                            allow_success=True,
                        )
                    )
                elif (
                    disposition.kind
                    is ScientificOperationDispositionKind.FAILED
                ):
                    operation_issues.extend(
                        self._terminal_occurrence_issues(
                            operation_id=operation_id,
                            operation=operation,
                            execution=execution,
                            allow_success=False,
                        )
                    )
                else:
                    if (
                        execution is None
                        and operation is not None
                        and operation.status
                        not in {
                            ControlledOperationStatus.FAILED,
                            ControlledOperationStatus.RECOVERY_FAILED,
                        }
                    ) or (
                        execution is not None
                        and (
                            execution.lifecycle_state
                            is not ControlledOperationExecutionLifecycle.TERMINAL
                            or execution.effect_certainty
                            is not ExternalEffectCertainty.NO_EFFECT
                        )
                    ):
                        operation_issues.append(
                            ScientificSelectionIssue(
                                code="selection_abandonment_not_no_effect",
                                operation_ids=(operation_id,),
                            )
                        )

            if adoption is not None and (
                disposition is None
                or disposition.kind
                is not ScientificOperationDispositionKind.ADOPTED
            ):
                operation_issues.append(
                    ScientificSelectionIssue(
                        code="selection_adoption_unexpected",
                        operation_ids=(operation_id,),
                    )
                )
            if len(adoption_records) > 1:
                operation_issues.append(
                    ScientificSelectionIssue(
                        code="selection_adoption_incomplete",
                        operation_ids=(operation_id,),
                        facts=(("duplicate_count", len(adoption_records)),),
                    )
                )

            issues.extend(operation_issues)
            occurrence_evaluations.append(
                ScientificSelectionOccurrenceEvaluation(
                    operation_id=operation_id,
                    sandbox_run_id=str(occurrence["sandbox_run_id"]),
                    sdk_module=(
                        None if operation is None else operation.sdk_module
                    ),
                    function_name=(
                        None if operation is None else operation.function_name
                    ),
                    operation_status=(
                        str(occurrence["operation_status"])
                        if operation is None
                        else operation.status.value
                    ),
                    execution_id=(
                        None if execution is None else execution.execution_id
                    ),
                    lifecycle_state=(
                        None
                        if execution is None
                        else execution.lifecycle_state.value
                    ),
                    terminal_outcome=(
                        None
                        if execution is None
                        or execution.terminal_outcome is None
                        else execution.terminal_outcome.value
                    ),
                    effect_certainty=(
                        None
                        if execution is None
                        else execution.effect_certainty.value
                    ),
                    disposition_id=(
                        None
                        if disposition is None
                        else disposition.disposition_id
                    ),
                    disposition_kind=(
                        None
                        if disposition is None
                        else disposition.kind.value
                    ),
                    disposition_role=(
                        None
                        if disposition is None
                        else disposition.workflow_role
                    ),
                    adoption_id=(
                        None if adoption is None else adoption.adoption_id
                    ),
                    adoption_role=(
                        None if adoption is None else adoption.workflow_role
                    ),
                    allowed_roles=allowed_roles,
                    compatible_roles=compatible_roles,
                    issue_codes=tuple(
                        dict.fromkeys(
                            issue.code for issue in operation_issues
                        )
                    ),
                )
            )

        unexpected_adoptions = tuple(
            sorted(set(adoptions_by_operation) - universe_ids)
        )
        if unexpected_adoptions:
            issues.append(
                ScientificSelectionIssue(
                    code="selection_adoption_unexpected",
                    operation_ids=unexpected_adoptions,
                )
            )
        for role, operation_ids in adopted_roles.items():
            if len(operation_ids) > 1:
                issues.append(
                    ScientificSelectionIssue(
                        code="selection_workflow_role_duplicated",
                        operation_ids=tuple(sorted(operation_ids)),
                        workflow_roles=(role,),
                    )
                )
        if not adopted_roles and not missing_dispositions:
            issues.append(
                ScientificSelectionIssue(
                    code="selection_adopted_chain_empty",
                )
            )

        active_writers = self.repositories.mutation_writers.list_active(
            attempt.mutation_scope_id
        )
        if active_writers:
            issues.append(
                ScientificSelectionIssue(
                    code="selection_active_writers",
                    facts=(("writer_count", len(active_writers)),),
                    blocks_seal=False,
                    blocks_closure=True,
                )
            )

        normalized_issues = tuple(
            sorted(
                self._deduplicate_issues(issues),
                key=lambda issue: (
                    _ISSUE_PRIORITY.get(issue.code, 1_000),
                    issue.code,
                    issue.operation_ids,
                    issue.workflow_roles,
                ),
            )
        )
        return ScientificSelectionEvaluation(
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            selection_revision=selection.revision,
            selection_state=selection.state.value,
            head_state_version=resolved_head.head.state_version,
            operation_universe_digest=universe.universe_digest,
            operation_count=len(universe.occurrences),
            workflow_contract_digest=attempt.workflow_contract_digest,
            contract_id=contract_id,
            contract_schema_id=contract_schema_id,
            occurrences=tuple(occurrence_evaluations),
            issues=normalized_issues,
        )

    def _attempt_authority_issues(
        self,
        attempt: ScientificAttempt,
    ) -> tuple[ScientificSelectionIssue, ...]:
        authority = self.repositories.scientific_attempt_authorizations.get(
            attempt.envelope_id
        )
        if authority is None:
            return (
                ScientificSelectionIssue(
                    code="selection_attempt_authority_missing",
                ),
            )
        if (
            authority.envelope_id != attempt.envelope_id
            or authority.session_id != attempt.session_id
            or authority.task_id != attempt.task_id
            or authority.campaign_id != attempt.campaign_id
            or authority.workflow_id != attempt.workflow_id
            or authority.root_ref != attempt.root_ref
            or attempt.scope not in authority.allowed_scopes
            or not set(attempt.requested_effect_classes).issubset(
                authority.allowed_effect_classes
            )
            or (
                attempt.provider is not None
                and authority.allowed_providers
                and attempt.provider not in authority.allowed_providers
            )
            or (
                attempt.hpc_target is not None
                and authority.allowed_hpc_targets
                and attempt.hpc_target not in authority.allowed_hpc_targets
            )
            or attempt.reserved_micu > authority.max_micu
            or attempt.reserved_cost_microunits
            > authority.max_cost_microunits
            or attempt.reserved_wall_time_seconds
            > authority.max_wall_time_seconds
        ):
            return (
                ScientificSelectionIssue(
                    code="selection_attempt_authority_mismatch",
                ),
            )
        if authority.status in {
            ScientificAttemptAuthorityStatus.EXPIRED,
            ScientificAttemptAuthorityStatus.REVOKED,
        }:
            return (
                ScientificSelectionIssue(
                    code="selection_attempt_authority_invalid",
                    facts=(("authority_status", authority.status.value),),
                ),
            )
        return ()

    def _adopted_execution_issues(
        self,
        *,
        attempt: ScientificAttempt,
        operation_id: str,
        operation: Any,
        execution: Any,
        result: Any,
        adoption: Any,
        selection_id: str,
    ) -> tuple[ScientificSelectionIssue, ...]:
        issues: list[ScientificSelectionIssue] = []
        if (
            self.repositories.scientific_attempt_bindings.attempt_for_operation(
                operation_id
            )
            != attempt.attempt_id
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="effect_adoption_cross_attempt",
                    operation_ids=(operation_id,),
                )
            )
            return tuple(issues)
        if operation is None or execution is None:
            issues.append(
                ScientificSelectionIssue(
                    code="effect_adoption_execution_missing",
                    operation_ids=(operation_id,),
                )
            )
            return tuple(issues)
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
            issues.append(
                ScientificSelectionIssue(
                    code="effect_adoption_not_terminal_known",
                    operation_ids=(operation_id,),
                )
            )
            return tuple(issues)
        if (
            result is None
            or result.operation_id != operation_id
            or result.execution_id != execution.execution_id
            or result.terminal_outcome
            is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            or result.result_digest != execution.result_digest
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="effect_adoption_result_invalid",
                    operation_ids=(operation_id,),
                )
            )
            return tuple(issues)
        if operation.approval_id is not None and (
            operation.approval_state != "approved"
            or execution.approval_digest is None
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="effect_adoption_approval_invalid",
                    operation_ids=(operation_id,),
                )
            )
        if adoption is not None and (
            adoption.selection_id != selection_id
            or adoption.attempt_id != attempt.attempt_id
            or adoption.execution_id != execution.execution_id
            or adoption.result_handle_id != result.result_handle_id
            or adoption.result_digest != result.result_digest
            or adoption.effect_certainty != execution.effect_certainty.value
            or adoption.approval_digest != execution.approval_digest
        ):
            issues.append(
                ScientificSelectionIssue(
                    code="selection_adoption_identity_invalid",
                    operation_ids=(operation_id,),
                )
            )
        return tuple(issues)

    @staticmethod
    def _terminal_occurrence_issues(
        *,
        operation_id: str,
        operation: Any,
        execution: Any,
        allow_success: bool,
    ) -> tuple[ScientificSelectionIssue, ...]:
        if execution is None:
            if operation is None or operation.status not in {
                ControlledOperationStatus.FAILED,
                ControlledOperationStatus.RECOVERY_FAILED,
            }:
                return (
                    ScientificSelectionIssue(
                        code="selection_occurrence_not_closed",
                        operation_ids=(operation_id,),
                    ),
                )
            return ()
        if (
            execution.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        ):
            return ()
        if (
            execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.TERMINAL
        ):
            return (
                ScientificSelectionIssue(
                    code="selection_occurrence_not_closed",
                    operation_ids=(operation_id,),
                ),
            )
        if (
            not allow_success
            and execution.terminal_outcome
            is ControlledOperationExecutionTerminalOutcome.SUCCEEDED
        ):
            return (
                ScientificSelectionIssue(
                    code="selection_occurrence_not_failure",
                    operation_ids=(operation_id,),
                ),
            )
        return ()

    @staticmethod
    def _deduplicate_issues(
        issues: list[ScientificSelectionIssue],
    ) -> tuple[ScientificSelectionIssue, ...]:
        return tuple(dict.fromkeys(issues))


__all__ = [
    "ScientificSelectionEvaluation",
    "ScientificSelectionEvaluator",
    "ScientificSelectionIssue",
    "ScientificSelectionOccurrenceEvaluation",
]
