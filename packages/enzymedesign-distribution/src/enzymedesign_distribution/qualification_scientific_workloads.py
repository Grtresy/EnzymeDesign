from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
import base64
from dataclasses import dataclass
from dataclasses import field
import gzip
from importlib.resources import files
from typing import Any

from enzymedesign_hmmer import HMMER_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_hmmer import HMMER_TOOL_SPECS
from enzymedesign_hmmer import HmmerDriver
from enzymedesign_hmmer import locate_hpc_driver_manifest as locate_hmmer_hpc_manifest
from enzymedesign_hmmer import locate_local_driver_manifest as locate_hmmer_local_manifest
from enzymedesign_structure import FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_structure import FPOCKET_TOOL_SPEC
from enzymedesign_structure import FpocketDriver
from enzymedesign_structure import locate_hpc_driver_manifest as locate_fpocket_hpc_manifest
from enzymedesign_structure import locate_local_driver_manifest as locate_fpocket_local_manifest
from enzymedesign_vina import VINA_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_vina import VINA_LEGACY_RESULT_SCHEMA_DIGEST
from enzymedesign_vina import VINA_MODERN_RESULT_SCHEMA_DIGEST
from enzymedesign_vina import VINA_TOOL_SPEC
from enzymedesign_vina import VinaDriver
from enzymedesign_vina import locate_hpc_driver_manifest as locate_vina_hpc_manifest
from enzymedesign_vina import locate_local_driver_manifest as locate_vina_local_manifest
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationInput
from openzyme_contracts import ExternalScientificQualificationRouteOutcome
from openzyme_contracts import ExternalScientificQualificationWorkload
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CompiledDriverWorkload
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import SubordinateDriver
from openzyme_extension_spi import parse_component_manifest_json


_ALIGNMENT = b">query_a\nACDEFGHIKLMNPQRSTVWY\n>query_b\nACDEYGHIKLMNPQRSTVWY\n"
_PROTEINS = b">target_a\nTTTACDEFGHIKLMNPQRSTVWYAAA\n>target_b\nGGGGGGGGGGGGGGGGGGGG\n"


def _qualification_asset(name: str) -> bytes:
    encoded = (
        files("enzymedesign_distribution.qualification_assets")
        .joinpath(name)
        .read_text(encoding="ascii")
    )
    compact = "".join(encoded.split())
    return gzip.decompress(base64.b64decode(compact, validate=True))


_RECEPTOR_PDBQT = _qualification_asset("vina-receptor.pdbqt.gz.b64")
_LIGAND_PDBQT = _qualification_asset("vina-ligand.pdbqt.gz.b64")
_VINA_CONFIG = (
    b"center_x = 15.190\ncenter_y = 53.903\ncenter_z = 16.917\n"
    b"size_x = 20\nsize_y = 20\nsize_z = 20\n"
    b"exhaustiveness = 1\nnum_modes = 1\nseed = 20260823\n"
)
_STRUCTURE_PDB = _qualification_asset("fpocket-1crn.pdb.gz.b64")
_LIGAND_SDF = b"""OpenZyme qualification
  OpenZyme

  9  8  0  0  0  0  0  0  0  0999 V2000
   -0.9254    0.0742    0.0328 C   0  0  0  0  0  0  0  0  0  0  0  0
    0.5123   -0.4192   -0.0743 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.3778    0.4494    0.6044 O   0  0  0  0  0  0  0  0  0  0  0  0
   -1.0220    1.0731   -0.4429 H   0  0  0  0  0  0  0  0  0  0  0  0
   -1.6044   -0.6368   -0.4832 H   0  0  0  0  0  0  0  0  0  0  0  0
   -1.2236    0.1472    1.1002 H   0  0  0  0  0  0  0  0  0  0  0  0
    0.8057   -0.5060   -1.1451 H   0  0  0  0  0  0  0  0  0  0  0  0
    0.5852   -1.4274    0.3853 H   0  0  0  0  0  0  0  0  0  0  0  0
    1.4949    1.2455    0.0227 H   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
  2  3  1  0  0  0  0
  1  4  1  0  0  0  0
  1  5  1  0  0  0  0
  1  6  1  0  0  0  0
  2  7  1  0  0  0  0
  2  8  1  0  0  0  0
  3  9  1  0  0  0  0
M  END
$$$$
"""
_RECEPTOR_PDB = _STRUCTURE_PDB


