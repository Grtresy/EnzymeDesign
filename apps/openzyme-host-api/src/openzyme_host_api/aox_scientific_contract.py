from __future__ import annotations

from typing import Final

from openzyme_core import HistoricalScientificWorkflowContract
from openzyme_core import SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
from openzyme_core import SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY
from openzyme_core import ScientificOperationSignature
from openzyme_core import ScientificWorkflowContract
from openzyme_core import ScientificWorkflowContractRegistry
from openzyme_core import ScientificWorkflowRolePolicy
from openzyme_core import ScientificWorkflowScopePolicy
from openzyme_core import canonical_digest
from openzyme_domain import ScientificAttemptScope


AOX_SELECTED_CHAIN_WORKFLOW_ID: Final = "aox_blank_world"
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_ID: Final = (
    "aox_blank_world_selected_chain@1"
)
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID: Final = (
    "aox_blank_world_selected_chain@2"
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

# Frozen historical preimage. Its digest is r54 evidence and must never be
# recomputed from the @2 role-signature model or used for new admission.
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1: Final[dict[str, object]] = {
    "schema_id": "scientific_workflow_role_contract@1",
    "contract_id": AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_ID,
    "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
    "formal_and_fault_roles": sorted(AOX_FORMAL_WORKFLOW_ROLES),
    "probe_roles": sorted(AOX_PROBE_WORKFLOW_ROLES),
    "role_cardinality": "exactly_one_adopted_per_reached_role",
    "branch_authority": "controlled_provider_and_hpc_effects_only",
}
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST: Final = canonical_digest(
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1
)


def _role_policy(role_id: str) -> ScientificWorkflowRolePolicy:
    sdk_module, function_name = AOX_WORKFLOW_METHOD_BY_ROLE[role_id]
    return ScientificWorkflowRolePolicy(
        role_id=role_id,
        operation_signatures=(
            ScientificOperationSignature(
                sdk_module=sdk_module,
                function_name=function_name,
            ),
        ),
        cardinality="exactly_one_adopted_per_reached_role",
    )


AOX_SELECTED_CHAIN_CONTRACT_V2: Final = ScientificWorkflowContract(
    schema_id="scientific_workflow_contract@2",
    contract_id=AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,
    workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
    scopes=(
        ScientificWorkflowScopePolicy(
            scope=ScientificAttemptScope.FORMAL,
            roles=tuple(
                _role_policy(role)
                for role in sorted(AOX_FORMAL_WORKFLOW_ROLES)
            ),
        ),
        ScientificWorkflowScopePolicy(
            scope=ScientificAttemptScope.FAULT,
            roles=tuple(
                _role_policy(role)
                for role in sorted(AOX_FORMAL_WORKFLOW_ROLES)
            ),
        ),
        ScientificWorkflowScopePolicy(
            scope=ScientificAttemptScope.PROBE,
            roles=tuple(
                _role_policy(role)
                for role in sorted(AOX_PROBE_WORKFLOW_ROLES)
            ),
        ),
    ),
    effect_adoption_policy=SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC,
    same_attempt_reuse_policy=SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY,
    projection_schema_version="scientific_workflow_contract_projection@1",
)
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT: Final[dict[str, object]] = (
    AOX_SELECTED_CHAIN_CONTRACT_V2.canonical_preimage
)
AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST: Final = (
    AOX_SELECTED_CHAIN_CONTRACT_V2.digest
)

AOX_SELECTED_CHAIN_CONTRACT_V1_READER: Final = (
    HistoricalScientificWorkflowContract(
        schema_id=str(
            AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1["schema_id"]
        ),
        contract_id=AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_ID,
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        workflow_contract_digest=(
            AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST
        ),
        scope_roles=(
            (
                ScientificAttemptScope.FORMAL,
                tuple(sorted(AOX_FORMAL_WORKFLOW_ROLES)),
            ),
            (
                ScientificAttemptScope.FAULT,
                tuple(sorted(AOX_FORMAL_WORKFLOW_ROLES)),
            ),
            (
                ScientificAttemptScope.PROBE,
                tuple(sorted(AOX_PROBE_WORKFLOW_ROLES)),
            ),
        ),
    )
)

AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY: Final = (
    ScientificWorkflowContractRegistry(
        contracts=(AOX_SELECTED_CHAIN_CONTRACT_V2,),
        historical_contracts=(AOX_SELECTED_CHAIN_CONTRACT_V1_READER,),
    )
)

__all__ = [
    "AOX_FORMAL_WORKFLOW_METHODS",
    "AOX_FORMAL_WORKFLOW_ROLES",
    "AOX_PROBE_WORKFLOW_ROLES",
    "AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY",
    "AOX_SELECTED_CHAIN_CONTRACT_V1_READER",
    "AOX_SELECTED_CHAIN_CONTRACT_V2",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST",
    "AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_ID",
    "AOX_SELECTED_CHAIN_WORKFLOW_ID",
    "AOX_WORKFLOW_METHOD_BY_ROLE",
]
