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

from .contracts import VINA_DOCK_TOOL
from .contracts import VINA_PLUGIN_ID
from .contracts import VINA_LEGACY_RESULT_CONTRACT
from .contracts import VINA_LEGACY_RESULT_SCHEMA_DIGEST
from .contracts import VINA_LEGACY_VERSION_SPEC
from .contracts import VINA_LEGACY_WORKLOAD_CONTRACT
from .contracts import VINA_MODERN_RESULT_CONTRACT
from .contracts import VINA_MODERN_RESULT_SCHEMA_DIGEST
from .contracts import VINA_MODERN_VERSION_SPEC
from .contracts import VINA_MODERN_WORKLOAD_CONTRACT
from .runtime import VINA_TOOL_SPEC


VINA_DRIVER_REQUEST_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "enzymedesign.vina.driver-request@2",
        "fields": [
            "workload_id",
            "cwd",
            "resource_policy_digest",
            "environment_policy_digest",
            "inputs",
            "result_root",
            "poses_path",
            "score_path",
        ],
        "input_order": ["receptor_pdbqt", "ligand_pdbqt", "vina_config"],
        "exact_route_profile_required": True,
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
VINA_LEGACY_WORKLOAD_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract_id": VINA_LEGACY_WORKLOAD_CONTRACT,
        "profile": "legacy-log-v1",
        "software_requirement": {
            "capability_id": "software.autodock-vina",
            "version_spec": VINA_LEGACY_VERSION_SPEC,
            "operations": ["dock", "score"],
        },
        "argv_semantics": "vina-with-log-v1",
        "score_semantics": "legacy-log-file-v1",
        "formal_only_through_compute": True,
    }
)
VINA_MODERN_WORKLOAD_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract_id": VINA_MODERN_WORKLOAD_CONTRACT,
        "profile": "modern-poses-remark-v1",
        "software_requirement": {
            "capability_id": "software.autodock-vina",
            "version_spec": VINA_MODERN_VERSION_SPEC,
            "operations": ["dock", "score"],
        },
        "argv_semantics": "vina-with-poses-remark-extractor-v1",
        "score_semantics": "poses-remark-derived-file-v1",
        "formal_only_through_compute": True,
    }
)
_MODERN_SCORE_EXTRACTOR = (
    "import pathlib,subprocess,sys;"
    "receptor,ligand,config,poses,score=sys.argv[1:];"
    "completed=subprocess.run(['vina','--receptor',receptor,'--ligand',ligand,"
    "'--config',config,'--out',poses],check=False);"
    "completed.returncode==0 or sys.exit(completed.returncode);"
    "lines=[line for line in pathlib.Path(poses).read_text(encoding='utf-8').splitlines() "
    "if line.startswith('REMARK VINA RESULT:')];"
    "lines or sys.exit(65);"
    "pathlib.Path(score).write_text('score_semantics=poses-remark-derived-file-v1\\n'"
    "+'\\n'.join(lines)+'\\n',encoding='utf-8')"
)
_ROUTE_PROFILES = {
    "enzymedesign.vina.hpc": {
        "route_id": "enzymedesign.vina.hpc-primary@1",
        "version_spec": VINA_LEGACY_VERSION_SPEC,
        "workload_contract": VINA_LEGACY_WORKLOAD_CONTRACT,
        "workload_digest": VINA_LEGACY_WORKLOAD_CONTRACT_DIGEST,
        "result_contract": VINA_LEGACY_RESULT_CONTRACT,
        "result_digest": VINA_LEGACY_RESULT_SCHEMA_DIGEST,
        "result_profile": "legacy-log-v1",
        "score_semantics": "legacy-log-file-v1",
    },
    "enzymedesign.vina.local": {
        "route_id": "enzymedesign.vina.local@1",
        "version_spec": VINA_MODERN_VERSION_SPEC,
        "workload_contract": VINA_MODERN_WORKLOAD_CONTRACT,
        "workload_digest": VINA_MODERN_WORKLOAD_CONTRACT_DIGEST,
        "result_contract": VINA_MODERN_RESULT_CONTRACT,
        "result_digest": VINA_MODERN_RESULT_SCHEMA_DIGEST,
        "result_profile": "modern-poses-remark-v1",
        "score_semantics": "poses-remark-derived-file-v1",
    },
}
_PAYLOAD_FIELDS = {
    "workload_id",
    "cwd",
    "resource_policy_digest",
    "environment_policy_digest",
    "inputs",
    "result_root",
    "poses_path",
    "score_path",
}


