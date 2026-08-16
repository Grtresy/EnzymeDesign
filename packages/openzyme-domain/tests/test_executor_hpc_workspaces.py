from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_domain import ExecutorHpcCleanupDisposition
from openzyme_domain import ExecutorHpcCredentialClaim
from openzyme_domain import ExecutorHpcCredentialOperation
from openzyme_domain import ExecutorHpcTargetQualification
from openzyme_domain import ExecutorHpcWorkspace
from openzyme_domain import ExecutorHpcWorkspaceCleanupReceipt
from openzyme_domain import ExecutorHpcWorkspaceProvisionIntent
from openzyme_domain import ExecutorHpcWorkspaceProvisionReceipt
from openzyme_domain import ExecutorHpcWorkspaceState


SHA = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
COMMIT = "1" * 40
NOW = "2026-08-17T01:00:00+00:00"


def _intent() -> ExecutorHpcWorkspaceProvisionIntent:
    return ExecutorHpcWorkspaceProvisionIntent.create(
        intent_id="hpcintent_1",
        workspace_id="hpcws_1",
        project_id="project_1",
        session_id="session_1",
        executor_agent_member_id="member_1",
        local_workspace_generation=1,
        remote_workspace_generation=1,
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        base_commit=COMMIT,
        target_profile_id="target_1",
        target_profile_digest=SHA,
        root_policy_digest=SHA_B,
        capability_lease_id="lease_1",
        capability_lease_version=1,
        idempotency_key="provision_1",
        absolute_deadline="2026-08-17T01:05:00+00:00",
        created_at=NOW,
    )


def _ready_workspace() -> ExecutorHpcWorkspace:
    return ExecutorHpcWorkspace(
        workspace_id="hpcws_1",
        project_id="project_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        session_id="session_1",
        executor_agent_member_id="member_1",
        executor_agent_id="agent_1",
        local_workspace_id="local_workspace_1",
        local_workspace_generation=1,
        capability_lease_id="lease_1",
        capability_lease_version=1,
        target_profile_id="target_1",
        target_profile_digest=SHA,
        remote_workspace_generation=1,
        provision_intent_id="hpcintent_1",
        runner_handle="hpcws_handle_1",
        provision_receipt_id="receipt_1",
        login_alias="target-login",
        remote_workspace_path="/srv/openzyme/hpcws_handle_1",
        remote_root_digest=SHA_B,
        os_principal_identity_digest=SHA,
        isolation_receipt_digest=SHA_B,
        state=ExecutorHpcWorkspaceState.READY,
        state_version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def test_workspace_shared_projection_hides_owner_and_remote_identity() -> None:
    workspace = _ready_workspace()

    shared = workspace.to_dict(include_owner_locator=False)
    owner = workspace.to_dict(include_owner_locator=True)

    assert set(shared) == {
        "schema_version",
        "workspace_id",
        "remote_workspace_generation",
        "state",
        "state_version",
        "created_at",
        "updated_at",
    }
    assert owner["remote_workspace_path"] == workspace.remote_workspace_path
    assert owner["runner_handle"] == workspace.runner_handle
    assert "capability_lease_id" not in shared


def test_provisioning_reconciliation_cannot_claim_remote_locators() -> None:
    with pytest.raises(ValueError, match="unsettled provisioning"):
        replace(
            _ready_workspace(),
            state=ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
            provision_receipt_id=None,
        )


def test_provision_and_cleanup_receipts_are_content_bound() -> None:
    intent = _intent()
    receipt = ExecutorHpcWorkspaceProvisionReceipt.create(
        receipt_id="receipt_1",
        intent_id=intent.intent_id,
        intent_digest=intent.intent_digest,
        workspace_id=intent.workspace_id,
        runner_handle="hpcws_handle_1",
        target_profile_digest=SHA,
        login_alias="target-login",
        remote_workspace_path="/srv/openzyme/hpcws_handle_1",
        remote_root_digest=SHA_B,
        repository_remote_digest=SHA,
        clone_head_commit=COMMIT,
        owner_identity_digest=SHA_B,
        os_principal_identity_digest=SHA,
        isolation_receipt_digest=SHA_B,
        created_at=NOW,
    )
    cleanup = ExecutorHpcWorkspaceCleanupReceipt.create(
        cleanup_receipt_id="cleanup_receipt_1",
        cleanup_intent_id="cleanup_intent_1",
        cleanup_intent_digest=SHA,
        workspace_id=intent.workspace_id,
        runner_handle=receipt.runner_handle,
        remote_root_digest=receipt.remote_root_digest,
        disposition=ExecutorHpcCleanupDisposition.DELETED,
        unsettled_effect_count=0,
        settlement_proof_digest=SHA_B,
        isolation_cleanup_receipt_digest=SHA,
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="digest mismatch"):
        replace(receipt, remote_workspace_path="/srv/openzyme/other")
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(cleanup, disposition=ExecutorHpcCleanupDisposition.RETAINED)


def test_credential_claim_binds_exact_root_principal_and_closed_operations() -> None:
    claim = ExecutorHpcCredentialClaim(
        claim_id="claim_1",
        workspace_id="hpcws_1",
        session_id="session_1",
        executor_agent_member_id="member_1",
        local_workspace_generation=1,
        remote_workspace_generation=1,
        target_profile_id="target_1",
        target_profile_digest=SHA,
        capability_lease_id="lease_1",
        capability_lease_version=1,
        credential_provider_id="provider_1",
        authenticator_id="authenticator_1",
        login_alias="target-login",
        remote_workspace_path="/srv/openzyme/hpcws_handle_1",
        remote_root_digest=SHA_B,
        os_principal_identity_digest=SHA,
        operations=(ExecutorHpcCredentialOperation.GIT,),
        issued_at=NOW,
        expires_at="2026-08-17T01:05:00+00:00",
    )

    assert claim.to_dict()["operations"] == ["git"]
    with pytest.raises(ValueError, match="follow issued_at"):
        replace(claim, expires_at="2026-08-17T00:59:00+00:00")


def test_target_qualification_requires_native_activation_identity() -> None:
    qualification = ExecutorHpcTargetQualification(
        target_profile_id="target_1",
        target_profile_digest=SHA,
        root_policy_digest=SHA_B,
        os_principal_policy_id="principal-policy-v1",
        credential_provider_id="provider_1",
        authenticator_id="authenticator_1",
        login_alias="target-login",
        workspace_root="/srv/openzyme",
        sidecar_root_digest=SHA,
        toolchain_digest=SHA_B,
        native_positive_proof_digest=SHA,
        native_negative_proof_digest=SHA_B,
        activated=True,
        qualified_at=NOW,
    )

    assert qualification.to_dict()["os_principal_policy_id"] == (
        "principal-policy-v1"
    )
    with pytest.raises(ValueError, match="native-proof-qualified"):
        replace(qualification, activated=False)
