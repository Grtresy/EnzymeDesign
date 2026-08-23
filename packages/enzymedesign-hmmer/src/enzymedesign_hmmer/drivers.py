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

from .contracts import HMMER_BUILD_TOOL
from .contracts import HMMER_PLUGIN_ID
from .contracts import HMMER_RESULT_CONTRACT
from .contracts import HMMER_RESULT_SCHEMA_DIGEST
from .contracts import HMMER_SEARCH_TOOL
from .contracts import HMMER_VERSION_SPEC
from .contracts import HmmerOperation
from .runtime import HMMER_TOOL_SPECS


HMMER_DRIVER_REQUEST_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "enzymedesign.hmmer.driver-request@1",
        "fields": [
            "operation",
            "workload_id",
            "cwd",
            "resource_policy_digest",
            "environment_policy_digest",
            "inputs",
            "result_root",
            "output_path",
        ],
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
HMMER_WORKLOAD_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "enzymedesign.hmmer.workload-family@1",
        "contracts": [
            "enzymedesign.hmmer.build@1",
            "enzymedesign.hmmer.search@1",
        ],
        "software_requirement": {
            "capability_id": "software.hmmer",
            "version_spec": HMMER_VERSION_SPEC,
            "operations": ["hmmbuild", "hmmsearch"],
        },
    }
)

_PAYLOAD_FIELDS = {
    "operation",
    "workload_id",
    "cwd",
    "resource_policy_digest",
    "environment_policy_digest",
    "inputs",
    "result_root",
    "output_path",
}


def _tool_spec(operation: HmmerOperation):
    name = HMMER_BUILD_TOOL if operation is HmmerOperation.BUILD else HMMER_SEARCH_TOOL
    return next(spec for spec in HMMER_TOOL_SPECS if spec.tool_name == name)


def _relative_output(*, result_root: object, output_path: object) -> tuple[str, str]:
    if not isinstance(result_root, str) or not isinstance(output_path, str):
        raise ValueError("HMMER result_root and output_path must be strings")
    root = PurePosixPath(result_root)
    output = PurePosixPath(output_path)
    if (
        root.is_absolute()
        or output.is_absolute()
        or ".." in root.parts
        or ".." in output.parts
        or root.as_posix() != result_root
        or output.as_posix() != output_path
        or output == root
        or root not in output.parents
    ):
        raise ValueError("HMMER output must be a normalized child of result_root")
    return result_root, output_path


@dataclass(frozen=True, slots=True)
class HmmerDriver:
    """Compile one HMMER request; dispatch remains exclusively Compute-owned."""

    manifest: DriverManifest

    def compile(self, request: DriverInvocationRequest) -> CompiledDriverWorkload:
        if (
            request.driver_id != self.manifest.identity.component_id
            or request.owning_plugin_id != HMMER_PLUGIN_ID
            or request.request_contract_digest != HMMER_DRIVER_REQUEST_CONTRACT_DIGEST
            or request.route_id == ""
        ):
            raise ValueError("HMMER driver identity or request contract drifted")
        try:
            operation = HmmerOperation(request.payload["operation"])
        except (KeyError, ValueError) as exc:
            raise ValueError("HMMER operation is unsupported") from exc
        spec = _tool_spec(operation)
        if request.tool_name != spec.tool_name or request.tool_contract_digest != spec.contract_digest:
            raise ValueError("HMMER tool contract drifted")
        if set(request.payload) != _PAYLOAD_FIELDS:
            raise ValueError("HMMER driver request fields are closed")
        inputs = request.payload["inputs"]
        expected_inputs = 1 if operation is HmmerOperation.BUILD else 2
        if not isinstance(inputs, tuple) or len(inputs) != expected_inputs:
            raise ValueError("HMMER request has the wrong immutable input cardinality")
        result_root, output_path = _relative_output(
            result_root=request.payload["result_root"],
            output_path=request.payload["output_path"],
        )
        input_paths = [item.get("path") if hasattr(item, "get") else None for item in inputs]
        if any(not isinstance(path, str) for path in input_paths):
            raise ValueError("HMMER input paths are invalid")
        if operation is HmmerOperation.BUILD:
            argv = ["hmmbuild", output_path, input_paths[0]]
        else:
            argv = [
                "hmmsearch",
                "--noali",
                "--tblout",
                output_path,
                input_paths[0],
                input_paths[1],
            ]
        identity = {
            "schema_version": "execution_workload_spec@1",
            "workload_id": request.payload["workload_id"],
            "workload_contract": operation.workload_contract,
            "entry_point": operation.workload_contract,
            "argv": argv,
            "cwd": request.payload["cwd"],
            "resource_policy_digest": request.payload["resource_policy_digest"],
            "environment_policy_digest": request.payload["environment_policy_digest"],
            "inputs": [dict(item) for item in inputs],
            "result_contract": {
                "contract_id": HMMER_RESULT_CONTRACT,
                "schema_digest": HMMER_RESULT_SCHEMA_DIGEST,
                "result_root": result_root,
            },
            "capability_requirements": [
                {
                    "capability_id": "software.hmmer",
                    "version_spec": HMMER_VERSION_SPEC,
                    "operations": [operation.executable],
                }
            ],
        }
        workload = ExecutionWorkloadSpec.from_dict(
            {
                **identity,
                "workload_digest": canonical_execution_wire_digest(identity),
            }
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
        self,
        workload: CompiledDriverWorkload,
        result: ToolResult,
    ) -> ToolResult:
        if (
            workload.driver_id != self.manifest.identity.component_id
            or workload.owning_plugin_id != HMMER_PLUGIN_ID
            or workload.workload_contract_digest != HMMER_WORKLOAD_CONTRACT_DIGEST
            or workload.result_contract_digest != HMMER_RESULT_SCHEMA_DIGEST
            or not isinstance(result.payload, Mapping)
            or result.payload.get("result_contract_digest") != HMMER_RESULT_SCHEMA_DIGEST
            or result.payload.get("raw_shell") is not False
        ):
            raise ValueError("HMMER formal result contract drifted")
        return result


__all__ = [
    "HMMER_DRIVER_REQUEST_CONTRACT_DIGEST",
    "HMMER_WORKLOAD_CONTRACT_DIGEST",
    "HmmerDriver",
]
