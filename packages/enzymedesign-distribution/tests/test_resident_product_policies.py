from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from enzymedesign_distribution.composition import activate_enzymedesign_composition
from enzymedesign_distribution.role_policies import ENZYMEDESIGN_RESIDENT_ROLES
from enzymedesign_distribution.role_policies import (
    enzymedesign_subject_policy_decisions,
)
from enzymedesign_distribution.role_policies import (
    enzymedesign_tool_exposure_policies,
)
from enzymedesign_distribution.workflow_registry import (
    ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS,
)
from enzymedesign_distribution.workflow_registry import (
    ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST,
)
from enzymedesign_distribution.workflow_registry import (
    EnzymeDesignExactWorkflowRegistry,
)
from openzyme_contracts import ToolExposure
from openzyme_contracts import WorkflowSelectionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import WorkflowRegistryResolutionError
from openzyme_kernel.affordance import ToolSubjectPolicyAction
from openzyme_kernel.errors import KernelContractError
from openzyme_kernel.testing import DeterministicClock


def _registry() -> EnzymeDesignExactWorkflowRegistry:
    return EnzymeDesignExactWorkflowRegistry(
        clock=DeterministicClock(datetime(2026, 8, 24, tzinfo=UTC))
    )


def test_workflow_registry_resolves_empty_exact_and_compatibility_without_default() -> (
    None
):
    registry = _registry()
    empty = registry.resolve(
        WorkflowSelectionRequest(
            request_id="workflow-request-empty",
            distribution_id="enzymedesign",
        )
    )
    exact = registry.resolve(
        WorkflowSelectionRequest(
            request_id="workflow-request-exact",
            distribution_id="enzymedesign",
            requested_workflow_refs=ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS,
        )
    )
    compatibility = registry.resolve(
        WorkflowSelectionRequest(
            request_id="workflow-request-compatibility",
            distribution_id="enzymedesign",
            compatibility_skill_keys=("aox_blank_world",),
        )
    )

    assert empty.selected_workflow_refs == ()
    assert exact.selected_workflow_refs == ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS
    assert compatibility.selected_workflow_refs == ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS
    assert {
        empty.registry_snapshot_digest,
        exact.registry_snapshot_digest,
        compatibility.registry_snapshot_digest,
    } == {ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST}


@pytest.mark.parametrize(
    ("workflow_refs", "skill_keys"),
    (
        (("aox_blank_world_selected_chain@latest",), ()),
        (("all",), ()),
        ((), ("aox_blank_world@latest",)),
    ),
)
def test_workflow_registry_rejects_latest_all_and_unknown_aliases(
    workflow_refs: tuple[str, ...],
    skill_keys: tuple[str, ...],
) -> None:
    with pytest.raises(WorkflowRegistryResolutionError) as caught:
        _registry().resolve(
            WorkflowSelectionRequest(
                request_id="workflow-request-invalid",
                distribution_id="enzymedesign",
                requested_workflow_refs=workflow_refs,
                compatibility_skill_keys=skill_keys,
            )
        )

    assert caught.value.code.startswith("enzymedesign_workflow_")
    assert caught.value.diagnostic_id.startswith("diagnostic-workflow-")


def test_unknown_compatibility_key_preserves_private_cause_without_fallback() -> None:
    with pytest.raises(WorkflowRegistryResolutionError) as caught:
        _registry().resolve(
            WorkflowSelectionRequest(
                request_id="workflow-request-unknown-compatibility-key",
                distribution_id="enzymedesign",
                compatibility_skill_keys=("private-unregistered-skill",),
            )
        )

    assert caught.value.code == "enzymedesign_workflow_compatibility_key_unknown"
    assert caught.value.diagnostic_id.startswith("diagnostic-workflow-")
    assert isinstance(caught.value.__cause__, KeyError)
    assert "private-unregistered-skill" not in str(caught.value)


def test_all_adopted_roles_close_catalog_with_direct_deferred_and_hidden() -> None:
    composition = activate_enzymedesign_composition()
    release_digest = canonical_sha256_digest({"release": "enzymedesign-policy-test"})
    policies = enzymedesign_tool_exposure_policies(
        composition.declared_tool_catalog,
        release_digest=release_digest,
    )
    catalog_names = {
        entry.contract.tool_name for entry in composition.declared_tool_catalog.entries
    }

    assert {policy.subject_role for policy in policies} == set(
        ENZYMEDESIGN_RESIDENT_ROLES
    )
    for policy in policies:
        decisions = {item.tool_name: item.exposure for item in policy.decisions}
        assert set(decisions) == catalog_names
        assert decisions["world.inspect"] is ToolExposure.DIRECT
        assert decisions["capabilities.inspect"] is ToolExposure.DIRECT
        assert ToolExposure.DEFERRED in decisions.values()
        assert ToolExposure.HIDDEN in decisions.values()

    reporter = next(policy for policy in policies if policy.subject_role == "reporter")
    reporter_decisions = {item.tool_name: item.exposure for item in reporter.decisions}
    assert reporter_decisions["report.publish"] is ToolExposure.DIRECT
    assert reporter_decisions["enzymedesign.hmmer.search"] is ToolExposure.DEFERRED
    assert reporter_decisions["hpc.workspace.exec"] is ToolExposure.HIDDEN


def test_hidden_exposure_is_also_hidden_from_subject_affordance_policy() -> None:
    composition = activate_enzymedesign_composition()
    decisions = {
        item.tool_name: item.action
        for item in enzymedesign_subject_policy_decisions(
            composition.declared_tool_catalog,
            subject_role="reporter",
        )
    }

    assert decisions["hpc.workspace.exec"] is ToolSubjectPolicyAction.HIDE
    assert decisions["enzymedesign.hmmer.search"] is ToolSubjectPolicyAction.ALLOW
    assert decisions["report.publish"] is ToolSubjectPolicyAction.ALLOW


def test_role_policy_rejects_an_incomplete_declared_catalog() -> None:
    catalog = activate_enzymedesign_composition().declared_tool_catalog

    with pytest.raises(KernelContractError) as caught:
        enzymedesign_tool_exposure_policies(
            replace(catalog, entries=catalog.entries[:-1]),
            release_digest=canonical_sha256_digest(
                {"release": "incomplete-policy-test"}
            ),
        )

    assert caught.value.code == "enzymedesign_tool_exposure_catalog_drift"
    assert caught.value.details["missing_tool_names"]
