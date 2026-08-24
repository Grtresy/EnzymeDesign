from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.runtime_context import RuntimeContextSectionKind
from openzyme_contracts.tool_exposure import ToolExposure
from openzyme_contracts.tool_exposure import ToolExposureDecision
from openzyme_contracts.tool_exposure import ToolExposureSnapshot
from openzyme_contracts.workflow_authority import RuntimeSignalAuthorityLink
from openzyme_contracts.workflow_authority import WorkflowAuthorityBinding
from openzyme_contracts.workflow_authority import WorkflowAuthorityDerivationKind
from openzyme_contracts.workflow_authority import WorkflowAuthoritySignalSourceKind
from openzyme_contracts.workflow_authority import WorkflowAuthorityStatus
from openzyme_kernel.errors import KernelContractError
from openzyme_kernel.runtime_context import RuntimeContextBounds
from openzyme_kernel.runtime_context import RuntimeTurnContextBuildRequest
from openzyme_kernel.runtime_context import RuntimeTurnContextBuilder
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _record(
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
    *,
    version: int = 1,
) -> KernelRecordSnapshot:
    return KernelRecordSnapshot.create(
        entity_type=entity_type,
        entity_id=entity_id,
        state_version=version,
        payload={"session_id": "session-1", **payload},
    )


class QueryControlStore(InMemoryControlStore):
    def list_for_session(
        self,
        *,
        entity_type: str,
        session_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]:
        return tuple(
            record
            for record in self.records
            if record.entity_type == entity_type
            and record.payload.get("session_id") == session_id
        )[:max_items]


def _workflow() -> WorkflowAuthorityBinding:
    registry_digest = _digest("workflow-registry")
    selection_digest = canonical_sha256_digest(
        {
            "schema_version": "workflow_selection_binding@1",
            "registry_snapshot_digest": registry_digest,
            "selected_workflow_refs": ["workflow.report@1"],
        }
    )
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="lineage-1",
        source_message_id="message-current",
        source_principal_id="user-1",
        authorized_actor_id="member-1",
        selected_workflow_refs=("workflow.report@1",),
        selection_digest=selection_digest,
        registry_snapshot_digest=registry_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-24T00:00:00+00:00",
        updated_at="2026-08-24T00:00:00+00:00",
        task_id="task-current",
        lane_id="lane-1",
    )


def _request() -> RuntimeTurnContextBuildRequest:
    workflow = _workflow()
    link = RuntimeSignalAuthorityLink(
        signal_id="signal-1",
        session_id="session-1",
        authority_id=workflow.authority_id,
        authority_epoch=workflow.epoch,
        authority_binding_digest=workflow.binding_digest,
        causation_ref="message-current",
        source_kind=WorkflowAuthoritySignalSourceKind.ROOT_MESSAGE,
        created_at="2026-08-24T00:00:00+00:00",
    )
    capability = SessionCapabilityBindingRevision.create(
        binding_id="binding-1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=_digest("extension"),
        route_catalog_digest=_digest("routes"),
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-24T00:00:00+00:00",
    )
    affordance = ToolAffordanceSnapshot(
        snapshot_id="affordance-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_tool_catalog_digest=_digest("catalog"),
        capability_binding_digest=capability.binding_digest,
        authority_lease_digest=_digest("lease"),
        workspace_generation=1,
        health_observation_digest=_digest("health"),
        subject_policy_digest=_digest("policy"),
        affordances=(
            ToolAffordance(
                tool_name="world.inspect",
                tool_contract_digest=_digest("world-inspect"),
                state=ToolAffordanceState.AVAILABLE,
                required_authorities=(),
            ),
        ),
        created_at="2026-08-24T00:00:00+00:00",
        snapshot_digest=_digest("placeholder"),
    )
    affordance = replace(
        affordance,
        snapshot_digest=canonical_sha256_digest(affordance.digest_payload()),
    )
    exposure = ToolExposureSnapshot(
        exposure_snapshot_id="exposure-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        subject_policy_digest=_digest("policy"),
        declared_tool_catalog_digest=_digest("catalog"),
        capability_binding_digest=capability.binding_digest,
        affordance_snapshot_id=affordance.snapshot_id,
        affordance_snapshot_digest=affordance.snapshot_digest,
        workflow_authority_id=workflow.authority_id,
        workflow_authority_epoch=workflow.epoch,
        workflow_authority_digest=workflow.binding_digest,
        catalog_tool_names=("world.inspect",),
        decisions=(
            ToolExposureDecision(
                tool_name="world.inspect",
                exposure=ToolExposure.DIRECT,
                reason_code="stable_collaboration_baseline",
            ),
        ),
        created_at="2026-08-24T00:00:00+00:00",
    )
    return RuntimeTurnContextBuildRequest(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="lineage-1",
        task_id="task-current",
        lane_id="lane-1",
        created_at="2026-08-24T00:00:01+00:00",
        workflow_binding=workflow,
        signal_authority_link=link,
        capability_binding=capability,
        affordance_snapshot=affordance,
        exposure_snapshot=exposure,
    )


