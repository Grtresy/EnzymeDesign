from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from types import SimpleNamespace

import pytest

from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolExposure
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import WorkflowSelectionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import WorkflowRegistryResolutionError
from openzyme_kernel import KernelContractError
from openzyme_kernel.affordance import ToolSubjectPolicyAction
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import InMemoryControlStore
from openzyme_kernel.tool_exposure import ToolExposureRolePolicy
from openzyme_kernel.tool_exposure import inspect_and_expand_tool_exposure
from openzyme_kernel.tool_exposure import resolve_tool_exposure_role_policy
from openzyme_kernel.tool_exposure import resolve_tool_exposure_snapshot
from openzyme_standard import activate_standard_composition
from openzyme_standard.role_policies import STANDARD_ADOPTED_TOOL_NAMES
from openzyme_standard.role_policies import STANDARD_RESIDENT_ROLES
from openzyme_standard.role_policies import standard_subject_policy_decisions
from openzyme_standard.role_policies import standard_subject_policy_decisions_by_role
from openzyme_standard.role_policies import standard_tool_exposure_policies
from openzyme_standard.runtime_admission import StandardKernelRuntimeAdmissionSource
from openzyme_standard.workflow_registry import (
    STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST,
)
from openzyme_standard.workflow_registry import StandardExplicitEmptyWorkflowRegistry


def _registry() -> StandardExplicitEmptyWorkflowRegistry:
    return StandardExplicitEmptyWorkflowRegistry(
        clock=DeterministicClock(datetime(2026, 8, 24, tzinfo=UTC))
    )


def _workflow_authority_records(
    *,
    registry_snapshot_digest: str,
) -> tuple[InMemoryControlStore, SimpleNamespace]:
    selection_digest = canonical_sha256_digest(
        {
            "schema_version": "workflow_selection_binding@1",
            "registry_snapshot_digest": registry_snapshot_digest,
            "selected_workflow_refs": [],
        }
    )
    binding = WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="request-lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="master-1",
        selected_workflow_refs=(),
        selection_digest=selection_digest,
        registry_snapshot_digest=registry_snapshot_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-24T00:00:00+00:00",
        updated_at="2026-08-24T00:00:00+00:00",
    )
    link = RuntimeSignalAuthorityLink(
        signal_id="signal-1",
        session_id="session-1",
        authority_id=binding.authority_id,
        authority_epoch=binding.epoch,
        authority_binding_digest=binding.binding_digest,
        causation_ref="message-1",
        source_kind=WorkflowAuthoritySignalSourceKind.ROOT_MESSAGE,
        created_at="2026-08-24T00:00:00+00:00",
    )
    records = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="workflow_authority_binding",
                entity_id=binding.authority_id,
                state_version=1,
                payload=binding.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="runtime_signal_authority_link",
                entity_id=link.signal_id,
                state_version=1,
                payload=link.to_dict(),
            ),
        )
    )
    signal = SimpleNamespace(
        signal_id="signal-1",
        session_id="session-1",
        task_id=None,
        lane_id=None,
    )
    return records, signal


def test_workflow_registry_resolves_only_the_explicit_empty_selection() -> None:
    resolved = _registry().resolve(
        WorkflowSelectionRequest(
            request_id="workflow-request-empty",
            distribution_id="openzyme.standard",
            requested_workflow_refs=(),
        )
    )

    assert resolved.selected_workflow_refs == ()
    assert (
        resolved.registry_snapshot_digest == STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST
    )


@pytest.mark.parametrize(
    ("distribution_id", "workflow_refs", "skill_keys"),
    (
        ("another.distribution", (), ()),
        ("openzyme.standard", ("latest",), ()),
        ("openzyme.standard", (), ("all",)),
    ),
)
def test_workflow_registry_rejects_distribution_or_nonempty_selection_drift(
    distribution_id: str,
    workflow_refs: tuple[str, ...],
    skill_keys: tuple[str, ...],
) -> None:
    with pytest.raises(WorkflowRegistryResolutionError) as caught:
        _registry().resolve(
            WorkflowSelectionRequest(
                request_id="workflow-request-invalid",
                distribution_id=distribution_id,
                requested_workflow_refs=workflow_refs,
                compatibility_skill_keys=skill_keys,
            )
        )

    assert caught.value.code.startswith("standard_workflow_")
    assert caught.value.diagnostic_id.startswith("diagnostic-workflow-")


