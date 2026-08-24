from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceBlocker
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_contracts import ToolSpec
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import KernelRecordSnapshot
from openzyme_kernel.catalog import DECLARED_TOOL_CATALOG_SCHEMA_VERSION
from openzyme_kernel.catalog import DeclaredToolCatalog
from openzyme_kernel.catalog import DeclaredToolEntry
from openzyme_kernel.errors import KernelContractError
from openzyme_kernel.tool_exposure import ToolExposureRolePolicy
from openzyme_kernel.tool_exposure import ControlStoreCommandToolExpansionStore
from openzyme_kernel.tool_exposure import inspect_and_expand_tool_exposure
from openzyme_kernel.tool_exposure import model_visible_exposed_tool_specs
from openzyme_kernel.tool_exposure import resolve_public_tool_exposure_snapshot
from openzyme_kernel.tool_exposure import resolve_tool_exposure_snapshot
from openzyme_kernel.tool_exposure import resolve_tool_exposure_role_policy
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        tool_name=name,
        description=f"Safely invoke {name}.",
        input_schema={"type": "object", "additionalProperties": False},
    )


def _catalog() -> DeclaredToolCatalog:
    entries = tuple(
        DeclaredToolEntry(
            owner_component_id="openzyme.kernel",
            runtime_id=f"runtime.{name}",
            contract=_spec(name),
        )
        for name in ("capabilities.inspect", "plugin.deferred", "plugin.hidden")
    )
    digest = canonical_sha256_digest(
        {
            "schema_version": DECLARED_TOOL_CATALOG_SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in entries],
        }
    )
    return DeclaredToolCatalog(entries=entries, catalog_digest=digest)


def _workflow() -> WorkflowAuthorityBinding:
    registry = _digest("registry")
    selection = canonical_sha256_digest(
        {
            "schema_version": "workflow_selection_binding@1",
            "registry_snapshot_digest": registry,
            "selected_workflow_refs": [],
        }
    )
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="member-1",
        selected_workflow_refs=(),
        selection_digest=selection,
        registry_snapshot_digest=registry,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-24T00:00:00+00:00",
        updated_at="2026-08-24T00:00:00+00:00",
    )


def _affordance(*, deferred_available: bool = True) -> ToolAffordanceSnapshot:
    catalog = _catalog()
    values = (
        ToolAffordance(
            tool_name="capabilities.inspect",
            tool_contract_digest=catalog.get("capabilities.inspect").contract.contract_digest,
            state=ToolAffordanceState.AVAILABLE,
            required_authorities=(),
        ),
        ToolAffordance(
            tool_name="plugin.deferred",
            tool_contract_digest=catalog.get("plugin.deferred").contract.contract_digest,
            state=(
                ToolAffordanceState.AVAILABLE
                if deferred_available
                else ToolAffordanceState.BLOCKED_AUTHORITY
            ),
            route_ids=("route-1",) if deferred_available else (),
            required_authorities=(),
            blockers=(
                ()
                if deferred_available
                else (ToolAffordanceBlocker(code="authority_requirement_unsatisfied"),)
            ),
        ),
        ToolAffordance(
            tool_name="plugin.hidden",
            tool_contract_digest=catalog.get("plugin.hidden").contract.contract_digest,
            state=ToolAffordanceState.AVAILABLE,
            required_authorities=(),
        ),
    )
    snapshot = ToolAffordanceSnapshot(
        snapshot_id="affordance-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_tool_catalog_digest=catalog.catalog_digest,
        capability_binding_digest=_digest("binding"),
        authority_lease_digest=_digest("lease"),
        workspace_generation=1,
        health_observation_digest=_digest("health"),
        subject_policy_digest=_digest("affordance-policy"),
        affordances=values,
        created_at="2026-08-24T00:00:00+00:00",
        snapshot_digest=_digest("placeholder"),
    )
    return replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )


