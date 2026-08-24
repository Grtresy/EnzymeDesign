from __future__ import annotations

from dataclasses import replace
import json

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RetryEligibility
from openzyme_contracts import RuntimeCommandRecord
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import RuntimeCommandType
from openzyme_contracts import RuntimeContextSection
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import ToolInvocation
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_kernel import KernelContractError
from openzyme_kernel.public_workspace import _contract_payloads
from openzyme_kernel.public_workspace import _ordered_transcript_projection
from openzyme_kernel.public_workspace import _public_conversation_payloads
from openzyme_kernel.public_workspace import _public_failure_payloads
from openzyme_kernel.public_workspace import _resident_workspace_projection
from openzyme_kernel.public_workspace import _runtime_commands_public
from openzyme_kernel.public_workspace import _runtime_outcome_consumptions_public
from openzyme_kernel.public_workspace import _runtime_outcomes_public
from openzyme_kernel.public_workspace import _runtime_signal_public
from openzyme_kernel.public_workspace import _runtime_turn_commands_public
from openzyme_kernel.public_workspace import _session_runtime_lease_public
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_runtime_spi import RuntimeTurnOutcomeReceipt


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _record(
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
    *,
    state_version: int = 1,
) -> KernelRecordSnapshot:
    return KernelRecordSnapshot.create(
        entity_type=entity_type,
        entity_id=entity_id,
        state_version=state_version,
        payload=payload,
    )


def _subject() -> KernelRecordSnapshot:
    return _record(
        "agent_member",
        "member-1",
        {
            "agent_member_id": "member-1",
            "workspace_generation": 1,
        },
    )


def _pending_intent() -> WorkspaceProvisioningIntent:
    return WorkspaceProvisioningIntent(
        intent_id="provisioning-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace_id="workspace-1",
        generation=1,
        repository_pin_digest=_digest("repository-pin"),
        provider_id="workspace-provider",
        target_id="workspace-target",
        adapter_binding_digest=_digest("workspace-adapter"),
        controlled_operation_id="operation-1",
        status=WorkspaceProvisioningStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at="2026-08-24T00:00:00Z",
        updated_at="2026-08-24T00:00:00Z",
    )


def _generation(*, ready: bool) -> WorkspaceGeneration:
    return WorkspaceGeneration(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=1,
        state_version=2 if ready else 1,
        status=(
            WorkspaceGenerationStatus.READY
            if ready
            else WorkspaceGenerationStatus.PROVISIONING
        ),
        provider_id="workspace-provider",
        target_id="workspace-target",
        created_at="2026-08-24T00:00:00Z",
        updated_at="2026-08-24T00:01:00Z" if ready else "2026-08-24T00:00:00Z",
        root_identity_digest=_digest("workspace-root") if ready else None,
        transition_receipt_digest=(_digest("provisioning-receipt") if ready else None),
        controlled_operation_id="operation-1",
    )


