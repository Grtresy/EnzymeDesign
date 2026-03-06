from __future__ import annotations

from pathlib import Path

import pytest

from preprocess_backend.operations.receptor_prep import prepare_ligand, prepare_receptor


def test_prepare_receptor_runs_meeko(monkeypatch: pytest.MonkeyPatch, molecular_files: dict[str, Path], tmp_path: Path) -> None:
    output = tmp_path / "receptor.pdbqt"

    def fake_run(module: str, args: list[str]) -> None:
        assert module == "meeko.cli.mk_prepare_receptor"
        assert args[1] == str(molecular_files["pdb"])
        assert args[3] == str(output)
        assert args[4] == "--allow_bad_res"
        output.write_text("RECEPTOR\n", encoding="utf-8")

    monkeypatch.setattr(
        "preprocess_backend.operations.receptor_prep._run_meeko_cli",
        fake_run,
    )

    result = prepare_receptor(molecular_files["pdb"], output_path=output)

    assert result.fmt_out == "pdbqt"
    assert output.exists()


def test_prepare_ligand_from_smiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "ligand.pdbqt"

    def fake_smiles_to_3d(smiles: str, output_path: Path, n_confs: int = 1):
        output_path.write_text("ligand\n$$$$\n", encoding="utf-8")

    def fake_run(module: str, args: list[str]) -> None:
        assert module == "meeko.cli.mk_prepare_ligand"
        assert args[3] == str(output)
        output.write_text("LIGAND\n", encoding="utf-8")

    monkeypatch.setattr(
        "preprocess_backend.operations.receptor_prep.smiles_to_3d",
        fake_smiles_to_3d,
    )
    monkeypatch.setattr(
        "preprocess_backend.operations.receptor_prep._run_meeko_cli",
        fake_run,
    )

    result = prepare_ligand(smiles="CCO", output_path=output)

    assert result.input_path is None
    assert result.details["source"] == "smiles"
    assert output.exists()


def test_prepare_ligand_prefers_input_path_over_smiles(
    monkeypatch: pytest.MonkeyPatch,
    molecular_files: dict[str, Path],
    tmp_path: Path,
) -> None:
    output = tmp_path / "ligand.pdbqt"

    def fake_smiles_to_3d(smiles: str, output_path: Path, n_confs: int = 1):
        raise AssertionError("smiles_to_3d should not be called when input_path is provided")

    def fake_run(module: str, args: list[str]) -> None:
        assert module == "meeko.cli.mk_prepare_ligand"
        assert args[1] == str(molecular_files["sdf"])
        assert args[3] == str(output)
        output.write_text("LIGAND\n", encoding="utf-8")

    monkeypatch.setattr(
        "preprocess_backend.operations.receptor_prep.smiles_to_3d",
        fake_smiles_to_3d,
    )
    monkeypatch.setattr(
        "preprocess_backend.operations.receptor_prep._run_meeko_cli",
        fake_run,
    )

    result = prepare_ligand(
        input_path=molecular_files["sdf"],
        smiles="CCO",
        output_path=output,
    )

    assert result.input_path == str(molecular_files["sdf"])
    assert result.details["source"] == "file"
    assert output.exists()


def test_prepare_ligand_requires_input_or_smiles() -> None:
    with pytest.raises(ValueError, match="Either input_path or smiles"):
        prepare_ligand()
