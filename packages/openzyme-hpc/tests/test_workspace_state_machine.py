from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_hpc import ExecutorHpcCredentialOperation
from openzyme_hpc import ExecutorHpcCleanupDisposition
from openzyme_hpc import ExecutorHpcProvisionContext
from openzyme_hpc import ExecutorHpcRevisionSource
from openzyme_hpc import ExecutorHpcRevisionSourceKind
from openzyme_hpc import ExecutorHpcTargetQualification
from openzyme_hpc import ExecutorHpcWorkspaceIdentityConflict
from openzyme_hpc import ExecutorHpcWorkspaceLifecycle
from openzyme_hpc import ExecutorHpcWorkspaceObservation
from openzyme_hpc import ExecutorHpcWorkspaceObservationKind
from openzyme_hpc import ExecutorHpcWorkspaceState
from openzyme_hpc import ExecutorHpcWorkspaceCleanupReceipt


DIGEST = "sha256:" + "a" * 64
NOW = "2026-08-20T00:00:00+00:00"


def _target() -> ExecutorHpcTargetQualification:
    return ExecutorHpcTargetQualification(
        target_profile_id="hpc-primary",
        target_profile_digest=DIGEST,
        root_policy_digest=DIGEST,
        os_principal_policy_id="principal-policy",
        credential_provider_id="credential-provider",
        authenticator_id="authenticator",
        login_alias="login-alias",
        workspace_root="/srv/openzyme/workspaces",
        sidecar_root_digest=DIGEST,
        inventory_generation=7,
        inventory_digest=DIGEST,
        native_positive_proof_digest=DIGEST,
        native_negative_proof_digest=DIGEST,
        activated=True,
        qualified_at=NOW,
    )


def _context() -> ExecutorHpcProvisionContext:
    return ExecutorHpcProvisionContext(
        project_id="project_1",
        session_id="session_1",
        executor_agent_id="agent_1",
        executor_agent_member_id="member_1",
        local_workspace_id="local_1",
        local_workspace_generation=3,
        repository_binding_id="binding_1",
        repository_binding_version=2,
        repository_id="repository_1",
        base_commit="a" * 40,
        capability_lease_id="lease_1",
        capability_lease_version=4,
        target=_target(),
    )


def _provisioning_records():
    return ExecutorHpcWorkspaceLifecycle().create_provision_records(
        context=_context(),
        remote_workspace_generation=5,
        idempotency_key="provision_1",
        absolute_deadline="2026-08-20T00:05:00+00:00",
        workspace_id="hpcws_1",
        intent_id="intent_1",
        created_at=NOW,
    )


def _ready_workspace():
    intent, workspace = _provisioning_records()
    return intent, replace(
        workspace,
        runner_handle="runner_1",
        provision_receipt_id="receipt_1",
        login_alias="login-alias",
        remote_workspace_path="/srv/openzyme/workspaces/runner_1",
        remote_root_digest=DIGEST,
        os_principal_identity_digest=DIGEST,
        isolation_receipt_digest=DIGEST,
        state=ExecutorHpcWorkspaceState.READY,
        state_version=2,
    )


def test_provision_records_bind_local_remote_generation_and_hide_locator() -> None:
    intent, workspace = _provisioning_records()

    assert intent.local_workspace_generation == 3
    assert intent.remote_workspace_generation == 5
    assert workspace.state is ExecutorHpcWorkspaceState.PROVISIONING
    projection = ExecutorHpcWorkspaceLifecycle.owner_projection(
        workspace,
        owner_authorized=True,
    )
    assert "login_alias" not in projection
    assert "remote_workspace_path" not in projection
    assert projection["native_admission_available"] is False


def test_equal_or_older_replacement_generation_is_rejected() -> None:
    _, prior = _provisioning_records()

    with pytest.raises(
        ExecutorHpcWorkspaceIdentityConflict,
        match="strictly higher",
    ):
        ExecutorHpcWorkspaceLifecycle().create_provision_records(
            context=_context(),
            remote_workspace_generation=5,
            idempotency_key="provision_2",
            absolute_deadline="2026-08-20T00:05:00+00:00",
            workspace_id="hpcws_2",
            intent_id="intent_2",
            created_at=NOW,
            prior_workspaces=(prior,),
        )


def test_native_credential_claim_is_short_lived_and_never_scheduler_scoped() -> None:
    _, ready = _ready_workspace()
    claim = ExecutorHpcWorkspaceLifecycle.create_native_credential_claim(
        workspace=ready,
        target=_target(),
        claim_id="claim_1",
        issued_at=NOW,
        expires_at="2026-08-20T00:05:00+00:00",
        operations=(ExecutorHpcCredentialOperation.SSH_LOGIN,),
    )

    assert claim.operations == (ExecutorHpcCredentialOperation.SSH_LOGIN,)
    assert all("scheduler" not in item.value for item in claim.operations)


