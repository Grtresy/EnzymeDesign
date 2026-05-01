from pathlib import Path

import pytest

from preprocess_backend import PreprocessError
from preprocess_backend import convert_format
from preprocess_backend import prepare_ligand
from preprocess_backend import prepare_receptor


PDB_TEXT = """\
ATOM      1  N   GLY A   1      11.104  13.207   9.541  1.00 20.00           N
ATOM      2  CA  GLY A   1      12.560  13.164   9.650  1.00 20.00           C
END
"""


def test_prepare_receptor_converts_pdb_to_pdbqt(tmp_path: Path) -> None:
    source = tmp_path / "receptor.pdb"
    source.write_text(PDB_TEXT, encoding="utf-8")

    output = prepare_receptor(source, tmp_path / "receptor.pdbqt")

    assert output.read_text(encoding="utf-8").startswith("ATOM")


def test_prepare_ligand_copies_existing_pdbqt(tmp_path: Path) -> None:
    source = tmp_path / "ligand.pdbqt"
    source.write_text("MODEL 1\nENDMDL\n", encoding="utf-8")

    output = prepare_ligand(source, tmp_path / "prepared.pdbqt")

    assert output.read_text(encoding="utf-8") == "MODEL 1\nENDMDL\n"


def test_convert_format_reports_missing_input(tmp_path: Path) -> None:
    with pytest.raises(PreprocessError, match="does not exist"):
        convert_format(tmp_path / "missing.sdf", tmp_path / "out.pdbqt")
