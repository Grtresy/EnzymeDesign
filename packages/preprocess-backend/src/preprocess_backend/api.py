from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


class PreprocessError(RuntimeError):
    pass


def _require_input(path: str | Path) -> Path:
    input_path = Path(path).expanduser()
    if not input_path.exists():
        raise PreprocessError(f"input file does not exist: {input_path}")
    if not input_path.is_file():
        raise PreprocessError(f"input path is not a file: {input_path}")
    return input_path


def _prepare_output(path: str | Path) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _run_obabel(input_path: Path, output_path: Path, *, input_format: str | None = None) -> None:
    executable = shutil.which("obabel")
    if executable is None:
        raise PreprocessError("OpenBabel executable 'obabel' is required for this conversion")
    command = [executable, str(input_path), "-O", str(output_path)]
    if input_format:
        command.extend(["-i", input_format])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "OpenBabel conversion failed").strip()
        raise PreprocessError(message)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PreprocessError(f"conversion produced no output: {output_path}")


def _copy_if_same_format(input_path: Path, output_path: Path) -> bool:
    if input_path.suffix.lower() == output_path.suffix.lower():
        shutil.copyfile(input_path, output_path)
        return True
    return False


def _simple_pdb_to_pdbqt(input_path: Path, output_path: Path) -> None:
    lines = input_path.read_text(encoding="utf-8", errors="replace").splitlines()
    atom_lines = [line for line in lines if line.startswith(("ATOM", "HETATM", "TER", "END"))]
    if not atom_lines:
        raise PreprocessError("PDB input does not contain ATOM/HETATM records")
    output_path.write_text(
        "\n".join(atom_lines) + "\n",
        encoding="utf-8",
    )


def convert_format(input_path: str | Path, output_path: str | Path, *, input_format: str | None = None) -> Path:
    source = _require_input(input_path)
    target = _prepare_output(output_path)
    if _copy_if_same_format(source, target):
        return target
    if source.suffix.lower() == ".pdb" and target.suffix.lower() == ".pdbqt":
        _simple_pdb_to_pdbqt(source, target)
        return target
    _run_obabel(source, target, input_format=input_format)
    return target


def prepare_receptor(input_path: str | Path, output_path: str | Path) -> Path:
    source = _require_input(input_path)
    target = _prepare_output(output_path)
    if target.suffix.lower() != ".pdbqt":
        raise PreprocessError("prepare_receptor output must use .pdbqt")
    if source.suffix.lower() == ".pdbqt":
        shutil.copyfile(source, target)
        return target
    return convert_format(source, target)


def prepare_ligand(input_path: str | Path, output_path: str | Path) -> Path:
    source = _require_input(input_path)
    target = _prepare_output(output_path)
    if target.suffix.lower() != ".pdbqt":
        raise PreprocessError("prepare_ligand output must use .pdbqt")
    if source.suffix.lower() == ".pdbqt":
        shutil.copyfile(source, target)
        return target
    return convert_format(source, target)


def smiles_to_3d(smiles: str, output_path: str | Path) -> Path:
    target = _prepare_output(output_path)
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise PreprocessError("RDKit is required for SMILES to 3D conversion") from exc

    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise PreprocessError("invalid SMILES string")
    molecule = Chem.AddHs(molecule)
    status = AllChem.EmbedMolecule(molecule, randomSeed=0xF00D)
    if status != 0:
        raise PreprocessError("RDKit failed to embed the SMILES molecule")
    AllChem.UFFOptimizeMolecule(molecule)
    writer = Chem.SDWriter(str(target))
    writer.write(molecule)
    writer.close()
    if not target.exists() or target.stat().st_size == 0:
        raise PreprocessError(f"SMILES conversion produced no output: {target}")
    return target
