from __future__ import annotations

import pytest

from openzyme_hpc import ExecutorHpcCredentialClaim
from openzyme_hpc import ExecutorHpcCredentialOperation
from openzyme_hpc import ExecutorHpcWorkspaceObservation
from openzyme_hpc import ExecutorHpcWorkspaceObservationKind
from openzyme_hpc import IssuedExecutorHpcCredential


DIGEST = "sha256:" + "a" * 64


def test_matching_workspace_observation_requires_protected_clone_facts() -> None:
    observation = ExecutorHpcWorkspaceObservation.create(
        workspace_id="hpcws_1",
        intent_digest=DIGEST,
        runner_handle="runner_1",
        remote_root_digest=DIGEST,
        kind=ExecutorHpcWorkspaceObservationKind.MATCHES,
        repository_remote_digest=DIGEST,
        head_commit="a" * 40,
        independent_git_directory=True,
        protected_root_mode="700",
        os_principal_identity_digest=DIGEST,
        isolation_receipt_digest=DIGEST,
        observed_at="2026-08-20T00:00:00+00:00",
    )

    assert observation.observation_digest.startswith("sha256:")


def test_native_workspace_credential_rejects_scheduler_environment() -> None:
    claim = ExecutorHpcCredentialClaim(
        claim_id="claim_1",
        workspace_id="hpcws_1",
        session_id="session_1",
        executor_agent_member_id="member_1",
        local_workspace_generation=1,
        remote_workspace_generation=1,
        target_profile_id="hpc-primary",
        target_profile_digest=DIGEST,
        capability_lease_id="lease_1",
        capability_lease_version=1,
        credential_provider_id="credential-provider",
        authenticator_id="authenticator",
        login_alias="login-alias",
        remote_workspace_path="/remote/workspaces/runner_1",
        remote_root_digest=DIGEST,
        os_principal_identity_digest=DIGEST,
        operations=(ExecutorHpcCredentialOperation.SSH_LOGIN,),
        issued_at="2026-08-20T00:00:00+00:00",
        expires_at="2026-08-20T00:05:00+00:00",
    )

    with pytest.raises(
        ValueError,
        match="scheduler authority",
    ):
        IssuedExecutorHpcCredential(
            claim=claim,
            credential_fingerprint=DIGEST,
            authentication_receipt_digest=DIGEST,
            environment=(("OPENZYME_HPC_SCHEDULER_TOKEN", "secret"),),
            exact_secret_material=("secret",),
        )
