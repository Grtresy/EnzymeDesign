from dataclasses import replace
from importlib.resources import files

import pytest

from enzymedesign_aox import AOX_COMPONENT_MANIFEST_DIGEST
from enzymedesign_aox import AOX_FORMAL_WORKFLOW_ROLES
from enzymedesign_aox import AOX_PROBE_WORKFLOW_ROLES
from enzymedesign_aox import AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
from enzymedesign_aox import AOX_SELECTED_CHAIN_CONTRACT_V2
from enzymedesign_aox import AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
from enzymedesign_aox import AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST
from enzymedesign_aox import AOX_SELECTED_CHAIN_WORKFLOW_ID
from enzymedesign_aox import AOX_WORKFLOW_METHOD_BY_ROLE
from enzymedesign_aox import locate_component_manifest
from openzyme_extension_spi import parse_component_manifest_json
from openzyme_science import SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
from openzyme_science import SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY
from openzyme_science import ScientificAttemptScope
from openzyme_science import ScientificOperationSignature
from openzyme_science import ScientificWorkflowContractError


def test_aox_historical_and_current_workflow_digests_remain_frozen() -> None:
    assert AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST == (
        "sha256:f7e8de4c7b0112bd8a1a527545d0c37df5f67c063743ffe48b2f3ff1375eb161"
    )
    assert AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST == (
        "sha256:ab9898f52fc9fd1f1dc8b6498d368ba68d2e658c1ebc819cb76f73b7737de922"
    )
    preimage = AOX_SELECTED_CHAIN_CONTRACT_V2.canonical_preimage
    assert preimage["effect_adoption_policy"] == (
        SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
    )
    assert preimage["same_attempt_reuse_policy"] == (
        SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY
    )


@pytest.mark.parametrize(
    ("scope", "expected_roles"),
    (
        (ScientificAttemptScope.FORMAL, AOX_FORMAL_WORKFLOW_ROLES),
        (ScientificAttemptScope.FAULT, AOX_FORMAL_WORKFLOW_ROLES),
        (ScientificAttemptScope.PROBE, AOX_PROBE_WORKFLOW_ROLES),
    ),
)
def test_aox_scope_roles_and_compatible_signatures_are_exact(
    scope: ScientificAttemptScope,
    expected_roles: frozenset[str],
) -> None:
    assert set(AOX_SELECTED_CHAIN_CONTRACT_V2.allowed_roles(scope)) == expected_roles
    for role in expected_roles:
        sdk_module, function_name = AOX_WORKFLOW_METHOD_BY_ROLE[role]
        compatible = AOX_SELECTED_CHAIN_CONTRACT_V2.compatible_roles_for_signature(
            scope,
            sdk_module=sdk_module,
            function_name=function_name,
        )
        assert compatible == (role,)


def test_aox_role_signatures_are_exact_and_tamper_changes_digest() -> None:
    formal = AOX_SELECTED_CHAIN_CONTRACT_V2.scope_policy(ScientificAttemptScope.FORMAL)
    assert (
        set(AOX_SELECTED_CHAIN_CONTRACT_V2.allowed_roles(ScientificAttemptScope.FORMAL))
        == AOX_FORMAL_WORKFLOW_ROLES
    )
    fetch = formal.role("ncbi_fetch")
    assert fetch is not None
    expected = AOX_WORKFLOW_METHOD_BY_ROLE["ncbi_fetch"]
    assert fetch.operation_signatures[0].to_dict() == {
        "sdk_module": expected[0],
        "function_name": expected[1],
    }
    tampered = replace(
        AOX_SELECTED_CHAIN_CONTRACT_V2,
        scopes=(
            replace(
                formal,
                roles=tuple(
                    replace(
                        role,
                        operation_signatures=(
                            ScientificOperationSignature("bio", "tampered"),
                        ),
                    )
                    if role.role_id == "ncbi_fetch"
                    else role
                    for role in formal.roles
                ),
            ),
            *AOX_SELECTED_CHAIN_CONTRACT_V2.scopes[1:],
        ),
    )
    assert tampered.digest != AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST


def test_aox_v1_is_historical_read_only() -> None:
    historical = AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        workflow_contract_digest=AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST,
    )
    assert (
        historical.project(ScientificAttemptScope.FORMAL)["historical_read_only"]
        is True
    )
    with pytest.raises(ScientificWorkflowContractError) as rejected:
        AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
            workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
            workflow_contract_digest=AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST,
            for_new_attempt=True,
        )
    assert rejected.value.error_code == "workflow_contract_historical_read_only"


def test_aox_manifest_is_exact_and_declares_product_dependencies() -> None:
    locator = locate_component_manifest()
    manifest = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )
    assert manifest.manifest_digest == AOX_COMPONENT_MANIFEST_DIGEST
    assert locator.manifest_digest == AOX_COMPONENT_MANIFEST_DIGEST
    assert {item.capability_id for item in manifest.requires} == {
        "enzymedesign.hmmer",
        "enzymedesign.sequence.toolpack",
        "openzyme.science",
    }
    assert manifest.tools == ()
    assert manifest.workers == ()
    assert manifest.http_routes == ()


def test_aox_product_contract_has_no_platform_private_imports() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in files("enzymedesign_aox").iterdir()
        if path.name.endswith(".py")
    )
    assert "openzyme_core" not in source
    assert "openzyme_host_api" not in source
    assert "openzyme_store_sqlite" not in source
    assert "openzyme_hpc_slurm" not in source
