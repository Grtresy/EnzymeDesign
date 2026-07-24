from dataclasses import replace

import pytest

from openzyme_core import SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
from openzyme_core import SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY
from openzyme_core import ScientificOperationSignature
from openzyme_core import ScientificWorkflowContractError
from openzyme_core import scientific_attempt_tool_descriptors
from openzyme_domain import ScientificAttemptScope
from openzyme_host_api.aox_scientific_contract import (
    AOX_FORMAL_WORKFLOW_ROLES,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_PROBE_WORKFLOW_ROLES,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_CONTRACT_V2,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_ID,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_WORKFLOW_METHOD_BY_ROLE,
)


def test_aox_v1_digest_is_frozen_and_v2_digest_closes_signature_mapping() -> None:
    assert AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST == (
        "sha256:f7e8de4c7b0112bd8a1a527545d0c37d"
        "f5f67c063743ffe48b2f3ff1375eb161"
    )
    assert AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST == (
        "sha256:ab9898f52fc9fd1f1dc8b6498d368ba6"
        "8d2e658c1ebc819cb76f73b7737de922"
    )
    assert (
        AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        != AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST
    )

    preimage = AOX_SELECTED_CHAIN_CONTRACT_V2.canonical_preimage
    assert preimage["effect_adoption_policy"] == (
        SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
    )
    assert preimage["same_attempt_reuse_policy"] == (
        SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY
    )
    for scope in preimage["scopes"]:
        for role in scope["roles"]:
            expected = AOX_WORKFLOW_METHOD_BY_ROLE[role["role_id"]]
            assert role["operation_signatures"] == [
                {
                    "sdk_module": expected[0],
                    "function_name": expected[1],
                }
            ]


@pytest.mark.parametrize(
    ("scope", "expected_roles"),
    (
        (ScientificAttemptScope.FORMAL, AOX_FORMAL_WORKFLOW_ROLES),
        (ScientificAttemptScope.FAULT, AOX_FORMAL_WORKFLOW_ROLES),
        (ScientificAttemptScope.PROBE, AOX_PROBE_WORKFLOW_ROLES),
    ),
)
def test_aox_v2_scope_roles_and_compatible_signatures_are_exact(
    scope: ScientificAttemptScope,
    expected_roles: frozenset[str],
) -> None:
    assert set(AOX_SELECTED_CHAIN_CONTRACT_V2.allowed_roles(scope)) == (
        expected_roles
    )
    for role in expected_roles:
        sdk_module, function_name = AOX_WORKFLOW_METHOD_BY_ROLE[role]
        compatible = (
            AOX_SELECTED_CHAIN_CONTRACT_V2.compatible_roles_for_signature(
                scope,
                sdk_module=sdk_module,
                function_name=function_name,
            )
        )
        assert compatible == (role,)


def test_aox_agent_surface_observes_roles_before_explicit_atomic_choice() -> (
    None
):
    descriptors = {
        descriptor.tool_name: descriptor
        for descriptor in scientific_attempt_tool_descriptors()
    }
    atomic = descriptors["scientific.operation.adopt"]
    disposition = descriptors["scientific.operation.disposition"]

    assert atomic.input_schema["required"] == [
        "selection_id",
        "operation_id",
        "workflow_role",
        "reason_code",
        "idempotency_key",
    ]
    assert "You choose the operation, role, and reason" in atomic.description
    assert "default" not in atomic.input_schema["properties"]["operation_id"]
    assert "default" not in atomic.input_schema["properties"]["workflow_role"]
    assert disposition.input_schema["properties"]["kind"]["enum"] == [
        "superseded",
        "failed",
        "abandoned",
    ]
    assert "scientific.effect.adopt" not in descriptors

    projection = AOX_SELECTED_CHAIN_CONTRACT_V2.project(
        ScientificAttemptScope.FORMAL
    )
    projected_roles = {
        role["role_id"]: role["operation_signatures"]
        for role in projection["roles"]
    }
    assert projected_roles == {
        role: [
            {
                "sdk_module": AOX_WORKFLOW_METHOD_BY_ROLE[role][0],
                "function_name": AOX_WORKFLOW_METHOD_BY_ROLE[role][1],
            }
        ]
        for role in sorted(AOX_FORMAL_WORKFLOW_ROLES)
    }


def test_aox_v1_is_readable_but_cannot_authorize_new_admission() -> None:
    historical = AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        workflow_contract_digest=(
            AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST
        ),
    )
    projection = historical.project(ScientificAttemptScope.FORMAL)
    assert projection["historical_read_only"] is True
    assert {
        item["role_id"] for item in projection["roles"]
    } == AOX_FORMAL_WORKFLOW_ROLES

    with pytest.raises(ScientificWorkflowContractError) as rejected:
        AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
            workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
            workflow_contract_digest=(
                AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST
            ),
            for_new_attempt=True,
        )
    assert rejected.value.error_code == "workflow_contract_historical_read_only"


def test_aox_role_signature_tamper_changes_contract_digest() -> None:
    formal = AOX_SELECTED_CHAIN_CONTRACT_V2.scope_policy(
        ScientificAttemptScope.FORMAL
    )
    fetch = formal.role("ncbi_fetch")
    assert fetch is not None
    tampered_fetch = replace(
        fetch,
        operation_signatures=(
            ScientificOperationSignature(
                sdk_module="bio",
                function_name="ncbi_fetch_proteins_v2",
            ),
        ),
    )
    tampered_formal = replace(
        formal,
        roles=tuple(
            tampered_fetch if role.role_id == "ncbi_fetch" else role
            for role in formal.roles
        ),
    )
    tampered = replace(
        AOX_SELECTED_CHAIN_CONTRACT_V2,
        scopes=tuple(
            tampered_formal
            if scope.scope is ScientificAttemptScope.FORMAL
            else scope
            for scope in AOX_SELECTED_CHAIN_CONTRACT_V2.scopes
        ),
    )

    assert tampered.digest != AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
    with pytest.raises(ScientificWorkflowContractError) as unsupported:
        AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
            workflow_id=tampered.workflow_id,
            workflow_contract_digest=tampered.digest,
            for_new_attempt=True,
        )
    assert unsupported.value.error_code == "workflow_contract_digest_unsupported"
