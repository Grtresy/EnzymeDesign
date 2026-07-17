from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .contracts import ToolExecutionContract
from .contracts import ToolOutputContract


CDHIT_MEMBERSHIP_SCHEMA_ID = "cdhit_cluster_membership@1"
CDHIT_MEMBERSHIP_COLUMNS = (
    "cluster_id",
    "member_id",
    "representative_id",
    "is_representative",
    "identity_to_representative",
    "member_length",
)

_CDHIT_MEMBERSHIP_AWK = (
    r'function mark_error(message) { '
    r'if (status == 0) print "cdhit .clstr normalization failed: " message > "/dev/stderr"; '
    r'status = 2 } '
    r'function csv_quote(value, escaped) { '
    r'escaped = value; gsub(/"/, "\"\"", escaped); return "\"" escaped "\"" } '
    r'function clear_members(i) { '
    r'for (i = 1; i <= members_seen; i++) { '
    r'delete member_ids[i]; delete member_is_representative[i]; '
    r'delete member_identities[i]; delete member_lengths[i] } '
    r'members_seen = 0; representative_count = 0; representative_id = "" } '
    r'function flush_cluster(i) { '
    r'if (cluster_id == "") return; cluster_count++; '
    r'if (members_seen == 0) mark_error(cluster_id " has no members"); '
    r'if (representative_count != 1) '
    r'mark_error(cluster_id " must contain exactly one representative"); '
    r'if (status == 0) for (i = 1; i <= members_seen; i++) '
    r'printf "%s,%s,%s,%s,%s,%s\n", csv_quote(cluster_id), '
    r'csv_quote(member_ids[i]), csv_quote(representative_id), '
    r'member_is_representative[i], member_identities[i], member_lengths[i]; '
    r'clear_members(); cluster_id = "" } '
    r'BEGIN { status = 0; cluster_count = 0; '
    r'print "cluster_id,member_id,representative_id,is_representative,'
    r'identity_to_representative,member_length" } '
    r'/^>Cluster[[:space:]]+/ { '
    r'flush_cluster(); raw_cluster = $0; '
    r'sub(/^>Cluster[[:space:]]+/, "", raw_cluster); '
    r'if (raw_cluster !~ /^[0-9]+$/) mark_error("invalid cluster header: " $0); '
    r'cluster_id = "cluster_" raw_cluster; next } '
    r'/^[[:space:]]*$/ { next } '
    r'{ '
    r'if (cluster_id == "") { mark_error("member row before cluster header"); next } '
    r'line = $0; member_length = line; '
    r'sub(/^[^[:space:]]+[[:space:]]+/, "", member_length); '
    r'sub(/aa,.*/, "", member_length); gsub(/[[:space:]]/, "", member_length); '
    r'if (member_length !~ /^[0-9]+$/) { '
    r'mark_error(cluster_id " has invalid member length: " line); next } '
    r'member_id = line; '
    r'if (member_id !~ />.*\.\.\./) { '
    r'mark_error(cluster_id " has invalid member identifier: " line); next } '
    r'sub(/^[^>]*>/, "", member_id); sub(/\.\.\..*$/, "", member_id); '
    r'if (member_id == "") { mark_error(cluster_id " has empty member identifier"); next } '
    r'is_representative = (line ~ /[[:space:]]\*[[:space:]]*$/); '
    r'if (is_representative) { '
    r'representative_count++; representative_id = member_id; identity = "1.000000" '
    r'} else { '
    r'identity = line; '
    r'if (identity !~ /[[:space:]]at[[:space:]]+.*%/) { '
    r'mark_error(cluster_id " member lacks identity: " line); next } '
    r'sub(/^.*[[:space:]]at[[:space:]]+/, "", identity); sub(/%.*/, "", identity); '
    r'sub(/^.*\//, "", identity); gsub(/[[:space:]]/, "", identity); '
    r'if (identity !~ /^[0-9]+([.][0-9]+)?$/ || identity + 0 > 100) { '
    r'mark_error(cluster_id " has invalid identity: " line); next } '
    r'identity = sprintf("%.6f", (identity + 0) / 100) } '
    r'members_seen++; member_ids[members_seen] = member_id; '
    r'member_is_representative[members_seen] = is_representative ? "true" : "false"; '
    r'member_identities[members_seen] = identity; member_lengths[members_seen] = member_length '
    r'} '
    r'END { flush_cluster(); '
    r'if (cluster_count == 0) mark_error("input contains no clusters"); exit status }'
)


def render_cdhit_membership_normalizer_command() -> str:
    """Render the fail-closed `.clstr` to canonical membership CSV boundary."""

    output_root = '"$MCP_OUTDIR/bio_tools/cdhit'
    clstr_path = f'{output_root}/clustered.fasta.clstr"'
    temporary_path = f'{output_root}/clusters.csv.tmp"'
    output_path = f'{output_root}/clusters.csv"'
    return (
        f"rm -f {output_path} {temporary_path}; "
        f"if awk '{_CDHIT_MEMBERSHIP_AWK}' {clstr_path} > {temporary_path}; then "
        f"mv {temporary_path} {output_path}; "
        f"else status=$?; rm -f {temporary_path}; exit \"$status\"; fi"
    )


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
    if contract.command_template_id == "bio_tools_cdhit_sif_v2":
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
                + render_cdhit_membership_normalizer_command()
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
    "CDHIT_MEMBERSHIP_COLUMNS",
    "CDHIT_MEMBERSHIP_SCHEMA_ID",
    "output_payload",
    "render_cdhit_membership_normalizer_command",
    "render_contract_command",
    "shell_number",
    "validate_runner_relative_path",
]
