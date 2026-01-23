from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_volume_metrics_real_mode(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import volume_metrics
    from utils.pdb import write_mock_pdb

    wt_fasta = tmp_path / "target.fasta"
    wt_fasta.write_text(">target\nAAAA\n", encoding="utf-8")
    variant_fasta = tmp_path / "variant.fasta"
    variant_fasta.write_text(">variant\nAAA\n", encoding="utf-8")

    wt_pdb = tmp_path / "reference_structure.pdb"
    variant_pdb = tmp_path / "variant.pdb"
    write_mock_pdb("AAAA", wt_pdb)
    write_mock_pdb("AAA", variant_pdb)

    output_path = tmp_path / "outputs" / "geometry_metrics.json"

    volume_metrics.run(
        inputs=[variant_pdb, wt_pdb, wt_fasta, variant_fasta],
        outputs={"geometry_metrics": output_path},
        params={"config": {"target_spec": {"shrink_mode": "both", "volume_method": "mc"}}},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["seq_length"] == 3
    assert data["wt_length"] == 4
    assert data["delta_length"] == -1
    assert data["shrink_mode"] == "both"
    assert data["volume_method"] == "mc"
