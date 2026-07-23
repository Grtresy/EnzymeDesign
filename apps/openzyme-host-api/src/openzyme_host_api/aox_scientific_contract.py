from __future__ import annotations

from typing import Final

from openzyme_core import ScientificAttemptError
from openzyme_core import canonical_digest
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificChainSelection


AOX_SELECTED_CHAIN_WORKFLOW_ID: Final = "aox_blank_world"
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID: Final = (
    "aox_blank_world_selected_chain@1"
)

AOX_FORMAL_WORKFLOW_ROLES: Final[frozenset[str]] = frozenset(
    {
        "ncbi_fetch",
        "reference_alignment",
        "hmm_build",
        "hmmer_search",
        "uniprot_fetch",
        "candidate_alignment",
        "cdhit",
    }
)
AOX_PROBE_WORKFLOW_ROLES: Final[frozenset[str]] = frozenset(
    {
        "ncbi_fetch",
        "reference_alignment",
        "hmm_build",
        "uniprot_fetch",
        "candidate_cluster",
        "candidate_alignment",
    }
)
AOX_WORKFLOW_METHOD_BY_ROLE: Final[dict[str, tuple[str, str]]] = {
    "ncbi_fetch": ("bio", "ncbi_fetch_proteins"),
    "reference_alignment": ("bio_tools", "mafft"),
    "hmm_build": ("bio_tools", "hmmbuild"),
    "hmmer_search": ("bio", "hmmer_search"),
    "uniprot_fetch": ("bio", "uniprot_fetch"),
    "candidate_cluster": ("bio_tools", "cdhit"),
    "candidate_alignment": ("bio_tools", "hmmalign"),
    "cdhit": ("bio_tools", "cdhit"),
}
AOX_FORMAL_WORKFLOW_METHODS: Final[frozenset[tuple[str, str]]] = frozenset(
    AOX_WORKFLOW_METHOD_BY_ROLE[role] for role in AOX_FORMAL_WORKFLOW_ROLES
)
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT: Final[dict[str, object]] = {
    "schema_id": "scientific_workflow_role_contract@1",
    "contract_id": AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,
    "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
    "formal_and_fault_roles": sorted(AOX_FORMAL_WORKFLOW_ROLES),
    "probe_roles": sorted(AOX_PROBE_WORKFLOW_ROLES),
    "role_cardinality": "exactly_one_adopted_per_reached_role",
    "branch_authority": "controlled_provider_and_hpc_effects_only",
}
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST: Final = canonical_digest(
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT
)


def validate_aox_scientific_workflow_role(
    *,
    attempt: ScientificAttempt,
    selection: ScientificChainSelection,
    workflow_role: str,
    operation: ControlledOperation,
    execution: ControlledOperationExecution,
) -> None:
    """Validate closed AOX role authority without selecting scientific strategy."""

    del execution
    if (
        attempt.workflow_id != AOX_SELECTED_CHAIN_WORKFLOW_ID
        or attempt.workflow_contract_digest
        != AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        or selection.workflow_contract_digest
        != AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
    ):
        raise ScientificAttemptError(
            "workflow_contract_digest_unsupported",
            "attempt does not bind the supported AOX selected-chain contract",
        )
    allowed_roles = (
        AOX_PROBE_WORKFLOW_ROLES
        if attempt.scope is ScientificAttemptScope.PROBE
        else AOX_FORMAL_WORKFLOW_ROLES
    )
    if workflow_role not in allowed_roles:
        raise ScientificAttemptError(
            "workflow_role_invalid",
            "workflow role is not declared by the exact AOX scope contract",
            details={
                "workflow_role": workflow_role,
                "attempt_scope": attempt.scope.value,
            },
        )
    if (
        operation.sdk_module,
        operation.function_name,
    ) != AOX_WORKFLOW_METHOD_BY_ROLE[workflow_role]:
        raise ScientificAttemptError(
            "workflow_role_operation_kind_invalid",
            "adopted operation does not implement the declared AOX workflow role",
            details={
                "workflow_role": workflow_role,
                "sdk_method": (
                    f"{operation.sdk_module}.{operation.function_name}"
                ),
            },
        )
    if (
        operation.session_id != attempt.session_id
        or operation.task_id != attempt.task_id
        or operation.lane_id != attempt.lane_id
        or not operation.logical_operation_key.strip()
    ):
        raise ScientificAttemptError(
            "workflow_role_operation_scope_invalid",
            "adopted operation does not belong to the exact AOX task and lane",
            details={"workflow_role": workflow_role},
        )


__all__ = [
    "AOX_FORMAL_WORKFLOW_ROLES",
    "AOX_FORMAL_WORKFLOW_METHODS",
    "AOX_PROBE_WORKFLOW_ROLES",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID",
    "AOX_SELECTED_CHAIN_WORKFLOW_ID",
    "AOX_WORKFLOW_METHOD_BY_ROLE",
    "validate_aox_scientific_workflow_role",
]