def test_resident_workspace_projection_is_exact_for_pending_and_ready() -> None:
    pending = _pending_intent()
    readiness, provisioning = _resident_workspace_projection(
        subject=_subject(),
        intents=(
            _record(
                "workspace_provisioning_intent",
                pending.intent_id,
                pending.to_dict(),
            ),
        ),
        generations=(
            _record(
                "workspace_generation",
                "workspace-1",
                _generation(ready=False).to_dict(),
            ),
        ),
        runtime_bindings=(),
        failures=(),
    )

    assert readiness["readiness"] == "provisioning"
    assert readiness["next_action"] == "wait_for_provisioning_worker"
    assert provisioning["runtime_binding_id"] is None
    assert provisioning["retry_permitted"] is False

    ready = replace(
        pending,
        status=WorkspaceProvisioningStatus.READY,
        state_version=2,
        claim_epoch=1,
        claim_owner_id="provisioning-worker",
        claim_token="provisioning-claim",
        claim_expires_at="2026-08-24T00:02:00Z",
        terminal_receipt_digest=_digest("provisioning-receipt"),
        effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
        mutation_applied=True,
        retry_eligibility=RetryEligibility.TERMINAL,
        settled_at="2026-08-24T00:01:00Z",
        updated_at="2026-08-24T00:01:00Z",
    )
    binding = WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=1,
        state_version=2,
        root_identity_digest=_digest("workspace-root"),
        provider_id="workspace-provider",
        target_id="workspace-target",
    )
    readiness, provisioning = _resident_workspace_projection(
        subject=_subject(),
        intents=(
            _record(
                "workspace_provisioning_intent",
                ready.intent_id,
                ready.to_dict(),
                state_version=2,
            ),
        ),
        generations=(
            _record(
                "workspace_generation",
                "workspace-1",
                _generation(ready=True).to_dict(),
                state_version=2,
            ),
        ),
        runtime_bindings=(
            _record(
                "workspace_runtime_binding",
                binding.workspace_id,
                binding.to_dict(),
            ),
        ),
        failures=(),
    )

    assert readiness["readiness"] == "ready"
    assert readiness["next_action"] == "message_or_drain"
    assert provisioning["runtime_binding_id"] == "workspace-1"
    assert provisioning["mutation_applied"] is True


def test_ready_reconciliation_preserves_blocked_intent_and_projects_activation() -> (
    None
):
    pending = _pending_intent()
    blocked = replace(
        pending,
        status=WorkspaceProvisioningStatus.BLOCKED,
        state_version=3,
        claim_epoch=1,
        claim_owner_id="provisioning-worker",
        claim_token="provisioning-claim",
        claim_expires_at="2026-08-24T00:02:00Z",
        terminal_receipt_digest=_digest("dispatch-in-doubt-receipt"),
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        mutation_applied=None,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        reconcile_required=True,
        failure_id="failure-dispatch-in-doubt",
        diagnostic_id="diagnostic-dispatch-in-doubt",
        settled_at="2026-08-24T00:01:00Z",
        updated_at="2026-08-24T00:01:00Z",
    )
    failure = FailureObservation(
        failure_id=blocked.failure_id or "",
        session_id=blocked.session_id,
        source_kind="workspace_provisioning",
        source_ref=blocked.intent_id,
        source_version=str(blocked.state_version),
        phase="dispatch",
        failure_class=FailureClass.CONTROLLED_EFFECT,
        recoverability=FailureRecoverability.RECONCILIATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="workspace_provisioning_dispatch_in_doubt",
        safe_summary="Workspace provisioning outcome requires observation.",
        facts={},
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-08-24T00:01:00Z",
        component="openzyme.kernel",
        operation="workspace_provisioning",
        mutation_applied=None,
        fallback_performed=False,
        diagnostic_id=blocked.diagnostic_id or "",
        next_action="reconcile_workspace_provisioning",
    )
    request = WorkspaceProvisioningRequest(
        request_id="provision-request-1",
        intent_id=blocked.intent_id,
        intent_digest=_digest("claimed-intent"),
        claim_token=blocked.claim_token or "",
        claim_epoch=blocked.claim_epoch,
        session_id=blocked.session_id,
        agent_member_id=blocked.agent_member_id,
        workspace_id=blocked.workspace_id,
        generation=blocked.generation,
        repository_pin_digest=blocked.repository_pin_digest,
        provider_id=blocked.provider_id,
        target_id=blocked.target_id,
        adapter_binding_digest=blocked.adapter_binding_digest,
        controlled_operation_id=blocked.controlled_operation_id,
    )
    reconciliation = WorkspaceProvisioningReconciliation(
        reconciliation_id="reconciliation-1",
        session_id=blocked.session_id,
        intent_id=blocked.intent_id,
        blocked_intent_state_version=blocked.state_version,
        blocked_intent_digest=blocked.intent_digest,
        source_receipt_id="dispatch-in-doubt-receipt-1",
        source_receipt_digest=_digest("dispatch-in-doubt-source-receipt"),
        dispatch_receipt_digest=blocked.terminal_receipt_digest or "",
        provision_request=request,
        attempt=1,
        parent_reconciliation_id=None,
        reason_code="explicit_operator_reconciliation",
        requested_at="2026-08-24T00:02:00Z",
        requested_claim_seconds=60,
        status=WorkspaceProvisioningReconciliationStatus.READY,
        state_version=3,
        claim_epoch=1,
        created_at="2026-08-24T00:02:00Z",
        updated_at="2026-08-24T00:03:00Z",
        claim_owner_id="reconciliation-worker",
        claim_token="reconciliation-claim",
        claim_expires_at="2026-08-24T00:04:00Z",
        result_receipt_id="reconciliation-ready-receipt-1",
        result_receipt_digest=_digest("reconciliation-ready-receipt"),
        result_terminal_receipt_digest=_digest("reconciliation-terminal"),
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        retry_eligibility=RetryEligibility.TERMINAL,
        settled_at="2026-08-24T00:03:00Z",
    )
    ready_generation = replace(
        _generation(ready=True),
        state_version=3,
        transition_receipt_digest=reconciliation.result_terminal_receipt_digest,
        updated_at="2026-08-24T00:03:00Z",
    )
    binding = ready_generation.runtime_binding()

    readiness, provisioning = _resident_workspace_projection(
        subject=_subject(),
        intents=(
            _record(
                "workspace_provisioning_intent",
                blocked.intent_id,
                blocked.to_dict(),
                state_version=blocked.state_version,
            ),
        ),
        reconciliations=(
            _record(
                "workspace_provisioning_reconciliation",
                reconciliation.reconciliation_id,
                reconciliation.to_dict(),
                state_version=reconciliation.state_version,
            ),
        ),
        generations=(
            _record(
                "workspace_generation",
                ready_generation.workspace_id,
                ready_generation.to_dict(),
                state_version=ready_generation.state_version,
            ),
        ),
        runtime_bindings=(
            _record(
                "workspace_runtime_binding",
                binding.workspace_id,
                binding.to_dict(),
            ),
        ),
        failures=(
            _record(
                "failure_observation",
                failure.failure_id,
                failure.to_dict(),
            ),
        ),
    )

    assert readiness["readiness"] == "ready"
    assert readiness["failure_id"] is None
    assert readiness["next_action"] == "message_or_drain"
    assert provisioning["status"] == "blocked"
    assert provisioning["failure_id"] == failure.failure_id
    assert provisioning["runtime_binding_id"] == binding.workspace_id
    assert provisioning["reconciliation"]["status"] == "ready"
    assert provisioning["reconciliation"]["blocked_intent_digest"] == (
        blocked.intent_digest
    )


