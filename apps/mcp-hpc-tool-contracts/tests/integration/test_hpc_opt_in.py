from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_hpc_tool_contracts.integration import _load_params, run_smoke_suite


pytestmark = pytest.mark.integration


def test_smoke_harness_is_guarded_without_hpc_config() -> None:
    runner_config = os.getenv("HPC_TOOL_CONTRACTS_RUNNER_CONFIG")
    params_file = os.getenv("HPC_TOOL_CONTRACTS_SMOKE_PARAMS")
    if not runner_config or not params_file:
        pytest.skip(
            "Set HPC_TOOL_CONTRACTS_RUNNER_CONFIG and HPC_TOOL_CONTRACTS_SMOKE_PARAMS to run"
        )

    config_path = Path(runner_config).expanduser()
    payload_path = Path(params_file).expanduser()
    if not config_path.exists():
        pytest.skip(f"Runner config not found: {config_path}")
    if not payload_path.exists():
        pytest.skip(f"Smoke payload file not found: {payload_path}")

    payloads = _load_params(payload_path)
    if not payloads:
        pytest.skip("No adapter payloads in integration params file")

    result = run_smoke_suite(
        payloads,
        runner_config=config_path,
        asynchronous=False,
        wait=False,
        poll_seconds=5,
        max_polls=1,
    )
    assert result
