from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from utils.io import write_json_atomic
from utils.pdb import parse_pdb_atoms


def get_version(mode: str) -> str:
    return "mock-residue-map-1.0" if mode == "mock" else "real-residue-map-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    atoms = parse_pdb_atoms(pdb_path)
    residues = []
    index_by_seq = {}
    index_by_auth = {}
    seen = {}
    seq_index = 0
    for atom in atoms:
        key = (atom.chain_id, atom.res_seq, atom.ins_code)
        if key not in seen:
            seq_index += 1
            uid = f"{atom.chain_id}:{atom.res_seq}{atom.ins_code}".strip()
            entry = {
                "uid": uid,
                "chain": atom.chain_id,
                "auth_seq_id": atom.res_seq,
                "ins_code": atom.ins_code,
                "res_name": atom.res_name,
                "seq_index_0based": seq_index - 1,
                "has_ca": False,
                "is_missing": False,
            }
            residues.append(entry)
            seen[key] = entry
            index_by_seq[str(seq_index - 1)] = uid
            index_by_auth[uid] = uid
        if atom.atom_name == "CA":
            seen[key]["has_ca"] = True

    payload = {
        "schema_version": "1.0",
        "residues": residues,
        "index": {"by_seq_index": index_by_seq, "by_auth": index_by_auth},
    }
    write_json_atomic(outputs["residue_map"], payload)

