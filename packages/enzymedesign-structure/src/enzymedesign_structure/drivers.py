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

from .contracts import FPOCKET_RESULT_CONTRACT
from .contracts import FPOCKET_RESULT_SCHEMA_DIGEST
from .contracts import FPOCKET_TOOL_NAME
from .contracts import FPOCKET_VERSION_SPEC
from .contracts import FPOCKET_WORKLOAD_CONTRACT
from .contracts import STRUCTURE_PLUGIN_ID
from .runtime import FPOCKET_TOOL_SPEC


FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "enzymedesign.fpocket.driver-request@1",
        "fields": [
            "workload_id",
            "cwd",
            "resource_policy_digest",
            "environment_policy_digest",
            "inputs",
            "result_root",
        ],
        "input_order": ["structure_pdb"],
        "forbidden": [
            "argv",
            "command",
            "credential",
            "host_path",
            "remote_path",
            "scheduler_job_id",
        ],
    }
)
FPOCKET_WORKLOAD_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract_id": FPOCKET_WORKLOAD_CONTRACT,
        "software_requirement": {
            "capability_id": "software.fpocket",
            "version_spec": FPOCKET_VERSION_SPEC,
            "operations": ["detect"],
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


def _relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"fpocket {field} must be a string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or value in {"", "."}
    ):
        raise ValueError(f"fpocket {field} must be normalized and root-relative")
    return value


@dataclass(frozen=True, slots=True)
class FpocketDriver:
    """Compile one fpocket workload without target access or dispatch authority."""

    manifest: DriverManifest

    def compile(self, request: DriverInvocationRequest) -> CompiledDriverWorkload:
        if (
            request.driver_id != self.manifest.identity.component_id
            or request.owning_plugin_id != STRUCTURE_PLUGIN_ID
            or request.tool_name != FPOCKET_TOOL_NAME
            or request.tool_contract_digest != FPOCKET_TOOL_SPEC.contract_digest
            or request.request_contract_digest != FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST
        ):
            raise ValueError("fpocket driver, tool or request contract drifted")
        if set(request.payload) != _PAYLOAD_FIELDS:
            raise ValueError("fpocket driver request fields are closed")
        inputs = request.payload["inputs"]
        if not isinstance(inputs, tuple) or len(inputs) != 1:
            raise ValueError("fpocket requires exactly one immutable structure input")
        input_path = inputs[0].get("path") if hasattr(inputs[0], "get") else None
        structure_path = _relative_path(input_path, field="structure path")
        result_root = _relative_path(
            request.payload["result_root"], field="result_root"
        )
        identity = {
            "schema_version": "execution_workload_spec@1",
            "workload_id": request.payload["workload_id"],
            "workload_contract": FPOCKET_WORKLOAD_CONTRACT,
            "entry_point": FPOCKET_WORKLOAD_CONTRACT,
            "argv": ["fpocket", "-f", structure_path],
            "cwd": request.payload["cwd"],
            "resource_policy_digest": request.payload["resource_policy_digest"],
            "environment_policy_digest": request.payload["environment_policy_digest"],
            "inputs": [dict(inputs[0])],
            "result_contract": {
                "contract_id": FPOCKET_RESULT_CONTRACT,
                "schema_digest": FPOCKET_RESULT_SCHEMA_DIGEST,
                "result_root": result_root,
            },
            "capability_requirements": [
                {
                    "capability_id": "software.fpocket",
                    "version_spec": FPOCKET_VERSION_SPEC,
                    "operations": ["detect"],
                }
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
            or workload.owning_plugin_id != STRUCTURE_PLUGIN_ID
            or workload.workload_contract_digest != FPOCKET_WORKLOAD_CONTRACT_DIGEST
            or workload.result_contract_digest != FPOCKET_RESULT_SCHEMA_DIGEST
            or not isinstance(result.payload, Mapping)
            or result.payload.get("result_contract_digest")
            != FPOCKET_RESULT_SCHEMA_DIGEST
            or result.payload.get("raw_shell") is not False
        ):
            raise ValueError("fpocket formal result contract drifted")
        return result


__all__ = [
    "FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST",
    "FPOCKET_WORKLOAD_CONTRACT_DIGEST",
    "FpocketDriver",
]
