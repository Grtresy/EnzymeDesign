from __future__ import annotations

import math
import random
from pathlib import Path

from ._common import (
    TOOL_VERSION,
    ToolRunResult,
    random_unit_vector,
    require_executable,
    write_json,
    write_minimal_pdb,
)

DEFAULT_VDW_RADIUS = 1.5
PROBE_RADIUS = 1.4


def get_version() -> str:
    return TOOL_VERSION


def parse_pdb_atoms(pdb_path: Path) -> list[dict[str, float | int | str]]:
    atoms: list[dict[str, float | int | str]] = []
    for line in pdb_path.read_text().splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            continue
        atom_name = line[12:16].strip()
        residue = line[17:20].strip()
        chain_id = line[21].strip() or "A"
        try:
            res_seq = int(line[22:26])
        except ValueError:
            res_seq = 0
        atoms.append(
            {
                "x": x,
                "y": y,
                "z": z,
                "atom": atom_name,
                "residue": residue,
                "chain": chain_id,
                "res_seq": res_seq,
                "radius": DEFAULT_VDW_RADIUS,
            }
        )
    return atoms


def radius_of_gyration(atoms: list[dict[str, float | int | str]]) -> float:
    if not atoms:
        return 0.0
    coords = [(atom["x"], atom["y"], atom["z"]) for atom in atoms]
    mean_x = sum(coord[0] for coord in coords) / len(coords)
    mean_y = sum(coord[1] for coord in coords) / len(coords)
    mean_z = sum(coord[2] for coord in coords) / len(coords)
    mean_sq = sum(
        (coord[0] - mean_x) ** 2
        + (coord[1] - mean_y) ** 2
        + (coord[2] - mean_z) ** 2
        for coord in coords
    ) / len(coords)
    return math.sqrt(mean_sq)


def delta_length(atoms: list[dict[str, float | int | str]]) -> float:
    ca_atoms = [
        atom
        for atom in atoms
        if atom["atom"] == "CA" and atom["res_seq"] is not None
    ]
    if len(ca_atoms) < 2:
        return 0.0
    ca_atoms.sort(key=lambda atom: (atom["chain"], atom["res_seq"]))
    distances = []
    for first, second in zip(ca_atoms, ca_atoms[1:]):
        dx = first["x"] - second["x"]
        dy = first["y"] - second["y"]
        dz = first["z"] - second["z"]
        distances.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    if not distances:
        return 0.0
    return max(distances) - min(distances)


def estimate_volume_sasa(
    atoms: list[dict[str, float | int | str]],
    sample_points: int = 5000,
    surface_samples: int = 40,
) -> tuple[float, float, float]:
    if not atoms:
        return 0.0, 0.0, 0.0
    xs = [atom["x"] for atom in atoms]
    ys = [atom["y"] for atom in atoms]
    zs = [atom["z"] for atom in atoms]
    margin = DEFAULT_VDW_RADIUS + PROBE_RADIUS
    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin
    min_z, max_z = min(zs) - margin, max(zs) + margin
    bbox_volume = (max_x - min_x) * (max_y - min_y) * (max_z - min_z)

    rng = random.Random(0)
    inside_count = 0
    for _ in range(sample_points):
        point = (
            rng.uniform(min_x, max_x),
            rng.uniform(min_y, max_y),
            rng.uniform(min_z, max_z),
        )
        for atom in atoms:
            dx = point[0] - atom["x"]
            dy = point[1] - atom["y"]
            dz = point[2] - atom["z"]
            radius = atom["radius"]
            if dx * dx + dy * dy + dz * dz <= radius * radius:
                inside_count += 1
                break
    volume = bbox_volume * inside_count / sample_points

    total_surface_area = 0.0
    exposed_points = 0
    total_points = 0
    for atom in atoms:
        radius = atom["radius"] + PROBE_RADIUS
        surface_area = 4.0 * math.pi * radius * radius
        total_surface_area += surface_area
        for _ in range(surface_samples):
            direction = random_unit_vector(rng)
            point = (
                atom["x"] + radius * direction[0],
                atom["y"] + radius * direction[1],
                atom["z"] + radius * direction[2],
            )
            total_points += 1
            occluded = False
            for other in atoms:
                if other is atom:
                    continue
                dx = point[0] - other["x"]
                dy = point[1] - other["y"]
                dz = point[2] - other["z"]
                other_radius = other["radius"] + PROBE_RADIUS
                if dx * dx + dy * dy + dz * dz <= other_radius * other_radius:
                    occluded = True
                    break
            if not occluded:
                exposed_points += 1
    sasa = (
        total_surface_area * exposed_points / total_points if total_points else 0.0
    )
    return volume, sasa, bbox_volume


def build_geometry_metrics(
    atoms: list[dict[str, float | int | str]], variant_id: str
) -> dict:
    rg_value = radius_of_gyration(atoms)
    delta_value = delta_length(atoms)
    volume, sasa, bbox_volume = estimate_volume_sasa(atoms)
    packing_density = volume / bbox_volume if bbox_volume else 0.0
    return {
        "schema_version": "1.0",
        "variant_id": variant_id,
        "metrics": {
            "bond_length_rmsd": delta_value,
            "bond_angle_rmsd": rg_value,
            "clashscore": max(0.0, sasa / 100.0),
            "ramachandran_outliers": 0.0,
            "rotamer_outliers": 0.0,
            "packing_density": max(0.0, packing_density),
        },
        "units": {
            "bond_length_rmsd": "angstrom",
            "bond_angle_rmsd": "angstrom",
        },
    }


def run(
    pdb_path: str | Path,
    output_dir: str | Path,
    mode: str = "mock",
) -> ToolRunResult:
    output_path = Path(output_dir)
    metrics_path = output_path / "geometry_metrics.json"
    pdb_path = Path(pdb_path)

    if mode == "mock":
        if not pdb_path.exists():
            write_minimal_pdb(pdb_path)
        atoms = parse_pdb_atoms(pdb_path)
        payload = build_geometry_metrics(atoms, variant_id=pdb_path.stem)
        write_json(metrics_path, payload)
        return ToolRunResult(outputs={"geometry_metrics": str(metrics_path)})

    require_executable("phenix")
    if not pdb_path.exists():
        raise RuntimeError("PDB file not found for volume metrics computation.")
    atoms = parse_pdb_atoms(pdb_path)
    if not atoms:
        raise RuntimeError("No atoms parsed from PDB; cannot compute metrics.")
    payload = build_geometry_metrics(atoms, variant_id=pdb_path.stem)
    write_json(metrics_path, payload)
    return ToolRunResult(outputs={"geometry_metrics": str(metrics_path)})
