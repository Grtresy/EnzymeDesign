from __future__ import annotations

from pathlib import Path

from ._common import (
    TOOL_VERSION,
    ToolRunResult,
    build_structure_confidence,
    require_executable,
    write_json,
    write_minimal_pdb,
)


def get_version() -> str:
    return TOOL_VERSION


def run(
    sequence: str | None,
    output_dir: str | Path,
    mode: str = "mock",
    model: str = "mockfold",
) -> ToolRunResult:
    output_path = Path(output_dir)
    pdb_path = output_path / "structure.pdb"
    confidence_path = output_path / "structure_confidence.json"

    if mode == "mock":
        write_minimal_pdb(pdb_path)
        residues = [(1, "A"), (2, "C"), (3, "D")]
        write_json(confidence_path, build_structure_confidence(residues, model=model))
        return ToolRunResult(
            outputs={
                "pdb": str(pdb_path),
                "structure_confidence": str(confidence_path),
            },
            command=None,
        )

    executable = require_executable("colabfold_batch")
    fasta_path = output_path / "input.fasta"
    fasta_path.write_text(f">query\n{sequence or 'ACD'}\n")
    command = [executable, str(fasta_path), str(output_path)]
    if not pdb_path.exists():
        raise RuntimeError(
            "Expected fold output not found. Ensure colabfold_batch ran successfully."
        )
    if not confidence_path.exists():
        residues = [(1, "A")]
        write_json(confidence_path, build_structure_confidence(residues, model=model))
    return ToolRunResult(
        outputs={
            "pdb": str(pdb_path),
            "structure_confidence": str(confidence_path),
        },
        command=command,
    )
