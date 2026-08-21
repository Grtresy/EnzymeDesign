from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_execution_contracts import canonical_execution_wire_digest
from openzyme_extension_spi import CompiledDriverWorkload
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import DriverManifest

from .contracts import ALPHAFOLD_PLUGIN_ID
from .contracts import ALPHAFOLD_RESULT_CONTRACT
from .contracts import ALPHAFOLD_RESULT_SCHEMA_DIGEST
from .contracts import ALPHAFOLD_TOOL_NAME
from .contracts import ALPHAFOLD_VERSION_SPEC
from .contracts import ALPHAFOLD_WORKLOAD_CONTRACT
from .runtime import ALPHAFOLD_RESOURCE_REQUIREMENTS
from .runtime import ALPHAFOLD_TOOL_SPEC


ALPHAFOLD_DRIVER_REQUEST_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "enzymedesign.alphafold.driver-request@1",
        "fields": [
            "workload_id",
            "cwd",
            "resource_policy_digest",
            "environment_policy_digest",
            "inputs",
            "result_root",
        ],
        "input_order": ["job_json"],
        "forbidden": [
            "argv",
            "command",
            "credential",
            "database_path",
            "host_path",
            "model_parameters_path",
            "remote_path",
            "scheduler_job_id",
        ],
    }
)
ALPHAFOLD_WORKLOAD_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract_id": ALPHAFOLD_WORKLOAD_CONTRACT,
        "software_requirement": {
            "capability_id": "software.alphafold3",
            "version_spec": ALPHAFOLD_VERSION_SPEC,
            "operations": ["predict"],
        },
        "formal_only_through_compute": True,
    }
)
_PAYLOAD_FIELDS = {
    "workload_id",
    "cwd",
    "resource_policy_digest",
    "environment_policy_digest",
    "inputs",
    "result_root",
}


def _relative(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"AlphaFold {field} must be a string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"AlphaFold {field} must be normalized and root-relative")
    return value


@dataclass(frozen=True, slots=True)
class AlphaFoldHpcDriver:
    manifest: DriverManifest

    def compile(self, request: DriverInvocationRequest) -> CompiledDriverWorkload:
        if (
            request.driver_id != self.manifest.identity.component_id
            or request.owning_plugin_id != ALPHAFOLD_PLUGIN_ID
            or request.tool_name != ALPHAFOLD_TOOL_NAME
            or request.tool_contract_digest != ALPHAFOLD_TOOL_SPEC.contract_digest
            or request.request_contract_digest
            != ALPHAFOLD_DRIVER_REQUEST_CONTRACT_DIGEST
        ):
            raise ValueError("AlphaFold driver, tool or request contract drifted")
        if set(request.payload) != _PAYLOAD_FIELDS:
            raise ValueError("AlphaFold driver request fields are closed")
        inputs = request.payload["inputs"]
        if not isinstance(inputs, tuple) or len(inputs) != 1:
            raise ValueError("AlphaFold requires one immutable job JSON input")
        job_path = _relative(inputs[0].get("path"), field="job path")
        result_root = _relative(request.payload["result_root"], field="result_root")
        identity = {
            "schema_version": "execution_workload_spec@1",
            "workload_id": request.payload["workload_id"],
            "workload_contract": ALPHAFOLD_WORKLOAD_CONTRACT,
            "entry_point": ALPHAFOLD_WORKLOAD_CONTRACT,
            "argv": [
                "python",
                "run_alphafold.py",
                "--json_path",
                job_path,
                "--output_dir",
                result_root,
            ],
            "cwd": request.payload["cwd"],
            "resource_policy_digest": request.payload["resource_policy_digest"],
            "environment_policy_digest": request.payload["environment_policy_digest"],
            "inputs": [dict(inputs[0])],
            "result_contract": {
                "contract_id": ALPHAFOLD_RESULT_CONTRACT,
                "schema_digest": ALPHAFOLD_RESULT_SCHEMA_DIGEST,
                "result_root": result_root,
            },
            "capability_requirements": [
                {
                    "capability_id": requirement.capability_id,
                    "version_spec": requirement.version_spec or "@qualified",
                    "operations": list(requirement.operations),
                }
                for requirement in ALPHAFOLD_RESOURCE_REQUIREMENTS
            ],
        }
        workload = ExecutionWorkloadSpec.from_dict(
            {**identity, "workload_digest": canonical_execution_wire_digest(identity)}
        )
        return CompiledDriverWorkload(
            driver_id=request.driver_id,
            owning_plugin_id=request.owning_plugin_id,
            route_id=request.route_id,
            workload_contract_digest=self.manifest.workload_contract_digest,
            result_contract_digest=self.manifest.result_contract_digest,
            workload=workload.to_dict(),
        )

    def validate_result(
        self, workload: CompiledDriverWorkload, result: ToolResult
    ) -> ToolResult:
        if (
            workload.driver_id != self.manifest.identity.component_id
            or workload.owning_plugin_id != ALPHAFOLD_PLUGIN_ID
            or workload.workload_contract_digest != ALPHAFOLD_WORKLOAD_CONTRACT_DIGEST
            or workload.result_contract_digest != ALPHAFOLD_RESULT_SCHEMA_DIGEST
            or not isinstance(result.payload, Mapping)
            or result.payload.get("result_contract_digest")
            != ALPHAFOLD_RESULT_SCHEMA_DIGEST
            or result.payload.get("raw_shell") is not False
        ):
            raise ValueError("AlphaFold formal result contract drifted")
        return result


__all__ = [
    "ALPHAFOLD_DRIVER_REQUEST_CONTRACT_DIGEST",
    "ALPHAFOLD_WORKLOAD_CONTRACT_DIGEST",
    "AlphaFoldHpcDriver",
]
