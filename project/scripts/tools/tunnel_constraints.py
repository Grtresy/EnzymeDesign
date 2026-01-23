from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import read_json, write_json_atomic


def get_version(mode: str) -> str:
    return "mock-tunnel-constraints-1.0" if mode == "mock" else "real-tunnel-constraints-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    tunnels = read_json(next(p for p in inputs if p.name == "tunnels.json"))
    tunnel_list = tunnels.get("tunnels") or []
    tunnel = max(
        tunnel_list,
        key=lambda item: item.get("throughput", 0.0),
        default=None,
    )
    lining = tunnel.get("lining_residues", []) if tunnel else []
    yaml_payload = {
        "schema_version": "1.0",
        "tunnel_id": tunnel.get("tunnel_id") if tunnel else None,
        "lining_residues": [{"uid": uid, "source": "caver"} for uid in lining],
    }
    outputs["tunnel_lining_residues"].write_text(
        yaml.safe_dump(yaml_payload, sort_keys=False),
        encoding="utf-8",
    )

    geometry_payload = {
        "schema_version": "1.0",
        "tunnel_id": tunnel.get("tunnel_id") if tunnel else None,
        "bottleneck_radius": tunnel.get("bottleneck_radius") if tunnel else None,
        "length": tunnel.get("length") if tunnel else None,
        "centerline": [],
        "radius_profile": [],
    }
    write_json_atomic(outputs["tunnel_geometry"], geometry_payload)
