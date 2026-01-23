from __future__ import annotations

from pathlib import Path

from ._common import TOOL_VERSION, ToolRunResult, build_pockets, require_executable, write_json


def get_version() -> str:
    return TOOL_VERSION


def run(
    pdb_path: str | Path,
    output_dir: str | Path,
    mode: str = "mock",
) -> ToolRunResult:
    output_path = Path(output_dir)
    pockets_path = output_path / "pockets.json"

    if mode == "mock":
        write_json(pockets_path, build_pockets())
        return ToolRunResult(outputs={"pockets": str(pockets_path)}, command=None)

    executable = require_executable("fpocket")
    command = [executable, "-f", str(pdb_path)]
    if not pockets_path.exists():
        raise RuntimeError(
            "Expected fpocket output not found. Ensure fpocket ran successfully."
        )
    write_json(pockets_path, build_pockets())
    return ToolRunResult(outputs={"pockets": str(pockets_path)}, command=command)
