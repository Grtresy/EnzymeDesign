from __future__ import annotations

from typing import Any

from .client import call
from .hpc import HpcWorkspace


def vina(
    *,
    receptor: dict[str, Any],
    ligand: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "docking.vina",
            {
                "receptor": dict(receptor),
                "ligand": dict(ligand),
                "placement": placement.to_dict(),
                "expected_outputs": list(expected_outputs),
                "params": dict(params or {}),
            },
        )
    )


__all__ = ["vina"]