def test_runtime_admission_names_missing_workflow_signal_link_exactly() -> None:
    source = SimpleNamespace(
        records=InMemoryControlStore(),
        workflow_registry_snapshot_digest=STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST,
    )
    signal = SimpleNamespace(
        signal_id="signal-1",
        session_id="session-1",
        task_id=None,
        lane_id=None,
    )

    with pytest.raises(KernelContractError) as caught:
        StandardKernelRuntimeAdmissionSource._workflow_authority(
            source,
            signal=signal,
            member_id="master-1",
        )

    assert caught.value.code == "workflow_authority_link_missing"


def test_runtime_admission_rejects_drifted_workflow_registry_snapshot() -> None:
    records, signal = _workflow_authority_records(
        registry_snapshot_digest=canonical_sha256_digest(
            {"registry": "retired-standard-snapshot"}
        )
    )
    source = SimpleNamespace(
        records=records,
        workflow_registry_snapshot_digest=STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST,
    )

    with pytest.raises(KernelContractError) as caught:
        StandardKernelRuntimeAdmissionSource._workflow_authority(
            source,
            signal=signal,
            member_id="master-1",
        )

    assert caught.value.code == "workflow_authority_stale"
    assert caught.value.details["fallback_performed"] is False


def test_every_standard_resident_role_explicitly_allows_and_directly_exposes_catalog() -> (
    None
):
    catalog = activate_standard_composition().declared_tool_catalog
    release_digest = canonical_sha256_digest({"release": "standard-policy-test"})
    policies = standard_tool_exposure_policies(
        catalog,
        release_digest=release_digest,
    )
    catalog_names = {entry.contract.tool_name for entry in catalog.entries}

    assert tuple(entry.contract.tool_name for entry in catalog.entries) == (
        STANDARD_ADOPTED_TOOL_NAMES
    )
    assert {policy.subject_role for policy in policies} == set(STANDARD_RESIDENT_ROLES)
    for policy in policies:
        assert {decision.tool_name for decision in policy.decisions} == catalog_names
        assert {decision.exposure for decision in policy.decisions} == {
            ToolExposure.DIRECT
        }
        execution = standard_subject_policy_decisions(
            catalog,
            subject_role=policy.subject_role,
        )
        assert {decision.tool_name for decision in execution} == catalog_names
        assert {decision.action for decision in execution} == {
            ToolSubjectPolicyAction.ALLOW
        }


@pytest.mark.parametrize(
    "entrypoint",
    ("subject", "subject_by_role", "exposure"),
)
@pytest.mark.parametrize(
    ("drift", "expected_missing", "expected_unknown"),
    (
        ("missing", ["workspace.status"], []),
        ("unknown", [], ["enzymedesign.hmmer.search"]),
    ),
)
def test_every_standard_policy_entrypoint_rejects_real_catalog_drift(
    entrypoint: str,
    drift: str,
    expected_missing: list[str],
    expected_unknown: list[str],
) -> None:
    catalog = activate_standard_composition().declared_tool_catalog
    if drift == "missing":
        drifted_catalog = replace(
            catalog,
            entries=tuple(
                entry
                for entry in catalog.entries
                if entry.contract.tool_name != "workspace.status"
            ),
        )
    else:
        source_entry = catalog.entries[0]
        drifted_catalog = replace(
            catalog,
            entries=(
                *catalog.entries,
                replace(
                    source_entry,
                    contract=replace(
                        source_entry.contract,
                        tool_name="enzymedesign.hmmer.search",
                    ),
                ),
            ),
        )

    with pytest.raises(KernelContractError) as caught:
        if entrypoint == "subject":
            standard_subject_policy_decisions(
                drifted_catalog,
                subject_role="master",
            )
        elif entrypoint == "subject_by_role":
            standard_subject_policy_decisions_by_role(drifted_catalog)
        else:
            standard_tool_exposure_policies(
                drifted_catalog,
                release_digest=canonical_sha256_digest(
                    {"release": "catalog-drift-test"}
                ),
            )

    assert caught.value.code == "standard_tool_exposure_catalog_drift"
    assert caught.value.details["missing_tool_names"] == expected_missing
    assert caught.value.details["unknown_tool_names"] == expected_unknown
    assert caught.value.details["fallback_performed"] is False


