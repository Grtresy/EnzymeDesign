from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any
import uuid


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_LEAF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self._ensure_contained_directory(
            self.root / "cache",
            root=self.root,
            field="artifact cache directory",
        )
        self.reservations_dir = self._ensure_contained_directory(
            self.root / "reservations",
            root=self.root,
            field="runner reservation directory",
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
        self._atomic_write(
            output_path,
            json.dumps(data, indent=2, sort_keys=True).encode("utf-8"),
            replace=True,
        )
        return output_path

    def write_json_once(
        self,
        run_id: str,
        name: str,
        data: dict[str, Any],
    ) -> Path:
        output_path = self._metadata_path(run_id, name)
        self._atomic_write(
            output_path,
            json.dumps(data, indent=2, sort_keys=True).encode("utf-8"),
            replace=False,
        )
        return output_path

    def write_reservation_once(
        self,
        identity_digest: str,
        data: dict[str, Any],
    ) -> Path:
        output_path = self._reservation_path(identity_digest)
        self._atomic_write(
            output_path,
            json.dumps(data, indent=2, sort_keys=True).encode("utf-8"),
            replace=False,
        )
        return output_path

    def read_reservation(self, identity_digest: str) -> dict[str, Any]:
        path = self._reservation_path(identity_digest)
        if not path.exists():
            raise FileNotFoundError(
                "No persisted runner execution reservation exists for the identity"
            )
        if path.is_symlink() or not path.is_file():
            raise ValueError("runner execution reservation is not a regular file")
        return json.loads(path.read_text(encoding="utf-8"))

    def _reservation_path(self, identity_digest: str) -> Path:
        normalized = str(identity_digest)
        if _SHA256_HEX.fullmatch(normalized) is None:
            raise ValueError("runner reservation identity digest must be sha256 hex")
        return self._safe_leaf_path(
            self.reservations_dir,
            f"{normalized}.json",
            field="runner reservation path",
        )

    def list_metadata(self, run_id: str, *, prefix: str) -> tuple[Path, ...]:
        if not _SAFE_LEAF_NAME.fullmatch(prefix):
            raise ValueError("artifact metadata prefix must be a safe leaf prefix")
        layout = self.ensure_run_layout(run_id)
        metadata_root = layout["metadata"].resolve()
        matches: list[Path] = []
        for path in metadata_root.iterdir():
            if not path.name.startswith(prefix):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError("artifact metadata entries must be regular files")
            if path.resolve().parent != metadata_root:
                raise ValueError("artifact metadata entry escapes the run root")
            matches.append(path)
        return tuple(sorted(matches, key=lambda item: item.name))

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, replace: bool) -> None:
        directory = path.parent.resolve()
        temporary = directory / f".{path.name}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path, follow_symlinks=False)
                temporary.unlink()
            directory_descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

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

    def read_log(self, run_id: str, name: str) -> str:
        layout = self.ensure_run_layout(run_id)
        normalized = str(name)
        if not _SAFE_LEAF_NAME.fullmatch(normalized):
            raise ValueError("artifact log name must be a safe leaf filename")
        path = self._safe_leaf_path(
            layout["logs"],
            normalized,
            field="artifact log path",
        )
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(
                f"No persisted runner log exists for run_id {run_id!r}"
            )
        return path.read_text(encoding="utf-8")

    def write_inputs_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "inputs_manifest.json", data)

    def write_outputs_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "outputs_manifest.json", data)

    def write_preflight_manifest(self, run_id: str, data: dict[str, Any]) -> Path:
        return self.write_json(run_id, "preflight_manifest.json", data)

    def write_runner_failure_manifest(
        self, run_id: str, data: dict[str, Any]
    ) -> Path:
        return self.write_json(run_id, "runner_failure.json", data)

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
        self._atomic_write(
            path,
            json.dumps(cache, indent=2, sort_keys=True).encode("utf-8"),
            replace=True,
        )
        return path
