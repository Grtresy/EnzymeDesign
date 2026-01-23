from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import write_json_atomic
from utils.pdb import parse_pdb_atoms


def get_version(mode: str) -> str:
    return "mock-evidence-lit-1.0" if mode == "mock" else "real-evidence-lit-1.0"


def _collect_residues(pdb_path: Path) -> List[str]:
    atoms = parse_pdb_atoms(pdb_path)
    residues = []
    seen = set()
    for atom in atoms:
        key = (atom.chain_id, atom.res_seq, atom.ins_code)
        if key in seen:
            continue
        seen.add(key)
        uid = f"{atom.chain_id}:{atom.res_seq}{atom.ins_code}".strip()
        residues.append(uid)
    return residues


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    residues = _collect_residues(pdb_path)
    key_residues = residues[:5] if residues else []

    hits = []
    for idx, uid in enumerate(key_residues, start=1):
        hits.append(
            {
                "hit_id": f"mock-hit-{idx}",
                "title": "Literature placeholder evidence",
                "source": "mock",
                "residues": [uid],
                "notes": "Replace with real RAG/Lit search results.",
            }
        )

    payload = {
        "schema_version": "1.0",
        "query": {
            "target_id": params.get("config", {}).get("target_id", "target"),
            "mode": mode,
        },
        "hits": hits,
    }
    write_json_atomic(outputs["lit_hits"], payload)

    key_payload = {
        "schema_version": "1.0",
        "protected_residues": [{"uid": uid, "source": "lit"} for uid in key_residues],
    }
    outputs["key_residues_from_lit"].write_text(
        yaml.safe_dump(key_payload, sort_keys=False),
        encoding="utf-8",
    )
