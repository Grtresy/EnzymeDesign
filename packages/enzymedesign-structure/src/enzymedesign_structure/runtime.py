from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import QualificationSpec

from .contracts import FPOCKET_TOOL_NAME
from .contracts import FPOCKET_VERSION_SPEC
from .contracts import STRUCTURE_PLUGIN_ID


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
FPOCKET_TOOL_SPEC = ToolSpec(
    tool_name=FPOCKET_TOOL_NAME,
    description=(
        "Compile one formal fpocket request against an explicit qualified route. "
        "The Plugin never probes or dispatches the target itself."
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

FPOCKET_COMPUTE_REQUIREMENT = CapabilityRequirement(
    capability_id="openzyme.execution.revision-job",
    contract_spec="@1",
    operations=("observe", "submit"),
)
FPOCKET_SOFTWARE_REQUIREMENT = CapabilityRequirement(
    capability_id="software.fpocket",
    contract_spec="@1",
    kind=CapabilityRequirementKind.RESOURCE,
    operations=("detect",),
    version_spec=FPOCKET_VERSION_SPEC,
    same_target_as="openzyme.execution.revision-job",
)
FPOCKET_QUALIFICATION_SPEC = QualificationSpec(
    qualification_spec_id="enzymedesign.fpocket.qualification@1",
    owner_plugin_id=STRUCTURE_PLUGIN_ID,
    capability_id="software.fpocket",
    contract_version="1",
    version_argv=("fpocket", "--version"),
    smoke_argv=("fpocket", "--help"),
    expected_result_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "operations", "exit_code"],
        "properties": {
            "version": _ID,
            "operations": {"type": "array", "items": {"const": "detect"}},
            "exit_code": {"const": 0},
        },
    },
)


class FpocketToolApplication(Protocol):
    def request(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class FpocketToolRuntime:
    application: FpocketToolApplication
    contract: ToolSpec = FPOCKET_TOOL_SPEC
    owner_plugin_id: str = STRUCTURE_PLUGIN_ID
    runtime_id: str = "enzymedesign.fpocket.detect-runtime@1"

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
                summary="fpocket requires its exact tool and explicit route identity.",
                payload={
                    "mutation_applied": False,
                    "fallback_performed": False,
                    "task_finished": False,
                },
                error_code="fpocket_route_or_tool_identity_invalid",
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
                error_code=getattr(exc, "error_code", "fpocket_request_invalid"),
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
            summary="fpocket accepted one explicit formal Compute request.",
            payload=payload,
        )


__all__ = [
    "FPOCKET_COMPUTE_REQUIREMENT",
    "FPOCKET_QUALIFICATION_SPEC",
    "FPOCKET_SOFTWARE_REQUIREMENT",
    "FPOCKET_TOOL_SPEC",
    "FpocketToolApplication",
    "FpocketToolRuntime",
]
