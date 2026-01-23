from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_paths(paths: Iterable[Path]) -> str:
    parts = []
    for path in paths:
        if not path.exists():
            parts.append(f"{path}:missing")
            continue
        parts.append(f"{path}:{sha256_file(path)}")
    return sha256_text("|".join(parts))


def sha256_json(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256_bytes(payload)

