from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import CommandToolExpansion
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import RetryEligibility
from openzyme_contracts import RuntimeContextSection
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import WorkflowAuthoritySubsetRequest
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningReceiptDisposition
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_workflow_authority_subset
from openzyme_contracts import validate_command_tool_expansion


NOW = "2026-08-24T00:00:00+00:00"


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _intent() -> WorkspaceProvisioningIntent:
    return WorkspaceProvisioningIntent(
        intent_id="intent-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace_id="workspace-1",
        generation=1,
        repository_pin_digest=_digest("repository-pin"),
        provider_id="workspace-provider-1",
        target_id="local-host",
        adapter_binding_digest=_digest("adapter-binding"),
        controlled_operation_id="operation-1",
        status=WorkspaceProvisioningStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at=NOW,
        updated_at=NOW,
    )


def _authority() -> WorkflowAuthorityBinding:
    registry_digest = _digest("registry")
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="member-1",
        selected_workflow_refs=("workflow.alpha@1", "workflow.beta@1"),
        selection_digest=canonical_sha256_digest(
            {
                "schema_version": "workflow_selection_binding@1",
                "registry_snapshot_digest": registry_digest,
                "selected_workflow_refs": [
                    "workflow.alpha@1",
                    "workflow.beta@1",
                ],
            }
        ),
        registry_snapshot_digest=registry_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_workspace_provisioning_round_trip_digest_and_lifecycle_are_closed() -> None:
    intent = _intent()
    assert WorkspaceProvisioningIntent.from_dict(intent.to_dict()) == intent
    with pytest.raises(ValueError, match="closed schema"):
        WorkspaceProvisioningIntent.from_dict(
            {**intent.to_dict(), "fallback_provider_id": "other"}
        )
    with pytest.raises(ValueError, match="complete settlement"):
        replace(intent, status=WorkspaceProvisioningStatus.READY, claim_epoch=1,
                claim_owner_id="worker-1", claim_token="claim-1",
                claim_expires_at=NOW)

    receipt = WorkspaceProvisioningReceipt(
        receipt_id="receipt-1",
        request_id="request-1",
        request_digest=_digest("request"),
        intent_id=intent.intent_id,
        intent_digest=intent.intent_digest,
        claim_token="claim-1",
        claim_epoch=1,
        controlled_operation_id=intent.controlled_operation_id,
        disposition=WorkspaceProvisioningReceiptDisposition.READY,
        session_id=intent.session_id,
        agent_member_id=intent.agent_member_id,
        workspace_id=intent.workspace_id,
        generation=intent.generation,
        repository_pin_digest=intent.repository_pin_digest,
        provider_id=intent.provider_id,
        target_id=intent.target_id,
        adapter_binding_digest=intent.adapter_binding_digest,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        fallback_performed=False,
        retry_eligibility=RetryEligibility.TERMINAL,
        reconcile_required=False,
        observed_root_identity_digest=_digest("root"),
        terminal_receipt_digest=_digest("terminal"),
        completed_at=NOW,
    )
    assert WorkspaceProvisioningReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(ValueError, match="digest mismatch"):
        WorkspaceProvisioningReceipt.from_dict(
            {**receipt.to_dict(), "receipt_digest": _digest("drift")}
        )


def test_workspace_provisioning_reconciliation_is_exact_closed_and_claim_fenced() -> None:
    pending_intent = _intent()
    claimed_intent = replace(
        pending_intent,
        status=WorkspaceProvisioningStatus.CLAIMED,
        state_version=2,
        claim_epoch=1,
        claim_owner_id="provisioning-worker-1",
        claim_token="claim-1",
        claim_expires_at="2026-08-24T00:01:00+00:00",
    )
    provision_request = WorkspaceProvisioningRequest(
        request_id="provision-request-1",
        intent_id=claimed_intent.intent_id,
        intent_digest=claimed_intent.intent_digest,
        claim_token=claimed_intent.claim_token or "",
        claim_epoch=claimed_intent.claim_epoch,
        session_id=claimed_intent.session_id,
        agent_member_id=claimed_intent.agent_member_id,
        workspace_id=claimed_intent.workspace_id,
        generation=claimed_intent.generation,
        repository_pin_digest=claimed_intent.repository_pin_digest,
        provider_id=claimed_intent.provider_id,
        target_id=claimed_intent.target_id,
        adapter_binding_digest=claimed_intent.adapter_binding_digest,
        controlled_operation_id=claimed_intent.controlled_operation_id,
    )
    assert (
        WorkspaceProvisioningRequest.from_dict(provision_request.to_dict())
        == provision_request
    )
    pending = WorkspaceProvisioningReconciliation(
        reconciliation_id="reconciliation-1",
        session_id=claimed_intent.session_id,
        intent_id=claimed_intent.intent_id,
        blocked_intent_state_version=3,
        blocked_intent_digest=_digest("blocked-intent"),
        source_receipt_id="dispatch-receipt-1",
        source_receipt_digest=_digest("dispatch-receipt-row"),
        dispatch_receipt_digest=_digest("dispatch-terminal"),
        provision_request=provision_request,
        attempt=1,
        parent_reconciliation_id=None,
        reason_code="explicit_operator_reconciliation",
        requested_at=NOW,
        requested_claim_seconds=60,
        status=WorkspaceProvisioningReconciliationStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at=NOW,
        updated_at=NOW,
    )
    assert WorkspaceProvisioningReconciliation.from_dict(pending.to_dict()) == pending
    claimed = replace(
        pending,
        status=WorkspaceProvisioningReconciliationStatus.CLAIMED,
        state_version=2,
        claim_epoch=1,
        claim_owner_id="reconciliation-worker-1",
        claim_token="reconciliation-claim-1",
        claim_expires_at="2026-08-24T00:01:00+00:00",
    )
    ready = replace(
        claimed,
        status=WorkspaceProvisioningReconciliationStatus.READY,
        state_version=3,
        result_receipt_id="reconciliation-receipt-1",
        result_receipt_digest=_digest("reconciliation-receipt-row"),
        result_terminal_receipt_digest=_digest("reconciliation-terminal"),
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        retry_eligibility=RetryEligibility.TERMINAL,
        settled_at=NOW,
    )
    assert WorkspaceProvisioningReconciliation.from_dict(ready.to_dict()) == ready
    with pytest.raises(ValueError, match="closed schema"):
        WorkspaceProvisioningReconciliation.from_dict(
            {**pending.to_dict(), "fallback_provider_id": "provider-2"}
        )
    with pytest.raises(ValueError, match="digest mismatch"):
        WorkspaceProvisioningReconciliation.from_dict(
            {**ready.to_dict(), "reconciliation_digest": _digest("drift")}
        )
    with pytest.raises(ValueError, match="full claim"):
        replace(
            pending,
            status=WorkspaceProvisioningReconciliationStatus.CLAIMED,
            claim_epoch=1,
        )


