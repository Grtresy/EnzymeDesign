from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import WorkspacePortError
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import WorkspaceProvisioningReconciliationRequest
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_workspace_git_lfs import AgentGitWorkspaceRecoveryProbe
from openzyme_workspace_git_lfs import AgentGitDirectoryKind
from openzyme_workspace_git_lfs import AgentGitWorkspace
from openzyme_workspace_git_lfs import AgentGitWorkspaceObservation
from openzyme_workspace_git_lfs import AgentGitWorkspaceStatus
from openzyme_workspace_git_lfs import GitLfsWorkspaceProvisioner
from openzyme_workspace_git_lfs import GitLfsWorkspaceProvisioningPlan

def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _workspace() -> AgentGitWorkspace:
    return AgentGitWorkspace.create(
        workspace_id="workspace_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        reservation_id="reservation_1",
        reservation_fingerprint=_digest("reservation"),
        capability_lease_id="lease_1",
        capability_lease_intent_digest=_digest("lease-intent"),
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_binding_digest=_digest("repository-binding"),
        repository_id="repository_1",
        internal_git_service_id="git_service_1",
        internal_git_endpoint="https://git.internal/repositories/repository_1.git",
        object_format=GitObjectFormat.SHA1,
        base_commit="8ae3d73b3054f2058ff33ea183f62c811b9272a3",
        volume_id="volume_session_1_member_1_g1",
        clone_logical_root="/workspace/repository",
        image_ref="localhost/openzyme-agent-capsule@sha256:" + "a" * 64,
        image_manifest_digest=_digest("image-manifest"),
        image_qualification_digest=_digest("image-qualification"),
        private_ref_namespace="refs/openzyme/private/session_1/member_1/g1",
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=_digest("repository-policy"),
        capability_policy_version="agent-capability-policy-v1",
        capability_policy_digest=_digest("capability-policy"),
        status=AgentGitWorkspaceStatus.PROVISIONING,
        state_version=1,
        created_at="2026-08-16T01:00:00+00:00",
        updated_at="2026-08-16T01:00:00+00:00",
    )


def _observation(workspace: AgentGitWorkspace) -> AgentGitWorkspaceObservation:
    return AgentGitWorkspaceObservation(
        workspace_id=workspace.workspace_id,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        agent_id=workspace.agent_id,
        workspace_generation=workspace.workspace_generation,
        volume_id=workspace.volume_id,
        clone_logical_root=workspace.clone_logical_root,
        git_directory_kind=AgentGitDirectoryKind.INDEPENDENT,
        internal_git_service_id=workspace.internal_git_service_id,
        internal_git_endpoint=workspace.internal_git_endpoint,
        repository_id=workspace.repository_id,
        object_format=workspace.object_format,
        base_commit=workspace.base_commit,
        head_commit=workspace.base_commit,
        head_tree="1" * 40,
        head_readable=True,
        private_ref_namespace=workspace.private_ref_namespace,
        repository_policy_digest=workspace.repository_policy_digest,
        capability_policy_digest=workspace.capability_policy_digest,
        observed_at="2026-08-16T01:01:00+00:00",
    )


@dataclass
class _Clock:
    def now_iso(self) -> str:
        return "2026-08-20T10:00:00+00:00"


@dataclass
class _Ids:
    value: int = 0

    def new_id(self, *, namespace: str) -> str:
        self.value += 1
        return f"{namespace}-{self.value}"


class _Resolver:
    def __init__(self, request: WorkspaceProvisioningRequest) -> None:
        self.request = request
        self.calls = 0

    def resolve(self, request):  # noqa: ANN001, ANN201
        self.calls += 1
        assert request.request_digest == self.request.request_digest
        return GitLfsWorkspaceProvisioningPlan(
            request_digest=request.request_digest,
            repository_pin_digest=request.repository_pin_digest,
            workspace=_workspace(),
            credential_token="secret-scoped-provision-token",
        )


class _ProvisioningMechanism:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def clone_and_observe(self, *, workspace, credential_token):  # noqa: ANN001, ANN201
        self.tokens.append(credential_token)
        return _observation(workspace)


class _RecoveryMechanism:
    def probe(self, workspace):  # noqa: ANN001, ANN201
        return AgentGitWorkspaceRecoveryProbe(
            observation=_observation(workspace),
            blocker_code=None,
            blocker_detail=None,
        )


def _request() -> WorkspaceProvisioningRequest:
    workspace = _workspace()
    return WorkspaceProvisioningRequest(
        request_id="workspace-provision-request-1",
        intent_id="workspace-provision-intent-1",
        intent_digest=_digest("claimed-intent"),
        claim_token="workspace-provision-claim-1",
        claim_epoch=1,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        workspace_id=workspace.workspace_id,
        generation=workspace.workspace_generation,
        repository_pin_digest=_digest("repository-pin"),
        provider_id="openzyme.workspace.git.lfs",
        target_id="local-primary",
        adapter_binding_digest=_digest("selected-git-lfs-adapter"),
        controlled_operation_id="workspace-controlled-operation-1",
    )


def _port(request: WorkspaceProvisioningRequest):  # noqa: ANN202
    resolver = _Resolver(request)
    mechanism = _ProvisioningMechanism()
    port = GitLfsWorkspaceProvisioner(
        provider_id=request.provider_id,
        adapter_binding_digest=request.adapter_binding_digest,
        plan_resolver=resolver,
        provisioning_mechanism=mechanism,
        recovery_mechanism=_RecoveryMechanism(),
        clock=_Clock(),
        ids=_Ids(),
    )
    return port, resolver, mechanism


def test_selected_git_lfs_port_returns_exact_ready_receipt_without_secret_leak() -> None:
    request = _request()
    port, resolver, mechanism = _port(request)

    receipt = port.provision(request)

    assert receipt.disposition.value == "ready"
    assert receipt.request_digest == request.request_digest
    assert receipt.adapter_binding_digest == request.adapter_binding_digest
    assert receipt.observed_root_identity_digest == _observation(
        _workspace()
    ).observation_digest
    assert receipt.fallback_performed is False
    assert resolver.calls == 1
    assert mechanism.tokens == ["secret-scoped-provision-token"]
    assert "secret-scoped-provision-token" not in str(receipt.to_dict())


def test_reconciliation_observes_exact_workspace_without_redispatch() -> None:
    request = _request()
    port, _, mechanism = _port(request)

    receipt = port.reconcile(
        WorkspaceProvisioningReconciliationRequest(
            reconciliation_id="workspace-reconciliation-1",
            provision_request=request,
            dispatch_receipt_digest=_digest("uncertain-dispatch"),
            reason_code="explicit-reconciliation",
            requested_at="2026-08-20T10:00:00+00:00",
        )
    )

    assert receipt.disposition.value == "ready"
    assert mechanism.tokens == []


def test_selected_port_rejects_another_adapter_binding_before_plan_resolution() -> None:
    request = _request()
    port, resolver, mechanism = _port(request)
    other = replace(
        request,
        adapter_binding_digest=_digest("another-adapter"),
    )

    with pytest.raises(WorkspacePortError) as mismatch:
        port.provision(other)

    assert mismatch.value.error_code == "git_lfs_provisioner_binding_mismatch"
    assert mismatch.value.effect_certainty.value == "no_effect"
    assert mismatch.value.fallback_performed is False
    assert resolver.calls == 0
    assert mechanism.tokens == []