def _policy(*, missing_hidden: bool = False) -> ToolExposureRolePolicy:
    decisions = (
        ToolExposureDecision(
            "capabilities.inspect",
            ToolExposure.DIRECT,
            "stable_collaboration_baseline",
        ),
        ToolExposureDecision(
            "plugin.deferred",
            ToolExposure.DEFERRED,
            "role_long_tail",
        ),
    )
    if not missing_hidden:
        decisions = (
            *decisions,
            ToolExposureDecision(
                "plugin.hidden",
                ToolExposure.HIDDEN,
                "role_forbidden",
            ),
        )
    return ToolExposureRolePolicy(
        policy_id="policy-1",
        distribution_id="openzyme.standard",
        release_digest=_digest("release"),
        subject_role="master",
        decisions=decisions,
    )


def _snapshot(*, deferred_available: bool = True):  # noqa: ANN201
    return resolve_tool_exposure_snapshot(
        snapshot_id="exposure-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        catalog=_catalog(),
        affordance_snapshot=_affordance(deferred_available=deferred_available),
        workflow_binding=_workflow(),
        policy=_policy(),
        adopted_release_digest=_digest("release"),
        created_at="2026-08-24T00:00:00+00:00",
    )


def test_exposure_policy_requires_exact_catalog_coverage() -> None:
    with pytest.raises(KernelContractError) as error:
        resolve_tool_exposure_snapshot(
            snapshot_id="exposure-1",
            session_id="session-1",
            agent_member_id="member-1",
            turn_id="turn-1",
            catalog=_catalog(),
            affordance_snapshot=_affordance(),
            workflow_binding=_workflow(),
            policy=_policy(missing_hidden=True),
            adopted_release_digest=_digest("release"),
            created_at="2026-08-24T00:00:00+00:00",
        )

    assert error.value.code == "tool_exposure_policy_catalog_drift"
    assert error.value.details["missing_tool_names"] == ["plugin.hidden"]


def test_role_policy_resolver_requires_one_full_catalog_decision_set() -> None:
    policy = resolve_tool_exposure_role_policy(
        policies=(_policy(),),
        distribution_id="openzyme.standard",
        adopted_release_digest=_digest("release"),
        subject_role="master",
        catalog=_catalog(),
    )

    assert policy.policy_id == "policy-1"
    assert tuple(item.tool_name for item in policy.decisions) == (
        "capabilities.inspect",
        "plugin.deferred",
        "plugin.hidden",
    )


def test_role_policy_rejects_duplicate_matching_entry_without_visibility_default() -> None:
    policy = _policy()

    with pytest.raises(KernelContractError) as error:
        resolve_tool_exposure_role_policy(
            policies=(policy, policy),
            distribution_id="openzyme.standard",
            adopted_release_digest=_digest("release"),
            subject_role="master",
            catalog=_catalog(),
        )

    assert error.value.code == "tool_exposure_role_policy_unresolved"
    assert error.value.details["matching_policy_count"] == 2
    assert error.value.details["fallback_performed"] is False


def test_role_policy_rejects_duplicate_tool_decision_before_snapshot() -> None:
    policy = _policy()

    with pytest.raises(ValueError, match="decisions must be unique"):
        ToolExposureRolePolicy(
            policy_id=policy.policy_id,
            distribution_id=policy.distribution_id,
            release_digest=policy.release_digest,
            subject_role=policy.subject_role,
            decisions=(*policy.decisions, policy.decisions[0]),
        )


def test_role_policy_rejects_unknown_extra_entry_without_visibility_default() -> None:
    policy = _policy()
    drifted = ToolExposureRolePolicy(
        policy_id=policy.policy_id,
        distribution_id=policy.distribution_id,
        release_digest=policy.release_digest,
        subject_role=policy.subject_role,
        decisions=(
            *policy.decisions,
            ToolExposureDecision(
                "plugin.extra",
                ToolExposure.DIRECT,
                "undeclared_extra",
            ),
        ),
    )

    with pytest.raises(KernelContractError) as error:
        resolve_tool_exposure_role_policy(
            policies=(drifted,),
            distribution_id="openzyme.standard",
            adopted_release_digest=_digest("release"),
            subject_role="master",
            catalog=_catalog(),
        )

    assert error.value.code == "tool_exposure_policy_catalog_drift"
    assert error.value.details["missing_tool_names"] == []
    assert error.value.details["unknown_tool_names"] == ["plugin.extra"]
    assert error.value.details["fallback_performed"] is False


