from __future__ import annotations

from pathlib import Path
import json
from typing import Any


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.root / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def run_root(self, run_id: str) -> Path:
        return self.root / run_id

    def ensure_run_layout(self, run_id: str) -> dict[str, Path]:
        run_root = self.run_root(run_id)
        inputs = run_root / "inputs"
        outputs = run_root / "outputs"
        logs = run_root / "logs"
        metadata = run_root / "metadata"
        for path in (inputs, outputs, logs, metadata):
            path.mkdir(parents=True, exist_ok=True)
        return {
            "run_root": run_root,
            "inputs": inputs,
            "outputs": outputs,
            "logs": logs,
            "metadata": metadata,
        }

    def write_json(self, run_id: str, name: str, data: dict[str, Any]) -> Path:
        layout = self.ensure_run_layout(run_id)
        output_path = layout["metadata"] / name
        output_path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
        return output_path

    def read_json(self, run_id: str, name: str) -> dict[str, Any]:
        path = self.run_root(run_id) / "metadata" / name
        return json.loads(path.read_text(encoding="utf-8"))

    def write_log(self, run_id: str, name: str, content: str) -> Path:
        layout = self.ensure_run_layout(run_id)
        output_path = layout["logs"] / name
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def write_inputs_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "inputs_manifest.json", data)

    def write_outputs_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "outputs_manifest.json", data)

    def write_preflight_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "preflight_manifest.json", data)

    def dedup_cache_path(self) -> Path:
        return self.cache_dir / "input_dedup.json"

    def load_dedup_cache(self) -> dict[str, str]:
        path = self.dedup_cache_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_dedup_cache(self, cache: dict[str, str]) -> Path:
        path = self.dedup_cache_path()
        path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
        return path
