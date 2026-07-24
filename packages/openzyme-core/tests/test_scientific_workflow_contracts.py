from dataclasses import replace

import pytest

from openzyme_core import HistoricalScientificWorkflowContract
from openzyme_core import ScientificOperationSignature
from openzyme_core import ScientificWorkflowContract
from openzyme_core import ScientificWorkflowContractError
from openzyme_core import ScientificWorkflowContractRegistry
from openzyme_core import ScientificWorkflowRolePolicy
from openzyme_core import ScientificWorkflowScopePolicy
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificChainSelection
from openzyme_domain import ScientificSelectionState


NOW = "2026-07-24T00:00:00+00:00"


def _role(
    role_id: str,
    sdk_module: str,
    function_name: str,
) -> ScientificWorkflowRolePolicy:
    return ScientificWorkflowRolePolicy(
        role_id=role_id,
        operation_signatures=(
            ScientificOperationSignature(
                sdk_module=sdk_module,
                function_name=function_name,
            ),
        ),
        cardinality="exactly_one",
    )


def _contract(
    *,
    formal_roles: tuple[ScientificWorkflowRolePolicy, ...] | None = None,
    probe_roles: tuple[ScientificWorkflowRolePolicy, ...] | None = None,
) -> ScientificWorkflowContract:
    return ScientificWorkflowContract(
        schema_id="scientific_workflow_contract@2",
        contract_id="workflow_selected_chain@2",
        workflow_id="workflow",
        scopes=(
            ScientificWorkflowScopePolicy(
                scope=ScientificAttemptScope.PROBE,
                roles=probe_roles or (_role("probe", "bio", "probe"),),
            ),
            ScientificWorkflowScopePolicy(
                scope=ScientificAttemptScope.FORMAL,
                roles=formal_roles
                or (
                    _role("fetch", "bio", "fetch"),
                    _role("align", "bio_tools", "align"),
                ),
            ),
        ),
        effect_adoption_policy="explicit_atomic_adoption",
        same_attempt_reuse_policy="same_attempt_only",
        projection_schema_version=(
            "scientific_workflow_contract_projection@1"
        ),
    )


def _attempt(contract: ScientificWorkflowContract) -> ScientificAttempt:
    return ScientificAttempt(
        attempt_id="attempt_001",
        admission_request_id="admission_001",
        envelope_id="envelope_001",
        session_id="session_001",
        task_id="task_001",
        lane_id="lane_001",
        campaign_id="campaign_001",
        workflow_id=contract.workflow_id,
        scope=ScientificAttemptScope.FORMAL,
        root_ref="attempts/001",
        mutation_scope_id="mutation_scope_001",
        ordinal=1,
        request_digest="sha256:request",
        idempotency_key="attempt-001",
        workflow_contract_digest=contract.digest,
        requested_effect_classes=("provider",),
        provider="provider",
        hpc_target=None,
        reserved_micu=1,
        reserved_cost_microunits=1,
        reserved_wall_time_seconds=1,
        status=ScientificAttemptStatus.ACTIVE,
        state_version=1,
        created_by="agent:scientist",
        created_at=NOW,
        updated_at=NOW,
    )


def _selection(attempt: ScientificAttempt) -> ScientificChainSelection:
    return ScientificChainSelection(
        selection_id="selection_001",
        attempt_id=attempt.attempt_id,
        revision=1,
        parent_selection_id=None,
        state=ScientificSelectionState.DRAFT,
        operation_universe_digest="sha256:universe",
        operation_count=1,
        disposition_digest="sha256:dispositions",
        adoption_digest="sha256:adoptions",
        workflow_contract_digest=attempt.workflow_contract_digest,
        actor_ref="agent:scientist",
        idempotency_key="selection-001",
        request_digest="sha256:selection",
        created_at=NOW,
    )


def _operation(
    *,
    sdk_module: str = "bio",
    function_name: str = "fetch",
) -> ControlledOperation:
    return ControlledOperation(
        operation_id="operation_001",
        session_id="session_001",
        sandbox_workspace_id="workspace_001",
        sandbox_run_id="run_001",
        logical_operation_key="workflow.fetch",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="fixture",
        status=ControlledOperationStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        task_id="task_001",
        lane_id="lane_001",
        sdk_module=sdk_module,
        function_name=function_name,
    )


