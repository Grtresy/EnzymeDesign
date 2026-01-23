from __future__ import annotations

from pathlib import Path

from ._common import TOOL_VERSION, ToolRunResult, build_tunnels, require_executable, write_json


def get_version() -> str:
    return TOOL_VERSION


def run(
    pdb_path: str | Path,
    output_dir: str | Path,
    mode: str = "mock",
) -> ToolRunResult:
    output_path = Path(output_dir)
    tunnels_path = output_path / "tunnels.json"

    if mode == "mock":
        write_json(tunnels_path, build_tunnels())
        return ToolRunResult(outputs={"tunnels": str(tunnels_path)}, command=None)

    executable = require_executable("caver")
    command = [executable, "-p", str(pdb_path), "-o", str(output_path)]
    if not tunnels_path.exists():
        raise RuntimeError(
            "Expected CAVER output not found. Ensure CAVER ran successfully."
        )
    write_json(tunnels_path, build_tunnels())
    return ToolRunResult(outputs={"tunnels": str(tunnels_path)}, command=command)