def test_role_policy_resolution_fails_closed_on_missing_release_or_catalog_decision() -> (
    None
):
    catalog = activate_standard_composition().declared_tool_catalog
    release_digest = canonical_sha256_digest({"release": "standard-policy-test"})
    policies = standard_tool_exposure_policies(
        catalog,
        release_digest=release_digest,
    )
    master = next(policy for policy in policies if policy.subject_role == "master")
    incomplete = ToolExposureRolePolicy(
        policy_id=master.policy_id,
        distribution_id=master.distribution_id,
        release_digest=master.release_digest,
        subject_role=master.subject_role,
        decisions=master.decisions[:-1],
    )

    with pytest.raises(KernelContractError) as missing_role:
        resolve_tool_exposure_role_policy(
            policies=tuple(
                policy for policy in policies if policy.subject_role != "teammate"
            ),
            distribution_id="openzyme.standard",
            adopted_release_digest=release_digest,
            subject_role="teammate",
            catalog=catalog,
        )
    assert missing_role.value.code == "tool_exposure_role_policy_unresolved"

    with pytest.raises(KernelContractError) as release_drift:
        resolve_tool_exposure_role_policy(
            policies=policies,
            distribution_id="openzyme.standard",
            adopted_release_digest=canonical_sha256_digest(
                {"release": "another-release"}
            ),
            subject_role="master",
            catalog=catalog,
        )
    assert release_drift.value.code == "tool_exposure_role_policy_unresolved"

    with pytest.raises(KernelContractError) as catalog_drift:
        resolve_tool_exposure_role_policy(
            policies=(incomplete,),
            distribution_id="openzyme.standard",
            adopted_release_digest=release_digest,
            subject_role="master",
            catalog=catalog,
        )
    assert catalog_drift.value.code == "tool_exposure_policy_catalog_drift"


def test_standard_capability_inspection_reports_vertical_tool_absent_without_fallback() -> (
    None
):
    catalog = activate_standard_composition().declared_tool_catalog
    release_digest = canonical_sha256_digest({"release": "standard-inspection-test"})
    policy = next(
        item
        for item in standard_tool_exposure_policies(
            catalog,
            release_digest=release_digest,
        )
        if item.subject_role == "master"
    )
    records, _signal = _workflow_authority_records(
        registry_snapshot_digest=STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST
    )
    binding_record = records.read(
        entity_type="workflow_authority_binding",
        entity_id="workflow-authority-1",
    )
    assert binding_record is not None
    binding = WorkflowAuthorityBinding.from_dict(binding_record.payload)
    affordances = tuple(
        ToolAffordance(
            tool_name=entry.contract.tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.AVAILABLE,
            required_authorities=(),
        )
        for entry in catalog.entries
    )
    affordance = ToolAffordanceSnapshot(
        snapshot_id="standard-affordance-1",
        session_id="session-1",
        agent_member_id="master-1",
        turn_id="standard-turn-1",
        declared_tool_catalog_digest=catalog.catalog_digest,
        capability_binding_digest=canonical_sha256_digest({"binding": "standard"}),
        authority_lease_digest=canonical_sha256_digest({"lease": "standard"}),
        workspace_generation=1,
        health_observation_digest=canonical_sha256_digest({"health": "ready"}),
        subject_policy_digest=canonical_sha256_digest({"policy": "standard"}),
        affordances=affordances,
        created_at="2026-08-24T00:00:00+00:00",
        snapshot_digest=canonical_sha256_digest({"placeholder": True}),
    )
    affordance = replace(
        affordance,
        snapshot_digest=canonical_sha256_digest(affordance.digest_payload()),
    )
    exposure = resolve_tool_exposure_snapshot(
        snapshot_id="standard-exposure-1",
        session_id="session-1",
        agent_member_id="master-1",
        turn_id="standard-turn-1",
        catalog=catalog,
        affordance_snapshot=affordance,
        workflow_binding=binding,
        policy=policy,
        adopted_release_digest=release_digest,
        created_at="2026-08-24T00:00:00+00:00",
    )

    inspection = inspect_and_expand_tool_exposure(
        command_id="standard-command-1",
        catalog=catalog,
        affordance_snapshot=affordance,
        exposure_snapshot=exposure,
        current_expansion=None,
        requested_tool_names=("enzymedesign.hmmer.search",),
        query="hmmer",
        max_items=20,
        created_at="2026-08-24T00:00:01+00:00",
    )

    assert inspection.reflection == ()
    assert inspection.expansion is None
    assert inspection.undisclosed_or_unknown_count == 1
    assert inspection.blocked_expansion_names == ()
    assert inspection.to_dict()["fallback_performed"] is False
    assert "enzymedesign.hmmer.search" not in {
        entry.contract.tool_name for entry in catalog.entries
    }
