from __future__ import annotations

import os
from pathlib import Path
import tempfile

from ..models import ConversionResult


def _rdkit_modules() -> tuple[object, object]:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError(
            "rdkit import failed. Install preprocess-backend dependencies with uv sync."
        ) from exc

    return Chem, AllChem


def _generate_3d_sdf(smiles: str, output_path: Path, n_confs: int) -> None:
    Chem, AllChem = _rdkit_modules()

    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError("Invalid SMILES string")

    molecule = Chem.AddHs(molecule)
    params = AllChem.ETKDGv3()
    conf_ids = list(AllChem.EmbedMultipleConfs(molecule, numConfs=n_confs, params=params))
    if not conf_ids:
        raise RuntimeError("Failed to embed any 3D conformers")

    for conf_id in conf_ids:
        AllChem.MMFFOptimizeMolecule(molecule, confId=conf_id)

    writer = Chem.SDWriter(str(output_path))
    try:
        for conf_id in conf_ids:
            writer.write(molecule, confId=conf_id)
    finally:
        writer.close()


def _default_output_path() -> Path:
    fd, path = tempfile.mkstemp(prefix="smiles_3d_", suffix=".sdf")
    os.close(fd)
    return Path(path)


def smiles_to_3d(
    smiles: str,
    output_path: str | Path | None = None,
    n_confs: int = 1,
) -> ConversionResult:
    if not smiles.strip():
        raise ValueError("SMILES string must not be empty")
    if n_confs < 1:
        raise ValueError("n_confs must be >= 1")

    dest = Path(output_path) if output_path is not None else _default_output_path()
    dest.parent.mkdir(parents=True, exist_ok=True)

    _generate_3d_sdf(smiles=smiles, output_path=dest, n_confs=n_confs)

    return ConversionResult(
        output_path=str(dest),
        fmt_in="smiles",
        fmt_out="sdf",
        details={"n_confs": n_confs},
    )
