from __future__ import annotations

import json
import sys
import textwrap

import pytest
from pathlib import Path


def test_real_backend_uses_subprocess(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("numpy")
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import fold

    backend_id = "fake_backend"
    backend_script = tmp_path / "fake_backend.py"
    weights_path = tmp_path / "weights.pt"
    weights_path.write_text("weights", encoding="utf-8")
    backend_script.write_text(
        textwrap.dedent(
            f"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--fasta", required=True)
parser.add_argument("--output-pdb", required=True)
parser.add_argument("--output-confidence", required=True)
parser.add_argument("--model-weights", required=True)
args = parser.parse_args()

if args.model_weights != r"{weights_path}":
    raise SystemExit(2)

Path(args.output_pdb).parent.mkdir(parents=True, exist_ok=True)
Path(args.output_pdb).write_text("HEADER    REAL STRUCTURE\\nEND\\n", encoding="utf-8")

payload = {{
    "schema_version": "1.0",
    "backend_id": "{backend_id}",
    "mean_plddt": 87.5,
    "per_res_plddt": [{{"uid": "A:1", "plddt": 87.5}}],
    "clash_score": 1.2,
}}
Path(args.output_confidence).parent.mkdir(parents=True, exist_ok=True)
Path(args.output_confidence).write_text(json.dumps(payload), encoding="utf-8")
"""
        ).lstrip(),
        encoding="utf-8",
    )

    def _fail_mock(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_mock_fold should not be used in real mode")

    monkeypatch.setattr(fold, "_mock_fold", _fail_mock)

    variant_fasta = tmp_path / "variant.fasta"
    variant_fasta.write_text(">variant\nAAAA\n", encoding="utf-8")
    target_fasta = tmp_path / "target.fasta"
    target_fasta.write_text(">target\nAAAA\n", encoding="utf-8")

    output_dir = tmp_path / "runs" / "target" / "variant" / "outputs" / "structures" / backend_id
    pdb_path = output_dir / "variant.pdb"
    conf_path = output_dir / "structure_confidence.json"

    params = {
        "config": {
            "structure_backends": [backend_id],
            "structure_primary_backend": backend_id,
            "structure_backend_configs": {
                backend_id: {
                    "executable": str(backend_script),
                    "model_weights": str(weights_path),
                    "args": [],
                }
            },
        }
    }

    fold.run(
        inputs=[variant_fasta, target_fasta],
        outputs={"pdb": pdb_path, "structure_confidence": conf_path},
        params=params,
        workdir=tmp_path,
        mode="real",
    )

    assert "REAL STRUCTURE" in pdb_path.read_text(encoding="utf-8")
    confidence = json.loads(conf_path.read_text(encoding="utf-8"))
    assert confidence["backend_id"] == backend_id