def test_authority_free_public_projection_removes_hidden_everywhere() -> None:
    public = resolve_public_tool_exposure_snapshot(
        snapshot_id="public-exposure-1",
        catalog=_catalog(),
        policy=_policy(),
        available_tool_names=(
            "capabilities.inspect",
            "plugin.deferred",
            "plugin.hidden",
        ),
        affordances=(
            {"tool_name": "plugin.hidden", "state": "available"},
            {"tool_name": "plugin.deferred", "state": "available"},
            {"tool_name": "capabilities.inspect", "state": "available"},
        ),
        created_at="2026-08-24T00:00:00+00:00",
    )
    payload = public.to_dict()

    assert payload["schema_version"] == "tool_exposure_public@1"
    assert payload["workflow_authority_bound"] is False
    assert payload["available_tool_names"] == ["capabilities.inspect"]
    assert "plugin.deferred" not in payload["available_tool_names"]
    assert "plugin.hidden" not in payload["available_tool_names"]
    assert "plugin.hidden" not in {
        item["tool_name"] for item in payload["affordances"]
    }
    assert "plugin.hidden" not in {
        item["tool_name"] for item in payload["tool_exposure"]
    }


def test_initial_model_list_has_only_callable_direct_tools() -> None:
    names = tuple(
        spec.tool_name
        for spec in model_visible_exposed_tool_specs(
            catalog=_catalog(),
            affordance_snapshot=_affordance(),
            exposure_snapshot=_snapshot(),
        )
    )

    assert names == ("capabilities.inspect",)


def test_inspect_expands_one_deferred_tool_without_hidden_disclosure_or_route_change() -> None:
    catalog = _catalog()
    affordance = _affordance()
    exposure = _snapshot()
    inspection = inspect_and_expand_tool_exposure(
        command_id="command-1",
        catalog=catalog,
        affordance_snapshot=affordance,
        exposure_snapshot=exposure,
        current_expansion=None,
        requested_tool_names=("plugin.hidden", "plugin.deferred", "unknown.tool"),
        query=None,
        max_items=20,
        created_at="2026-08-24T00:00:01+00:00",
    )

    assert inspection.undisclosed_or_unknown_count == 2
    assert {item["tool_name"] for item in inspection.reflection} == {
        "capabilities.inspect",
        "plugin.deferred",
    }
    assert inspection.expansion is not None
    assert inspection.expansion.expanded_tool_names == ("plugin.deferred",)
    visible = model_visible_exposed_tool_specs(
        catalog=catalog,
        affordance_snapshot=affordance,
        exposure_snapshot=exposure,
        expansion=inspection.expansion,
    )
    assert tuple(spec.tool_name for spec in visible) == (
        "capabilities.inspect",
        "plugin.deferred",
    )
    reflected = next(
        item for item in inspection.reflection if item["tool_name"] == "plugin.deferred"
    )
    assert reflected["route_ids"] == ("route-1",)
    assert inspection.to_dict()["authority_widened"] is False
    assert inspection.to_dict()["route_changed"] is False


def test_blocked_deferred_tool_is_reflected_but_not_expanded() -> None:
    inspection = inspect_and_expand_tool_exposure(
        command_id="command-1",
        catalog=_catalog(),
        affordance_snapshot=_affordance(deferred_available=False),
        exposure_snapshot=_snapshot(deferred_available=False),
        current_expansion=None,
        requested_tool_names=("plugin.deferred",),
        query=None,
        max_items=20,
        created_at="2026-08-24T00:00:01+00:00",
    )

    assert inspection.expansion is None
    assert inspection.blocked_expansion_names == ("plugin.deferred",)
    deferred = next(
        item for item in inspection.reflection if item["tool_name"] == "plugin.deferred"
    )
    assert deferred["affordance_state"] == "blocked_authority"


def test_expansion_is_exactly_command_scoped() -> None:
    inspection = inspect_and_expand_tool_exposure(
        command_id="command-1",
        catalog=_catalog(),
        affordance_snapshot=_affordance(),
        exposure_snapshot=_snapshot(),
        current_expansion=None,
        requested_tool_names=("plugin.deferred",),
        query=None,
        max_items=20,
        created_at="2026-08-24T00:00:01+00:00",
    )
    assert inspection.expansion is not None

    with pytest.raises(KernelContractError) as error:
        inspect_and_expand_tool_exposure(
            command_id="command-2",
            catalog=_catalog(),
            affordance_snapshot=_affordance(),
            exposure_snapshot=_snapshot(),
            current_expansion=inspection.expansion,
            requested_tool_names=(),
            query=None,
            max_items=20,
            created_at="2026-08-24T00:00:02+00:00",
        )

    assert error.value.code == "command_tool_expansion_scope_drift"


