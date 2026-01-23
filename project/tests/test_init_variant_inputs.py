from __future__ import annotations

import json
import sys
from pathlib import Path


def test_init_variant_inputs_copies_files(tmp_path: Path) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import init_variant_inputs

    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    variants_dir = inputs_dir / "variants"
    variants_dir.mkdir()

    variant_fasta = variants_dir / "var1.fasta"
    variant_fasta.write_text(">var1\nAAAA\n", encoding="utf-8")

    variant_list = inputs_dir / "variants.txt"
    variant_list.write_text("variant_id\nvar1\n", encoding="utf-8")
    target_fasta = inputs_dir / "target.fasta"
    target_fasta.write_text(">target\nAAAA\n", encoding="utf-8")
    reference_structure = inputs_dir / "reference_structure.pdb"
    reference_structure.write_text("ATOM", encoding="utf-8")
    key_residues = inputs_dir / "key_residues.json"
    key_residues.write_text("{}", encoding="utf-8")
    hitl_decisions = inputs_dir / "hitl_decisions.csv"
    hitl_decisions.write_text("variant_id,decision,reason\n", encoding="utf-8")

    ligand_dir = inputs_dir / "ligands"
    ligand_dir.mkdir()
    ligand_path = ligand_dir / "ligand.sdf"
    ligand_path.write_text("LIGAND", encoding="utf-8")

    output_path = tmp_path / "runs" / "target" / "var1" / "inputs" / "snapshot.json"

    init_variant_inputs.run(
        inputs=[
            variant_list,
            target_fasta,
            reference_structure,
            key_residues,
            hitl_decisions,
            variant_fasta,
        ],
        outputs={"snapshot": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["variant_id"] == "var1"
    copied_files = {Path(path).name for path in data["files"]}
    assert "variants.txt" in copied_files
    assert "ligand.sdf" in copied_files