def _execution() -> ControlledOperationExecution:
    return ControlledOperationExecution(
        execution_id="execution_001",
        operation_id="operation_001",
        session_id="session_001",
        task_id="task_001",
        lane_id="lane_001",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest="sha256:operation",
        approval_digest=None,
        route_policy_id="route",
        selected_backend="fixture",
        adapter_policy_id="adapter",
        input_identity_digest="sha256:input",
        expected_output_contract_digest="sha256:output",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        dispatch_generation=1,
        state_version=1,
        fencing_token=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_contract_digest_covers_role_signatures_and_is_order_stable() -> None:
    contract = _contract()
    reordered = replace(
        contract,
        scopes=tuple(reversed(contract.scopes)),
    )
    changed = _contract(
        formal_roles=(
            _role("fetch", "bio", "fetch_v2"),
            _role("align", "bio_tools", "align"),
        )
    )

    assert reordered.digest == contract.digest
    assert changed.digest != contract.digest
    preimage = contract.canonical_preimage
    assert preimage["effect_adoption_policy"] == "explicit_atomic_adoption"
    assert preimage["same_attempt_reuse_policy"] == "same_attempt_only"
    formal = next(
        item for item in preimage["scopes"] if item["scope"] == "formal"
    )
    fetch = next(item for item in formal["roles"] if item["role_id"] == "fetch")
    assert fetch["operation_signatures"] == [
        {"sdk_module": "bio", "function_name": "fetch"}
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        {"effect_adoption_policy": "atomic_policy_typo"},
        {"same_attempt_reuse_policy": "same_attempt_policy_typo"},
    ),
)
def test_contract_rejects_unknown_policy_identifiers(
    mutation: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="unsupported scientific"):
        replace(_contract(), **mutation)


def test_registry_resolves_exact_identity_and_rejects_historical_admission() -> (
    None
):
    contract = _contract()
    historical = HistoricalScientificWorkflowContract(
        schema_id="scientific_workflow_role_contract@1",
        contract_id="workflow_selected_chain@1",
        workflow_id=contract.workflow_id,
        workflow_contract_digest="sha256:historical",
        scope_roles=((ScientificAttemptScope.FORMAL, ("fetch",)),),
    )
    registry = ScientificWorkflowContractRegistry(
        contracts=(contract,),
        historical_contracts=(historical,),
    )

    assert (
        registry.resolve(
            workflow_id=contract.workflow_id,
            workflow_contract_digest=contract.digest,
            for_new_attempt=True,
        )
        is contract
    )
    assert registry.resolve(
        workflow_id=historical.workflow_id,
        workflow_contract_digest=historical.digest,
    ).project(ScientificAttemptScope.FORMAL)["historical_read_only"] is True

    with pytest.raises(ScientificWorkflowContractError) as frozen:
        registry.resolve(
            workflow_id=historical.workflow_id,
            workflow_contract_digest=historical.digest,
            for_new_attempt=True,
        )
    assert frozen.value.error_code == "workflow_contract_historical_read_only"
    with pytest.raises(ScientificWorkflowContractError) as unsupported:
        registry.resolve(
            workflow_id=contract.workflow_id,
            workflow_contract_digest="sha256:unknown",
            for_new_attempt=True,
        )
    assert unsupported.value.error_code == "workflow_contract_digest_unsupported"


def test_projection_and_validation_share_scope_and_compatibility_facts() -> None:
    contract = _contract()
    registry = ScientificWorkflowContractRegistry(contracts=(contract,))
    attempt = _attempt(contract)
    selection = _selection(attempt)
    operation = _operation()
    execution = _execution()

    projection = contract.project(ScientificAttemptScope.FORMAL)
    assert contract.allowed_roles(ScientificAttemptScope.FORMAL) == (
        "align",
        "fetch",
    )
    assert registry.compatible_roles(
        attempt=attempt,
        operation=operation,
    ) == ("fetch",)
    registry.validate_role(
        attempt=attempt,
        selection=selection,
        workflow_role="fetch",
        operation=operation,
        execution=execution,
    )

    with pytest.raises(ScientificWorkflowContractError) as other_scope:
        registry.validate_role(
            attempt=attempt,
            selection=selection,
            workflow_role="probe",
            operation=operation,
            execution=execution,
        )
    assert other_scope.value.error_code == "workflow_role_invalid"
    assert other_scope.value.details["allowed_roles"] == ["align", "fetch"]
    assert other_scope.value.details["compatible_roles"] == ["fetch"]

    serialized = repr(projection).lower()
    for forbidden in (
        "recommended_action",
        "credential",
        "host_path",
        "lease_token",
        "fencing_token",
        "runner_locator",
    ):
        assert forbidden not in serialized


def test_invalid_alias_is_not_rewritten_to_the_compatible_role() -> None:
    contract = _contract()
    registry = ScientificWorkflowContractRegistry(contracts=(contract,))
    attempt = _attempt(contract)

    with pytest.raises(ScientificWorkflowContractError) as rejected:
        registry.validate_role(
            attempt=attempt,
            selection=_selection(attempt),
            workflow_role="fetch_proteins",
            operation=_operation(),
            execution=_execution(),
        )

    assert rejected.value.error_code == "workflow_role_invalid"
    assert rejected.value.details["compatible_roles"] == ["fetch"]
    assert rejected.value.details["mutation_applied"] is False