def _durable_expansion_store() -> tuple[
    ControlStoreCommandToolExpansionStore,
    InMemoryControlStore,
]:
    workflow = _workflow()
    exposure = _snapshot()
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=4,
                payload={"session_id": "session-1", "status": "active"},
            ),
            KernelRecordSnapshot.create(
                entity_type="runtime_turn_command",
                entity_id="command-1",
                state_version=1,
                payload={
                    "command_id": "command-1",
                    "session_id": "session-1",
                    "agent_member_id": "member-1",
                    "signal_id": "signal-1",
                    "signal_claim_token": "signal-claim-1",
                    "runtime_lease_token": "runtime-lease-1",
                    "runtime_lease_generation": 1,
                    "runtime_fence": 1,
                    "process_epoch": 1,
                    "workflow_authority_id": workflow.authority_id,
                    "workflow_authority_epoch": workflow.epoch,
                    "workflow_authority_digest": workflow.binding_digest,
                    "tool_exposure_snapshot_id": exposure.exposure_snapshot_id,
                    "tool_exposure_snapshot_digest": (
                        exposure.exposure_snapshot_digest
                    ),
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_runtime_signal",
                entity_id="signal-1",
                state_version=2,
                payload={
                    "session_id": "session-1",
                    "status": "claimed",
                    "claim_token": "signal-claim-1",
                    "claim_expires_at": "2026-08-24T00:05:00+00:00",
                    "session_lease_token": "runtime-lease-1",
                    "session_fencing_token": 1,
                    "capability_lease_id": "authority-lease-1",
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="session_runtime_lease",
                entity_id="session-1",
                state_version=1,
                payload={
                    "session_id": "session-1",
                    "lease_token": "runtime-lease-1",
                    "generation": 1,
                    "fencing_token": 1,
                    "expires_at": "2026-08-24T00:05:00+00:00",
                    "released_at": None,
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="member-1",
                state_version=1,
                payload={"process_epoch": 1, "status": "working"},
            ),
            KernelRecordSnapshot.create(
                entity_type="workflow_authority_binding",
                entity_id=workflow.authority_id,
                state_version=1,
                payload=workflow.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="tool_exposure_snapshot",
                entity_id=exposure.exposure_snapshot_id,
                state_version=1,
                payload=exposure.to_dict(),
            ),
        )
    )
    return (
        ControlStoreCommandToolExpansionStore(
            store=store,
            reader=store,
            clock=DeterministicClock(
                datetime(2026, 8, 24, 0, 0, 2, tzinfo=UTC)
            ),
            ids=DeterministicIdGenerator(),
        ),
        store,
    )


def test_control_store_expansion_owner_is_cas_fenced_and_restart_stable() -> None:
    owner, store = _durable_expansion_store()
    inspection = inspect_and_expand_tool_exposure(
        command_id="command-1",
        catalog=_catalog(),
        affordance_snapshot=_affordance(),
        exposure_snapshot=_snapshot(),
        current_expansion=None,
        requested_tool_names=("plugin.deferred",),
        query=None,
        max_items=20,
        created_at="2026-08-24T00:00:01+00:00",
    )
    expansion = inspection.expansion
    assert expansion is not None

    owner.put(expansion, expected_revision=0)
    owner.put(expansion, expected_revision=0)

    assert store.commit_count == 1
    assert owner.get("command-1") == expansion
    restarted = ControlStoreCommandToolExpansionStore(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 24, 0, 0, 3, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )
    assert restarted.get("command-1") == expansion

    with pytest.raises(KernelContractError) as stale:
        restarted.put(
            replace(
                expansion,
                expansion_id="tool-expansion-next",
                expansion_revision=2,
                created_at="2026-08-24T00:00:02+00:00",
            ),
            expected_revision=0,
        )
    assert stale.value.code == "command_tool_expansion_revision_conflict"
