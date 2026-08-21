from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from enzymedesign_core import ExactProductCapabilityRouteRuntime
from enzymedesign_core import ProductCapabilityRouteApplication
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import QualificationSpec
from openzyme_extension_spi import ToolDispatchBinding

from .contracts import VINA_DOCK_TOOL
from .contracts import VINA_PLUGIN_ID
from .contracts import VINA_VERSION_SPEC


_ID = {"type": "string", "minLength": 1}
_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_REVISION_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["revision_id", "commit", "tree", "path", "content_digest"],
    "properties": {
        "revision_id": _ID,
        "commit": {"type": "string", "pattern": "^[0-9a-f]{40}(?:[0-9a-f]{24})?$"},
        "tree": {"type": "string", "pattern": "^[0-9a-f]{40}(?:[0-9a-f]{24})?$"},
        "path": _ID,
        "content_digest": _DIGEST,
    },
}
VINA_TOOL_SPEC = ToolSpec(
    tool_name=VINA_DOCK_TOOL,
    description=(
        "Compile one formal AutoDock Vina docking request against an explicit qualified "
        "route. The Plugin does not probe, preprocess or dispatch the target."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "workload_id",
            "route_id",
            "affordance_snapshot_digest",
            "cwd",
            "resource_policy_digest",
            "environment_policy_digest",
            "result_root",
            "poses_path",
            "score_path",
            "inputs",
        ],
        "properties": {
            "workload_id": _ID,
            "route_id": _ID,
            "affordance_snapshot_digest": _DIGEST,
            "cwd": _ID,
            "resource_policy_digest": _DIGEST,
            "environment_policy_digest": _DIGEST,
            "result_root": _ID,
            "poses_path": _ID,
            "score_path": _ID,
            "inputs": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": _REVISION_INPUT,
            },
        },
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "execution_id",
            "operation_id",
            "workload_id",
            "workload_digest",
            "state",
            "formal_compute_requested",
            "raw_shell",
            "fallback_performed",
            "task_finished",
        ],
        "properties": {
            "execution_id": _ID,
            "operation_id": _ID,
            "workload_id": _ID,
            "workload_digest": _DIGEST,
            "state": _ID,
            "formal_compute_requested": {"const": True},
            "raw_shell": {"const": False},
            "fallback_performed": {"const": False},
            "task_finished": {"const": False},
        },
    },
    required_authorities=("external_compute",),
)
VINA_COMPUTE_REQUIREMENT = CapabilityRequirement(
    capability_id="openzyme.execution.revision-job",
    contract_spec="@1",
    operations=("observe", "submit"),
)
VINA_SOFTWARE_REQUIREMENT = CapabilityRequirement(
    capability_id="software.autodock-vina",
    contract_spec="@1",
    kind=CapabilityRequirementKind.RESOURCE,
    operations=("dock", "score"),
    version_spec=VINA_VERSION_SPEC,
    same_target_as="openzyme.execution.revision-job",
)
VINA_QUALIFICATION_SPEC = QualificationSpec(
    qualification_spec_id="enzymedesign.vina.qualification@1",
    owner_plugin_id=VINA_PLUGIN_ID,
    capability_id="software.autodock-vina",
    contract_version="1",
    version_argv=("vina", "--version"),
    smoke_argv=("vina", "--help"),
    expected_result_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "operations", "exit_code"],
        "properties": {
            "version": {"type": "string"},
            "operations": {
                "type": "array",
                "items": {"enum": ["dock", "score"]},
            },
            "exit_code": {"const": 0},
        },
    },
)


class VinaToolApplication(Protocol):
    def request(
        self,
        *,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
    ) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class VinaToolRuntime:
    application: VinaToolApplication
    contract: ToolSpec = VINA_TOOL_SPEC
    owner_plugin_id: str = VINA_PLUGIN_ID
    runtime_id: str = "enzymedesign.vina.dock-runtime@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name or invocation.route_id is None:
            return self._rejected(
                invocation,
                "vina_route_or_tool_identity_invalid",
                "Vina requires its exact tool and explicit route identity.",
            )
        return self._rejected(
            invocation,
            "vina_dispatch_binding_missing",
            "Formal Vina invocation requires the Kernel-admitted route proof.",
        )

    def invoke_admitted(
        self,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
    ) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name or invocation.route_id is None:
            return self._rejected(
                invocation,
                "vina_route_or_tool_identity_invalid",
                "Vina requires its exact tool and explicit route identity.",
            )
        if (
            dispatch.tool_name != invocation.tool_name
            or dispatch.tool_contract_digest != self.contract.contract_digest
            or dispatch.route_id != invocation.route_id
            or dispatch.affordance_snapshot_digest
            != invocation.affordance_snapshot_digest
            or dispatch.driver_id is None
        ):
            return self._rejected(
                invocation,
                "vina_dispatch_binding_stale",
                "Vina dispatch facts differ from the exact admitted route.",
            )
        try:
            payload = dict(
                self.application.request(invocation=invocation, dispatch=dispatch)
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary=str(exc),
                payload={"mutation_applied": False, "fallback_performed": False, "task_finished": False},
                error_code=getattr(exc, "error_code", "vina_request_invalid"),
            )
        payload.update(
            {
                "formal_compute_requested": True,
                "raw_shell": False,
                "fallback_performed": False,
                "task_finished": False,
            }
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="accepted",
            summary="Vina accepted one explicit formal Compute request.",
            payload=payload,
        )

    @staticmethod
    def _rejected(
        invocation: ToolInvocation,
        error_code: str,
        summary: str,
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "mutation_applied": False,
                "fallback_performed": False,
                "task_finished": False,
            },
            error_code=error_code,
        )


VINA_ROUTE_BINDINGS = (
    ("enzymedesign.vina.hpc-primary@1", "enzymedesign.vina.hpc"),
    ("enzymedesign.vina.local@1", "enzymedesign.vina.local"),
)


@dataclass(frozen=True, slots=True)
class VinaPluginRuntimeSurfaces:
    tools: tuple[VinaToolRuntime, ...]
    capability_routes: tuple[ExactProductCapabilityRouteRuntime, ...]


def build_vina_plugin_runtime_surfaces(
    *,
    application: VinaToolApplication,
    route_application: ProductCapabilityRouteApplication,
) -> VinaPluginRuntimeSurfaces:
    return VinaPluginRuntimeSurfaces(
        tools=(VinaToolRuntime(application),),
        capability_routes=tuple(
            ExactProductCapabilityRouteRuntime(
                route_id=route_id,
                owner_plugin_id=VINA_PLUGIN_ID,
                driver_id=driver_id,
                capability_ids=(
                    VINA_PLUGIN_ID,
                    "openzyme.execution.revision-job",
                    "software.autodock-vina",
                ),
                application=route_application,
            )
            for route_id, driver_id in VINA_ROUTE_BINDINGS
        ),
    )


__all__ = [
    "VINA_COMPUTE_REQUIREMENT",
    "VINA_QUALIFICATION_SPEC",
    "VINA_ROUTE_BINDINGS",
    "VINA_SOFTWARE_REQUIREMENT",
    "VINA_TOOL_SPEC",
    "VinaToolApplication",
    "VinaPluginRuntimeSurfaces",
    "VinaToolRuntime",
    "build_vina_plugin_runtime_surfaces",
]
