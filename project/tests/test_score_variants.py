from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_score_variants_cli(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("yaml")
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    import score_variants

    structure_conf = tmp_path / "structure_confidence.json"
    structure_conf.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "backend_id": "mock",
                "mean_plddt": 90.0,
                "per_res_plddt": [{"uid": "A:1", "plddt": 90.0}],
                "clash_score": 1.0,
            }
        ),
        encoding="utf-8",
    )

    geometry = tmp_path / "geometry_metrics.json"
    geometry.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "seq_length": 1,
                "wt_length": 1,
                "delta_length": 0,
                "rg": 1.0,
                "wt_rg": 1.0,
                "delta_rg": 0.0,
                "sasa_total": 1.0,
                "wt_sasa_total": 1.0,
                "delta_sasa": 0.0,
                "volume_protein": 1.0,
                "wt_volume_protein": 1.0,
                "delta_volume": 0.0,
                "volume_method": "mock",
                "shrink_mode": "both",
                "notes": [],
            }
        ),
        encoding="utf-8",
    )

    conservation = tmp_path / "conservation.json"
    conservation.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "msa": {"n_seq": 1, "neff": 1.0, "coverage": 1.0},
                "per_residue": [{"uid": "A:1", "cons_score": 0.9, "gap_fraction": 0.0}],
            }
        ),
        encoding="utf-8",
    )

    residue_map = tmp_path / "residue_map.json"
    residue_map.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "residues": [
                    {
                        "uid": "A:1",
                        "chain": "A",
                        "auth_seq_id": 1,
                        "ins_code": "",
                        "res_name": "ALA",
                        "seq_index_0based": 0,
                        "has_ca": True,
                        "is_missing": False,
                    }
                ],
                "index": {"by_seq_index": {"0": "A:1"}, "by_auth": {"A:1": "A:1"}},
            }
        ),
        encoding="utf-8",
    )

    key_residues = tmp_path / "key_residues.json"
    key_residues.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "protected_residues": [{"uid": "A:1", "description": "core"}],
                "active_site_residues": [{"uid": "A:1", "description": "active"}],
            }
        ),
        encoding="utf-8",
    )

    hitl_decisions = tmp_path / "hitl_decisions.csv"
    hitl_decisions.write_text("variant_id,decision,reason\nvariant,keep,ok\n", encoding="utf-8")

    output_path = tmp_path / "runs" / "target" / "variant" / "outputs" / "scores" / "score_breakdown.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        "score_variants.py",
        "--structure-conf",
        str(structure_conf),
        "--geometry",
        str(geometry),
        "--conservation",
        str(conservation),
        "--residue-map",
        str(residue_map),
        "--key-residues",
        str(key_residues),
        "--hitl-decisions",
        str(hitl_decisions),
        "--output",
        str(output_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert score_variants.main() == 0

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["variant_id"] == "variant"
    assert "final_score" in data
    assert output_path.with_suffix(".json.meta.json").exists()
