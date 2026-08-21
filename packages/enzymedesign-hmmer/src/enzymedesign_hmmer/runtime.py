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

from .contracts import HMMER_BUILD_TOOL
from .contracts import HMMER_PLUGIN_ID
from .contracts import HMMER_SEARCH_TOOL
from .contracts import HMMER_VERSION_SPEC


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
_OUTPUT = {
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
}


def _input_schema(*, search: bool) -> dict[str, JsonValue]:
    properties: dict[str, JsonValue] = {
        "workload_id": _ID,
        "route_id": _ID,
        "affordance_snapshot_digest": _DIGEST,
        "cwd": _ID,
        "resource_policy_digest": _DIGEST,
        "environment_policy_digest": _DIGEST,
        "result_root": _ID,
        "output_path": _ID,
        "inputs": {
            "type": "array",
            "minItems": 2 if search else 1,
            "maxItems": 2 if search else 1,
            "items": _REVISION_INPUT,
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


HMMER_TOOL_SPECS = (
    ToolSpec(
        tool_name=HMMER_BUILD_TOOL,
        description=(
            "Compile one formal hmmbuild request against an explicit qualified route. "
            "The Plugin never probes or dispatches the target itself."
        ),
        input_schema=_input_schema(search=False),
        output_schema=_OUTPUT,
        required_authorities=("external_compute",),
    ),
    ToolSpec(
        tool_name=HMMER_SEARCH_TOOL,
        description=(
            "Compile one formal hmmsearch request against an explicit qualified route. "
            "The Plugin never probes or dispatches the target itself."
        ),
        input_schema=_input_schema(search=True),
        output_schema=_OUTPUT,
        required_authorities=("external_compute",),
    ),
)

HMMER_COMPUTE_REQUIREMENT = CapabilityRequirement(
    capability_id="openzyme.execution.revision-job",
    contract_spec="@1",
    operations=("observe", "submit"),
)
HMMER_SOFTWARE_REQUIREMENT = CapabilityRequirement(
    capability_id="software.hmmer",
    contract_spec="@1",
    kind=CapabilityRequirementKind.RESOURCE,
    operations=("hmmbuild", "hmmsearch"),
    version_spec=HMMER_VERSION_SPEC,
    same_target_as="openzyme.execution.revision-job",
)
HMMER_QUALIFICATION_SPEC = QualificationSpec(
    qualification_spec_id="enzymedesign.hmmer.qualification@1",
    owner_plugin_id=HMMER_PLUGIN_ID,
    capability_id="software.hmmer",
    contract_version="1",
    version_argv=("hmmsearch", "-h"),
    smoke_argv=("hmmbuild", "-h"),
    expected_result_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "operations", "exit_code"],
        "properties": {
            "version": {"type": "string"},
            "operations": {
                "type": "array",
                "items": {"enum": ["hmmbuild", "hmmsearch", "hmmpress"]},
            },
            "exit_code": {"const": 0},
        },
    },
)


class HmmerToolApplication(Protocol):
    def request(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class HmmerToolRuntime:
    contract: ToolSpec
    application: HmmerToolApplication
    owner_plugin_id: str = HMMER_PLUGIN_ID

    @property
    def runtime_id(self) -> str:
        suffix = "build" if self.contract.tool_name == HMMER_BUILD_TOOL else "search"
        return f"enzymedesign.hmmer.{suffix}-runtime@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name or invocation.route_id is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary="HMMER requires its exact tool and explicit route identity.",
                payload={
                    "mutation_applied": False,
                    "fallback_performed": False,
                    "task_finished": False,
                },
                error_code="hmmer_route_or_tool_identity_invalid",
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
                error_code=getattr(exc, "error_code", "hmmer_request_invalid"),
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
            summary="HMMER accepted one explicit formal Compute request.",
            payload=payload,
        )


@dataclass(frozen=True, slots=True)
class HmmerPluginRuntimeSurfaces:
    tools: tuple[HmmerToolRuntime, ...]


def build_hmmer_plugin_runtime_surfaces(
    *, application: HmmerToolApplication
) -> HmmerPluginRuntimeSurfaces:
    return HmmerPluginRuntimeSurfaces(
        tools=tuple(HmmerToolRuntime(spec, application) for spec in HMMER_TOOL_SPECS)
    )


__all__ = [
    "HMMER_COMPUTE_REQUIREMENT",
    "HMMER_QUALIFICATION_SPEC",
    "HMMER_SOFTWARE_REQUIREMENT",
    "HMMER_TOOL_SPECS",
    "HmmerToolApplication",
    "HmmerPluginRuntimeSurfaces",
    "HmmerToolRuntime",
    "build_hmmer_plugin_runtime_surfaces",
]
