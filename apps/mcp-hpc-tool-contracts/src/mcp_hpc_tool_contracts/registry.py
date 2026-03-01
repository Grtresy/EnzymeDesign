from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .constants import (
    ADAPTER_IDS,
    CANONICAL_SIF_IMAGES,
    CANONICAL_WRAPPER_ENTRYPOINTS,
    HHBLITS_SPACK_FALLBACK,
)
from .invocation import InvocationCandidate, build_sif_command, select_invocation
from .models import CompiledAdapterRun
from .runspec import (
    build_metadata,
    build_runspec,
    expected_output,
    failure_signature,
    staged_input,
    success_check,
)


CompileFn = Callable[[dict[str, Any]], CompiledAdapterRun]


@dataclass(frozen=True, slots=True)
class AdapterDefinition:
    adapter_id: str
    description: str
    parameter_schema: dict[str, Any]
    compile_fn: CompileFn


def _required_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"Missing required parameter: {key}")
    return str(value)


def _number(params: dict[str, Any], key: str) -> float:
    if key not in params:
        raise ValueError(f"Missing required numeric parameter: {key}")
    return float(params[key])


def _optional_str(params: dict[str, Any], key: str, default: str) -> str:
    value = params.get(key, default)
    return str(value)


def _stable_name(local_path: str, default_stem: str) -> str:
    stem = Path(local_path).stem
    return stem or default_stem


def _generic_failures() -> list[dict[str, str]]:
    return [
        failure_signature(r"CUDA out of memory", "CUDA_OOM"),
        failure_signature(r"No such file or directory", "MISSING_FILE"),
        failure_signature(r"permission denied", "PERMISSION_DENIED"),
        failure_signature(r"sbatch: error", "SBATCH_ERROR"),
    ]


def _ensure_hhblits_fallback_binary(path: str) -> None:
    if Path(path).name != "hhblits":
        raise ValueError(
            f"HHBLITS_SPACK_FALLBACK must point to a hhblits binary, got: {path}"
        )


def _compile_hhblits(params: dict[str, Any]) -> CompiledAdapterRun:
    query_fasta = _required_str(params, "query_fasta")
    db_prefix = _optional_str(params, "db_prefix", "uniclust30")
    iterations = int(params.get("iterations", 3))
    run_stem = _stable_name(query_fasta, "query")
    a3m_output = f"hhblits/{run_stem}.a3m"
    hhr_output = f"hhblits/{run_stem}.hhr"

    query_remote = "inputs/query.fasta"
    argv = [
        "-i",
        f"/work/{query_remote}",
        "-d",
        f"/db/{db_prefix}",
        "-n",
        str(iterations),
        "-oa3m",
        f"/out/{a3m_output}",
        "-o",
        f"/out/{hhr_output}",
    ]
    _ensure_hhblits_fallback_binary(HHBLITS_SPACK_FALLBACK)

    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint="/opt/tools/hhblits",
        smoke_check=["/opt/tools/hhblits", "-h"],
        command=["/opt/tools/hhblits", *argv],
    )
    sif = InvocationCandidate(
        mode="sif",
        entrypoint=CANONICAL_SIF_IMAGES["hhblits"],
        command=build_sif_command(
            image=CANONICAL_SIF_IMAGES["hhblits"],
            entrypoint="hhblits",
            args=argv,
            extra_host_binds=["/db"],
        ),
    )
    spack = InvocationCandidate(
        mode="spack",
        entrypoint=HHBLITS_SPACK_FALLBACK,
        command=[HHBLITS_SPACK_FALLBACK, *argv],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=spack)

    metadata = build_metadata(
        adapter_id="hhblits",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
    )
    runspec = build_runspec(
        name="hhblits-contract",
        stage="evidence",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 8, "mem_mb": 16000, "gpus": 0, "time_minutes": 180},
        inputs=[staged_input(query_fasta, query_remote)],
        expected_outputs=[
            expected_output(a3m_output, kind="file", required=True, non_empty=True),
            expected_output(hhr_output, kind="file", required=True, non_empty=True),
        ],
        success_checks=[
            success_check("non_empty", a3m_output),
            success_check("non_empty", hhr_output),
        ],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="hhblits",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