def _content_digest(content: bytes) -> str:
    return canonical_sha256_digest({"content_hex": content.hex()})


@dataclass(frozen=True, slots=True)
class FixedScientificQualificationInputRegistry:
    _content: Mapping[str, bytes] = field(repr=False)

    @classmethod
    def create(cls, contents: tuple[bytes, ...]) -> "FixedScientificQualificationInputRegistry":
        values = {_content_digest(content): content for content in contents}
        if len(values) != len(contents):
            raise ValueError("scientific qualification fixed inputs must be unique")
        return cls(values)

    def resolve(self, content_digest: str) -> bytes:
        try:
            return self._content[content_digest]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_compute_input_unknown",
                "scientific qualification input digest is not in the fixed registry",
            ) from exc


SCIENTIFIC_QUALIFICATION_INPUTS = FixedScientificQualificationInputRegistry.create(
    (
        _ALIGNMENT,
        _PROTEINS,
        _RECEPTOR_PDBQT,
        _LIGAND_PDBQT,
        _VINA_CONFIG,
        _STRUCTURE_PDB,
        _LIGAND_SDF,
    )
)


def _manifest(locator: Any) -> DriverManifest:
    manifest = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )
    if not isinstance(manifest, DriverManifest):
        raise TypeError("selected scientific component is not a Driver manifest")
    return manifest


def _input_metadata(path: str, content_digest: str, revision: str) -> dict[str, object]:
    return {
        "revision_id": revision,
        "commit": "a" * 40,
        "tree": "b" * 40,
        "path": path,
        "content_digest": content_digest,
    }


def _fixed_input(path: str, content: bytes) -> ExternalScientificQualificationInput:
    return ExternalScientificQualificationInput(
        path=path,
        content_digest=_content_digest(content),
        size_bytes=len(content),
    )


InvocationBuilder = Callable[[ExternalQualificationProbeRequest], DriverInvocationRequest]
OutputBuilder = Callable[[CompiledDriverWorkload], tuple[str, ...]]
InputBuilder = Callable[
    [ExternalQualificationProbeRequest],
    tuple[ExternalScientificQualificationInput, ...],
]


