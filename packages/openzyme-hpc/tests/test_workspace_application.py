from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Iterator

import pytest

from openzyme_hpc import ExecutorHpcProvisionContext
from openzyme_hpc import ExecutorHpcTargetQualification
from openzyme_hpc import ExecutorHpcWorkspace
from openzyme_hpc import ExecutorHpcWorkspaceAuthorityError
from openzyme_hpc import ExecutorHpcWorkspaceService
from openzyme_hpc import ExecutorHpcWorkspaceState


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


@dataclass(slots=True)
class _WorkspaceRepository:
    target: ExecutorHpcTargetQualification = field(default_factory=_target)
    workspaces: dict[str, ExecutorHpcWorkspace] = field(default_factory=dict)
    intents: dict[str, object] = field(default_factory=dict)

    def get_target_qualification(self, target_profile_id: str):
        return self.target if target_profile_id == self.target.target_profile_id else None

    def get_intent_by_idempotency(self, **_values):
        return None

    def list_by_agent_member(self, **_values):
        return list(self.workspaces.values())

    def add_intent(self, intent, *, local_workspace_id: str):
        assert local_workspace_id == "local_1"
        self.intents[intent.intent_id] = intent
        return intent

    def add_workspace(self, workspace: ExecutorHpcWorkspace):
        self.workspaces[workspace.workspace_id] = workspace
        return workspace

    def get(self, workspace_id: str):
        return self.workspaces.get(workspace_id)


@dataclass(slots=True)
class _KernelFacts:
    context: ExecutorHpcProvisionContext = field(default_factory=_context)
    authorization_count: int = 0

    def prepare_provision_context(self, **_values):
        return self.context

    def authorize_workspace(self, _workspace, **_values) -> None:
        self.authorization_count += 1

    def agent_member_id(self, **_values):
        return self.context.executor_agent_member_id

    def resolve_revision_source(self, **_values):
        raise AssertionError("revision source was not requested")

    def repository_binding_digest(self, _intent):
        return DIGEST


@contextmanager
def _unit_of_work(*, prefix: str) -> Iterator[None]:
    assert prefix.startswith("executor_hpc_workspace_")
    yield


def _service() -> tuple[ExecutorHpcWorkspaceService, _WorkspaceRepository, _KernelFacts]:
    repository = _WorkspaceRepository()
    facts = _KernelFacts()
    return (
        ExecutorHpcWorkspaceService(
            workspace_repository=repository,  # type: ignore[arg-type]
            kernel_facts=facts,  # type: ignore[arg-type]
            unit_of_work=_unit_of_work,
        ),
        repository,
        facts,
    )


def test_workspace_application_is_plugin_owned_and_uses_narrow_facts_port() -> None:
    service, repository, _facts = _service()

    workspace = service.prepare_provisioning(
        session_id="session_1",
        executor_agent_id="agent_1",
        target_profile_id="hpc-primary",
        remote_workspace_generation=5,
        idempotency_key="provision_1",
        absolute_deadline="2026-08-20T00:05:00+00:00",
        workspace_id="hpcws_1",
        intent_id="intent_1",
        created_at=NOW,
    )

    assert ExecutorHpcWorkspaceService.__module__ == "openzyme_hpc.workspace_application"
    assert repository.workspaces == {workspace.workspace_id: workspace}
    assert set(repository.intents) == {"intent_1"}


def test_non_owner_projection_fails_without_revealing_locator() -> None:
    service, repository, facts = _service()
    workspace = service.prepare_provisioning(
        session_id="session_1",
        executor_agent_id="agent_1",
        target_profile_id="hpc-primary",
        remote_workspace_generation=5,
        idempotency_key="provision_1",
        absolute_deadline="2026-08-20T00:05:00+00:00",
        workspace_id="hpcws_1",
        intent_id="intent_1",
        created_at=NOW,
    )
    repository.workspaces[workspace.workspace_id] = replace(
        workspace,
        state=ExecutorHpcWorkspaceState.READY,
        state_version=2,
        runner_handle="runner_1",
        provision_receipt_id="receipt_1",
        login_alias="private-login",
        remote_workspace_path="/srv/openzyme/workspaces/runner_1",
        remote_root_digest=DIGEST,
        os_principal_identity_digest=DIGEST,
        isolation_receipt_digest=DIGEST,
    )

    with pytest.raises(ExecutorHpcWorkspaceAuthorityError) as raised:
        service.owner_projection(
            workspace_id="hpcws_1",
            session_id="session_1",
            agent_id="other_agent",
        )

    assert "private-login" not in str(raised.value)
    assert "/srv/openzyme" not in str(raised.value)
    assert facts.authorization_count == 0
