from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import ToolInvocation
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import ResolvedLocalWorkspaceToolContext


@dataclass(frozen=True, slots=True)
class EnzymeDesignLocalWorkspaceToolContextResolver:
    """Resolve one local workspace solely from canonical Kernel read Ports."""

    records: KernelRecordQueryPort

    def resolve(
        self,
        invocation: ToolInvocation,
        *,
        effectful: bool,
    ) -> ResolvedLocalWorkspaceToolContext:
        if "workspace_id" in invocation.arguments:
            raise KernelContractError(
                "workspace_id_forbidden",
                "Local workspace identity is resolved from canonical Agent state",
            )
        session = self.records.read(
            entity_type="session",
            entity_id=invocation.session_id,
        )
        member = self.records.read(
            entity_type="agent_member",
            entity_id=invocation.agent_member_id,
        )
        if (
            session is None
            or member is None
            or member.payload.get("session_id") != invocation.session_id
            or member.payload.get("status") != "active"
        ):
            raise KernelContractError(
                "local_workspace_owner_unavailable",
                "Local workspace owner is absent, retired or belongs elsewhere",
            )
        generation_value = member.payload.get("workspace_generation")
        lease_id = member.payload.get("active_authority_lease_id")
        process_epoch = member.payload.get("process_epoch")
        if (
            not isinstance(generation_value, int)
            or isinstance(generation_value, bool)
            or generation_value < 1
            or not isinstance(lease_id, str)
            or not lease_id
            or not isinstance(process_epoch, int)
            or isinstance(process_epoch, bool)
            or process_epoch < 1
        ):
            raise KernelContractError(
                "local_workspace_runtime_binding_missing",
                "Agent has no complete local workspace runtime identity",
            )

        workspaces = self.records.list_for_session(
            entity_type="workspace_runtime_binding",
            session_id=invocation.session_id,
            max_items=16,
        )
        matching = tuple(
            record
            for record in workspaces
            if record.payload.get("owner_member_id") == invocation.agent_member_id
            and record.payload.get("generation") == generation_value
            and record.payload.get("workspace_kind") == WorkspaceKind.AGENT_LOCAL.value
        )
        if len(matching) != 1:
            raise KernelContractError(
                "local_workspace_binding_ambiguous",
                "Agent must have exactly one current local workspace binding",
            )
        try:
            workspace = WorkspaceRuntimeBinding.from_dict(dict(matching[0].payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "local_workspace_binding_invalid",
                "Canonical local workspace binding is invalid",
            ) from exc
        generation_record = self.records.read(
            entity_type="workspace_generation",
            entity_id=workspace.workspace_id,
        )
        try:
            generation = (
                None
                if generation_record is None
                else WorkspaceGeneration.from_dict(dict(generation_record.payload))
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "local_workspace_generation_invalid",
                "Canonical local workspace generation is invalid",
            ) from exc
        if (
            generation is None
            or generation.status is not WorkspaceGenerationStatus.READY
            or generation.runtime_binding() != workspace
        ):
            raise KernelContractError(
                "local_workspace_not_ready",
                "Current local workspace generation is not ready",
            )

        lease_record = self.records.read(
            entity_type="agent_authority_lease",
            entity_id=lease_id,
        )
        try:
            lease = (
                None
                if lease_record is None
                else AgentAuthorityLease.from_dict(dict(lease_record.payload))
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "local_workspace_authority_invalid",
                "Canonical workspace authority lease is invalid",
            ) from exc
        if (
            lease is None
            or lease.state is not AgentAuthorityLeaseState.ACTIVE
            or lease.agent_member_id != invocation.agent_member_id
            or lease.workspace_generation != workspace.generation
        ):
            raise KernelContractError(
                "local_workspace_authority_stale",
                "Current Agent authority is not bound to the workspace generation",
            )

        pin_records = self.records.list_for_session(
            entity_type="session_composition_pin",
            session_id=invocation.session_id,
            max_items=2,
        )
        try:
            pin = (
                None
                if len(pin_records) != 1
                else SessionCompositionPin.from_dict(dict(pin_records[0].payload))
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "session_composition_pin_invalid",
                "Session composition pin is invalid",
            ) from exc
        bindings = self.records.list_for_session(
            entity_type="session_capability_binding_revision",
            session_id=invocation.session_id,
            max_items=64,
        )
        try:
            parsed_bindings = tuple(
                SessionCapabilityBindingRevision.from_dict(dict(item.payload))
                for item in bindings
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "session_capability_binding_invalid",
                "Session capability binding is invalid",
            ) from exc
        if pin is None or not parsed_bindings:
            raise KernelContractError(
                "session_runtime_composition_missing",
                "Workspace operation requires a pinned Session composition",
            )
        binding = max(parsed_bindings, key=lambda item: item.revision)
        extension_bundle_digest = pin.release_identity.extension_bundle_digest
        if binding.extension_bundle_digest != extension_bundle_digest:
            raise KernelContractError(
                "session_runtime_composition_stale",
                "Session capability binding differs from its composition pin",
            )

        context = KernelCommandContext(
            command_id=f"workspace-context-{invocation.call_id}",
            session_id=invocation.session_id,
            actor_id=invocation.agent_member_id,
            owner_plugin_id="openzyme.kernel",
            authority_lease_id=lease.lease_id,
            authority_generation=lease.generation,
            authority_fence=lease.fence,
            expected_session_version=session.state_version,
            extension_bundle_digest=extension_bundle_digest,
            capability_binding_digest=binding.binding_digest,
            idempotency_key=f"workspace-context-{invocation.call_id}",
            correlation_id=f"workspace-tool-{invocation.call_id}",
            workspace_generation=workspace.generation,
            route_id=workspace.provider_id if effectful else None,
        )
        return ResolvedLocalWorkspaceToolContext(
            binding=workspace,
            command_context=context,
            process_epoch=process_epoch,
        )


__all__ = ["EnzymeDesignLocalWorkspaceToolContextResolver"]
