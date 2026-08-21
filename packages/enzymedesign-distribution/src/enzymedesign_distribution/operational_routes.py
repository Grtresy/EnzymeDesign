from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ProtocolApplicationCommand
from openzyme_extension_spi import ProtocolCommandKind
from openzyme_extension_spi import PublicationApplicationCommand
from openzyme_extension_spi import PublicationCommandKind
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_kernel import ProtocolKernelApplicationService
from openzyme_kernel import PublicationKernelApplicationService

from .coordination_routes import build_enzymedesign_command_context


STANDARD_OPERATIONAL_ROUTE_IDS = (
    "openzyme.kernel.runtime.drain@2",
    "openzyme.kernel.workspace.fs.mutate@2",
    "openzyme.kernel.workspace.exec@2",
    "openzyme.kernel.workspace.checkpoint@2",
    "openzyme.kernel.workspace.publish@2",
    "openzyme.kernel.workspace.handoff@2",
)


class EnzymeDesignRuntimeDrainApplication(Protocol):
    """Distribution-owned bounded drain over Kernel runtime coordination."""

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt: ...


class EnzymeDesignWorkspaceToolRuntime(Protocol):
    """One mounted Kernel base-tool runtime, never a Host implementation detail."""

    def invoke(self, invocation: ToolInvocation) -> ToolResult: ...


@dataclass(slots=True)
class EnzymeDesignKernelOperationalRouteApplication:
    """Translate exact @2 operational routes to injected Kernel applications.

    The class owns no Provider, Git, Podman, filesystem, process or credential
    implementation.  EnzymeDesign selects those Adapters and injects the already-mounted
    runtime applications here.  This keeps the generic Host unaware of mechanisms and
    lets deterministic fakes exercise the identical command path.
    """

    runtime_drain: EnzymeDesignRuntimeDrainApplication
    workspace_tools: Mapping[str, EnzymeDesignWorkspaceToolRuntime]
    publications: PublicationKernelApplicationService
    protocols: ProtocolKernelApplicationService
    ids: IdGeneratorPort

    def __post_init__(self) -> None:
        expected = {"workspace.fs.mutate", "workspace.exec"}
        if set(self.workspace_tools) != expected:
            raise ValueError(
                "EnzymeDesign operational HTTP routes require exact workspace mutation "
                "and process runtimes"
            )

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        route = invocation.route_id
        if route == "openzyme.kernel.runtime.drain@2":
            return self.runtime_drain.invoke(invocation)
        if route == "openzyme.kernel.workspace.fs.mutate@2":
            return self._workspace_tool(invocation, "workspace.fs.mutate")
        if route == "openzyme.kernel.workspace.exec@2":
            return self._workspace_tool(invocation, "workspace.exec")
        if route == "openzyme.kernel.workspace.checkpoint@2":
            return self._publication(
                invocation,
                operation=PublicationCommandKind.VERIFY_CHECKPOINT,
            )
        if route == "openzyme.kernel.workspace.publish@2":
            return self._publication(
                invocation,
                operation=PublicationCommandKind.PUBLISH,
            )
        if route == "openzyme.kernel.workspace.handoff@2":
            return self._handoff(invocation)
        raise _payload_error(route, "The operational application does not own this route")

    def _workspace_tool(
        self,
        invocation: HostV2MutationInvocation,
        tool_name: str,
    ) -> KernelMutationReceipt:
        context = build_enzymedesign_command_context(invocation, ids=self.ids)
        result = self.workspace_tools[tool_name].invoke(
            ToolInvocation(
                call_id=self.ids.new_id(namespace="tool-call"),
                tool_name=tool_name,
                arguments=invocation.payload,
                session_id=invocation.session_id,
                agent_member_id=context.actor_id,
                affordance_snapshot_digest=(
                    invocation.precondition.affordance_snapshot_digest
                ),
            )
        )
        operation = _operation_result(result)
        certainty = ExternalEffectCertainty(
            str(operation.get("effect_certainty", "no_effect"))
        )
        mutation = operation.get("mutation_applied")
        if mutation not in {True, False, None}:
            raise _payload_error(invocation.route_id, "Workspace result is malformed")
        if not result.ok:
            raise HostV2CommandError(
                result.error_code or "workspace_operation_failed",
                result.summary,
                status_code=409,
                mutation_applied=mutation,
                effect_certainty=certainty.value,
                details={
                    "tool_name": tool_name,
                    "tool_result": result.to_dict(),
                },
            )
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id="openzyme.enzymedesign.workspace-route",
            operation=tool_name,
            mutation_applied=mutation is True,
            effect_certainty=certainty,
            result={
                "tool_result": result.to_dict(),
                "task_transition_performed": False,
            },
        )

    def _publication(
        self,
        invocation: HostV2MutationInvocation,
        *,
        operation: PublicationCommandKind,
    ) -> KernelMutationReceipt:
        payload = dict(invocation.payload)
        resource_id = _pop_text(payload, "resource_id")
        workspace_id = _pop_text(payload, "workspace_id")
        generation = _pop_positive_integer(payload, "expected_workspace_generation")
        if operation is PublicationCommandKind.VERIFY_CHECKPOINT:
            expected = {"proof"}
        else:
            phase = payload.get("phase")
            expected = (
                {"phase", "intent"}
                if phase == "admit"
                else {"phase", "controlled_operation_id", "remote_receipt"}
            )
        if set(payload) != expected:
            raise _payload_error(
                invocation.route_id,
                "Publication payload differs from its exact phase contract",
            )
        context = build_enzymedesign_command_context(invocation, ids=self.ids)
        return self.publications.execute(
            PublicationApplicationCommand(
                context=context,
                operation=operation,
                resource_id=resource_id,
                workspace_id=workspace_id,
                expected_workspace_generation=generation,
                payload=payload,
            )
        )

    def _handoff(
        self,
        invocation: HostV2MutationInvocation,
    ) -> KernelMutationReceipt:
        payload = dict(invocation.payload)
        protocol_ref = _pop_text(payload, "protocol_ref", required=False)
        expected = {"recipient_actor_id", "task_id", "revision_path_ref", "message"}
        if not set(payload).issubset(expected) or not {
            "recipient_actor_id",
            "task_id",
            "revision_path_ref",
        }.issubset(payload):
            raise _payload_error(
                invocation.route_id,
                "Handoff payload differs from its closed protocol contract",
            )
        return self.protocols.execute(
            ProtocolApplicationCommand(
                context=build_enzymedesign_command_context(invocation, ids=self.ids),
                operation=ProtocolCommandKind.HANDOFF,
                protocol_ref=protocol_ref or self.ids.new_id(namespace="protocol"),
                payload=payload,
            )
        )