def _compile_chai_fold(params: dict[str, Any]) -> CompiledAdapterRun:
    input_fasta = _required_str(params, "input_fasta")
    output_dir = _optional_str(params, "output_dir", "chai_fold")
    input_remote = "inputs/input.fasta"
    common_args = ["fold", f"/work/{input_remote}", f"/out/{output_dir}"]

    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint=CANONICAL_WRAPPER_ENTRYPOINTS["chai_fold"],
        smoke_check=[CANONICAL_WRAPPER_ENTRYPOINTS["chai_fold"], "--help"],
        command=[CANONICAL_WRAPPER_ENTRYPOINTS["chai_fold"], *common_args],
    )
    sif = InvocationCandidate(
        mode="sif",
        entrypoint="~/containers/chai-1.sif",
        command=build_sif_command(
            image="~/containers/chai-1.sif",
            entrypoint="chai-lab",
            args=common_args,
            extra_host_binds=["/models"],
        ),
    )
    native = InvocationCandidate(
        mode="native",
        entrypoint="chai-lab",
        command=["chai-lab", *common_args],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=native)

    metadata = build_metadata(
        adapter_id="chai_fold",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
    )
    runspec = build_runspec(
        name="chai-fold-contract",
        stage="generator",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 8, "mem_mb": 48000, "gpus": 1, "time_minutes": 240},
        inputs=[staged_input(input_fasta, input_remote)],
        expected_outputs=[
            expected_output(output_dir, kind="dir", required=True, non_empty=True)
        ],
        success_checks=[success_check("non_empty", output_dir)],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="chai_fold",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


def _compile_alphafold3(params: dict[str, Any]) -> CompiledAdapterRun:
    input_json = _required_str(params, "input_json")
    output_dir = _optional_str(params, "output_dir", "alphafold3")
    input_remote = "inputs/input.json"
    common_args = [
        "--json_path",
        f"/work/{input_remote}",
        "--output_dir",
        f"/out/{output_dir}",
    ]

    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint=CANONICAL_WRAPPER_ENTRYPOINTS["alphafold3"],
        smoke_check=[CANONICAL_WRAPPER_ENTRYPOINTS["alphafold3"], "--help"],
        command=[CANONICAL_WRAPPER_ENTRYPOINTS["alphafold3"], *common_args],
    )
    sif = InvocationCandidate(
        mode="sif",
        entrypoint="~/containers/alphafold3.sif",
        command=build_sif_command(
            image="~/containers/alphafold3.sif",
            entrypoint="alphafold3",
            args=common_args,
            extra_host_binds=["/models"],
        ),
    )
    native = InvocationCandidate(
        mode="native",
        entrypoint="alphafold3",
        command=["alphafold3", *common_args],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=native)

    metadata = build_metadata(
        adapter_id="alphafold3",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
    )
    runspec = build_runspec(
        name="alphafold3-contract",
        stage="evaluator",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 8, "mem_mb": 64000, "gpus": 1, "time_minutes": 360},
        inputs=[staged_input(input_json, input_remote)],
        expected_outputs=[
            expected_output(output_dir, kind="dir", required=True, non_empty=True)
        ],
        success_checks=[success_check("non_empty", output_dir)],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="alphafold3",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


