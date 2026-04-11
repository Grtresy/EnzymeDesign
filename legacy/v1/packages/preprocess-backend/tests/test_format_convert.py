from __future__ import annotations

from pathlib import Path

import pytest

from preprocess_backend.operations.format_convert import convert_format


def test_convert_format_cif_to_pdb(monkeypatch: pytest.MonkeyPatch, molecular_files: dict[str, Path]) -> None:
    def fake_convert(input_path: Path, fmt_in: str, fmt_out: str, output_path: Path) -> None:
        assert fmt_in == "cif"
        assert fmt_out == "pdb"
        output_path.write_text("ATOM\n", encoding="utf-8")

    monkeypatch.setattr(
        "preprocess_backend.operations.format_convert._convert_with_openbabel",
        fake_convert,
    )

    result = convert_format(molecular_files["cif"], "pdb")

    assert result.fmt_in == "cif"
    assert result.fmt_out == "pdb"
    assert Path(result.output_path).suffix == ".pdb"
    assert Path(result.output_path).exists()


def test_convert_format_sdf_to_pdbqt(monkeypatch: pytest.MonkeyPatch, molecular_files: dict[str, Path], tmp_path: Path) -> None:
    target = tmp_path / "ligand.pdbqt"

    def fake_convert(input_path: Path, fmt_in: str, fmt_out: str, output_path: Path) -> None:
        assert input_path == molecular_files["sdf"]
        assert fmt_in == "sdf"
        assert fmt_out == "pdbqt"
        assert output_path == target
        output_path.write_text("REMARK\n", encoding="utf-8")

    monkeypatch.setattr(
        "preprocess_backend.operations.format_convert._convert_with_openbabel",
        fake_convert,
    )

    result = convert_format(molecular_files["sdf"], "pdbqt", output_path=target)

    assert result.output_path == str(target)
    assert target.exists()


def test_convert_format_raises_for_unsupported_format(molecular_files: dict[str, Path]) -> None:
    with pytest.raises(ValueError, match="Unsupported format"):
        convert_format(molecular_files["cif"], "xyz")
