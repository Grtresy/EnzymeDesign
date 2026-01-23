from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic
from utils.pdb import write_mock_pdb


def get_version(mode: str) -> str:
    return "mock-fold-1.0" if mode == "mock" else "real-fold-1.0"


def _mock_fold(sequence: str, pdb_path: Path, conf_path: Path, backend_id: str) -> None:
    write_mock_pdb(sequence, pdb_path)
    rng = np.random.default_rng(7)
    plddt = rng.normal(78, 4, size=len(sequence)).clip(50, 95)
    per_res = [
        {"uid": f"A:{idx}", "plddt": float(score)}
        for idx, score in enumerate(plddt, start=1)
    ]
    payload = {
        "schema_version": "1.0",
        "backend_id": backend_id,
        "mean_plddt": float(np.mean(plddt)) if len(plddt) else 0.0,
        "per_res_plddt": per_res,
        "clash_score": float(max(0.0, 10.0 - np.mean(plddt) / 10.0)),
    }
    write_json_atomic(conf_path, payload)


def _fallback_confidence(sequence: str, conf_path: Path, backend_id: str) -> None:
    plddt = np.zeros(len(sequence), dtype=float)
    per_res = [
        {"uid": f"A:{idx}", "plddt": float(score)}
        for idx, score in enumerate(plddt, start=1)
    ]
    payload = {
        "schema_version": "1.0",
        "backend_id": backend_id,
        "mean_plddt": float(np.mean(plddt)) if len(plddt) else 0.0,
        "per_res_plddt": per_res,
        "clash_score": 0.0,
    }
    write_json_atomic(conf_path, payload)


def _ordered_backends(config: dict) -> List[str]:
    backends = list(config.get("structure_backends", ["esmfold"]))
    primary = config.get("structure_primary_backend")
    if primary:
        return [primary] + [backend for backend in backends if backend != primary]
    return backends


def _resolve_backend_paths(pdb_path: Path, conf_path: Path, backend_id: str) -> tuple[Path, Path]:
    def replace_backend(path: Path) -> Path:
        parts = list(path.parts)
        if "structures" in parts:
            idx = parts.index("structures")
            if idx + 1 < len(parts):
                parts[idx + 1] = backend_id
                return Path(*parts)
        return path

    return replace_backend(pdb_path), replace_backend(conf_path)


def _backend_executable(backend_id: str, backend_config: dict) -> tuple[str, bool]:
    executable = backend_config.get("executable") or backend_config.get("script") or backend_id
    is_script = Path(executable).suffix == ".py"
    return executable, is_script


def _executable_available(executable: str, is_script: bool) -> bool:
    if is_script:
        return Path(executable).exists()
    return Path(executable).exists() or shutil.which(executable) is not None


def _build_backend_command(
    backend_id: str,
    backend_config: dict,
    fasta_path: Path,
    pdb_path: Path,
    conf_path: Path,
) -> List[str] | None:
    executable, is_script = _backend_executable(backend_id, backend_config)
    if not _executable_available(executable, is_script):
        return None
    command = [sys.executable, executable] if is_script else [executable]
    model_weights = backend_config.get("model_weights")
    if model_weights:
        command += ["--model-weights", str(model_weights)]
    extra_args = backend_config.get("args", [])
    command += [str(arg) for arg in extra_args]
    command += [
        "--fasta",
        str(fasta_path),
        "--output-pdb",
        str(pdb_path),
        "--output-confidence",
        str(conf_path),
    ]
    return command


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fasta_path = next(p for p in inputs if p.suffix == ".fasta" and p.name != "target.fasta")
    sequence = "".join(
        line.strip()
        for line in fasta_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(">")
    )
    pdb_path = outputs["pdb"]
    conf_path = outputs["structure_confidence"]
    config = params["config"]
    backends = _ordered_backends(config)

    if mode == "mock":
        _mock_fold(sequence, pdb_path, conf_path, backends[0])
        return

    backend_configs = config.get("structure_backend_configs", {})
    errors: List[str] = []

    for backend_id in backends:
        backend_config = backend_configs.get(backend_id, {})
        actual_pdb_path, actual_conf_path = _resolve_backend_paths(
            pdb_path, conf_path, backend_id
        )
        command = _build_backend_command(
            backend_id, backend_config, fasta_path, actual_pdb_path, actual_conf_path
        )
        if not command:
            continue
        actual_pdb_path.parent.mkdir(parents=True, exist_ok=True)
        actual_conf_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append(
                f"{backend_id} failed with code {result.returncode}: {result.stderr.strip()}"
            )
            continue
        if not actual_pdb_path.exists():
            errors.append(f"{backend_id} did not produce PDB at {actual_pdb_path}")
            continue
        if not actual_conf_path.exists():
            _fallback_confidence(sequence, actual_conf_path, backend_id)
        if actual_pdb_path != pdb_path:
            pdb_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(actual_pdb_path, pdb_path)
        if actual_conf_path != conf_path:
            conf_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(actual_conf_path, conf_path)
        return

    detail = "; ".join(errors) if errors else "No available folding backend found"
    raise DeterministicToolError(detail)