def test_resident_workspace_projection_rejects_legacy_missing_intent() -> None:
    with pytest.raises(KernelContractError) as rejected:
        _resident_workspace_projection(
            subject=_subject(),
            intents=(),
            generations=(),
            runtime_bindings=(),
            failures=(),
        )

    assert rejected.value.code == "resident_teammate_state_incompatible"
    assert rejected.value.details["fallback_performed"] is False


def _outcome_receipt() -> RuntimeTurnOutcomeReceipt:
    outcome = RuntimeTurnOutcome(
        outcome_id="outcome-1",
        command_id="turn-command-1",
        command_digest=_digest("turn-command"),
        turn_id="turn-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        signal_id="signal-1",
        signal_attempt=1,
        runtime_lease_generation=1,
        runtime_fence=1,
        process_epoch=1,
        workflow_authority_id="workflow-authority-1",
        workflow_authority_epoch=1,
        workflow_authority_digest=_digest("workflow-authority"),
        tool_exposure_snapshot_id="tool-exposure-1",
        tool_exposure_snapshot_digest=_digest("tool-exposure"),
        disposition=RuntimeTurnDisposition.IDLE,
        summary="The bounded turn is idle.",
        messages=(
            RuntimeMessage(
                message_id="assistant-1",
                role=RuntimeMessageRole.ASSISTANT,
                content="I inspected the workspace.",
                correlation_id="correlation-1",
            ),
            RuntimeMessage(
                message_id="tool-1",
                role=RuntimeMessageRole.TOOL,
                content="Workspace is ready.",
                correlation_id="correlation-1",
                tool_call_id="tool-call-1",
            ),
        ),
        correlation_id="correlation-1",
    )
    return RuntimeTurnOutcomeReceipt(
        receipt_id="outcome-receipt-1",
        outcome=outcome,
        accepted_at="2026-08-24T00:01:00Z",
    )


