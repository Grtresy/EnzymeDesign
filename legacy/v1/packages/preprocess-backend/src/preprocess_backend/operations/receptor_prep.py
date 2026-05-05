from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

from ..models import ConversionResult
from .conformer import smiles_to_3d


def _run_meeko_cli(module: str, args: list[str]) -> None:
    command = [sys.executable, "-m", module] + args
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown meeko error"
        raise RuntimeError(stderr)


def prepare_receptor(
    input_path: str | Path,
    output_path: str | Path | None = None,
) -> ConversionResult:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Input file does not exist: {src}")

    dest = Path(output_path) if output_path is not None else src.with_suffix(".pdbqt")
    dest.parent.mkdir(parents=True, exist_ok=True)

    _run_meeko_cli(
        "meeko.cli.mk_prepare_receptor",
        ["-i", str(src), "-p", str(dest), "--allow_bad_res"],
    )

    return ConversionResult(
        input_path=str(src),
        output_path=str(dest),
        fmt_in="pdb",
        fmt_out="pdbqt",
    )


def prepare_ligand(
    input_path: str | Path | None = None,
    smiles: str | None = None,
    output_path: str | Path | None = None,
) -> ConversionResult:
    if input_path is None and (smiles is None or not smiles.strip()):
        raise ValueError("Either input_path or smiles must be provided")

    source = Path(input_path) if input_path is not None else None
    generated_input: Path | None = None

    try:
        if source is None:
            with tempfile.NamedTemporaryFile(
                prefix="ligand_from_smiles_",
                suffix=".sdf",
                delete=False,
            ) as tmp_file:
                source = Path(tmp_file.name)
            generated_input = source
            smiles_to_3d(smiles=smiles or "", output_path=source)

        if not source.exists():
            raise FileNotFoundError(f"Ligand input file does not exist: {source}")

        dest = Path(output_path) if output_path is not None else source.with_suffix(".pdbqt")
        dest.parent.mkdir(parents=True, exist_ok=True)

        _run_meeko_cli("meeko.cli.mk_prepare_ligand", ["-i", str(source), "-o", str(dest)])

        return ConversionResult(
            input_path=str(source) if input_path is not None else None,
            output_path=str(dest),
            fmt_in=source.suffix.lstrip(".").lower() if source.suffix else None,
            fmt_out="pdbqt",
            details={"source": "smiles" if generated_input is not None else "file"},
        )
    finally:
        if generated_input is not None:
            generated_input.unlink(missing_ok=True)
