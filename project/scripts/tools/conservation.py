from __future__ import annotations

from pathlib import Path

from ._common import TOOL_VERSION, ToolRunResult, build_conservation, require_executable, write_json


def get_version() -> str:
    return TOOL_VERSION


def run(
    sequence: str,
    output_dir: str | Path,
    mode: str = "mock",
) -> ToolRunResult:
    output_path = Path(output_dir)
    conservation_path = output_path / "conservation.json"

    residues = [(idx + 1, res) for idx, res in enumerate(sequence)]

    if mode == "mock":
        payload = build_conservation(residues)
        write_json(conservation_path, payload)
        return ToolRunResult(
            outputs={"conservation": str(conservation_path)}, command=None
        )

    executable = require_executable("rate4site")
    command = [
        executable,
        "-s",
        "alignment.fasta",
        "-o",
        str(conservation_path),
    ]
    if not conservation_path.exists():
        raise RuntimeError(
            "Expected rate4site output not found. Ensure the tool ran successfully."
        )
    payload = build_conservation(residues)
    write_json(conservation_path, payload)
    return ToolRunResult(outputs={"conservation": str(conservation_path)}, command=command)
