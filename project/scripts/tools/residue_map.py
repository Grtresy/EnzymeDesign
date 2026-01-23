from __future__ import annotations

from pathlib import Path

from ._common import TOOL_VERSION, ToolRunResult, build_residue_map, require_executable, write_json


def get_version() -> str:
    return TOOL_VERSION


def run(
    source_sequence: str,
    target_sequence: str,
    output_dir: str | Path,
    mode: str = "mock",
) -> ToolRunResult:
    output_path = Path(output_dir)
    mapping_path = output_path / "residue_map.json"

    if mode == "mock":
        payload = build_residue_map(source_sequence, target_sequence)
        write_json(mapping_path, payload)
        return ToolRunResult(outputs={"residue_map": str(mapping_path)}, command=None)

    executable = require_executable("needle")
    alignment_path = output_path / "alignment.txt"
    command = [
        executable,
        "-asequence",
        source_sequence,
        "-bsequence",
        target_sequence,
        "-gapopen",
        "10",
        "-gapextend",
        "0.5",
        "-outfile",
        str(alignment_path),
    ]
    if not alignment_path.exists():
        raise RuntimeError(
            "Expected EMBOSS needle alignment output not found. "
            "Ensure the external tool ran successfully."
        )
    payload = build_residue_map(source_sequence, target_sequence)
    write_json(mapping_path, payload)
    return ToolRunResult(outputs={"residue_map": str(mapping_path)}, command=command)