def _child_path(root_value: object, path_value: object, *, field: str) -> tuple[str, str]:
    if not isinstance(root_value, str) or not isinstance(path_value, str):
        raise ValueError(f"Vina {field} and result_root must be strings")
    root = PurePosixPath(root_value)
    path = PurePosixPath(path_value)
    if (
        root.is_absolute()
        or path.is_absolute()
        or ".." in root.parts
        or ".." in path.parts
        or root.as_posix() != root_value
        or path.as_posix() != path_value
        or path == root
        or root not in path.parents
    ):
        raise ValueError(f"Vina {field} must be a normalized child of result_root")
    return root_value, path_value


@dataclass(frozen=True, slots=True)
class VinaDriver:
    """Compile one Vina request; Compute alone owns external dispatch."""

    manifest: DriverManifest

    def compile(self, request: DriverInvocationRequest) -> CompiledDriverWorkload:
        profile = _ROUTE_PROFILES.get(self.manifest.identity.component_id)
        if (
            profile is None
            or request.driver_id != self.manifest.identity.component_id
            or request.owning_plugin_id != VINA_PLUGIN_ID
            or request.tool_name != VINA_DOCK_TOOL
            or request.tool_contract_digest != VINA_TOOL_SPEC.contract_digest
            or request.request_contract_digest != VINA_DRIVER_REQUEST_CONTRACT_DIGEST
            or request.route_id != profile["route_id"]
            or self.manifest.workload_contract_digest != profile["workload_digest"]
            or self.manifest.result_contract_digest != profile["result_digest"]
        ):
            raise ValueError("Vina driver, tool or request contract drifted")
        if set(request.payload) != _PAYLOAD_FIELDS:
            raise ValueError("Vina driver request fields are closed")
        inputs = request.payload["inputs"]
        if not isinstance(inputs, tuple) or len(inputs) != 3:
            raise ValueError("Vina requires exact receptor, ligand and config revision inputs")
        input_paths = [item.get("path") if hasattr(item, "get") else None for item in inputs]
        if any(not isinstance(path, str) for path in input_paths):
            raise ValueError("Vina input paths are invalid")
        result_root, poses_path = _child_path(
            request.payload["result_root"], request.payload["poses_path"], field="poses_path"
        )
        _, score_path = _child_path(
            request.payload["result_root"], request.payload["score_path"], field="score_path"
        )
        base_argv = [
            "vina",
            "--receptor",
            input_paths[0],
            "--ligand",
            input_paths[1],
            "--config",
            input_paths[2],
            "--out",
            poses_path,
        ]
        argv = (
            [*base_argv, "--log", score_path]
            if profile["result_profile"] == "legacy-log-v1"
            else [
                "python",
                "-c",
                _MODERN_SCORE_EXTRACTOR,
                input_paths[0],
                input_paths[1],
                input_paths[2],
                poses_path,
                score_path,
            ]
        )
        identity = {
            "schema_version": "execution_workload_spec@1",
            "workload_id": request.payload["workload_id"],
            "workload_contract": profile["workload_contract"],
            "entry_point": profile["workload_contract"],
            "argv": argv,
            "cwd": request.payload["cwd"],
            "resource_policy_digest": request.payload["resource_policy_digest"],
            "environment_policy_digest": request.payload["environment_policy_digest"],
            "inputs": [dict(item) for item in inputs],
            "result_contract": {
                "contract_id": profile["result_contract"],
                "schema_digest": profile["result_digest"],
                "result_root": result_root,
            },
            "capability_requirements": [
                {
                    "capability_id": "software.autodock-vina",
                    "version_spec": profile["version_spec"],
                    "operations": ["dock", "score"],
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
        profile = _ROUTE_PROFILES.get(self.manifest.identity.component_id)
        if (
            profile is None
            or workload.driver_id != self.manifest.identity.component_id
            or workload.owning_plugin_id != VINA_PLUGIN_ID
            or workload.route_id != profile["route_id"]
            or workload.workload_contract_digest != profile["workload_digest"]
            or workload.result_contract_digest != profile["result_digest"]
            or not isinstance(result.payload, Mapping)
            or result.payload.get("result_contract_digest") != profile["result_digest"]
            or result.payload.get("vina_result_profile")
            != profile["result_profile"]
            or result.payload.get("score_semantics") != profile["score_semantics"]
            or result.payload.get("raw_shell") is not False
        ):
            raise ValueError("Vina formal result contract drifted")
        return result


__all__ = [
    "VINA_DRIVER_REQUEST_CONTRACT_DIGEST",
    "VINA_LEGACY_WORKLOAD_CONTRACT_DIGEST",
    "VINA_MODERN_WORKLOAD_CONTRACT_DIGEST",
    "VinaDriver",
]