@dataclass(slots=True)
class SelectedDriverScientificQualificationCompiler:
    driver: SubordinateDriver
    operation: str
    route_kind: str
    invocation_builder: InvocationBuilder = field(repr=False)
    input_builder: InputBuilder = field(repr=False)
    output_builder: OutputBuilder = field(repr=False)
    _compiled: dict[str, CompiledDriverWorkload] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def compile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalScientificQualificationWorkload:
        if request.operation != self.operation:
            raise ExternalQualificationError(
                "qualification_compute_operation_mismatch",
                "scientific compiler received a different operation",
            )
        compiled = self.driver.compile(self.invocation_builder(request))
        workload = compiled.workload
        argv = workload.get("argv")
        cwd = workload.get("cwd")
        workload_id = workload.get("workload_id")
        compiled_digest = workload.get("workload_digest")
        if (
            not isinstance(argv, tuple)
            or not isinstance(cwd, str)
            or not isinstance(workload_id, str)
            or not isinstance(compiled_digest, str)
        ):
            raise ExternalQualificationError(
                "qualification_compute_compiled_workload_invalid",
                "selected Driver returned an invalid formal workload",
            )
        wrapped = ExternalScientificQualificationWorkload.create(
            workload_id=workload_id,
            driver_component_id=compiled.driver_id,
            operation=request.operation,
            route_kind=self.route_kind,
            argv=argv,
            cwd=cwd,
            inputs=self.input_builder(request),
            expected_output_paths=self.output_builder(compiled),
            compiled_workload_digest=compiled_digest,
        )
        self._compiled[wrapped.workload_digest] = compiled
        return wrapped

    def validate_terminal_result(
        self,
        workload: ExternalScientificQualificationWorkload,
        outcome: ExternalScientificQualificationRouteOutcome,
    ) -> None:
        try:
            compiled = self._compiled[workload.workload_digest]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_compute_compiled_workload_missing",
                "terminal scientific result has no exact compiled Driver workload",
            ) from exc
        result_payload: dict[str, object] = {
            "result_contract_digest": compiled.result_contract_digest,
            "raw_shell": False,
            "route_receipt_digest": outcome.receipt_digest,
        }
        if compiled.driver_id.startswith("enzymedesign.vina."):
            try:
                result_profile, score_semantics = {
                    VINA_LEGACY_RESULT_SCHEMA_DIGEST: (
                        "legacy-log-v1",
                        "legacy-log-file-v1",
                    ),
                    VINA_MODERN_RESULT_SCHEMA_DIGEST: (
                        "modern-poses-remark-v1",
                        "poses-remark-derived-file-v1",
                    ),
                }[compiled.result_contract_digest]
            except KeyError as exc:
                raise ExternalQualificationError(
                    "qualification_vina_result_profile_missing",
                    "Vina workload lacks its exact route result profile",
                ) from exc
            result_payload.update(
                {
                    "vina_result_profile": result_profile,
                    "score_semantics": score_semantics,
                }
            )
        result = ToolResult(
            call_id=f"call.{workload.workload_id}",
            tool_name="qualification.scientific.result",
            ok=True,
            status="completed",
            summary="Scientific qualification completed through formal Compute.",
            payload=result_payload,
        )
        self.driver.validate_result(compiled, result)


@dataclass(slots=True)
class PreprocessScientificQualificationCompiler:
    operation: str
    software: str
    route_kind: str = "local"

    def compile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalScientificQualificationWorkload:
        if request.operation != self.operation:
            raise ExternalQualificationError(
                "qualification_compute_operation_mismatch",
                "preprocess compiler received a different operation",
            )
        argv, inputs, outputs = self._command()
        identity = {
            "schema_version": "enzymedesign_preprocess_qualification_workload@1",
            "operation": self.operation,
            "software": self.software,
            "argv": list(argv),
            "inputs": [item.to_dict() for item in inputs],
            "outputs": list(outputs),
        }
        return ExternalScientificQualificationWorkload.create(
            workload_id=f"workload.{request.attempt_id}",
            driver_component_id="enzymedesign.docking.preprocess",
            operation=request.operation,
            route_kind=self.route_kind,
            argv=argv,
            cwd="analysis/preprocess",
            inputs=inputs,
            expected_output_paths=outputs,
            compiled_workload_digest=canonical_sha256_digest(identity),
        )

    def validate_terminal_result(
        self,
        workload: ExternalScientificQualificationWorkload,
        outcome: ExternalScientificQualificationRouteOutcome,
    ) -> None:
        if not outcome.terminal or not outcome.succeeded or outcome.output_digest is None:
            raise ExternalQualificationError(
                "qualification_compute_preprocess_result_invalid",
                "preprocess terminal result is incomplete",
            )

    def _command(
        self,
    ) -> tuple[
        tuple[str, ...],
        tuple[ExternalScientificQualificationInput, ...],
        tuple[str, ...],
    ]:
        if self.software == "rdkit" and self.operation == "smiles_to_3d":
            output = "results/ethanol.sdf"
            script = (
                "from rdkit import Chem; from rdkit.Chem import AllChem; "
                "m=Chem.AddHs(Chem.MolFromSmiles('CCO')); "
                "assert AllChem.EmbedMolecule(m,randomSeed=0xF00D)==0; "
                f"w=Chem.SDWriter('{output}'); w.write(m); w.close()"
            )
            return ("python", "-c", script), (), (output,)
        if self.software == "meeko" and self.operation == "prepare_ligand":
            return (
                "mk_prepare_ligand.py",
                "-i",
                "inputs/ligand.sdf",
                "-o",
                "results/ligand-meeko.pdbqt",
            ), (_fixed_input("inputs/ligand.sdf", _LIGAND_SDF),), (
                "results/ligand-meeko.pdbqt",
            )
        if self.software == "openbabel":
            if self.operation == "prepare_receptor":
                input_path = "inputs/receptor.pdb"
                output = "results/receptor.pdbqt"
                item = _fixed_input(input_path, _RECEPTOR_PDB)
            else:
                input_path = "inputs/ligand.sdf"
                output = (
                    "results/ligand.mol2"
                    if self.operation == "convert_format"
                    else "results/ligand-openbabel.pdbqt"
                )
                item = _fixed_input(input_path, _LIGAND_SDF)
            return ("obabel", input_path, "-O", output), (item,), (output,)
        raise ExternalQualificationError(
            "qualification_compute_preprocess_operation_unsupported",
            "preprocess qualification compiler does not own this operation",
        )


