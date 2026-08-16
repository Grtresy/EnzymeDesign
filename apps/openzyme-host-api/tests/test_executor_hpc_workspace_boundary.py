from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

from openzyme_host_api.executor_hpc_workspaces import (
    CommandExecutorHpcCredentialProvider,
)
from openzyme_host_api.executor_hpc_workspaces import (
    CommandExecutorHpcQualificationEvidenceVerifier,
)
from openzyme_host_api.executor_hpc_workspaces import (
    ExecutorHpcCredentialCommandResult,
)
from openzyme_core import ExecutorHpcNativeQualificationEvidence
from openzyme_domain import ExecutorHpcCredentialClaim
from openzyme_domain import ExecutorHpcCredentialOperation
from openzyme_domain import canonical_executor_hpc_digest


DIGEST = "sha256:" + "a" * 64
NOW = "2026-08-17T01:00:00+00:00"


@dataclass(slots=True)
class _CommandExecutor:
    result: dict[str, object]
    request: dict[str, object] | None = None

    def run(
        self,
        argv: tuple[str, ...],
        *,
        stdin: str,
        timeout_seconds: int,
    ) -> ExecutorHpcCredentialCommandResult:
        assert argv[0].startswith("/")
        assert timeout_seconds > 0
        self.request = json.loads(stdin)
        return ExecutorHpcCredentialCommandResult(
            returncode=0,
            stdout=json.dumps(self.result),
            stderr="",
        )


def _claim() -> ExecutorHpcCredentialClaim:
    return ExecutorHpcCredentialClaim(
        claim_id="claim_1",
        workspace_id="workspace_1",
        session_id="session_1",
        executor_agent_member_id="member_1",
        local_workspace_generation=1,
        remote_workspace_generation=1,
        target_profile_id="target_1",
        target_profile_digest=DIGEST,
        capability_lease_id="lease_1",
        capability_lease_version=1,
        credential_provider_id="provider_1",
        authenticator_id="authenticator_1",
        login_alias="target-login",
        remote_workspace_path="/srv/openzyme/workspace_1",
        remote_root_digest=DIGEST,
        os_principal_identity_digest=DIGEST,
        operations=(ExecutorHpcCredentialOperation.GIT,),
        issued_at=NOW,
        expires_at="2026-08-17T01:05:00+00:00",
    )


def test_command_credential_provider_authenticates_exact_non_scheduler_claim() -> None:
    claim = _claim()
    claim_digest = canonical_executor_hpc_digest(claim.to_dict())
    command = _CommandExecutor(
        {
            "schema_version": "executor_hpc_credential_provider_result@1",
            "provider_id": claim.credential_provider_id,
            "authenticator_id": claim.authenticator_id,
            "claim_digest": claim_digest,
            "credential_fingerprint": DIGEST,
            "authentication_receipt_digest": DIGEST,
            "authenticated": True,
            "environment": {
                "OPENZYME_HPC_AUTHENTICATOR_ID": claim.authenticator_id,
                "OPENZYME_HPC_CREDENTIAL_ID": claim.claim_id,
                "OPENZYME_HPC_LOGIN_ALIAS": claim.login_alias,
                "OPENZYME_HPC_OS_PRINCIPAL_IDENTITY_DIGEST": (
                    claim.os_principal_identity_digest
                ),
                "OPENZYME_HPC_REMOTE_ROOT": claim.remote_workspace_path,
                "OPENZYME_HPC_TARGET_PROFILE_ID": claim.target_profile_id,
                "OPENZYME_HPC_SSH_PRIVATE_KEY_B64": "private-key",
            },
            "exact_secret_material": ["private-key"],
        }
    )
    provider = CommandExecutorHpcCredentialProvider(
        provider_id=claim.credential_provider_id,
        authenticator_id=claim.authenticator_id,
        issue_command=("/usr/local/bin/issue-hpc-credential",),
        revoke_command=("/usr/local/bin/revoke-hpc-credential",),
        executor=command,
    )

    issued = provider.issue(claim)

    assert issued.claim == claim
    assert command.request is not None
    assert command.request["scheduler_submit_authorized"] is False
    assert command.request["claim"] == claim.to_dict()


def test_command_credential_provider_rejects_scheduler_material() -> None:
    claim = _claim()
    claim_digest = canonical_executor_hpc_digest(claim.to_dict())
    command = _CommandExecutor(
        {
            "schema_version": "executor_hpc_credential_provider_result@1",
            "provider_id": claim.credential_provider_id,
            "authenticator_id": claim.authenticator_id,
            "claim_digest": claim_digest,
            "credential_fingerprint": DIGEST,
            "authentication_receipt_digest": DIGEST,
            "authenticated": True,
            "environment": {"OPENZYME_HPC_SBATCH_TOKEN": "forbidden"},
            "exact_secret_material": ["forbidden"],
        }
    )
    provider = CommandExecutorHpcCredentialProvider(
        provider_id=claim.credential_provider_id,
        authenticator_id=claim.authenticator_id,
        issue_command=("/usr/local/bin/issue-hpc-credential",),
        revoke_command=("/usr/local/bin/revoke-hpc-credential",),
        executor=command,
    )

    with pytest.raises(ValueError, match="unknown environment"):
        provider.issue(claim)


def test_native_qualification_requires_external_exact_evidence_attestation() -> None:
    positive = (
        "file_create",
        "file_delete",
        "file_read",
        "file_update",
        "git",
        "git_lfs",
        "git_lfs_actual_bytes",
        "private_ref_push_fetch",
        "published_ref_fetch",
        "rsync",
        "scp",
        "ssh_login",
    )
    negative = (
        "absolute_path_substitution",
        "cross_executor",
        "cross_generation",
        "cross_target_replay",
        "hardlink_escape",
        "parent_traversal",
        "private_ref_cross_owner_denied",
        "published_ref_delete_denied",
        "published_ref_force_update_denied",
        "revoked_credential",
        "rsync_destination_escape",
        "runner_sidecar_access",
        "scheduler_submit_absent",
        "scp_destination_escape",
        "symlink_escape",
    )
    evidence = ExecutorHpcNativeQualificationEvidence.create(
        target_profile_id="target_1",
        target_profile_digest=DIGEST,
        credential_provider_id="provider_1",
        authenticator_id="authenticator_1",
        os_principal_policy_id="principal-policy-v1",
        root_policy_digest=DIGEST,
        login_alias="target-login",
        workspace_root="/srv/openzyme/workspaces",
        sidecar_root_digest=DIGEST,
        toolchain_digest=DIGEST,
        positive_receipt_digest=DIGEST,
        negative_receipt_digest=DIGEST,
        positive_scenarios=positive,
        negative_scenarios=negative,
        execution_mode="native_target_ssh",
        mocked=False,
        verified_at=NOW,
    )
    command = _CommandExecutor(
        {
            "schema_version": (
                "executor_hpc_native_qualification_verify_result@1"
            ),
            "evidence_digest": evidence.evidence_digest,
            "verification_receipt_digest": DIGEST,
            "verified": True,
        }
    )
    verifier = CommandExecutorHpcQualificationEvidenceVerifier(
        verifier_command=("/usr/local/bin/verify-hpc-qualification",),
        executor=command,
    )

    assert verifier.verify(evidence) == evidence.evidence_digest
