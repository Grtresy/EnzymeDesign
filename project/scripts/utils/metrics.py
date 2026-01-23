from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class MonteCarloResult:
    volume: float
    sasa: float


def monte_carlo_volume_sasa(
    coords: np.ndarray,
    radius: float = 1.9,
    samples: int = 20000,
    seed: int = 13,
) -> MonteCarloResult:
    if coords.size == 0:
        return MonteCarloResult(volume=0.0, sasa=0.0)
    rng = np.random.default_rng(seed)
    min_xyz = coords.min(axis=0) - radius
    max_xyz = coords.max(axis=0) + radius
    box = max_xyz - min_xyz
    points = rng.random((samples, 3)) * box + min_xyz
    diff = points[:, None, :] - coords[None, :, :]
    dist2 = (diff**2).sum(axis=2)
    inside = (dist2 <= radius**2).any(axis=1)
    volume = inside.mean() * box.prod()
    surface_points = rng.random((samples, 3)) * box + min_xyz
    dist2_surface = ((surface_points[:, None, :] - coords[None, :, :]) ** 2).sum(axis=2)
    near = (dist2_surface <= (radius * 1.2) ** 2).any(axis=1)
    sasa = near.mean() * box.prod() / (radius * 2.5)
    return MonteCarloResult(volume=float(volume), sasa=float(sasa))


def normalize_score(value: float, min_val: float, max_val: float) -> float:
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))