def _compile_colabfold(params: dict[str, Any]) -> CompiledAdapterRun:
    input_fasta = _required_str(params, "input_fasta")
    output_dir = _optional_str(params, "output_dir", "colabfold")
    input_remote = "inputs/input.fasta"
    common_args = [f"/work/{input_remote}", f"/out/{output_dir}"]

    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint=CANONICAL_WRAPPER_ENTRYPOINTS["colabfold"],
        smoke_check=[CANONICAL_WRAPPER_ENTRYPOINTS["colabfold"], "--help"],
        command=[CANONICAL_WRAPPER_ENTRYPOINTS["colabfold"], *common_args],
    )
    sif = InvocationCandidate(
        mode="sif",
        entrypoint="~/containers/colabfold.sif",
        command=build_sif_command(
            image="~/containers/colabfold.sif",
            entrypoint="colabfold_batch",
            args=common_args,
            extra_host_binds=["/db"],
        ),
    )
    native = InvocationCandidate(
        mode="native",
        entrypoint="colabfold_batch",
        command=["colabfold_batch", *common_args],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=native)

    metadata = build_metadata(
        adapter_id="colabfold",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
    )
    runspec = build_runspec(
        name="colabfold-contract",
        stage="evaluator",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 8, "mem_mb": 48000, "gpus": 1, "time_minutes": 240},
        inputs=[staged_input(input_fasta, input_remote)],
        expected_outputs=[
            expected_output(output_dir, kind="dir", required=True, non_empty=True)
        ],
        success_checks=[success_check("non_empty", output_dir)],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="colabfold",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


def _compile_fpocket(params: dict[str, Any]) -> CompiledAdapterRun:
    structure_path = _required_str(params, "structure_path")
    input_stem = _stable_name(structure_path, "target")
    input_remote = f"inputs/{input_stem}.pdb"
    # fpocket writes {stem}_out/ next to the input file.
    # Staging the input to out/inputs/ makes the output land in out/inputs/{stem}_out/,
    # which is exactly where staging looks for it (relative path inputs/{stem}_out).
    output_dir = f"inputs/{input_stem}_out"

    # SIF: input accessible at /out/inputs/{stem}.pdb; output written to /out/inputs/{stem}_out/.
    sif = InvocationCandidate(
        mode="sif",
        entrypoint=CANONICAL_SIF_IMAGES["fpocket"],
        command=build_sif_command(
            image=CANONICAL_SIF_IMAGES["fpocket"],
            entrypoint="fpocket",
            args=["-f", f"/out/{input_remote}"],
        ),
    )
    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint="/opt/tools/fpocket",
        smoke_check=["/opt/tools/fpocket", "-h"],
        command=["/opt/tools/fpocket", "-f", f"/out/{input_remote}"],
    )
    native = InvocationCandidate(
        mode="native",
        entrypoint="fpocket",
        command=["fpocket", "-f", f"/out/{input_remote}"],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=native)

    metadata = build_metadata(
        adapter_id="fpocket",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
    )
    runspec = build_runspec(
        name="fpocket-contract",
        stage="evaluator",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 4, "mem_mb": 8000, "gpus": 0, "time_minutes": 120},
        inputs=[staged_input(structure_path, input_remote, stage_to="out")],
        expected_outputs=[
            expected_output(output_dir, kind="dir", required=True, non_empty=True)
        ],
        success_checks=[success_check("non_empty", output_dir)],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="fpocket",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


def _compile_tunnels(params: dict[str, Any]) -> CompiledAdapterRun:
    structure_path = _required_str(params, "structure_path")
    mode = str(params.get("mode", "detect"))
    if mode not in {"detect", "dock"}:
        raise ValueError("tunnels.mode must be detect or dock")
    _VALID_BACKENDS = {"detect": "caver", "dock": "caverdock"}
    default_backend = _VALID_BACKENDS[mode]
    backend = str(params.get("backend", default_backend))
    if backend != default_backend:
        raise ValueError(
            f"tunnels.backend must be '{default_backend}' when mode='{mode}', got '{backend}'"
        )
    output_dir = _optional_str(params, "output_dir", f"tunnels-{mode}")
    input_remote = "inputs/target.pdb"

    if mode == "detect":
        entrypoint = "caver"
        wrapper_entrypoint = "/opt/tools/caver"
        command_args = [
            "--input",
            f"/work/{input_remote}",
            "--output",
            f"/out/{output_dir}",
        ]
    else:
        entrypoint = "cd-screening"
        wrapper_entrypoint = "/opt/tools/caverdock"
        command_args = [f"/work/{input_remote}", "-o", f"/out/{output_dir}"]

    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint=wrapper_entrypoint,
        smoke_check=[wrapper_entrypoint, "-h"],
        command=[wrapper_entrypoint, *command_args],
    )
    sif = InvocationCandidate(
        mode="sif",
        entrypoint=CANONICAL_SIF_IMAGES["tunnels"],
        command=build_sif_command(
            image=CANONICAL_SIF_IMAGES["tunnels"],
            entrypoint=entrypoint,
            args=command_args,
        ),
    )
    native = InvocationCandidate(
        mode="native",
        entrypoint=entrypoint,
        command=[entrypoint, *command_args],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=native)

    metadata = build_metadata(
        adapter_id="tunnels",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
        extra={"tunnel_mode": mode, "tunnel_backend": backend},
    )
    runspec = build_runspec(
        name="tunnels-contract",
        stage="evaluator",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 8, "mem_mb": 16000, "gpus": 0, "time_minutes": 180},
        inputs=[staged_input(structure_path, input_remote)],
        expected_outputs=[
            expected_output(output_dir, kind="dir", required=True, non_empty=True)
        ],
        success_checks=[success_check("non_empty", output_dir)],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="tunnels",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


