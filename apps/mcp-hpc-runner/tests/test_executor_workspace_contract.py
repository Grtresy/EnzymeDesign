from __future__ import annotations

from dataclasses import replace

import pytest

from mcp_hpc_runner.config import ExecutorWorkspaceTargetConfig
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceCleanupRequest
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisionRequest
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisioningService
from mcp_hpc_runner.models import ExecutorWorkspaceRunSpec


DIGEST = "sha256:" + "a" * 64
COMMIT = "1" * 40


def _provision_request() -> ExecutorWorkspaceProvisionRequest:
    return ExecutorWorkspaceProvisionRequest(
        intent_id="intent_1",
        intent_digest=DIGEST,
        workspace_id="workspace_1",
        target_profile_digest=DIGEST,
        repository_endpoint="https://git.internal/repository.git",
        repository_remote_digest=DIGEST,
        base_commit=COMMIT,
        owner_identity_digest=DIGEST,
        idempotency_key="provision_1",
        absolute_deadline="2026-08-17T01:05:00+00:00",
    )


def test_activated_target_requires_native_isolation_and_proof_contract() -> None:
    with pytest.raises(ValueError, match="native positive and negative proofs"):
        ExecutorWorkspaceTargetConfig(activated=True)

    target = ExecutorWorkspaceTargetConfig(
        activated=True,
        target_profile_id="target_1",
        workspace_root="/srv/openzyme/workspaces",
        sidecar_root="/srv/openzyme-sidecars",
        os_principal_policy_id="principal-policy-v1",
        root_policy_digest=DIGEST,
        isolation_command="/usr/local/libexec/openzyme-workspace-isolation",
        credential_provider_id="credential-provider-v1",
        authenticator_id="target-authenticator-v1",
        login_alias="openzyme-target",
        toolchain_digest=DIGEST,
        native_positive_proof_digest=DIGEST,
        native_negative_proof_digest=DIGEST,
    )

    assert target.to_authority_dict()["scheduler_submit_enabled"] is False
    assert target.isolation_command == (
        "/usr/local/libexec/openzyme-workspace-isolation"
    )


def test_provision_and_cleanup_requests_are_closed_and_settlement_bound() -> None:
    provision = _provision_request()
    assert ExecutorWorkspaceProvisionRequest.from_dict(
        provision.to_dict()
    ) == provision
    with pytest.raises(ValueError, match="fields are closed"):
        ExecutorWorkspaceProvisionRequest.from_dict(
            {**provision.to_dict(), "host_path": "/tmp/repository"}
        )

    cleanup = ExecutorWorkspaceCleanupRequest(
        provision_request=provision,
        cleanup_intent_id="cleanup_1",
        cleanup_intent_digest=DIGEST,
        workspace_state_version=3,
        settlement_proof_digest=DIGEST,
        idempotency_key="cleanup_key_1",
        unsettled_effect_count=0,
    )
    assert ExecutorWorkspaceCleanupRequest.from_dict(cleanup.to_dict()) == cleanup
    with pytest.raises(ValueError, match="zero unsettled"):
        replace(cleanup, unsettled_effect_count=1)


@pytest.mark.parametrize(
    "stale_field",
    ["inputs", "expected_outputs", "artifact_id", "stage_to", "local_path"],
)
def test_workspace_runspec_rejects_every_artifact_staging_field(
    stale_field: str,
) -> None:
    runspec = {
        "schema_version": "executor_workspace_runspec@1",
        "executor_hpc_workspace_id": "workspace_1",
        "executor_hpc_workspace_generation": 1,
        "repository_binding_id": "binding_1",
        "repository_binding_version": 1,
        "target_profile_digest": DIGEST,
        "cwd": ".",
        "command": ["true"],
        "execution_mode": "ssh",
        "resources": {},
        stale_field: [],
    }

    with pytest.raises(ValueError, match="forbids artifact staging"):
        ExecutorWorkspaceRunSpec.from_dict(runspec)


def test_remote_scripts_delegate_isolation_and_never_directly_delete_root() -> None:
    provision_script = ExecutorWorkspaceProvisioningService._provision_script()
    cleanup_script = ExecutorWorkspaceProvisioningService._cleanup_script()

    assert '"${isolation_command}" "${isolation_operation}"' in provision_script
    assert "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST" in provision_script
    assert '"${isolation_command}" cleanup' in cleanup_script
    assert "rm -rf" not in cleanup_script
    assert "OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST" in cleanup_script