def build_selected_driver_scientific_compiler(
    *,
    component_id: str,
    operation: str,
    route_kind: str,
) -> SelectedDriverScientificQualificationCompiler:
    is_hpc = route_kind == "hpc-primary"
    policy_digest = canonical_sha256_digest(
        {"qualification": "batch-1", "route_kind": route_kind}
    )
    if component_id.startswith("enzymedesign.hmmer."):
        manifest = _manifest(
            locate_hmmer_hpc_manifest() if is_hpc else locate_hmmer_local_manifest()
        )
        driver = HmmerDriver(manifest)
        search = operation == "hmmsearch"
        tool_spec = next(
            item
            for item in HMMER_TOOL_SPECS
            if item.tool_name.endswith(".search" if search else ".build")
        )

        def invocation(request: ExternalQualificationProbeRequest) -> DriverInvocationRequest:
            if search:
                driver_inputs = (
                    _input_metadata(
                        "inputs/model.hmm",
                        canonical_sha256_digest(
                            {"generated_from": _content_digest(_ALIGNMENT), "tool": "hmmbuild"}
                        ),
                        "revision-model-derived",
                    ),
                    _input_metadata(
                        "inputs/proteins.fasta",
                        _content_digest(_PROTEINS),
                        "revision-proteins",
                    ),
                )
            else:
                driver_inputs = (
                    _input_metadata(
                        "inputs/alignment.fasta",
                        _content_digest(_ALIGNMENT),
                        "revision-alignment",
                    ),
                )
            return DriverInvocationRequest(
                driver_id=component_id,
                owning_plugin_id="enzymedesign.hmmer",
                route_id=request.operation,
                tool_name=tool_spec.tool_name,
                tool_contract_digest=tool_spec.contract_digest,
                request_contract_digest=HMMER_DRIVER_REQUEST_CONTRACT_DIGEST,
                payload={
                    "operation": "search" if search else "build",
                    "workload_id": f"workload.{request.attempt_id}",
                    "cwd": "analysis/hmmer",
                    "resource_policy_digest": policy_digest,
                    "environment_policy_digest": policy_digest,
                    "inputs": driver_inputs,
                    "result_root": "results/hmmer",
                    "output_path": (
                        "results/hmmer/hits.tbl"
                        if search
                        else "results/hmmer/model.hmm"
                    ),
                },
            )

        return SelectedDriverScientificQualificationCompiler(
            driver=driver,
            operation=operation,
            route_kind=route_kind,
            invocation_builder=invocation,
            input_builder=(
                (lambda _request: (
                    _fixed_input("inputs/alignment.fasta", _ALIGNMENT),
                    _fixed_input("inputs/proteins.fasta", _PROTEINS),
                ))
                if search
                else (lambda _request: (
                    _fixed_input("inputs/alignment.fasta", _ALIGNMENT),
                ))
            ),
            output_builder=lambda compiled: (
                str(compiled.workload["argv"][3 if search else 1]),
            ),
        )
    if component_id.startswith("enzymedesign.vina."):
        manifest = _manifest(
            locate_vina_hpc_manifest() if is_hpc else locate_vina_local_manifest()
        )
        driver = VinaDriver(manifest)

        def invocation(request: ExternalQualificationProbeRequest) -> DriverInvocationRequest:
            return DriverInvocationRequest(
                driver_id=component_id,
                owning_plugin_id="enzymedesign.vina",
                route_id=(
                    "enzymedesign.vina.hpc-primary@1"
                    if is_hpc
                    else "enzymedesign.vina.local@1"
                ),
                tool_name=VINA_TOOL_SPEC.tool_name,
                tool_contract_digest=VINA_TOOL_SPEC.contract_digest,
                request_contract_digest=VINA_DRIVER_REQUEST_CONTRACT_DIGEST,
                payload={
                    "workload_id": f"workload.{request.attempt_id}",
                    "cwd": "analysis/vina",
                    "resource_policy_digest": policy_digest,
                    "environment_policy_digest": policy_digest,
                    "inputs": (
                        _input_metadata(
                            "inputs/receptor.pdbqt",
                            _content_digest(_RECEPTOR_PDBQT),
                            "revision-receptor",
                        ),
                        _input_metadata(
                            "inputs/ligand.pdbqt",
                            _content_digest(_LIGAND_PDBQT),
                            "revision-ligand",
                        ),
                        _input_metadata(
                            "inputs/vina.conf",
                            _content_digest(_VINA_CONFIG),
                            "revision-config",
                        ),
                    ),
                    "result_root": "results/vina",
                    "poses_path": "results/vina/poses.pdbqt",
                    "score_path": "results/vina/vina.log",
                },
            )

        return SelectedDriverScientificQualificationCompiler(
            driver=driver,
            operation=operation,
            route_kind=route_kind,
            invocation_builder=invocation,
            input_builder=lambda _request: (
                _fixed_input("inputs/receptor.pdbqt", _RECEPTOR_PDBQT),
                _fixed_input("inputs/ligand.pdbqt", _LIGAND_PDBQT),
                _fixed_input("inputs/vina.conf", _VINA_CONFIG),
            ),
            output_builder=lambda _compiled: (
                "results/vina/poses.pdbqt",
                "results/vina/vina.log",
            ),
        )
    if component_id.startswith("enzymedesign.fpocket."):
        manifest = _manifest(
            locate_fpocket_hpc_manifest() if is_hpc else locate_fpocket_local_manifest()
        )
        driver = FpocketDriver(manifest)

        def invocation(request: ExternalQualificationProbeRequest) -> DriverInvocationRequest:
            return DriverInvocationRequest(
                driver_id=component_id,
                owning_plugin_id="enzymedesign.structure",
                route_id=request.operation,
                tool_name=FPOCKET_TOOL_SPEC.tool_name,
                tool_contract_digest=FPOCKET_TOOL_SPEC.contract_digest,
                request_contract_digest=FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST,
                payload={
                    "workload_id": f"workload.{request.attempt_id}",
                    "cwd": "analysis/fpocket",
                    "resource_policy_digest": policy_digest,
                    "environment_policy_digest": policy_digest,
                    "inputs": (
                        _input_metadata(
                            "structure.pdb",
                            _content_digest(_STRUCTURE_PDB),
                            "revision-structure",
                        ),
                    ),
                    "result_root": "results/fpocket",
                },
            )

        return SelectedDriverScientificQualificationCompiler(
            driver=driver,
            operation=operation,
            route_kind=route_kind,
            invocation_builder=invocation,
            input_builder=lambda _request: (
                _fixed_input("structure.pdb", _STRUCTURE_PDB),
            ),
            output_builder=lambda _compiled: (
                "structure_out/structure_info.txt",
            ),
        )
    raise ValueError("unsupported selected scientific Driver component")


__all__ = [
    "FixedScientificQualificationInputRegistry",
    "PreprocessScientificQualificationCompiler",
    "SCIENTIFIC_QUALIFICATION_INPUTS",
    "SelectedDriverScientificQualificationCompiler",
    "build_selected_driver_scientific_compiler",
]
