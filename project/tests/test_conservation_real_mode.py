from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest


def test_conservation_real_mode_uses_msa(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import conservation

    pdb_path = tmp_path / "variant.pdb"
    pdb_path.write_text(
        "\n".join(
            [
                "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C",
                "ATOM      2  CA  CYS A   2       1.500   0.000   0.000  1.00 20.00           C",
                "ATOM      3  CA  ASP A   3       3.000   0.000   0.000  1.00 20.00           C",
                "ATOM      4  CA  GLU A   4       4.500   0.000   0.000  1.00 20.00           C",
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    msa_path = tmp_path / "msa.a3m"
    msa_path.write_text(
        ">seq1\nACDE\n>seq2\nAC-E\n>seq3\nACDE\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "outputs" / "conservation.json"

    conservation.run(
        inputs=[pdb_path, msa_path],
        outputs={"conservation": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["msa"]["n_seq"] == 3
    assert math.isclose(data["msa"]["coverage"], 11 / 12, rel_tol=1e-6)
    per_residue = data["per_residue"]
    assert per_residue[0]["uid"] == "A:1"
    assert math.isclose(per_residue[2]["gap_fraction"], 1 / 3, rel_tol=1e-6)
    assert math.isclose(per_residue[2]["cons_score"], 1.0, rel_tol=1e-6)