def test_missing_remote_observation_invalidates_exact_ready_generation() -> None:
    intent, ready = _ready_workspace()
    observation = ExecutorHpcWorkspaceObservation.create(
        workspace_id=ready.workspace_id,
        intent_digest=intent.intent_digest,
        runner_handle="runner_1",
        remote_root_digest=DIGEST,
        kind=ExecutorHpcWorkspaceObservationKind.MISSING,
        repository_remote_digest=None,
        head_commit=None,
        independent_git_directory=False,
        protected_root_mode=None,
        os_principal_identity_digest=DIGEST,
        isolation_receipt_digest=DIGEST,
        observed_at="2026-08-20T00:01:00+00:00",
    )

    missing = ExecutorHpcWorkspaceLifecycle().apply_remote_observation(
        workspace=ready,
        intent=intent,
        repository_binding_digest=DIGEST,
        observation=observation,
    )

    assert missing.state is ExecutorHpcWorkspaceState.MISSING
    assert missing.state_version == ready.state_version + 1
    assert missing.invalid_reason == "canonical_remote_root_missing"


def test_private_revision_sync_is_generation_bound_and_performs_no_mutation() -> None:
    _, ready = _ready_workspace()
    source = ExecutorHpcRevisionSource(
        source_kind=ExecutorHpcRevisionSourceKind.PRIVATE_CHECKPOINT,
        source_id="checkpoint_1",
        ref="refs/openzyme/private/member_1",
        commit="b" * 40,
        tree="c" * 40,
        source_digest=DIGEST,
        workspace_id=ready.local_workspace_id,
        project_id=ready.project_id,
        session_id=ready.session_id,
        agent_member_id=ready.executor_agent_member_id,
        workspace_generation=ready.local_workspace_generation,
        repository_binding_id=ready.repository_binding_id,
        repository_binding_version=ready.repository_binding_version,
        repository_id=ready.repository_id,
    )

    identity = ExecutorHpcWorkspaceLifecycle.revision_sync_identity(
        workspace=ready,
        source=source,
    )

    assert identity["source_kind"] == "private_checkpoint"
    assert identity["working_tree_mutation_performed"] is False
    assert identity["fallback_permitted"] is False
    assert identity["lfs_closure"] is None

    with pytest.raises(ExecutorHpcWorkspaceIdentityConflict, match="generation"):
        ExecutorHpcWorkspaceLifecycle.revision_sync_identity(
            workspace=ready,
            source=replace(
                source,
                workspace_generation=ready.local_workspace_generation + 1,
            ),
        )


def test_retention_and_cleanup_require_monotonic_exact_identity() -> None:
    lifecycle = ExecutorHpcWorkspaceLifecycle()
    _, ready = _ready_workspace()
    retained = lifecycle.mark_retention_eligible(
        ready,
        updated_at="2026-08-20T00:01:00+00:00",
        reason="owner_retired",
    )
    cleaning = lifecycle.transition(
        retained,
        ExecutorHpcWorkspaceState.CLEANING,
        updated_at="2026-08-20T00:02:00+00:00",
    )
    intent = lifecycle.create_cleanup_intent(
        workspace=cleaning,
        cleanup_intent_id="cleanup_intent_1",
        settlement_proof_digest=DIGEST,
        idempotency_key="cleanup_1",
        created_at="2026-08-20T00:03:00+00:00",
    )
    receipt = ExecutorHpcWorkspaceCleanupReceipt.create(
        cleanup_receipt_id="cleanup_receipt_1",
        cleanup_intent_id=intent.cleanup_intent_id,
        cleanup_intent_digest=intent.intent_digest,
        workspace_id=cleaning.workspace_id,
        runner_handle=str(cleaning.runner_handle),
        remote_root_digest=str(cleaning.remote_root_digest),
        disposition=ExecutorHpcCleanupDisposition.DELETED,
        unsettled_effect_count=0,
        settlement_proof_digest=DIGEST,
        isolation_cleanup_receipt_digest=DIGEST,
        created_at="2026-08-20T00:04:00+00:00",
    )

    cleaned = lifecycle.accept_cleanup_receipt(
        workspace=cleaning,
        intent=intent,
        receipt=receipt,
    )

    assert retained.state is ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE
    assert retained.state_version == ready.state_version + 1
    assert cleaned.state is ExecutorHpcWorkspaceState.CLEANED
    assert cleaned.state_version == cleaning.state_version + 1

    wrong_workspace_receipt = ExecutorHpcWorkspaceCleanupReceipt.create(
        **{
            key: value
            for key, value in receipt.payload.items()
            if key not in {"schema_version", "disposition"}
        }
        | {
            "workspace_id": "hpcws_other",
            "disposition": ExecutorHpcCleanupDisposition.DELETED,
        }
    )
    with pytest.raises(ExecutorHpcWorkspaceIdentityConflict, match="differs"):
        lifecycle.accept_cleanup_receipt(
            workspace=cleaning,
            intent=intent,
            receipt=wrong_workspace_receipt,
        )