def test_ordered_transcript_joins_runtime_causality_and_preserves_tool_identity() -> (
    None
):
    receipt = _outcome_receipt()
    transcript = _ordered_transcript_projection(
        messages=(
            _record(
                "conversation_message",
                "user-1",
                {
                    "message_id": "user-1",
                    "sender_kind": "user",
                    "content": "Inspect the workspace.",
                    "correlation_id": "correlation-1",
                    "created_at": "2026-08-24T00:00:00Z",
                },
            ),
            *(
                _record(
                    "conversation_message",
                    message.message_id,
                    {
                        "message_id": message.message_id,
                        "sender_kind": message.role.value,
                        "content": message.content,
                        "correlation_id": message.correlation_id,
                        "created_at": receipt.accepted_at,
                    },
                )
                for message in receipt.outcome.messages
            ),
        ),
        outcomes=(
            _record(
                "runtime_turn_outcome",
                receipt.receipt_id,
                receipt.to_dict(),
            ),
        ),
    )

    rows = transcript["messages"]
    assert isinstance(rows, list)
    assert [row["role"] for row in rows] == ["user", "assistant", "tool"]
    assert rows[0]["source_command_id"] is None
    assert rows[1]["source_command_id"] == "turn-command-1"
    assert rows[1]["source_outcome_id"] == "outcome-1"
    assert rows[2]["tool_call_id"] == "tool-call-1"
    canonical = dict(transcript)
    supplied = canonical.pop("transcript_digest")
    assert canonical_sha256_digest(canonical) == supplied


def test_runtime_outcome_consumption_projects_only_closed_aggregate_facts() -> None:
    receipt = _outcome_receipt()
    settlement = {
        "schema_version": "runtime_settlement_intent@1",
        "settlement_id": "settlement-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "member-1",
        "signal_id": "signal-1",
        "signal_attempt": 1,
        "source_command_id": receipt.outcome.command_id,
        "source_command_digest": receipt.outcome.command_digest,
        "source_outcome_id": receipt.outcome.outcome_id,
        "source_outcome_digest": receipt.outcome.outcome_digest,
        "disposition": "idle",
        "waiting_approval_id": None,
        "failure_id": None,
        "task_transition_performed": False,
    }
    payload = {
        "schema_version": "runtime_outcome_consumption@2",
        "consumption_id": "consumption-1",
        "command_id": receipt.outcome.command_id,
        "command_digest": receipt.outcome.command_digest,
        "outcome_id": receipt.outcome.outcome_id,
        "outcome_digest": receipt.outcome.outcome_digest,
        "outcome_receipt": receipt.to_dict(),
        "session_id": receipt.outcome.session_id,
        "agent_id": receipt.outcome.agent_id,
        "agent_member_id": receipt.outcome.agent_member_id,
        "signal_id": receipt.outcome.signal_id,
        "signal_attempt": receipt.outcome.signal_attempt,
        "continuation_intent": None,
        "settlement_intent": settlement,
        "consumed_at": "2026-08-24T00:01:01Z",
    }
    payload["consumption_digest"] = canonical_sha256_digest(payload)

    public = _runtime_outcome_consumptions_public(
        (
            _record(
                "runtime_outcome_consumption",
                receipt.outcome.command_id,
                payload,
            ),
        )
    )[0]

    assert set(public) == {
        "schema_version",
        "consumption_id",
        "consumption_digest",
        "command_id",
        "command_digest",
        "outcome_id",
        "outcome_digest",
        "outcome_receipt_id",
        "outcome_receipt_digest",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "continuation_intent_id",
        "settlement_intent_id",
        "consumed_at",
    }
    serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
    assert "I inspected the workspace" not in serialized
    assert "Workspace is ready" not in serialized
    assert "outcome_receipt" not in public
    assert public["outcome_receipt_id"] == receipt.receipt_id

    drifted = dict(payload)
    drifted["consumption_digest"] = _digest("wrong-consumption")
    with pytest.raises(KernelContractError) as rejected:
        _runtime_outcome_consumptions_public(
            (
                _record(
                    "runtime_outcome_consumption",
                    receipt.outcome.command_id,
                    drifted,
                ),
            )
        )
    assert rejected.value.code == "public_runtime_outcome_consumption_identity_drift"