def test_workflow_authority_round_trip_link_and_stale_epoch_fail_closed() -> None:
    authority = _authority()
    assert WorkflowAuthorityBinding.from_dict(authority.to_dict()) == authority
    link = RuntimeSignalAuthorityLink(
        signal_id="signal-1",
        session_id=authority.session_id,
        authority_id=authority.authority_id,
        authority_epoch=authority.epoch,
        authority_binding_digest=authority.binding_digest,
        causation_ref="message-1",
        source_kind=WorkflowAuthoritySignalSourceKind.ROOT_MESSAGE,
        created_at=NOW,
    )
    assert RuntimeSignalAuthorityLink.from_dict(link.to_dict()) == link
    stale = WorkflowAuthoritySubsetRequest(
        request_id="subset-1",
        parent_authority_id=authority.authority_id,
        parent_binding_digest=authority.binding_digest,
        parent_epoch=2,
        authorized_actor_id="member-2",
        selected_workflow_refs=("workflow.alpha@1",),
        task_id=None,
        lane_id=None,
        derivation_kind=WorkflowAuthorityDerivationKind.DELEGATION,
        causation_ref="delegation-1",
    )
    with pytest.raises(ValueError, match="stale parent epoch") as error:
        require_workflow_authority_subset(authority, stale)
    assert error.value.mutation_applied is False
    assert error.value.fallback_performed is False


def test_context_and_tool_exposure_round_trip_preserve_hidden_boundary() -> None:
    context = RuntimeTurnContext(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="lineage-1",
        sections=tuple(
            RuntimeContextSection(kind=kind, items=())
            for kind in RuntimeContextSectionKind
        ),
        max_bytes=32_768,
        created_at=NOW,
    )
    assert RuntimeTurnContext.from_dict(context.to_dict()) == context
    authority = _authority()
    snapshot = ToolExposureSnapshot(
        exposure_snapshot_id="exposure-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        subject_policy_digest=_digest("policy"),
        declared_tool_catalog_digest=_digest("catalog"),
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_id="affordance-1",
        affordance_snapshot_digest=_digest("affordance"),
        workflow_authority_id=authority.authority_id,
        workflow_authority_epoch=authority.epoch,
        workflow_authority_digest=authority.binding_digest,
        catalog_tool_names=("tool.deferred", "tool.direct", "tool.hidden"),
        decisions=(
            ToolExposureDecision("tool.deferred", ToolExposure.DEFERRED, "long_tail"),
            ToolExposureDecision("tool.direct", ToolExposure.DIRECT, "essential"),
            ToolExposureDecision("tool.hidden", ToolExposure.HIDDEN, "forbidden"),
        ),
        created_at=NOW,
    )
    assert ToolExposureSnapshot.from_dict(snapshot.to_dict()) == snapshot
    expansion = CommandToolExpansion(
        expansion_id="expansion-1",
        command_id="command-1",
        session_id="session-1",
        exposure_snapshot_id=snapshot.exposure_snapshot_id,
        exposure_snapshot_digest=snapshot.exposure_snapshot_digest,
        workflow_authority_id=authority.authority_id,
        workflow_authority_epoch=authority.epoch,
        workflow_authority_digest=authority.binding_digest,
        expansion_revision=1,
        expanded_tool_names=("tool.deferred",),
        created_at=NOW,
    )
    validate_command_tool_expansion(snapshot, expansion)
    with pytest.raises(ValueError, match="only exact Deferred"):
        validate_command_tool_expansion(
            snapshot,
            replace(expansion, expanded_tool_names=("tool.hidden",)),
        )
