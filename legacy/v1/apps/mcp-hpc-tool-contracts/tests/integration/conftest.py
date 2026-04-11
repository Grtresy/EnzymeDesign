from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mcp_hpc_tool_contracts.cluster_profile import ClusterProfile
from mcp_hpc_tool_contracts.runner_client import RunnerClient

_REPO_ROOT = Path(__file__).parents[4]
_RUNNER_CONFIG = _REPO_ROOT / "apps" / "mcp-hpc-runner" / "config" / "hpc_runner.toml"
_RUNNER_DIR = _REPO_ROOT / "apps" / "mcp-hpc-runner"


def _find_runner_bin() -> str | None:
    try:
        result = subprocess.run(
            ["uv", "run", "which", "mcp-hpc-runner"],
            cwd=_RUNNER_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


@pytest.fixture(scope="session")
def runner_config() -> Path | None:
    return _RUNNER_CONFIG if _RUNNER_CONFIG.exists() else None


@pytest.fixture(scope="session")
def runner_bin() -> str | None:
    return _find_runner_bin()


@pytest.fixture(scope="session")
def cluster_profile(runner_config: Path | None) -> ClusterProfile:
    if runner_config and runner_config.exists():
        return ClusterProfile.from_toml(runner_config)
    return ClusterProfile.empty()


@pytest.fixture(scope="session")
def runner_client(runner_bin: str | None, runner_config: Path | None) -> RunnerClient:
    return RunnerClient(runner_bin=runner_bin, runner_config=runner_config)


