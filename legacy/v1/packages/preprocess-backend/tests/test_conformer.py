from __future__ import annotations

from pathlib import Path

import pytest

from preprocess_backend.operations.conformer import smiles_to_3d


def test_smiles_to_3d_valid_smiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "ligand.sdf"

    def fake_generate(smiles: str, output_path: Path, n_confs: int) -> None:
        assert smiles == "CCO"
        assert n_confs == 2
        output_path.write_text("ligand\n$$$$\n", encoding="utf-8")

    monkeypatch.setattr(
        "preprocess_backend.operations.conformer._generate_3d_sdf",
        fake_generate,
    )

    result = smiles_to_3d("CCO", output_path=output, n_confs=2)

    assert result.output_path == str(output)
    assert result.fmt_out == "sdf"
    assert output.exists()


def test_smiles_to_3d_invalid_smiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "invalid.sdf"

    def fake_generate(smiles: str, output_path: Path, n_confs: int) -> None:
        raise ValueError("Invalid SMILES string")

    monkeypatch.setattr(
        "preprocess_backend.operations.conformer._generate_3d_sdf",
        fake_generate,
    )

    with pytest.raises(ValueError, match="Invalid SMILES"):
        smiles_to_3d("this-is-not-smiles", output_path=output)