def _compile_vina(params: dict[str, Any]) -> CompiledAdapterRun:
    receptor = _required_str(params, "receptor_path")
    ligand = _required_str(params, "ligand_path")
    center_x = _number(params, "center_x")
    center_y = _number(params, "center_y")
    center_z = _number(params, "center_z")
    size_x = _number(params, "size_x")
    size_y = _number(params, "size_y")
    size_z = _number(params, "size_z")
    output_dir = _optional_str(params, "output_dir", "vina")

    receptor_remote = "inputs/receptor.pdbqt"
    ligand_remote = "inputs/ligand.pdbqt"
    out_file = f"{output_dir}/vina_out.pdbqt"
    log_file = f"{output_dir}/vina.log"

    common_args = [
        "--receptor",
        f"/work/{receptor_remote}",
        "--ligand",
        f"/work/{ligand_remote}",
        "--center_x",
        str(center_x),
        "--center_y",
        str(center_y),
        "--center_z",
        str(center_z),
        "--size_x",
        str(size_x),
        "--size_y",
        str(size_y),
        "--size_z",
        str(size_z),
        "--out",
        f"/out/{out_file}",
        "--log",
        f"/out/{log_file}",
    ]

    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint="/opt/tools/vina",
        smoke_check=["/opt/tools/vina", "--help"],
        command=["/opt/tools/vina", *common_args],
    )
    sif = InvocationCandidate(
        mode="sif",
        entrypoint=CANONICAL_SIF_IMAGES["vina"],
        command=build_sif_command(
            image=CANONICAL_SIF_IMAGES["vina"], entrypoint="vina", args=common_args
        ),
    )
    native = InvocationCandidate(
        mode="native",
        entrypoint="vina",
        command=["vina", *common_args],
    )
    selected = select_invocation(wrapper=wrapper, sif=sif, fallback=native)

    metadata = build_metadata(
        adapter_id="vina",
        selected_mode=selected.selected.mode,
        fallback=selected.fallback,
    )
    runspec = build_runspec(
        name="vina-contract",
        stage="evaluator",
        command=selected.selected.command,
        execution_mode="auto",
        resources={"cpus": 8, "mem_mb": 12000, "gpus": 0, "time_minutes": 180},
        inputs=[
            staged_input(receptor, receptor_remote),
            staged_input(ligand, ligand_remote),
        ],
        expected_outputs=[
            expected_output(output_dir, kind="dir", required=True, non_empty=True),
            expected_output(out_file, kind="file", required=True, non_empty=True),
            expected_output(log_file, kind="file", required=True, non_empty=True),
        ],
        success_checks=[
            success_check("non_empty", output_dir),
            success_check("non_empty", out_file),
            success_check("non_empty", log_file),
        ],
        failure_signatures=_generic_failures(),
        fallback=selected.fallback,
        metadata=metadata,
    )
    return CompiledAdapterRun(
        adapter_id="vina",
        runspec=runspec,
        invocation_mode=selected.selected.mode,
        fallback=selected.fallback,
        metadata=metadata,
    )


