"""Selected Git/LFS implementation of the workspace provisioning SPI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import RetryEligibility
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningReceiptDisposition
from openzyme_contracts import WorkspaceProvisioningReconciliationRequest
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_extension_spi import validate_workspace_provisioner_identity

from .agent_workspaces import AgentGitWorkspace
from .agent_workspaces import AgentGitWorkspaceBlockerCode
from .agent_workspaces import AgentGitWorkspaceStatus
from .agent_workspaces import compare_agent_git_workspace_identity
from .workspace_lifecycle_mechanism import AgentGitWorkspaceProvisioningMechanism
from .workspace_lifecycle_mechanism import AgentGitWorkspaceRecoveryMechanism


@dataclass(frozen=True, slots=True)
class GitLfsWorkspaceProvisioningPlan:
    """Secret-bearing mechanism input resolved for one exact Kernel request.

    The resolver must be read-only. Credential material stays inside the Adapter
    and is never returned in a Kernel receipt or failure record.
    """

    request_digest: str
    repository_pin_digest: str
    workspace: AgentGitWorkspace
    credential_token: str

    def __post_init__(self) -> None:
        require_digest(self.request_digest, field_name="request_digest")
        require_digest(
            self.repository_pin_digest,
            field_name="repository_pin_digest",
        )
        if (
            not self.credential_token
            or self.credential_token != self.credential_token.strip()
        ):
            raise ValueError(
                "credential_token must be non-empty without surrounding whitespace"
            )


class GitLfsWorkspaceProvisioningPlanResolverPort(Protocol):
    """Pure resolver for a preselected Adapter binding and exact request."""

    def resolve(
        self,
        request: WorkspaceProvisioningRequest,
    ) -> GitLfsWorkspaceProvisioningPlan: ...


@dataclass(slots=True)
class GitLfsWorkspaceProvisioner:
    """Runs only the configured Git/LFS mechanism; never selects a fallback."""

    provider_id: str
    adapter_binding_digest: str
    plan_resolver: GitLfsWorkspaceProvisioningPlanResolverPort
    provisioning_mechanism: AgentGitWorkspaceProvisioningMechanism
    recovery_mechanism: AgentGitWorkspaceRecoveryMechanism
    clock: ClockPort
    ids: IdGeneratorPort

    def __post_init__(self) -> None:
        validate_workspace_provisioner_identity(self)

    def provision(
        self,
        request: WorkspaceProvisioningRequest,
    ) -> WorkspaceProvisioningReceipt:
        plan = self._resolve(request)
        try:
            observation = self.provisioning_mechanism.clone_and_observe(
                workspace=plan.workspace,
                credential_token=plan.credential_token,
            )
        except WorkspacePortError:
            raise
        except Exception as exc:
            raise WorkspacePortError(
                "git_lfs_workspace_provisioning_failed",
                "Git/LFS provisioning did not produce a ready exact workspace",
                effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
                mutation_applied=True,
                diagnostic_id=self.ids.new_id(namespace="diagnostic"),
            ) from exc
        return self._ready_receipt(request, plan.workspace, observation)

    def reconcile(
        self,
        request: WorkspaceProvisioningReconciliationRequest,
    ) -> WorkspaceProvisioningReceipt:
        provision_request = request.provision_request
        plan = self._resolve(provision_request)
        probe = self.recovery_mechanism.probe(plan.workspace)
        if probe.observation is not None:
            return self._ready_receipt(
                provision_request,
                plan.workspace,
                probe.observation,
            )
        assert probe.blocker_code is not None
        mutation_applied = probe.blocker_code not in {
            AgentGitWorkspaceBlockerCode.MISSING_VOLUME,
            AgentGitWorkspaceBlockerCode.CROSS_AGENT_VOLUME,
        }
        raise WorkspacePortError(
            f"git_lfs_reconciliation_{probe.blocker_code.value}",
            "Git/LFS reconciliation proved that the exact workspace is not ready",
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=mutation_applied,
            diagnostic_id=self.ids.new_id(namespace="diagnostic"),
        ) from probe.private_error

    def _resolve(
        self,
        request: WorkspaceProvisioningRequest,
    ) -> GitLfsWorkspaceProvisioningPlan:
        if (
            request.provider_id != self.provider_id
            or request.adapter_binding_digest != self.adapter_binding_digest
        ):
            raise WorkspacePortError(
                "git_lfs_provisioner_binding_mismatch",
                "Provisioning request names another selected Adapter binding",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id=self.ids.new_id(namespace="diagnostic"),
            )
        try:
            plan = self.plan_resolver.resolve(request)
        except WorkspacePortError:
            raise
        except Exception as exc:
            raise WorkspacePortError(
                "git_lfs_provisioning_plan_unavailable",
                "Exact Git/LFS provisioning inputs could not be resolved",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id=self.ids.new_id(namespace="diagnostic"),
            ) from exc
        workspace = plan.workspace
        if (
            plan.request_digest != request.request_digest
            or plan.repository_pin_digest != request.repository_pin_digest
            or workspace.workspace_id != request.workspace_id
            or workspace.session_id != request.session_id
            or workspace.agent_member_id != request.agent_member_id
            or workspace.workspace_generation != request.generation
            or workspace.status is not AgentGitWorkspaceStatus.PROVISIONING
        ):
            raise WorkspacePortError(
                "git_lfs_provisioning_plan_identity_mismatch",
                "Resolved Git/LFS plan differs from the exact Kernel request",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id=self.ids.new_id(namespace="diagnostic"),
            )
        return plan

    def _ready_receipt(
        self,
        request: WorkspaceProvisioningRequest,
        workspace: AgentGitWorkspace,
        observation,  # noqa: ANN001 - observation remains Adapter-internal
    ) -> WorkspaceProvisioningReceipt:
        comparison = compare_agent_git_workspace_identity(workspace, observation)
        if not comparison.matches:
            raise WorkspacePortError(
                "git_lfs_workspace_identity_drift",
                "Git/LFS observation differs from the exact requested identity",
                effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
                mutation_applied=True,
                diagnostic_id=self.ids.new_id(namespace="diagnostic"),
            )
        receipt_id = self.ids.new_id(namespace="workspace-provision-receipt")
        terminal_receipt_digest = canonical_sha256_digest(
            {
                "schema_version": "git_lfs_workspace_provisioning_terminal@1",
                "receipt_id": receipt_id,
                "request_digest": request.request_digest,
                "observation_digest": observation.observation_digest,
                "comparison_drift": [item.value for item in comparison.drift],
            }
        )
        return WorkspaceProvisioningReceipt(
            receipt_id=receipt_id,
            request_id=request.request_id,
            request_digest=request.request_digest,
            intent_id=request.intent_id,
            intent_digest=request.intent_digest,
            claim_token=request.claim_token,
            claim_epoch=request.claim_epoch,
            controlled_operation_id=request.controlled_operation_id,
            disposition=WorkspaceProvisioningReceiptDisposition.READY,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            workspace_id=request.workspace_id,
            generation=request.generation,
            repository_pin_digest=request.repository_pin_digest,
            provider_id=request.provider_id,
            target_id=request.target_id,
            adapter_binding_digest=request.adapter_binding_digest,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            fallback_performed=False,
            retry_eligibility=RetryEligibility.TERMINAL,
            reconcile_required=False,
            observed_root_identity_digest=observation.observation_digest,
            terminal_receipt_digest=terminal_receipt_digest,
            completed_at=self.clock.now_iso(),
        )


__all__ = [
    "GitLfsWorkspaceProvisioner",
    "GitLfsWorkspaceProvisioningPlan",
    "GitLfsWorkspaceProvisioningPlanResolverPort",
]
