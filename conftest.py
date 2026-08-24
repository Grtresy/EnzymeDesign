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
pytest_plugins = ("scripts.test_gate.no_live_effects",)


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


def _skip_if_needed(reason: str | None) -> None:
    if reason is not None:
        pytest.skip(reason)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _live_opt_in(marker: str) -> bool:
    return _enabled(f"OPENZYME_TEST_ENABLE_{marker.upper()}") or (
        marker != "quality_eval" and _enabled("OPENZYME_TEST_ENABLE_LIVE_E2E")
    )


def _live_skip_reason(marker: str) -> str | None:
    if not _live_opt_in(marker):
        return (
            f"{marker} tests are disabled; set "
            f"OPENZYME_TEST_ENABLE_{marker.upper()}=true explicitly."
        )
    if marker != "quality_eval" and not _enabled("OPENZYME_ALLOW_LIVE"):
        return (
            f"{marker} tests require the independent operator gate "
            "OPENZYME_ALLOW_LIVE=true."
        )
    if marker == "live_llm" and not os.environ.get("OPENZYME_LLM_API_KEY"):
        return "live_llm tests require OPENZYME_LLM_API_KEY."
    if marker == "live_tavily" and not os.environ.get("TAVILY_API_KEY"):
        return "live_tavily tests require TAVILY_API_KEY."
    if marker == "live_hpc":
        if os.environ.get("OPENZYME_EXECUTION_BACKEND") != "hpc":
            return "live_hpc tests require OPENZYME_EXECUTION_BACKEND=hpc."
        config_value = os.environ.get("OPENZYME_HPC_RUNNER_CONFIG") or os.environ.get(
            "HPC_RUNNER_CONFIG"
        )
        if not config_value:
            return "live_hpc tests require an explicit HPC runner config path."
        if not Path(config_value).expanduser().is_file():
            return "live_hpc runner config path does not exist."
    if marker == "live_e2e":
        for prerequisite in ("live_llm", "live_tavily", "live_hpc"):
            reason = _live_skip_reason(prerequisite)
            if reason is not None:
                return f"live_e2e prerequisite missing: {reason}"
    return None


def pytest_runtest_setup(item: pytest.Item) -> None:
    for marker in (
        "live_llm",
        "live_tavily",
        "live_hpc",
        "live_e2e",
        "seeded_live_smoke",
        "quality_eval",
    ):
        if item.get_closest_marker(marker):
            _skip_if_needed(_live_skip_reason(marker))
