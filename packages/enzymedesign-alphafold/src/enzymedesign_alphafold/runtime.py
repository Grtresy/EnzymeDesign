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

from .contracts import ALPHAFOLD_PLUGIN_ID
from .contracts import ALPHAFOLD_TOOL_NAME
from .contracts import ALPHAFOLD_VERSION_SPEC


_DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_ID = {"type": "string", "minLength": 1}
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
ALPHAFOLD_TOOL_SPEC = ToolSpec(
    tool_name=ALPHAFOLD_TOOL_NAME,
    description=(
        "Compile one formal AlphaFold 3 request from an immutable job JSON on an "
        "explicit qualified route. No model parameters or database paths are exposed."
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
            "inputs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": _REVISION_INPUT,
            },
        },
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "workload_id",
            "workload_digest",
            "state",
            "formal_compute_requested",
            "raw_shell",
            "fallback_performed",
            "task_finished",
        ],
        "properties": {
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

ALPHAFOLD_COMPUTE_REQUIREMENT = CapabilityRequirement(
    capability_id="openzyme.execution.revision-job",
    contract_spec="@1",
    operations=("observe", "submit"),
)
ALPHAFOLD_RESOURCE_REQUIREMENTS = (
    CapabilityRequirement(
        capability_id="software.alphafold3",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("predict",),
        version_spec=ALPHAFOLD_VERSION_SPEC,
        same_target_as="openzyme.execution.revision-job",
    ),
    CapabilityRequirement(
        capability_id="asset.alphafold3-model-parameters",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("read",),
        same_target_as="openzyme.execution.revision-job",
    ),
    CapabilityRequirement(
        capability_id="dataset.alphafold3-database",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("query",),
        same_target_as="openzyme.execution.revision-job",
    ),
    CapabilityRequirement(
        capability_id="accelerator.cuda",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("compute",),
        same_target_as="openzyme.execution.revision-job",
    ),
)
ALPHAFOLD_QUALIFICATION_SPEC = QualificationSpec(
    qualification_spec_id="enzymedesign.alphafold.qualification@1",
    owner_plugin_id=ALPHAFOLD_PLUGIN_ID,
    capability_id="software.alphafold3",
    contract_version="1",
    version_argv=("python", "run_alphafold.py", "--help"),
    smoke_argv=("python", "run_alphafold.py", "--help"),
    expected_result_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "operations", "exit_code"],
        "properties": {
            "version": _ID,
            "operations": {"type": "array", "items": {"const": "predict"}},
            "exit_code": {"const": 0},
        },
    },
    required_resource_capabilities=(
        "accelerator.cuda",
        "asset.alphafold3-model-parameters",
        "dataset.alphafold3-database",
    ),
)


class AlphaFoldToolApplication(Protocol):
    def request(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class AlphaFoldToolRuntime:
    application: AlphaFoldToolApplication
    contract: ToolSpec = ALPHAFOLD_TOOL_SPEC
    owner_plugin_id: str = ALPHAFOLD_PLUGIN_ID
    runtime_id: str = "enzymedesign.alphafold.predict-runtime@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if (
            invocation.tool_name != self.contract.tool_name
            or invocation.route_id is None
        ):
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary="AlphaFold requires its exact tool and explicit route identity.",
                payload={
                    "mutation_applied": False,
                    "fallback_performed": False,
                    "task_finished": False,
                },
                error_code="alphafold_route_or_tool_identity_invalid",
            )
        try:
            payload = dict(self.application.request(invocation=invocation))
        except (KeyError, TypeError, ValueError) as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary=str(exc),
                payload={
                    "mutation_applied": False,
                    "fallback_performed": False,
                    "task_finished": False,
                },
                error_code=getattr(exc, "error_code", "alphafold_request_invalid"),
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
            summary="AlphaFold accepted one explicit formal Compute request.",
            payload=payload,
        )


ALPHAFOLD_ROUTE_BINDINGS = (
    ("enzymedesign.alphafold.hpc-primary@1", "enzymedesign.alphafold.hpc"),
)


@dataclass(frozen=True, slots=True)
class AlphaFoldPluginRuntimeSurfaces:
    tools: tuple[AlphaFoldToolRuntime, ...]
    capability_routes: tuple[ExactProductCapabilityRouteRuntime, ...]


def build_alphafold_plugin_runtime_surfaces(
    *,
    application: AlphaFoldToolApplication,
    route_application: ProductCapabilityRouteApplication,
) -> AlphaFoldPluginRuntimeSurfaces:
    return AlphaFoldPluginRuntimeSurfaces(
        tools=(AlphaFoldToolRuntime(application),),
        capability_routes=tuple(
            ExactProductCapabilityRouteRuntime(
                route_id=route_id,
                owner_plugin_id=ALPHAFOLD_PLUGIN_ID,
                driver_id=driver_id,
                capability_ids=(
                    ALPHAFOLD_PLUGIN_ID,
                    "openzyme.execution.revision-job",
                    "software.alphafold3",
                ),
                application=route_application,
            )
            for route_id, driver_id in ALPHAFOLD_ROUTE_BINDINGS
        ),
    )


__all__ = [
    "ALPHAFOLD_COMPUTE_REQUIREMENT",
    "ALPHAFOLD_QUALIFICATION_SPEC",
    "ALPHAFOLD_ROUTE_BINDINGS",
    "ALPHAFOLD_RESOURCE_REQUIREMENTS",
    "ALPHAFOLD_TOOL_SPEC",
    "AlphaFoldToolApplication",
    "AlphaFoldPluginRuntimeSurfaces",
    "AlphaFoldToolRuntime",
    "build_alphafold_plugin_runtime_surfaces",
]
