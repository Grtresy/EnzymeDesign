from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_residue_map_parses_atoms(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import residue_map

    pdb_path = tmp_path / "variant.pdb"
    pdb_path.write_text(
        "\n".join(
            [
                "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C",
                "ATOM      2  CA  GLY A   2       1.000   0.000   0.000  1.00 20.00           C",
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fasta_path = tmp_path / "variant.fasta"
    fasta_path.write_text(">variant\nAG\n", encoding="utf-8")

    output_path = tmp_path / "outputs" / "residue_map.json"

    residue_map.run(
        inputs=[pdb_path, fasta_path],
        outputs={"residue_map": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data["residues"]) == 2
    assert data["residues"][0]["uid"] == "A:1"
    assert data["residues"][0]["has_ca"] is True
    assert data["index"]["by_seq_index"]["0"] == "A:1"