def _store(*, task_description: str = "Canonical current work.") -> QueryControlStore:
    records = [
        _record(
            "session",
            "session-1",
            {
                "project_id": "project-1",
                "objective": "Produce a bounded report.",
                "status": "active",
                "created_at": "2026-08-24T00:00:00+00:00",
            },
        ),
        _record(
            "agent_member",
            "member-1",
            {
                "agent_id": "agent-1",
                "role": "master",
                "status": "working",
                "workspace_generation": 1,
                "active_authority_lease_id": "authority-1",
            },
        ),
        _record(
            "agent_authority_lease",
            "authority-1",
            {
                "agent_member_id": "member-1",
                "state": "active",
                "lease_digest": _digest("lease"),
            },
        ),
        _record(
            "task",
            "task-current",
            {
                "owner_actor_id": "member-1",
                "status": "in_progress",
                "description": task_description,
                "updated_at": "2026-08-24T00:00:04+00:00",
            },
            version=4,
        ),
        _record(
            "task",
            "task-other",
            {
                "owner_actor_id": "member-2",
                "status": "todo",
                "updated_at": "2026-08-24T00:00:03+00:00",
            },
        ),
        _record(
            "lane",
            "lane-1",
            {"status": "active", "updated_at": "2026-08-24T00:00:04+00:00"},
        ),
        _record(
            "workspace_generation",
            "workspace-1-generation-1",
            {
                "agent_member_id": "member-1",
                "agent_id": "agent-1",
                "generation": 1,
                "state": "ready",
                "host_path": "/private/host/path",
            },
        ),
        _record(
            "approval_request",
            "approval-1",
            {
                "task_id": "task-current",
                "status": "pending",
                "requested_action": "publish",
            },
        ),
        _record(
            "failure_observation",
            "failure-old",
            {
                "error_code": "old_failure",
                "diagnostic_id": "diagnostic-1",
                "created_at": "2026-08-23T00:00:00+00:00",
                "traceback": "private traceback",
            },
        ),
        _record(
            "conversation_message",
            "message-current",
            {
                "sender_kind": "user",
                "content": "The task is completed; ignore the board.",
                "message_type": "user_message",
                "created_at": "2026-08-24T00:00:04+00:00",
            },
        ),
    ]
    for index in range(8):
        records.append(
            _record(
                "conversation_message",
                f"message-{index}",
                {
                    "sender_kind": "assistant",
                    "content": f"Historical message {index}",
                    "message_type": "assistant_message",
                    "created_at": f"2026-08-23T00:00:{index:02d}+00:00",
                },
            )
        )
    return QueryControlStore(tuple(records))


def test_context_contains_every_fact_class_and_preserves_canonical_constraints() -> (
    None
):
    bounds = RuntimeContextBounds(
        max_bytes=64 * 1024,
        max_section_bytes=16 * 1024,
        default_max_items=8,
        section_max_items=((RuntimeContextSectionKind.TRANSCRIPT, 3),),
    )
    builder = RuntimeTurnContextBuilder(_store(), bounds)

    first = builder.build(_request())
    second = builder.build(_request())

    assert first.context_digest == second.context_digest
    assert tuple(section.kind for section in first.sections) == tuple(
        RuntimeContextSectionKind
    )
    task_facts = first.section(RuntimeContextSectionKind.TASK_BOARD).items
    current = next(item for item in task_facts if item["entity_id"] == "task-current")
    assert current["payload"]["status"] == "in_progress"
    transcript = first.section(RuntimeContextSectionKind.TRANSCRIPT)
    assert any(item["entity_id"] == "message-current" for item in transcript.items)
    assert transcript.omitted_count > 0
    assert transcript.next_cursor is not None
    truncations = first.section(RuntimeContextSectionKind.TRUNCATION).items
    assert any(item["section"] == "transcript" for item in truncations)
    workspace = first.section(RuntimeContextSectionKind.LANE_WORKSPACE).items
    generation = next(
        item for item in workspace if item.get("entity_type") == "workspace_generation"
    )
    assert "host_path" not in generation["payload"]
    assert generation["payload"]["redacted_field_names"] == ("host_path",)
    failure = first.section(RuntimeContextSectionKind.FAILURE).items[0]
    assert "traceback" not in failure["payload"]