_ADAPTERS: dict[str, AdapterDefinition] = {
    "hhblits": AdapterDefinition(
        adapter_id="hhblits",
        description="Compile hhblits query FASTA to A3M run contract",
        parameter_schema={
            "type": "object",
            "required": ["query_fasta"],
            "properties": {
                "query_fasta": {"type": "string"},
                "db_prefix": {"type": "string", "default": "uniclust30"},
                "iterations": {"type": "integer", "default": 3, "minimum": 1},
            },
        },
        compile_fn=_compile_hhblits,
    ),
    "chai_fold": AdapterDefinition(
        adapter_id="chai_fold",
        description="Compile chai-lab fold FASTA contract",
        parameter_schema={
            "type": "object",
            "required": ["input_fasta"],
            "properties": {
                "input_fasta": {"type": "string"},
                "output_dir": {"type": "string", "default": "chai_fold"},
            },
        },
        compile_fn=_compile_chai_fold,
    ),
    "alphafold3": AdapterDefinition(
        adapter_id="alphafold3",
        description="Compile AlphaFold3 JSON contract",
        parameter_schema={
            "type": "object",
            "required": ["input_json"],
            "properties": {
                "input_json": {"type": "string"},
                "output_dir": {"type": "string", "default": "alphafold3"},
            },
        },
        compile_fn=_compile_alphafold3,
    ),
    "colabfold": AdapterDefinition(
        adapter_id="colabfold",
        description="Compile ColabFold contract",
        parameter_schema={
            "type": "object",
            "required": ["input_fasta"],
            "properties": {
                "input_fasta": {"type": "string"},
                "output_dir": {"type": "string", "default": "colabfold"},
            },
        },
        compile_fn=_compile_colabfold,
    ),
    "fpocket": AdapterDefinition(
        adapter_id="fpocket",
        description="Compile fpocket contract",
        parameter_schema={
            "type": "object",
            "required": ["structure_path"],
            "properties": {
                "structure_path": {"type": "string"},
                "output_dir": {"type": "string"},
            },
        },
        compile_fn=_compile_fpocket,
    ),
    "tunnels": AdapterDefinition(
        adapter_id="tunnels",
        description="Compile tunnels detect/dock contract",
        parameter_schema={
            "type": "object",
            "required": ["structure_path"],
            "properties": {
                "structure_path": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["detect", "dock"],
                    "default": "detect",
                },
                "backend": {"type": "string", "enum": ["caver", "caverdock"]},
                "output_dir": {"type": "string"},
            },
        },
        compile_fn=_compile_tunnels,
    ),
    "vina": AdapterDefinition(
        adapter_id="vina",
        description="Compile Vina docking contract",
        parameter_schema={
            "type": "object",
            "required": [
                "receptor_path",
                "ligand_path",
                "center_x",
                "center_y",
                "center_z",
                "size_x",
                "size_y",
                "size_z",
            ],
            "properties": {
                "receptor_path": {"type": "string"},
                "ligand_path": {"type": "string"},
                "center_x": {"type": "number"},
                "center_y": {"type": "number"},
                "center_z": {"type": "number"},
                "size_x": {"type": "number"},
                "size_y": {"type": "number"},
                "size_z": {"type": "number"},
                "output_dir": {"type": "string", "default": "vina"},
            },
        },
        compile_fn=_compile_vina,
    ),
}


def list_adapters() -> list[dict[str, Any]]:
    adapters: list[dict[str, Any]] = []
    for adapter_id in ADAPTER_IDS:
        definition = _ADAPTERS[adapter_id]
        adapters.append(
            {
                "id": definition.adapter_id,
                "description": definition.description,
                "parameter_schema": definition.parameter_schema,
            }
        )
    return adapters


def get_adapter(adapter_id: str) -> AdapterDefinition:
    try:
        return _ADAPTERS[adapter_id]
    except KeyError as exc:
        available = ", ".join(ADAPTER_IDS)
        raise ValueError(
            f"Unknown adapter '{adapter_id}'. Available: {available}"
        ) from exc


def compile_adapter(adapter_id: str, params: dict[str, Any]) -> CompiledAdapterRun:
    definition = get_adapter(adapter_id)
    return definition.compile_fn(dict(params))
