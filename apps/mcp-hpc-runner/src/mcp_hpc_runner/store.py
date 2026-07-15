from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_LEAF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self._ensure_contained_directory(
            self.root / "cache",
            root=self.root,
            field="artifact cache directory",
        )

    @staticmethod
    def _ensure_contained_directory(
        path: Path,
        *,
        root: Path,
        field: str,
    ) -> Path:
        if path.is_symlink():
            raise ValueError(f"{field} must not be a symbolic link")
        path.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"{field} escapes the artifact store root")
        if not resolved.is_dir():
            raise ValueError(f"{field} must be a directory")
        return resolved

    def run_root(self, run_id: str) -> Path:
        normalized = str(run_id)
        if not _SAFE_RUN_ID.fullmatch(normalized):
            raise ValueError(
                "run_id must contain only letters, digits, '.', '_', or '-' "
                "and must not contain path separators"
            )
        candidate = (self.root / normalized).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ValueError("run_id escapes the artifact store root")
        return candidate

    def _metadata_path(self, run_id: str, name: str) -> Path:
        normalized = str(name)
        if not _SAFE_LEAF_NAME.fullmatch(normalized):
            raise ValueError("artifact metadata name must be a safe leaf filename")
        layout = self.ensure_run_layout(run_id)
        return self._safe_leaf_path(
            layout["metadata"],
            normalized,
            field="artifact metadata path",
        )

    @staticmethod
    def _safe_leaf_path(directory: Path, name: str, *, field: str) -> Path:
        candidate = directory / name
        if candidate.is_symlink():
            raise ValueError(f"{field} must not be a symbolic link")
        resolved = candidate.resolve()
        if resolved.parent != directory.resolve():
            raise ValueError(f"{field} escapes its managed directory")
        return candidate

    def ensure_run_layout(self, run_id: str) -> dict[str, Path]:
        run_root = self.run_root(run_id)
        run_root = self._ensure_contained_directory(
            run_root,
            root=self.root,
            field="artifact run directory",
        )
        inputs = self._ensure_contained_directory(
            run_root / "inputs",
            root=run_root,
            field="artifact inputs directory",
        )
        outputs = self._ensure_contained_directory(
            run_root / "outputs",
            root=run_root,
            field="artifact outputs directory",
        )
        logs = self._ensure_contained_directory(
            run_root / "logs",
            root=run_root,
            field="artifact logs directory",
        )
        metadata = self._ensure_contained_directory(
            run_root / "metadata",
            root=run_root,
            field="artifact metadata directory",
        )
        return {
            "run_root": run_root,
            "inputs": inputs,
            "outputs": outputs,
            "logs": logs,
            "metadata": metadata,
        }

    def write_json(self, run_id: str, name: str, data: dict[str, Any]) -> Path:
        output_path = self._metadata_path(run_id, name)
        output_path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
        return output_path

    def read_json(self, run_id: str, name: str) -> dict[str, Any]:
        normalized = str(name)
        if not _SAFE_LEAF_NAME.fullmatch(normalized):
            raise ValueError("artifact metadata name must be a safe leaf filename")
        run_root = self.run_root(run_id)
        metadata_root = run_root / "metadata"
        if not run_root.exists() or not metadata_root.exists():
            raise FileNotFoundError(
                f"No persisted metadata exists for run_id {run_id!r}"
            )
        if run_root.is_symlink() or metadata_root.is_symlink():
            raise ValueError("artifact metadata directories must not be symbolic links")
        resolved_metadata_root = metadata_root.resolve()
        if resolved_metadata_root.parent != run_root.resolve():
            raise ValueError("artifact metadata directory escapes the run root")
        path = self._safe_leaf_path(
            resolved_metadata_root,
            normalized,
            field="artifact metadata path",
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def write_log(self, run_id: str, name: str, content: str) -> Path:
        layout = self.ensure_run_layout(run_id)
        normalized = str(name)
        if not _SAFE_LEAF_NAME.fullmatch(normalized):
            raise ValueError("artifact log name must be a safe leaf filename")
        output_path = self._safe_leaf_path(
            layout["logs"],
            normalized,
            field="artifact log path",
        )
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def write_inputs_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "inputs_manifest.json", data)

    def write_outputs_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "outputs_manifest.json", data)

    def write_preflight_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "preflight_manifest.json", data)

    def dedup_cache_path(self) -> Path:
        return self._safe_leaf_path(
            self.cache_dir,
            "input_dedup.json",
            field="artifact dedup cache path",
        )

    def load_dedup_cache(self) -> dict[str, str]:
        path = self.dedup_cache_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_dedup_cache(self, cache: dict[str, str]) -> Path:
        path = self.dedup_cache_path()
        path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
        return path
