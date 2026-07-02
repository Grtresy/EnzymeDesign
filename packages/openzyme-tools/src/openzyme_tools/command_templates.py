from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .contracts import ToolExecutionContract
from .contracts import ToolOutputContract


def validate_runner_relative_path(path: str) -> str:
    normalized = path.strip()
    if not normalized or normalized.startswith("/"):
        raise ValueError(f"runner path must be relative under work/out: {path!r}")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"runner path must not contain empty, '.', or '..' segments: {path!r}")
    if any(char in normalized for char in (";", "&", "|", "`", "$", "\\", "\n", "\r")):
        raise ValueError(f"runner path must not contain shell metacharacters: {path!r}")
    return normalized


def shell_number(value: Any, default: float | int) -> str:
    candidate = default if value is None else value
    try:
        number = float(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"numeric execution parameter must be a number: {candidate!r}") from exc
    if number.is_integer():
        return str(int(number))
    return str(number)


def render_contract_command(contract: ToolExecutionContract, tool_inputs: dict[str, Any]) -> list[str]:
    if contract.command_template_id == "fpocket_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'apptainer exec --cleanenv --pwd /out '
                '--bind "$MCP_WORKDIR:/work" --bind "$MCP_OUTDIR:/out" '
                '--bind "$MCP_TMPDIR:/tmp" ~/containers/fpocket.sif fpocket -f /work/target.pdb && '
                'if [ -d "$MCP_WORKDIR/target_out" ]; then rm -rf "$MCP_OUTDIR/target_out" && '
                'mv "$MCP_WORKDIR/target_out" "$MCP_OUTDIR/target_out"; fi'
            ),
        ]
    if contract.command_template_id == "vina_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" ~/containers/vina.sif vina '
                "--receptor /work/receptor.pdbqt --ligand /work/ligand.pdbqt "
                f"--center_x {shell_number(tool_inputs.get('center_x'), 0)} "
                f"--center_y {shell_number(tool_inputs.get('center_y'), 0)} "
                f"--center_z {shell_number(tool_inputs.get('center_z'), 0)} "
                f"--size_x {shell_number(tool_inputs.get('size_x'), 10)} "
                f"--size_y {shell_number(tool_inputs.get('size_y'), 10)} "
                f"--size_z {shell_number(tool_inputs.get('size_z'), 10)} "
                f"--exhaustiveness {shell_number(tool_inputs.get('exhaustiveness'), 8)} "
                f"--num_modes {shell_number(tool_inputs.get('num_modes'), 9)} "
                "--out /out/vina_out.pdbqt --log /out/vina.log"
            ),
        ]
    if contract.command_template_id == "bio_tools_cdhit_sif_v1":
        identity = shell_number(tool_inputs.get("identity"), 0.9)
        word_size = shell_number(tool_inputs.get("word_size"), 5)
        return [
            "bash",
            "-lc",
            (
                'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/cdhit"; '
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
                '"${CDHIT_SIF:-$HOME/containers/cd-hit_4.8.1.sif}" cd-hit '
                f"-i /work/input.fasta -o /out/bio_tools/cdhit/clustered.fasta -c {identity} -n {word_size} -d 0 -T 1 -M 256 "
                '> "$MCP_OUTDIR/bio_tools/cdhit/cdhit.log"; '
                "printf 'cluster_id,representative,member_count\\n' > \"$MCP_OUTDIR/bio_tools/cdhit/clusters.csv\"; "
                "awk 'BEGIN{c=\"cluster_1\"} /^>/{c=\"cluster_\" substr($2,1)} /\\*/{gsub(/[>.]/,\"\",$3); print c \",\" $3 \",1\"}' "
                '"$MCP_OUTDIR/bio_tools/cdhit/clustered.fasta.clstr" >> "$MCP_OUTDIR/bio_tools/cdhit/clusters.csv"'
            ),
        ]
    if contract.command_template_id == "bio_tools_mafft_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/mafft"; '
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
                '"${MAFFT_SIF:-$HOME/containers/mafft_7.525.sif}" mafft --auto /work/input.fasta '
                '> "$MCP_OUTDIR/bio_tools/mafft/alignment.fasta"'
            ),
        ]
    if contract.command_template_id == "bio_tools_hmmbuild_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/hmmbuild"; '
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
                '"${HMMER_SIF:-$HOME/containers/hmmer_3.4.sif}" hmmbuild --amino '
                "/out/bio_tools/hmmbuild/model.hmm /work/alignment.fasta "
                '> "$MCP_OUTDIR/bio_tools/hmmbuild/hmmbuild.summary.txt"'
            ),
        ]
    if contract.command_template_id == "bio_tools_hmmalign_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/hmmalign"; '
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
                '"${HMMER_SIF:-$HOME/containers/hmmer_3.4.sif}" hmmalign --amino --outformat afa '
                "-o /out/bio_tools/hmmalign/aligned.fasta /work/model.hmm /work/input.fasta"
            ),
        ]
    raise ValueError(f"unsupported command template {contract.command_template_id!r}")


def contract_payload(contract: ToolExecutionContract) -> dict[str, Any]:
    return {
        "adapter_id": contract.adapter_id,
        "tool_id": contract.tool_id,
        "command_template_id": contract.command_template_id,
        "parser_hints": contract.parser_hints,
        "preprocess_requirements": contract.preprocess_requirements,
    }


def output_payload(output: ToolOutputContract) -> dict[str, Any]:
    return {
        "path": validate_runner_relative_path(output.path),
        "kind": output.kind,
        "required": output.required,
        "non_empty": output.non_empty,
    }


def contract_outputs(contract: ToolExecutionContract) -> list[dict[str, Any]]:
    return [output_payload(output) for output in contract.expected_outputs]


__all__ = [
    "contract_outputs",
    "contract_payload",
    "output_payload",
    "render_contract_command",
    "shell_number",
    "validate_runner_relative_path",
]
