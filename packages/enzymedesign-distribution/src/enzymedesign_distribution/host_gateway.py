from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ClockPort
from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_kernel import SessionBootstrapCommand
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel import KernelContractError


ENZYMEDESIGN_ROOT_AUTHORITY_OPERATIONS = (
    "approval.consume",
    "approval.request",
    "authority.lease.issue",
    "authority.lease.revoke",
    "collaboration.add_task_dependency",
    "collaboration.create_lane",
    "collaboration.create_task",
    "collaboration.record_conversation",
    "collaboration.register_agent",
    "collaboration.retire_agent",
    "collaboration.write_memory",
    "continuation.register",
    "conversation.message.ingress",
    "extension.state.mutate",
    "external_compute",
    "protocol.delegate",
    "protocol.handoff",
    "protocol.send",
    "repository.binding.pin",
    "repository.binding.register",
    "runtime.lease.acquire",
    "runtime.lease.release",
    "runtime.lease.renew",
    "runtime.signal.claim",
    "runtime.signal.enqueue",
    "task.finish",
    "task.update",
    "workspace.checkpoint.verify",
    "workspace.fs.read",
    "workspace.fs.write",
    "workspace.generation.transition",
    "workspace.process.exec",
    "workspace.publish",
    "workspace.revision.verify",
)


class EnzymeDesignSessionBootstrapAuthorityPort(Protocol):
    """Delivery authority Adapter; EnzymeDesign never manufactures operator trust."""

    def issue(
        self,
        *,
        actor_id: str,
        project_id: str,
        session_id: str,
        root_authority_lease_digest: str,
        session_composition_pin_digest: str,
        extension_bundle_digest: str,
        capability_binding_digest: str,
        correlation_id: str,
    ) -> SessionBootstrapAuthorization: ...

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision: ...


class EnzymeDesignHostRouteApplication(Protocol):
    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt: ...


@dataclass(slots=True)
class EnzymeDesignHostKernelCommandGateway:
    """Distribution-owned bridge from generic HTTP admission to Kernel APIs."""

    deployment_epoch: DeploymentActivationEpoch
    bootstrap_service: SessionBootstrapKernelApplicationService
    bootstrap_authority: EnzymeDesignSessionBootstrapAuthorityPort
    clock: ClockPort
    ids: IdGeneratorPort
    route_applications: Mapping[str, EnzymeDesignHostRouteApplication]

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt:
        expected_fields = {"session_id", "project_id", "title", "objective"}
        if set(invocation.payload) != expected_fields:
            raise HostV2CommandError(
                "enzymedesign_session_bootstrap_payload_invalid",
                "Session bootstrap payload differs from its closed EnzymeDesign contract",
                status_code=422,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={
                    "missing": sorted(expected_fields.difference(invocation.payload)),
                    "unknown": sorted(set(invocation.payload).difference(expected_fields)),
                },
            )
        if invocation.payload["session_id"] != invocation.session_id:
            raise HostV2CommandError(
                "enzymedesign_session_bootstrap_identity_mismatch",
                "Session bootstrap body differs from its admitted identity",
                status_code=422,
                mutation_applied=False,
                effect_certainty="no_effect",
            )
        now = self.clock.now_iso()
        project_id = _text(invocation.payload, "project_id")
        title = _text(invocation.payload, "title")
        objective = _text(invocation.payload, "objective")
        master_member_id = self.ids.new_id(namespace="agent-member")
        binding = SessionCapabilityBindingRevision.create(
            binding_id=self.ids.new_id(namespace="capability-binding"),
            session_id=invocation.session_id,
            revision=1,
            extension_bundle_digest=(
                self.deployment_epoch.release_identity.extension_bundle_digest
            ),
            route_catalog_digest=(
                self.deployment_epoch.release_identity.route_catalog_digest
            ),
            inventory_bindings=(),
            created_by_actor_id=invocation.actor_id,
            created_at=now,
        )
        pin = SessionCompositionPin.create(
            pin_id=self.ids.new_id(namespace="composition-pin"),
            session_id=invocation.session_id,
            deployment_epoch=self.deployment_epoch,
            initial_capability_binding_id=binding.binding_id,
            initial_capability_binding_revision=binding.revision,
            initial_capability_binding_digest=binding.binding_digest,
            created_by_actor_id=invocation.actor_id,
            created_at=now,
        )
        grant = AuthorityGrant.create(
            grant_id=self.ids.new_id(namespace="authority-grant"),
            scope_id=invocation.session_id,
            operations=ENZYMEDESIGN_ROOT_AUTHORITY_OPERATIONS,
            generation=1,
            fence=1,
        )
        root_lease = AgentAuthorityLease.create(
            lease_id=self.ids.new_id(namespace="authority-lease"),
            session_id=invocation.session_id,
            agent_member_id=master_member_id,
            grants=(grant,),
            generation=1,
            fence=1,
            state=AgentAuthorityLeaseState.ACTIVE,
            issued_at=now,
            expires_at=None,
            agent_id=master_member_id,
            policy_digest=canonical_sha256_digest(
                {
                    "schema_version": "openzyme_enzymedesign_root_authority_policy@1",
                    "operations": list(ENZYMEDESIGN_ROOT_AUTHORITY_OPERATIONS),
                }
            ),
            idempotency_key=invocation.idempotency_key,
            updated_at=now,
        )
        authorization = self.bootstrap_authority.issue(
            actor_id=invocation.actor_id,
            project_id=project_id,
            session_id=invocation.session_id,
            root_authority_lease_digest=root_lease.lease_digest,
            session_composition_pin_digest=pin.pin_digest,
            extension_bundle_digest=binding.extension_bundle_digest,
            capability_binding_digest=binding.binding_digest,
            correlation_id=invocation.correlation_id,
        )
        try:
            return self.bootstrap_service.bootstrap(
                SessionBootstrapCommand(
                    command_id=self.ids.new_id(namespace="command"),
                    idempotency_key=invocation.idempotency_key,
                    correlation_id=invocation.correlation_id,
                    authorization=authorization,
                    session_id=invocation.session_id,
                    project_id=project_id,
                    title=title,
                    objective=objective,
                    master_member_id=master_member_id,
                    master_name="Master",
                    root_authority_lease=root_lease,
                    initial_capability_binding=binding,
                    session_composition_pin=pin,
                )
            )
        except KernelContractError as exc:
            raise _host_kernel_error(exc) from exc

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        application = self.route_applications.get(invocation.route_id)
        if application is None:
            raise HostV2CommandError(
                "enzymedesign_kernel_route_unconfigured",
                "The active EnzymeDesign composition has no application for this Kernel route",
                status_code=503,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={"route_id": invocation.route_id},
            )
        try:
            return application.invoke(invocation)
        except KernelContractError as exc:
            raise _host_kernel_error(exc) from exc


def _text(payload: Mapping[str, object], field_name: str) -> str:
    value = payload[field_name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise HostV2CommandError(
            "enzymedesign_session_bootstrap_payload_invalid",
            f"Session bootstrap {field_name} must be one non-empty string",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        )
    return value


def _host_kernel_error(exc: KernelContractError) -> HostV2CommandError:
    return HostV2CommandError(
        exc.code,
        str(exc),
        status_code=409,
        mutation_applied=exc.mutation_applied,
        effect_certainty=exc.effect_certainty,
        details=exc.details,
    )


__all__ = [
    "ENZYMEDESIGN_ROOT_AUTHORITY_OPERATIONS",
    "EnzymeDesignHostKernelCommandGateway",
    "EnzymeDesignHostRouteApplication",
    "EnzymeDesignSessionBootstrapAuthorityPort",
]