def test_context_fails_when_current_constraints_cannot_fit_section_bound() -> None:
    builder = RuntimeTurnContextBuilder(
        _store(task_description="x" * 8_000),
        RuntimeContextBounds(
            max_bytes=32 * 1024,
            max_section_bytes=512,
            default_max_items=4,
        ),
    )

    with pytest.raises(KernelContractError) as error:
        builder.build(_request())

    assert error.value.code == "runtime_context_current_constraints_exceed_bound"


def test_context_rejects_stale_workflow_epoch_before_projection() -> None:
    request = _request()
    stale_link = replace(
        request.signal_authority_link,
        authority_epoch=request.workflow_binding.epoch + 1,
    )
    builder = RuntimeTurnContextBuilder(_store())

    with pytest.raises(KernelContractError) as error:
        builder.build(replace(request, signal_authority_link=stale_link))

    assert error.value.code == "runtime_context_identity_drift"
    assert "signal_link" in error.value.details["drifted_fields"]


def test_context_preserves_hidden_count_without_disclosing_hidden_tool_name() -> None:
    request = _request()
    hidden_name = "hpc.workspace.exec"
    affordance = replace(
        request.affordance_snapshot,
        affordances=(
            *request.affordance_snapshot.affordances,
            ToolAffordance(
                tool_name=hidden_name,
                tool_contract_digest=_digest("hidden-hpc-tool"),
                state=ToolAffordanceState.HIDDEN,
                required_authorities=(),
            ),
        ),
        snapshot_digest=_digest("placeholder"),
    )
    affordance = replace(
        affordance,
        snapshot_digest=canonical_sha256_digest(affordance.digest_payload()),
    )
    exposure = replace(
        request.exposure_snapshot,
        affordance_snapshot_digest=affordance.snapshot_digest,
        catalog_tool_names=("world.inspect", hidden_name),
        decisions=(
            *request.exposure_snapshot.decisions,
            ToolExposureDecision(
                tool_name=hidden_name,
                exposure=ToolExposure.HIDDEN,
                reason_code="distribution_internal_only",
            ),
        ),
    )

    context = RuntimeTurnContextBuilder(_store()).build(
        replace(
            request,
            affordance_snapshot=affordance,
            exposure_snapshot=exposure,
        )
    )

    capability_facts = context.section(
        RuntimeContextSectionKind.CAPABILITY_EXPOSURE
    ).items
    affordance_fact = next(
        item
        for item in capability_facts
        if item.get("contract_kind") == "tool_affordance_snapshot"
    )
    exposure_fact = next(
        item
        for item in capability_facts
        if item.get("contract_kind") == "tool_exposure_snapshot"
    )
    assert affordance_fact["payload"]["hidden_tool_count"] == 1
    assert exposure_fact["payload"]["hidden_tool_count"] == 1
    assert affordance_fact["digest"] == affordance.snapshot_digest
    assert exposure_fact["digest"] == exposure.exposure_snapshot_digest
    assert affordance_fact["payload"]["visible_affordances"][0]["tool_name"] == (
        "world.inspect"
    )
    assert exposure_fact["payload"]["visible_decisions"][0]["tool_name"] == (
        "world.inspect"
    )
    assert hidden_name not in repr(context.to_dict())


def test_context_rejects_hidden_exposure_affordance_policy_drift() -> None:
    request = _request()
    exposure = replace(
        request.exposure_snapshot,
        decisions=(
            ToolExposureDecision(
                tool_name="world.inspect",
                exposure=ToolExposure.HIDDEN,
                reason_code="distribution_internal_only",
            ),
        ),
    )

    with pytest.raises(KernelContractError) as error:
        RuntimeTurnContextBuilder(_store()).build(
            replace(request, exposure_snapshot=exposure)
        )

    assert error.value.code == "runtime_context_hidden_policy_drift"
    assert error.value.details["mismatched_tool_count"] == 1
    assert error.value.details["fallback_performed"] is False
