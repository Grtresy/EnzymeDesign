from __future__ import annotations

from typing import Any

from .client import call


def convert_format(*, artifact_id: str, output_format: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(call("preprocess.convert_format", {"artifact_id": artifact_id, "output_format": output_format, "params": dict(params or {})}))


def prepare_receptor(*, artifact_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(call("preprocess.prepare_receptor", {"artifact_id": artifact_id, "params": dict(params or {})}))


def prepare_ligand(*, artifact_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(call("preprocess.prepare_ligand", {"artifact_id": artifact_id, "params": dict(params or {})}))


def smiles_to_3d(*, smiles: str, title: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(call("preprocess.smiles_to_3d", {"smiles": smiles, "title": title, "params": dict(params or {})}))


__all__ = ["convert_format", "prepare_ligand", "prepare_receptor", "smiles_to_3d"]