def build_enzymedesign_operational_route_applications(
    application: EnzymeDesignKernelOperationalRouteApplication,
) -> dict[str, EnzymeDesignKernelOperationalRouteApplication]:
    return {route_id: application for route_id in STANDARD_OPERATIONAL_ROUTE_IDS}


def _operation_result(result: ToolResult) -> Mapping[str, JsonValue]:
    payload = result.payload
    if not isinstance(payload, Mapping):
        raise _payload_error(result.tool_name, "Workspace result has no operation proof")
    operation = payload.get("operation")
    if not isinstance(operation, Mapping):
        raise _payload_error(result.tool_name, "Workspace result has no operation proof")
    return operation


def _pop_text(
    payload: dict[str, JsonValue],
    field_name: str,
    *,
    required: bool = True,
) -> str | None:
    value = payload.pop(field_name, None)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise _payload_error(field_name, f"{field_name} must be one identifier")
    return value


def _pop_positive_integer(payload: dict[str, JsonValue], field_name: str) -> int:
    value = payload.pop(field_name, None)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _payload_error(field_name, f"{field_name} must be positive")
    return value


def _payload_error(route_id: str, message: str) -> HostV2CommandError:
    return HostV2CommandError(
        "enzymedesign_operational_route_payload_invalid",
        message,
        status_code=422,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={"route_id": route_id},
    )


__all__ = [
    "STANDARD_OPERATIONAL_ROUTE_IDS",
    "EnzymeDesignKernelOperationalRouteApplication",
    "EnzymeDesignRuntimeDrainApplication",
    "EnzymeDesignWorkspaceToolRuntime",
    "build_enzymedesign_operational_route_applications",
]
