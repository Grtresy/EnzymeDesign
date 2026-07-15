from __future__ import annotations

import hashlib
import json
from pathlib import Path


def immutable_source_tree_digest(root: Path) -> str:
    """Hash the exact regular source files shipped into an execution runtime."""

    resolved_root = root.resolve()
    entries: list[dict[str, str]] = []
    for path in sorted(
        resolved_root.rglob("*"),
        key=lambda item: item.relative_to(resolved_root).as_posix(),
    ):
        relative_path = path.relative_to(resolved_root)
        if "__pycache__" in relative_path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if not path.is_file() or path.is_symlink():
            continue
        entries.append(
            {
                "path": relative_path.as_posix(),
                "content_digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return "sha256:" + hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["immutable_source_tree_digest"]
