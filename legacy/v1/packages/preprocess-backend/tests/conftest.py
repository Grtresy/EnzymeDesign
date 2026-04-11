from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def molecular_files(tmp_path: Path) -> dict[str, Path]:
    cif = tmp_path / "protein.cif"
    cif.write_text("data_test\n#\n", encoding="utf-8")

    sdf = tmp_path / "ligand.sdf"
    sdf.write_text("ligand\n$$$$\n", encoding="utf-8")

    pdb = tmp_path / "receptor.pdb"
    pdb.write_text("ATOM      1  N   GLY A   1\n", encoding="utf-8")

    return {"cif": cif, "sdf": sdf, "pdb": pdb}
