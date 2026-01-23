from __future__ import annotations

from pathlib import Path

from ._common import TOOL_VERSION, ToolRunResult, require_executable


def get_version() -> str:
    return TOOL_VERSION


def run(
    sequence: str,
    output_dir: str | Path,
    mode: str = "mock",
    database: str = "uniclust30",
) -> ToolRunResult:
    output_path = Path(output_dir)
    msa_path = output_path / "alignment.a3m"

    if mode == "mock":
        output_path.mkdir(parents=True, exist_ok=True)
        msa_path.write_text(
            f">query\n{sequence}\n>mock_hit\n{sequence}\n"
        )
        return ToolRunResult(outputs={"msa": str(msa_path)}, command=None)

    executable = require_executable("hhblits")
    command = [
        executable,
        "-i",
        "input.fasta",
        "-d",
        database,
        "-oa3m",
        str(msa_path),
    ]
    if not msa_path.exists():
        raise RuntimeError(
            "Expected hhblits output not found. Ensure hhblits ran successfully."
        )
    return ToolRunResult(outputs={"msa": str(msa_path)}, command=command)