def test_closed_contract_projection_never_injects_store_state_version() -> None:
    payloads = _contract_payloads(
        (_record("runtime_turn_command", "command-1", {"schema_version": "x@1"}),)
    )

    assert payloads == [{"schema_version": "x@1"}]


def _runtime_turn_command() -> RuntimeTurnCommand:
    context = RuntimeTurnContext(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="lineage-1",
        task_id="task-1",
        lane_id="lane-1",
        sections=tuple(
            RuntimeContextSection(kind=kind, items=())
            for kind in RuntimeContextSectionKind
        ),
        max_bytes=32_768,
        created_at="2026-08-24T00:00:00Z",
    )
    return RuntimeTurnCommand(
        command_id="turn-command-private-1",
        turn_id="turn-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        signal_id="signal-1",
        signal_attempt=1,
        signal_claim_token="signal-claim-private-1",
        runtime_lease_token="runtime-lease-private-1",
        runtime_lease_generation=2,
        runtime_fence=7,
        process_epoch=3,
        distribution_id="openzyme.standard",
        distribution_manifest_digest=_digest("distribution"),
        release_digest=_digest("release"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("catalog"),
        capability_binding_id="binding-1",
        capability_binding_revision=4,
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_id="snapshot-1",
        affordance_snapshot_digest=_digest("affordance"),
        workflow_authority_id="workflow-authority-1",
        workflow_authority_epoch=1,
        workflow_authority_digest=_digest("workflow-authority"),
        signal_authority_link_digest=_digest("signal-authority-link"),
        tool_exposure_snapshot_id="exposure-1",
        tool_exposure_snapshot_digest=_digest("tool-exposure"),
        context=context,
        runtime_adapter_id="test.runtime.fake",
        runtime_adapter_contract_digest=_digest("runtime-adapter"),
        max_steps=8,
        max_duration_seconds=120,
        max_input_units=16_000,
        max_output_units=4_000,
        messages=(
            RuntimeMessage(
                message_id="runtime-input-1",
                role=RuntimeMessageRole.USER,
                content="Continue the exact task.",
            ),
        ),
        task_id="task-1",
        lane_id="lane-1",
    )


def test_public_runtime_projection_redacts_all_claim_and_lease_tokens() -> None:
    command = _runtime_turn_command()
    drain = RuntimeCommandRecord(
        command_id="runtime-drain-1",
        session_id="session-1",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest=_digest("runtime-drain"),
        idempotency_key="runtime-drain-1",
        status=RuntimeCommandStatus.CLAIMED,
        max_signals=2,
        max_steps_per_agent=4,
        auto_enqueue_ready_tasks=False,
        state_version=2,
        fencing_token=3,
        accepted_at="2026-08-24T00:00:00Z",
        claim_owner="runtime-worker-1",
        lease_token="runtime-command-lease-private-1",
        lease_expires_at="2026-08-24T00:02:00Z",
        started_at="2026-08-24T00:00:01Z",
    )
    public = {
        "signals": _runtime_signal_public(
            (
                _record(
                    "agent_runtime_signal",
                    "signal-1",
                    {
                        "signal_id": "signal-1",
                        "session_id": "session-1",
                        "agent_id": "agent-1",
                        "reason": "message_received",
                        "status": "claimed",
                        "created_at": "2026-08-24T00:00:00Z",
                        "claim_token": "signal-claim-private-1",
                        "session_lease_token": "session-lease-private-1",
                        "claimed_by": "runtime-worker-1",
                    },
                ),
            )
        ),
        "session_leases": _session_runtime_lease_public(
            (
                _record(
                    "session_runtime_lease",
                    "session-1",
                    {
                        "session_id": "session-1",
                        "owner_id": "runtime-worker-1",
                        "lease_token": "session-lease-private-1",
                        "mode": "draining",
                        "acquired_at": "2026-08-24T00:00:00Z",
                        "heartbeat_at": "2026-08-24T00:00:00Z",
                        "expires_at": "2026-08-24T00:02:00Z",
                        "fencing_token": 3,
                        "released_at": None,
                    },
                ),
            )
        ),
        "commands": _runtime_commands_public(
            (
                _record(
                    "runtime_command",
                    drain.command_id,
                    drain.to_dict(),
                    state_version=drain.state_version,
                ),
            )
        ),
        "turn_commands": _runtime_turn_commands_public(
            (
                _record(
                    "runtime_turn_command",
                    command.command_id,
                    command.to_dict(),
                ),
            )
        ),
    }

    serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
    assert "signal_claim_token" not in serialized
    assert "runtime_lease_token" not in serialized
    assert "lease_token" not in serialized
    assert "signal-claim-private-1" not in serialized
    assert "runtime-lease-private-1" not in serialized
    assert "session-lease-private-1" not in serialized
    assert "runtime-command-lease-private-1" not in serialized
    assert public["turn_commands"][0]["context_digest"] == (
        command.context.context_digest
    )
    assert public["turn_commands"][0]["message_count"] == 1


def test_public_runtime_command_summary_is_closed_and_aggregate_only() -> None:
    drain = RuntimeCommandRecord(
        command_id="runtime-drain-settled-1",
        session_id="session-1",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest=_digest("runtime-drain-settled"),
        idempotency_key="runtime-drain-settled-1",
        status=RuntimeCommandStatus.COMPLETED,
        max_signals=2,
        max_steps_per_agent=4,
        auto_enqueue_ready_tasks=False,
        state_version=3,
        fencing_token=3,
        accepted_at="2026-08-24T00:00:00Z",
        claim_owner="runtime-worker-1",
        lease_token="runtime-command-lease-private-1",
        lease_expires_at="2026-08-24T00:02:00Z",
        bounded_outcome_summary={
            "processed_signals": 1,
            "turns": [
                {
                    "context": "PRIVATE CONTEXT",
                    "messages": ["PRIVATE MESSAGE"],
                    "tool_requests": [
                        {
                            "tool_name": "hidden.admin",
                            "arguments": {"private": "argument"},
                        }
                    ],
                }
            ],
            "runtime_executed": True,
            "task_transition_performed": False,
            "fallback_performed": False,
        },
        started_at="2026-08-24T00:00:01Z",
        completed_at="2026-08-24T00:01:00Z",
    )

    public = _runtime_commands_public(
        (
            _record(
                "runtime_command",
                drain.command_id,
                drain.to_dict(),
                state_version=drain.state_version,
            ),
        )
    )[0]
    summary = public["bounded_outcome_summary"]
    assert isinstance(summary, dict)
    assert set(summary) == {
        "schema_version",
        "processed_signals",
        "turn_count",
        "turns_digest",
        "runtime_executed",
        "task_transition_performed",
        "fallback_performed",
    }
    assert summary["schema_version"] == "runtime_command_outcome_summary_public@1"
    assert summary["processed_signals"] == 1
    assert summary["turn_count"] == 1
    serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
    assert "PRIVATE CONTEXT" not in serialized
    assert "PRIVATE MESSAGE" not in serialized
    assert "hidden.admin" not in serialized
    assert "argument" not in serialized
    assert "runtime-command-lease-private-1" not in serialized


def test_failed_runtime_command_public_projection_resolves_only_safe_pair_ids() -> None:
    claimed = RuntimeCommandRecord(
        command_id="runtime-drain-failed-1",
        session_id="session-1",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest=_digest("runtime-drain-failed"),
        idempotency_key="runtime-drain-failed-1",
        status=RuntimeCommandStatus.CLAIMED,
        max_signals=1,
        max_steps_per_agent=2,
        auto_enqueue_ready_tasks=False,
        state_version=2,
        fencing_token=1,
        accepted_at="2026-08-24T00:00:00Z",
        claim_owner="runtime-worker-1",
        lease_token="runtime-command-lease-private-1",
        lease_expires_at="2026-08-24T00:02:00Z",
        started_at="2026-08-24T00:00:01Z",
    )
    failure = FailureObservation(
        failure_id="failure-runtime-command-1",
        session_id=claimed.session_id,
        source_kind="runtime_command",
        source_ref=claimed.command_id,
        source_version=canonical_sha256_digest(claimed.to_dict()),
        phase="runtime_context_projection",
        failure_class=FailureClass.HARNESS,
        recoverability=FailureRecoverability.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="runtime_context_projection_failed",
        safe_summary="Runtime context projection failed before provider invocation.",
        facts={
            "mutation_applied": False,
            "fallback_performed": False,
            "retry_performed": False,
            "retry_eligibility": "terminal",
            "reconcile_required": False,
        },
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-08-24T00:00:02Z",
        safe_hint="Inspect the exact diagnostic; no provider or fallback ran.",
        private_diagnostic_digest=_digest("private-runtime-command-diagnostic"),
        component="openzyme.standard.runtime_worker",
        operation="runtime_command_execute",
        identities={
            "command_id": claimed.command_id,
            "session_id": claimed.session_id,
        },
        mutation_applied=False,
        fallback_performed=False,
        cause_chain=(),
        diagnostic_id="diagnostic-runtime-command-1",
        next_action="inspect_runtime_command_diagnostic",
    )
    failed = replace(
        claimed,
        status=RuntimeCommandStatus.FAILED,
        state_version=3,
        bounded_outcome_summary={
            "processed_signals": 0,
            "turns": [],
            "runtime_executed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        },
        failure_id=failure.failure_id,
        diagnostic_id=failure.diagnostic_id,
        error_code=failure.error_code,
        safe_error_summary=failure.safe_summary,
        safe_retry_hint=failure.safe_hint,
        completed_at="2026-08-24T00:00:02Z",
    )
    command_record = _record(
        "runtime_command",
        failed.command_id,
        failed.to_dict(),
        state_version=failed.state_version,
    )
    failure_record = _record(
        "failure_observation",
        failure.failure_id,
        failure.to_internal_dict(),
    )

    public = _runtime_commands_public(
        (command_record,),
        failures=(failure_record,),
    )[0]

    assert public["failure_id"] == failure.failure_id
    assert public["diagnostic_id"] == failure.diagnostic_id
    serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
    assert "runtime-command-lease-private-1" not in serialized
    assert failure.private_diagnostic_digest not in serialized
    assert "traceback" not in serialized
    assert "private_context" not in serialized
    with pytest.raises(
        KernelContractError,
        match="does not resolve its exact public failure",
    ):
        _runtime_commands_public((command_record,), failures=())


def test_public_failure_projection_rejects_legacy_and_allowlists_current_facts() -> (
    None
):
    legacy = _record(
        "failure_observation",
        "failure-legacy-1",
        {
            "schema_version": "failure_observation@1",
            "failure_id": "failure-legacy-1",
            "session_id": "session-1",
            "traceback": "PRIVATE TRACEBACK",
            "bounded_stderr": "PRIVATE STDERR",
            "private_context": {
                "tool_requests": [
                    {
                        "tool_name": "hidden.admin",
                        "arguments": {"private": "argument"},
                    }
                ]
            },
        },
    )
    with pytest.raises(KernelContractError) as rejected:
        _public_failure_payloads((legacy,))
    assert rejected.value.code == "resident_teammate_state_incompatible"

    current = FailureObservation(
        failure_id="failure-current-1",
        session_id="session-1",
        source_kind="runtime",
        source_ref="runtime-command-1",
        source_version=_digest("runtime-command-1"),
        phase="runtime_settlement",
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="runtime_settlement_failed",
        safe_summary="The runtime settlement failed before effect.",
        facts={
            "fallback_performed": False,
            "provider_id": "provider-1",
            "tool_requests": [
                {
                    "tool_name": "hidden.admin",
                    "arguments": {"private": "argument"},
                }
            ],
        },
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-08-24T00:01:00Z",
        component="openzyme.runtime",
        operation="settle_runtime",
        identities={
            "command_id": "runtime-command-1",
            "tool_name": "hidden.admin",
        },
        mutation_applied=False,
        fallback_performed=False,
        diagnostic_id="diagnostic-current-1",
        next_action="inspect_diagnostic",
    )
    public = _public_failure_payloads(
        (
            _record(
                "failure_observation",
                current.failure_id,
                current.to_dict(),
            ),
        )
    )[0]
    serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
    assert public["facts"] == {
        "fallback_performed": False,
        "provider_id": "provider-1",
    }
    assert public["identities"] == {"command_id": "runtime-command-1"}
    assert "hidden.admin" not in serialized
    assert "argument" not in serialized


def test_hidden_tool_guess_never_enters_public_outcome_or_tool_transcript() -> None:
    hidden_guess = "enzymedesign.private.admin_tool"
    base = _outcome_receipt().outcome
    invocation = ToolInvocation(
        call_id="hidden-call-1",
        tool_name=hidden_guess,
        arguments={"private_argument": "must-not-be-public"},
        session_id="session-1",
        agent_member_id="member-1",
        affordance_snapshot_digest=_digest("tool-exposure"),
    )
    request = RuntimeToolRequest(
        request_id="hidden-request-1",
        invocation=invocation,
        affordance_snapshot_digest=_digest("tool-exposure"),
    )
    tool_content = json.dumps(
        {
            "schema_version": "tool_result@1",
            "call_id": invocation.call_id,
            "tool_name": hidden_guess,
            "ok": False,
            "status": "rejected",
            "summary": "The requested tool is not exposed in this runtime command.",
            "payload": {
                "effect_certainty": "no_effect",
                "mutation_applied": False,
                "fallback_performed": False,
                "retry_performed": False,
                "reconcile_required": False,
            },
            "error_code": "tool_not_exposed",
            "hint": None,
            "terminates_turn": False,
        }
    )
    tool_message = RuntimeMessage(
        message_id="hidden-tool-result-1",
        role=RuntimeMessageRole.TOOL,
        content=tool_content,
        correlation_id="correlation-1",
        tool_call_id=invocation.call_id,
    )
    outcome = replace(base, messages=(tool_message,), tool_requests=(request,))
    receipt = RuntimeTurnOutcomeReceipt(
        receipt_id="hidden-outcome-receipt-1",
        outcome=outcome,
        accepted_at="2026-08-24T00:01:00Z",
    )
    outcome_record = _record(
        "runtime_turn_outcome",
        receipt.receipt_id,
        receipt.to_dict(),
    )
    message_record = _record(
        "conversation_message",
        tool_message.message_id,
        {
            "message_id": tool_message.message_id,
            "sender_kind": "tool",
            "content": tool_message.content,
            "correlation_id": tool_message.correlation_id,
            "created_at": receipt.accepted_at,
        },
    )
    public = {
        "outcomes": _runtime_outcomes_public((outcome_record,)),
        "messages": _public_conversation_payloads((message_record,)),
        "transcript": _ordered_transcript_projection(
            messages=(message_record,),
            outcomes=(outcome_record,),
        ),
    }

    serialized = json.dumps(public, ensure_ascii=False, sort_keys=True)
    assert hidden_guess not in serialized
    assert "must-not-be-public" not in serialized
    public_outcome = public["outcomes"][0]["outcome"]
    assert public_outcome["tool_request_count"] == 1
    assert "tool_requests" not in public_outcome
    assert "messages" not in public_outcome
