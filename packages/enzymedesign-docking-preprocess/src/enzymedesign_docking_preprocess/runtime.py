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


PREPROCESS_PLUGIN_ID = "enzymedesign.docking.preprocess"
PREPROCESS_TOOL_NAME = "enzymedesign.docking.preprocess"
_ID = {"type": "string", "minLength": 1}

PREPROCESS_TOOL_SPEC = ToolSpec(
    tool_name=PREPROCESS_TOOL_NAME,
    description=(
        "Run one declared docking preprocessing operation inside the current "
        "workspace. Paths are workspace-root-relative; no Host path is accepted."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["operation", "output_path", "idempotency_key"],
        "properties": {
            "operation": {
                "enum": [
                    "convert_format",
                    "prepare_receptor",
                    "prepare_ligand",
                    "smiles_to_3d",
                ]
            },
            "input_path": _ID,
            "output_path": _ID,
            "input_format": {"type": ["string", "null"]},
            "smiles": {"type": ["string", "null"], "maxLength": 4096},
            "idempotency_key": _ID,
        },
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "state",
            "output_path",
            "output_digest",
            "fallback_performed",
            "task_finished",
        ],
        "properties": {
            "state": {"const": "completed"},
            "output_path": _ID,
            "output_digest": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "fallback_performed": {"const": False},
            "task_finished": {"const": False},
        },
    },
    required_authorities=(
        "workspace.fs.read",
        "workspace.fs.write",
        "workspace.process.exec",
    ),
)

PREPROCESS_RESOURCE_REQUIREMENTS = (
    CapabilityRequirement(
        capability_id="software.rdkit",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("smiles_to_3d",),
        version_spec=">=2024.9.1",
    ),
    CapabilityRequirement(
        capability_id="software.meeko",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("prepare_ligand",),
        version_spec=">=0.6.1",
    ),
    CapabilityRequirement(
        capability_id="software.openbabel",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("convert_format", "prepare_ligand", "prepare_receptor"),
        version_spec=">=3.1.1,<4",
    ),
)

def _qualification_output(*operations: str) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "operations", "exit_code"],
        "properties": {
            "version": _ID,
            "operations": {
                "type": "array",
                "items": {"enum": list(operations)},
            },
            "exit_code": {"const": 0},
        },
    }


PREPROCESS_QUALIFICATION_SPECS = (
    QualificationSpec(
        qualification_spec_id="enzymedesign.docking.preprocess.rdkit@1",
        owner_plugin_id=PREPROCESS_PLUGIN_ID,
        capability_id="software.rdkit",
        contract_version="1",
        version_argv=("python", "-c", "import rdkit; print(rdkit.__version__)"),
        smoke_argv=(
            "python",
            "-c",
            "from rdkit import Chem; assert Chem.MolFromSmiles('CC')",
        ),
        expected_result_schema=_qualification_output("smiles_to_3d"),
    ),
    QualificationSpec(
        qualification_spec_id="enzymedesign.docking.preprocess.meeko@1",
        owner_plugin_id=PREPROCESS_PLUGIN_ID,
        capability_id="software.meeko",
        contract_version="1",
        version_argv=("python", "-c", "import meeko; print(meeko.__version__)"),
        smoke_argv=("python", "-c", "import meeko"),
        expected_result_schema=_qualification_output("prepare_ligand"),
    ),
    QualificationSpec(
        qualification_spec_id="enzymedesign.docking.preprocess.openbabel@1",
        owner_plugin_id=PREPROCESS_PLUGIN_ID,
        capability_id="software.openbabel",
        contract_version="1",
        version_argv=("obabel", "-V"),
        smoke_argv=("obabel", "-L", "formats"),
        expected_result_schema=_qualification_output(
            "convert_format",
            "prepare_ligand",
            "prepare_receptor",
        ),
    ),
)


class PreprocessToolApplication(Protocol):
    def request(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class PreprocessToolRuntime:
    application: PreprocessToolApplication
    contract: ToolSpec = PREPROCESS_TOOL_SPEC
    owner_plugin_id: str = PREPROCESS_PLUGIN_ID
    runtime_id: str = "enzymedesign.docking.preprocess.runtime@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary="Preprocess tool identity does not match the exact contract.",
                payload={
                    "mutation_applied": False,
                    "fallback_performed": False,
                    "task_finished": False,
                },
                error_code="preprocess_tool_identity_invalid",
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
                error_code=getattr(exc, "error_code", "preprocess_request_invalid"),
            )
        payload.update({"fallback_performed": False, "task_finished": False})
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="completed",
            summary="Docking preprocessing completed without fallback.",
            payload=payload,
        )


@dataclass(frozen=True, slots=True)
class PreprocessPluginRuntimeSurfaces:
    tools: tuple[PreprocessToolRuntime, ...]


def build_preprocess_plugin_runtime_surfaces(
    *, application: PreprocessToolApplication
) -> PreprocessPluginRuntimeSurfaces:
    return PreprocessPluginRuntimeSurfaces(tools=(PreprocessToolRuntime(application),))


__all__ = [
    "PREPROCESS_PLUGIN_ID",
    "PREPROCESS_QUALIFICATION_SPECS",
    "PREPROCESS_RESOURCE_REQUIREMENTS",
    "PREPROCESS_TOOL_NAME",
    "PREPROCESS_TOOL_SPEC",
    "PreprocessPluginRuntimeSurfaces",
    "PreprocessToolApplication",
    "PreprocessToolRuntime",
    "build_preprocess_plugin_runtime_surfaces",
]
