from __future__ import annotations

from pathlib import Path

from ._common import TOOL_VERSION, ToolRunResult, build_docking, require_executable, write_json


def get_version() -> str:
    return TOOL_VERSION


def run(
    receptor_path: str | Path,
    ligand_path: str | Path,
    output_dir: str | Path,
    mode: str = "mock",
) -> ToolRunResult:
    output_path = Path(output_dir)
    docking_path = output_path / "docking.json"

    if mode == "mock":
        write_json(docking_path, build_docking("diffdock"))
        return ToolRunResult(outputs={"docking": str(docking_path)}, command=None)

    executable = require_executable("diffdock")
    command = [
        executable,
        "--receptor",
        str(receptor_path),
        "--ligand",
        str(ligand_path),
        "--out",
        str(output_path),
    ]
    if not docking_path.exists():
        raise RuntimeError(
            "Expected DiffDock output not found. Ensure diffdock ran successfully."
        )
    write_json(docking_path, build_docking("diffdock"))
    return ToolRunResult(outputs={"docking": str(docking_path)}, command=command)
