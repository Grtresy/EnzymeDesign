from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from uuid import uuid4

from .contracts import ExecutorHpcCredentialClaim
from .contracts import ExecutorHpcCredentialOperation
from .contracts import ExecutorHpcCleanupDisposition
from .contracts import ExecutorHpcWorkspace
from .contracts import ExecutorHpcWorkspaceCleanupIntent
from .contracts import ExecutorHpcWorkspaceCleanupReceipt
from .contracts import ExecutorHpcWorkspaceProvisionIntent
from .contracts import ExecutorHpcWorkspaceProvisionReceipt
from .contracts import ExecutorHpcWorkspaceState
from .workspace_state_machine import ExecutorHpcWorkspaceLifecycle
from .workspace_lifecycle import ExecutorHpcCredentialProvider
from .workspace_lifecycle import ExecutorHpcWorkspaceCleaner
from .workspace_lifecycle import ExecutorHpcWorkspaceDispatchInDoubt
from .workspace_lifecycle import ExecutorHpcWorkspaceError
from .workspace_lifecycle import ExecutorHpcWorkspaceExecutionRequired
from .workspace_lifecycle import ExecutorHpcWorkspaceIdentityConflict
from .workspace_lifecycle import ExecutorHpcWorkspaceObservation
from .workspace_lifecycle import ExecutorHpcWorkspaceObservationKind
from .workspace_lifecycle import ExecutorHpcWorkspaceProvisioner
from .workspace_lifecycle import ExecutorHpcWorkspaceProvisioningRequired
from .workspace_lifecycle import ExecutorHpcWorkspaceSettlementInspector
from .workspace_lifecycle import ExecutorHpcWorkspaceSettlementProof
from .workspace_lifecycle import IssuedExecutorHpcCredential
from .sqlite_workspace_repository import ExecutorHpcWorkspaceRepository
from .workspace_application_ports import ExecutorHpcAuthorityCapability
from .workspace_application_ports import ExecutorHpcWorkspaceAuthorityError
from .workspace_application_ports import ExecutorHpcWorkspaceKernelFactsPort
from .workspace_application_ports import ExecutorHpcWorkspaceUnitOfWork


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ExecutorHpcWorkspaceService:
    workspace_repository: ExecutorHpcWorkspaceRepository
    kernel_facts: ExecutorHpcWorkspaceKernelFactsPort
    unit_of_work: ExecutorHpcWorkspaceUnitOfWork
    provisioner: ExecutorHpcWorkspaceProvisioner | None = None
    credential_provider: ExecutorHpcCredentialProvider | None = None
    cleaner: ExecutorHpcWorkspaceCleaner | None = None
    settlement_inspector: ExecutorHpcWorkspaceSettlementInspector | None = None
    lifecycle: ExecutorHpcWorkspaceLifecycle = field(
        default_factory=ExecutorHpcWorkspaceLifecycle
    )

    def prepare_provisioning(
        self,
        *,
        session_id: str,
        executor_agent_id: str,
        target_profile_id: str,
        remote_workspace_generation: int,
        idempotency_key: str,
        absolute_deadline: str,
        workspace_id: str | None = None,
        intent_id: str | None = None,
        created_at: str | None = None,
    ) -> ExecutorHpcWorkspace:
        target = self.workspace_repository.get_target_qualification(target_profile_id)
        if target is None or not target.activated:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "HPC target lacks native owner and isolation qualification"
            )
        context = self.kernel_facts.prepare_provision_context(
            session_id=session_id,
            executor_agent_id=executor_agent_id,
            target=target,
        )
        replay = self.workspace_repository.get_intent_by_idempotency(
            session_id=session_id,
            executor_agent_member_id=context.executor_agent_member_id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            replay_workspace = self._require_workspace(replay.workspace_id)
            if (
                replay.target_profile_id != target_profile_id
                or replay.remote_workspace_generation
                != remote_workspace_generation
                or replay.local_workspace_generation
                != context.local_workspace_generation
                or replay.absolute_deadline != absolute_deadline
                or (workspace_id is not None and workspace_id != replay.workspace_id)
                or (intent_id is not None and intent_id != replay.intent_id)
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "provision idempotency key was reused with different identity"
                )
            return replay_workspace
        prior_workspaces = [
            prior
            for prior in self.workspace_repository.list_by_agent_member(
                session_id=session_id,
                agent_member_id=context.executor_agent_member_id,
            )
            if prior.target_profile_id == target_profile_id
        ]
        now = created_at or _utc_now_iso()
        allocated_workspace_id = workspace_id or f"hpcws_{uuid4().hex}"
        allocated_intent_id = intent_id or f"hpcintent_{uuid4().hex}"
        intent, workspace = self.lifecycle.create_provision_records(
            context=context,
            remote_workspace_generation=remote_workspace_generation,
            idempotency_key=idempotency_key,
            absolute_deadline=absolute_deadline,
            workspace_id=allocated_workspace_id,
            intent_id=allocated_intent_id,
            created_at=now,
            prior_workspaces=tuple(prior_workspaces),
        )
        with self.unit_of_work(prefix="executor_hpc_workspace_prepare"):
            self.workspace_repository.add_intent(
                intent,
                local_workspace_id=context.local_workspace_id,
            )
            self.workspace_repository.add_workspace(workspace)
        for prior in prior_workspaces:
            if (
                prior.workspace_id != workspace.workspace_id
                and prior.target_profile_id == workspace.target_profile_id
                and prior.state
                not in {
                    ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
                    ExecutorHpcWorkspaceState.CLEANING,
                    ExecutorHpcWorkspaceState.CLEANED,
                }
            ):
                self.mark_retention_eligible(
                    prior.workspace_id,
                    reason="superseded_by_explicit_higher_generation",
                )
        return workspace

    def provision(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.provisioner is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace provisioner is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.READY:
            return workspace
        if (
            workspace.state
            is ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED
        ):
            return self.reconcile(workspace_id)
        if workspace.state is not ExecutorHpcWorkspaceState.PROVISIONING:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "workspace state cannot dispatch provisioning"
            )
        self._require_active_workspace_owner(workspace)
        intent = self._require_intent(workspace.provision_intent_id)
        try:
            receipt = self.provisioner.provision(intent)
        except ExecutorHpcWorkspaceDispatchInDoubt:
            return self._transition(
                workspace,
                ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
            )
        return self.accept_provision_receipt(receipt)

    def reconcile(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.provisioner is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace provisioner is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.READY:
            return workspace
        if workspace.state not in {
            ExecutorHpcWorkspaceState.PROVISIONING,
            ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
        }:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "workspace state cannot reconcile provisioning"
            )
        intent = self._require_intent(workspace.provision_intent_id)
        receipt = self.provisioner.reconcile(intent)
        if receipt is None:
            if workspace.state is ExecutorHpcWorkspaceState.PROVISIONING:
                return self._transition(
                    workspace,
                    ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
                )
            return workspace
        return self.accept_provision_receipt(receipt)

    def verify_remote_state(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.provisioner is None or not callable(
            getattr(self.provisioner, "inspect_state", None)
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC exact remote verifier is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is not ExecutorHpcWorkspaceState.READY:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "formal remote verification requires exact ready state"
            )
        intent = self._require_intent(workspace.provision_intent_id)
        observation = self.provisioner.inspect_state(intent, workspace)
        observed = self.lifecycle.apply_remote_observation(
            workspace=workspace,
            intent=intent,
            repository_binding_digest=self._require_binding_digest(intent),
            observation=observation,
        )
        if observed is workspace:
            return workspace
        return self.workspace_repository.transition(
            observed,
            expected_state_version=workspace.state_version,
        )

    def accept_provision_receipt(
        self,
        receipt: ExecutorHpcWorkspaceProvisionReceipt,
    ) -> ExecutorHpcWorkspace:
        workspace = self._require_workspace(receipt.workspace_id)
        intent = self._require_intent(receipt.intent_id)
        binding_digest = self._require_binding_digest(intent)
        target = self.workspace_repository.get_target_qualification(
            intent.target_profile_id
        )
        if target is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision target qualification is unavailable"
            )
        ready = self.lifecycle.accept_provision_receipt(
            workspace=workspace,
            intent=intent,
            target=target,
            repository_binding_digest=binding_digest,
            receipt=receipt,
        )
        with self.unit_of_work(prefix="executor_hpc_workspace_accept"):
            self.workspace_repository.add_receipt(receipt)
            self.workspace_repository.transition(
                ready,
                expected_state_version=workspace.state_version,
            )
        try:
            self._require_active_workspace_owner(ready)
        except ExecutorHpcWorkspaceAuthorityError:
            return self.mark_retention_eligible(
                ready.workspace_id,
                reason="owner_lease_inactive_after_provision_reconciliation",
            )
        return ready

    def owner_projection(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_id: str,
    ) -> dict[str, object]:
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.session_id != session_id
            or workspace.executor_agent_id != agent_id
        ):
            raise ExecutorHpcWorkspaceAuthorityError(
                "HPC workspace owner authorization failed"
            )
        include_locator = workspace.state is ExecutorHpcWorkspaceState.READY
        if include_locator:
            self.kernel_facts.authorize_workspace(
                workspace,
                service_id="executor_hpc_workspace_projection",
                protocol="owner_native_view",
                operation_class="workspace_inspect",
                required_capabilities=(ExecutorHpcAuthorityCapability.SSH,),
            )
        return self.lifecycle.owner_projection(
            workspace,
            owner_authorized=include_locator,
        )

    def owner_projections_for_agent(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> tuple[dict[str, object], ...]:
        agent_member_id = self.kernel_facts.agent_member_id(
            session_id=session_id,
            agent_id=agent_id,
        )
        if agent_member_id is None:
            return ()
        projections: list[dict[str, object]] = []
        for workspace in self.workspace_repository.list_by_agent_member(
            session_id=session_id,
            agent_member_id=agent_member_id,
        ):
            try:
                projections.append(
                    self.owner_projection(
                        workspace_id=workspace.workspace_id,
                        session_id=session_id,
                        agent_id=agent_id,
                    )
                )
            except ExecutorHpcWorkspaceAuthorityError:
                safe = workspace.to_dict(include_owner_locator=False)
                safe["native_admission_available"] = False
                projections.append(safe)
        return tuple(projections)

    def revision_sync_identity(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_id: str,
        checkpoint_id: str | None = None,
        publication_id: str | None = None,
    ) -> dict[str, object]:
        if (checkpoint_id is None) == (publication_id is None):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "revision sync requires exactly one checkpoint or publication"
            )
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.state is not ExecutorHpcWorkspaceState.READY
            or workspace.session_id != session_id
            or workspace.executor_agent_id != agent_id
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "revision sync identity requires the exact ready workspace owner"
            )
        self._require_active_workspace_owner(workspace)
        workspace = self.verify_remote_state(workspace.workspace_id)
        if workspace.state is not ExecutorHpcWorkspaceState.READY:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "remote workspace drift blocks revision sync"
            )
        source = self.kernel_facts.resolve_revision_source(
            workspace=workspace,
            checkpoint_id=checkpoint_id,
            publication_id=publication_id,
        )
        return self.lifecycle.revision_sync_identity(
            workspace=workspace,
            source=source,
        )

    def issue_native_credential(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_id: str,
        claim_id: str,
        expires_at: str,
        issued_at: str | None = None,
        operations: tuple[ExecutorHpcCredentialOperation, ...] | None = None,
    ) -> IssuedExecutorHpcCredential:
        if self.credential_provider is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC credential provider is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.state is not ExecutorHpcWorkspaceState.READY
            or workspace.session_id != session_id
            or workspace.executor_agent_id != agent_id
            or workspace.login_alias is None
            or workspace.remote_workspace_path is None
            or workspace.remote_root_digest is None
            or workspace.os_principal_identity_digest is None
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace is not exact ready owner state"
            )
        self.kernel_facts.authorize_workspace(
            workspace,
            service_id="executor_hpc_native_credential",
            protocol="target_scoped_ssh",
            operation_class="credential_issue",
            required_capabilities=(
                ExecutorHpcAuthorityCapability.SSH,
                ExecutorHpcAuthorityCapability.RSYNC_SCP,
                ExecutorHpcAuthorityCapability.HPC_LOGIN_WORKSPACE_CRUD,
                ExecutorHpcAuthorityCapability.GIT,
                ExecutorHpcAuthorityCapability.GIT_LFS,
            ),
        )
        target = self.workspace_repository.get_target_qualification(
            workspace.target_profile_id
        )
        if (
            target is None
            or self.credential_provider.provider_id != target.credential_provider_id
            or self.credential_provider.authenticator_id != target.authenticator_id
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "credential provider/authenticator does not match target qualification"
            )
        claim = self.lifecycle.create_native_credential_claim(
            workspace=workspace,
            target=target,
            claim_id=claim_id,
            issued_at=issued_at or _utc_now_iso(),
            expires_at=expires_at,
            operations=(
                tuple(ExecutorHpcCredentialOperation)
                if operations is None
                else operations
            ),
        )
        issued = self.credential_provider.issue(claim)
        if issued.claim != claim:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider changed the authorized claim"
            )
        environment = dict(issued.environment)
        if (
            environment.get("OPENZYME_HPC_CREDENTIAL_ID") != claim.claim_id
            or environment.get("OPENZYME_HPC_LOGIN_ALIAS")
            != workspace.login_alias
            or environment.get("OPENZYME_HPC_TARGET_PROFILE_ID")
            != workspace.target_profile_id
            or environment.get("OPENZYME_HPC_REMOTE_ROOT")
            != workspace.remote_workspace_path
            or environment.get(
                "OPENZYME_HPC_OS_PRINCIPAL_IDENTITY_DIGEST"
            )
            != workspace.os_principal_identity_digest
            or environment.get("OPENZYME_HPC_AUTHENTICATOR_ID")
            != target.authenticator_id
            or any(
                token in value.casefold()
                for _, value in issued.environment
                for token in ("scheduler.submit", "sbatch")
            )
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native workspace credential changed its exact non-scheduler audience"
            )
        self.workspace_repository.add_credential_claim(
            claim,
            credential_fingerprint=issued.credential_fingerprint,
            authentication_receipt_digest=(
                issued.authentication_receipt_digest
            ),
        )
        return issued

    def revoke_native_credential(
        self,
        *,
        claim_id: str,
        revoked_at: str | None = None,
    ) -> ExecutorHpcCredentialClaim:
        if self.credential_provider is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC credential provider is unavailable"
            )
        persisted = self.workspace_repository.get_credential_claim(
            claim_id
        )
        if persisted is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC credential claim does not exist"
            )
        claim, fingerprint = persisted
        if claim.revoked_at is not None:
            return claim
        self.credential_provider.revoke(fingerprint)
        return self.workspace_repository.revoke_credential_claim(
            claim_id,
            revoked_at=revoked_at or _utc_now_iso(),
        )

    def mark_retention_eligible(
        self,
        workspace_id: str,
        *,
        reason: str,
    ) -> ExecutorHpcWorkspace:
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE:
            return workspace
        if (
            workspace.state
            is ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED
        ):
            # An accepted remote create may still exist. Preserve the exact
            # provisioning reconciler until it adopts or rejects that handle;
            # the inactive lease already closes new native admission.
            return workspace
        if workspace.state in {
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
            ExecutorHpcWorkspaceState.CLEANED,
        }:
            return workspace
        self._revoke_active_workspace_credentials(workspace)
        transitioned = self.lifecycle.mark_retention_eligible(
            workspace,
            updated_at=_utc_now_iso(),
            reason=reason,
        )
        return self.workspace_repository.transition(
            transitioned,
            expected_state_version=workspace.state_version,
        )

    def reconcile_owner_admission(
        self,
        *,
        session_id: str,
    ) -> tuple[ExecutorHpcWorkspace, ...]:
        reconciled: list[ExecutorHpcWorkspace] = []
        for workspace in self.workspace_repository.list_by_session(
            session_id
        ):
            if workspace.state in {
                ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
                ExecutorHpcWorkspaceState.CLEANING,
                ExecutorHpcWorkspaceState.CLEANED,
            }:
                reconciled.append(workspace)
                continue
            try:
                self.kernel_facts.authorize_workspace(
                    workspace,
                    service_id="executor_hpc_workspace_admission_reconcile",
                    protocol="native_hpc_login_workspace",
                    operation_class="workspace_admission_reconcile",
                    required_capabilities=(
                        ExecutorHpcAuthorityCapability.SSH,
                        ExecutorHpcAuthorityCapability.RSYNC_SCP,
                        ExecutorHpcAuthorityCapability.HPC_LOGIN_WORKSPACE_CRUD,
                        ExecutorHpcAuthorityCapability.GIT,
                        ExecutorHpcAuthorityCapability.GIT_LFS,
                    ),
                )
            except ExecutorHpcWorkspaceAuthorityError:
                reconciled.append(
                    self.mark_retention_eligible(
                        workspace.workspace_id,
                        reason=(
                            "owner_session_retirement_lease_or_generation_inactive"
                        ),
                    )
                )
            else:
                reconciled.append(workspace)
        return tuple(reconciled)

    def cleanup(
        self,
        workspace_id: str,
        *,
        idempotency_key: str,
    ) -> ExecutorHpcWorkspace:
        if self.cleaner is None or self.settlement_inspector is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC cleanup requires exact cleaner and settlement inspector"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.CLEANED:
            return workspace
        if workspace.state not in {
            ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
        }:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC workspace is not cleanup eligible"
            )
        if (
            workspace.state
            is ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED
        ):
            return self.reconcile_cleanup(workspace_id)
        self._revoke_active_workspace_credentials(workspace)
        cleanup_intent = (
            self.workspace_repository.get_cleanup_intent_by_workspace(
                workspace.workspace_id
            )
        )
        if workspace.state is ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE:
            if (
                workspace.runner_handle is None
                or workspace.remote_root_digest is None
                or workspace.provision_receipt_id is None
            ):
                raise ExecutorHpcWorkspaceProvisioningRequired(
                    "retained pre-dispatch workspace has no remote cleanup effect"
                )
            workspace = self._transition(
                workspace,
                ExecutorHpcWorkspaceState.CLEANING,
                invalid_reason="cleanup_started_pending_settlement_proof",
            )
        if cleanup_intent is None:
            settlement_proof = self.settlement_inspector.prove_settled(workspace)
            if (
                settlement_proof.workspace_id != workspace.workspace_id
                or settlement_proof.workspace_state_version
                != workspace.state_version
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "settlement proof does not bind the exact workspace version"
                )
            if settlement_proof.unsettled_effect_count:
                raise ExecutorHpcWorkspaceProvisioningRequired(
                    "executor HPC workspace retains unsettled controlled effects"
                )
            cleanup_intent = self.lifecycle.create_cleanup_intent(
                workspace=workspace,
                cleanup_intent_id=f"hpccleanupintent_{uuid4().hex}",
                settlement_proof_digest=settlement_proof.proof_digest,
                idempotency_key=idempotency_key,
                created_at=_utc_now_iso(),
            )
            self.workspace_repository.add_cleanup_intent(
                cleanup_intent
            )
        elif cleanup_intent.idempotency_key != idempotency_key:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup replay changed the immutable idempotency key"
            )
        intent = self._require_intent(workspace.provision_intent_id)
        try:
            receipt = self.cleaner.cleanup(workspace, intent, cleanup_intent)
        except ExecutorHpcWorkspaceDispatchInDoubt:
            return self._transition(
                workspace,
                ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
                invalid_reason="cleanup_dispatch_in_doubt",
            )
        return self._accept_cleanup_receipt(
            workspace,
            receipt,
            cleanup_intent,
        )

    def reconcile_cleanup(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.cleaner is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC cleanup reconciler is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.CLEANED:
            return workspace
        if workspace.state not in {
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
        }:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "workspace state cannot reconcile cleanup"
            )
        cleanup_intent = (
            self.workspace_repository.get_cleanup_intent_by_workspace(
                workspace.workspace_id
            )
        )
        if cleanup_intent is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup reconciliation has no immutable intent"
            )
        receipt = self.cleaner.reconcile_cleanup(
            workspace,
            self._require_intent(workspace.provision_intent_id),
            cleanup_intent,
        )
        if receipt is None:
            return workspace
        return self._accept_cleanup_receipt(
            workspace,
            receipt,
            cleanup_intent,
        )

    def _accept_cleanup_receipt(
        self,
        workspace: ExecutorHpcWorkspace,
        receipt: ExecutorHpcWorkspaceCleanupReceipt,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspace:
        transitioned = self.lifecycle.accept_cleanup_receipt(
            workspace=workspace,
            intent=cleanup_intent,
            receipt=receipt,
        )
        if receipt.disposition is ExecutorHpcCleanupDisposition.UNCERTAIN:
            if transitioned is workspace:
                return workspace
            return self.workspace_repository.transition(
                transitioned,
                expected_state_version=workspace.state_version,
            )
        with self.unit_of_work(prefix="executor_hpc_workspace_cleanup_accept"):
            self.workspace_repository.add_cleanup_receipt(receipt)
            self.workspace_repository.transition(
                transitioned,
                expected_state_version=workspace.state_version,
            )
        return transitioned

    def _revoke_active_workspace_credentials(
        self,
        workspace: ExecutorHpcWorkspace,
    ) -> None:
        for claim, _ in (
            self.workspace_repository.list_active_credential_claims(
                workspace.workspace_id
            )
        ):
            self.revoke_native_credential(claim_id=claim.claim_id)

    def require_job_change(self, workspace_id: str) -> None:
        self._require_workspace(workspace_id)
        raise ExecutorHpcWorkspaceExecutionRequired(
            "HPC job admission remains closed until workspace-revision execution is installed"
        )

    def _transition(
        self,
        workspace: ExecutorHpcWorkspace,
        state: ExecutorHpcWorkspaceState,
        *,
        invalid_reason: str | None = None,
    ) -> ExecutorHpcWorkspace:
        transitioned = self.lifecycle.transition(
            workspace,
            state,
            updated_at=_utc_now_iso(),
            invalid_reason=invalid_reason,
        )
        return self.workspace_repository.transition(
            transitioned,
            expected_state_version=workspace.state_version,
        )

    def _require_workspace(self, workspace_id: str) -> ExecutorHpcWorkspace:
        workspace = self.workspace_repository.get(workspace_id)
        if workspace is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace does not exist"
            )
        return workspace

    def _require_intent(
        self,
        intent_id: str,
    ) -> ExecutorHpcWorkspaceProvisionIntent:
        intent = self.workspace_repository.get_intent(intent_id)
        if intent is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC provision intent does not exist"
            )
        return intent

    def _require_binding_digest(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> str:
        return self.kernel_facts.repository_binding_digest(intent)

    def _require_active_workspace_owner(
        self,
        workspace: ExecutorHpcWorkspace,
    ) -> None:
        self.kernel_facts.authorize_workspace(
            workspace,
            service_id="executor_hpc_workspace",
            protocol="native_hpc_login_workspace",
            operation_class="workspace_provision",
            required_capabilities=(
                ExecutorHpcAuthorityCapability.SSH,
                ExecutorHpcAuthorityCapability.RSYNC_SCP,
                ExecutorHpcAuthorityCapability.HPC_LOGIN_WORKSPACE_CRUD,
                ExecutorHpcAuthorityCapability.GIT,
                ExecutorHpcAuthorityCapability.GIT_LFS,
            ),
        )


@dataclass(slots=True)
class UnavailableExecutorHpcCredentialProvider:
    provider_id: str = "unavailable"
    authenticator_id: str = "unavailable"

    def issue(
        self,
        claim: ExecutorHpcCredentialClaim,
    ) -> IssuedExecutorHpcCredential:
        raise ExecutorHpcWorkspaceProvisioningRequired(
            "real target credential provider is not configured"
        )

    def revoke(self, credential_fingerprint: str) -> None:
        raise ExecutorHpcWorkspaceProvisioningRequired(
            "real target credential provider is not configured"
        )


def credential_fingerprint(secret: bytes) -> str:
    return f"sha256:{hashlib.sha256(secret).hexdigest()}"

__all__ = [
    "ExecutorHpcCredentialProvider",
    "ExecutorHpcWorkspaceDispatchInDoubt",
    "ExecutorHpcWorkspaceError",
    "ExecutorHpcWorkspaceExecutionRequired",
    "ExecutorHpcWorkspaceObservation",
    "ExecutorHpcWorkspaceObservationKind",
    "ExecutorHpcWorkspaceIdentityConflict",
    "ExecutorHpcWorkspaceProvisioner",
    "ExecutorHpcWorkspaceCleaner",
    "ExecutorHpcWorkspaceSettlementInspector",
    "ExecutorHpcWorkspaceSettlementProof",
    "ExecutorHpcWorkspaceProvisioningRequired",
    "ExecutorHpcWorkspaceService",
    "IssuedExecutorHpcCredential",
    "UnavailableExecutorHpcCredentialProvider",
    "credential_fingerprint",
]
