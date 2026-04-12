from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
ENV_FILES = (".env", ".env.test")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _load_env_files() -> None:
    for file_name in ENV_FILES:
        path = REPO_ROOT / file_name
        if not path.exists():
            continue
        for key, value in _parse_env_file(path).items():
            if key in os.environ and file_name != ".env.test":
                continue
            os.environ[key] = value


_load_env_files()
