from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.test_gate.hypothesis_storage import (  # noqa: E402
    configure_hypothesis_storage,
)


ENV_FILES = (".env", ".env.test")
HYPOTHESIS_STORAGE_DIRECTORY = configure_hypothesis_storage(repo_root=REPO_ROOT)


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


def _get_settings():
    from openzyme_runtime import load_current_settings

    return load_current_settings()


def _skip_if_needed(reason: str | None) -> None:
    if reason is not None:
        pytest.skip(reason)


def pytest_runtest_setup(item: pytest.Item) -> None:
    from openzyme_runtime import live_e2e_skip_reason
    from openzyme_runtime import live_hpc_skip_reason
    from openzyme_runtime import live_llm_skip_reason
    from openzyme_runtime import live_tavily_skip_reason
    from openzyme_runtime import quality_eval_skip_reason

    settings = _get_settings()
    if item.get_closest_marker("live_llm"):
        _skip_if_needed(live_llm_skip_reason(settings))
    if item.get_closest_marker("live_tavily"):
        _skip_if_needed(live_tavily_skip_reason(settings))
    if item.get_closest_marker("live_hpc"):
        _skip_if_needed(live_hpc_skip_reason(settings))
    if item.get_closest_marker("live_e2e"):
        _skip_if_needed(live_e2e_skip_reason(settings))
    if item.get_closest_marker("quality_eval"):
        _skip_if_needed(quality_eval_skip_reason(settings))
