"""Exact context revalidation for EnzymeDesign collaboration tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolInvocation
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel.collaboration_tools import ResolvedCollaborationToolContext
from openzyme_contracts.identity import JsonValue

from .composition import EnzymeDesignDeploymentStartup
from .runtime_admission import EnzymeDesignKernelRuntimeAdmissionSource


@dataclass(frozen=True, slots=True)
class EnzymeDesignCollaborationToolContextResolver:
    """Reload all mutable fences for every resident collaboration dispatch."""

    records: KernelRecordQueryPort
    admissions: EnzymeDesignKernelRuntimeAdmissionSource
    startup: EnzymeDesignDeploymentStartup

    def resolve(
        self,
        invocation: ToolInvocation,
        *,
        effectful: bool,
    ) -> ResolvedCollaborationToolContext:
        del effectful  # all collaboration calls receive the same strict fence set
        scope = self.admissions.resolve_invocation_scope(
            session_id=invocation.session_id,
            agent_member_id=invocation.agent_member_id,
            affordance_snapshot_digest=invocation.affordance_snapshot_digest,
        )
        active = self.startup.gate.active_epoch
        if active is None:
            raise KernelContractError(
                "runtime_collaboration_release_inactive",
                "The EnzymeDesign runtime release is no longer active",
            )
        session = self.records.read(
            entity_type="session",
            entity_id=invocation.session_id,
        )
        member = self.records.read(
            entity_type="agent_member",
            entity_id=invocation.agent_member_id,
        )
        authority_record = self.records.read(
            entity_type="agent_authority_lease",
            entity_id=scope.current_context.authority_lease.lease_id,
        )
        workflow = scope.current_workflow_authority
        workflow_record = (
            None
            if workflow is None
            else self.records.read(
                entity_type="workflow_authority_binding",
                entity_id=workflow.authority_id,
            )
        )
        capability = scope.current_context.capability_binding
        capability_record = self.records.read(
            entity_type="session_capability_binding_revision",
            entity_id=capability.binding_id,
        )
        exposure = scope.exposure_snapshot
        if session is None or member is None or authority_record is None:
            raise KernelContractError(
                "runtime_collaboration_context_missing",
                "Current Session, member or authority record is absent",
            )
        try:
            current_authority = AgentAuthorityLease.from_dict(authority_record.payload)
            current_capability = (
                None
                if capability_record is None
                else SessionCapabilityBindingRevision.from_dict(
                    capability_record.payload
                )
            )
            current_workflow = (
                None
                if workflow_record is None
                else WorkflowAuthorityBinding.from_dict(workflow_record.payload)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_collaboration_context_invalid",
                "Current collaboration fences violate their closed contracts",
            ) from exc
        mismatches = {
            "session": session.payload.get("session_id") != invocation.session_id,
            "member_session": member.payload.get("session_id") != invocation.session_id,
            "member_status": member.payload.get("status") != "active",
            "authority": current_authority != scope.current_context.authority_lease,
            "capability": current_capability != capability,
            "workflow_missing": (
                workflow is None or workflow_record is None or exposure is None
            ),
            "workflow": workflow is not None and current_workflow != workflow,
            "release_catalog": (
                active.release_identity.declared_tool_catalog_digest
                != scope.catalog.catalog_digest
            ),
            "release_bundle": (
                active.release_identity.extension_bundle_digest
                != capability.extension_bundle_digest
            ),
        }
        drifted = sorted(name for name, mismatch in mismatches.items() if mismatch)
        if drifted:
            raise KernelContractError(
                "runtime_collaboration_context_stale",
                "Collaboration dispatch fences changed after runtime admission",
                details={"drifted_fields": drifted, "fallback_performed": False},
            )
        assert workflow is not None
        return ResolvedCollaborationToolContext(
            command_context=KernelCommandContext(
                command_id=f"command-{invocation.call_id}",
                session_id=invocation.session_id,
                actor_id=invocation.agent_member_id,
                owner_plugin_id="openzyme.kernel",
                authority_lease_id=current_authority.lease_id,
                authority_generation=current_authority.generation,
                authority_fence=current_authority.fence,
                expected_session_version=session.state_version,
                extension_bundle_digest=active.release_identity.extension_bundle_digest,
                capability_binding_digest=capability.binding_digest,
                idempotency_key=f"tool-call-{invocation.call_id}",
                correlation_id=invocation.call_id,
                workspace_generation=current_authority.workspace_generation,
                route_id=invocation.route_id,
            ),
            runtime_command_id=scope.command_id,
            workflow_authority_id=workflow.authority_id,
            workflow_authority_epoch=workflow.epoch,
            workflow_authority_digest=workflow.binding_digest,
        )


@dataclass(frozen=True, slots=True)
class EnzymeDesignWorldInspectionApplication:
    """Return bounded canonical facts without exposing Hidden tool identities."""

    records: KernelRecordQueryPort
    admissions: EnzymeDesignKernelRuntimeAdmissionSource

    def inspect(
        self,
        *,
        context: ResolvedCollaborationToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]:
        raw_sections = arguments.get("sections", ())
        if not isinstance(raw_sections, tuple | list) or any(
            not isinstance(item, str) or not item for item in raw_sections
        ):
            raise ValueError("sections must be an array of exact identifiers")
        sections = tuple(raw_sections) or (
            "capability",
            "session",
            "tool_exposure",
            "workflow",
        )
        if sections != tuple(sorted(set(sections))):
            raise ValueError("sections must be sorted and unique")
        allowed = {"session", "workflow", "capability", "tool_exposure"}
        unknown = sorted(set(sections).difference(allowed))
        if unknown:
            raise ValueError(f"unknown world inspection sections: {unknown}")
        scope = self.admissions.get(context.runtime_command_id)
        if scope is None or scope.exposure_snapshot is None:
            raise KernelContractError(
                "runtime_tool_scope_unresolved",
                "World inspection command scope is absent",
            )
        result: dict[str, JsonValue] = {}
        if "session" in sections:
            session = self.records.read(
                entity_type="session",
                entity_id=scope.snapshot.session_id,
            )
            if session is None:
                raise KernelContractError(
                    "runtime_collaboration_context_missing",
                    "World inspection Session is absent",
                )
            result["session"] = {
                "session_id": session.entity_id,
                "state_version": session.state_version,
                "record_digest": session.record_digest,
            }
        if "workflow" in sections:
            result["workflow"] = {
                "authority_id": context.workflow_authority_id,
                "authority_epoch": context.workflow_authority_epoch,
                "authority_digest": context.workflow_authority_digest,
            }
        if "capability" in sections:
            result["capability"] = {
                "binding_digest": (
                    scope.current_context.capability_binding.binding_digest
                ),
                "affordance_snapshot_digest": scope.snapshot.snapshot_digest,
            }
        if "tool_exposure" in sections:
            direct = sum(
                decision.exposure is ToolExposure.DIRECT
                for decision in scope.exposure_snapshot.decisions
            )
            deferred = sum(
                decision.exposure is ToolExposure.DEFERRED
                for decision in scope.exposure_snapshot.decisions
            )
            result["tool_exposure"] = {
                "exposure_snapshot_id": (
                    scope.exposure_snapshot.exposure_snapshot_id
                ),
                "exposure_snapshot_digest": (
                    scope.exposure_snapshot.exposure_snapshot_digest
                ),
                "direct_count": direct,
                "deferred_count": deferred,
                "hidden_names_disclosed": False,
            }
        return result


__all__ = [
    "EnzymeDesignCollaborationToolContextResolver",
    "EnzymeDesignWorldInspectionApplication",
]
