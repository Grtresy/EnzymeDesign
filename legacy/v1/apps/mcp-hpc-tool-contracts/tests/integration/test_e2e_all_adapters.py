"""End-to-end integration tests for all HPC adapters.

Each test submits a real job to the Diannan 340 cluster and waits for completion,
asserting that outputs are produced. All tests require a valid hpc_runner.toml.

Run CPU adapters only (faster, ~5-10 min each):
    pytest tests/integration/test_e2e_all_adapters.py -m "integration and not slow" -v

Run GPU adapters too:
    pytest tests/integration/test_e2e_all_adapters.py -m integration -v

Run a single adapter:
    pytest tests/integration/test_e2e_all_adapters.py::test_fpocket -m integration -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hpc_tool_contracts.cluster_profile import ClusterProfile
from mcp_hpc_tool_contracts.runner_client import RunnerClient
from mcp_hpc_tool_contracts.service import run_adapter

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures"


def _run_e2e(
    adapter_id: str,
    params: dict,
    *,
    runner_config: Path | None,
    cluster_profile: ClusterProfile,
    runner_client: RunnerClient,
    gpu: bool = False,
) -> dict:
    """Submit adapter job and block until completion. Returns full response dict."""
    if runner_config is None:
        pytest.skip("hpc_runner.toml not found — set up cluster config to run e2e tests")
    poll_seconds = 30
    max_polls = 90 if adapter_id == "alphafold3" else 60 if gpu else 20
    return run_adapter(
        adapter_id,
        params,
        profile=cluster_profile,
        asynchronous=True,
        wait=True,
        poll_seconds=poll_seconds,
        max_polls=max_polls,
        runner_client=runner_client,
    )


def _assert_completed(response: dict, adapter_id: str) -> None:
    """Assert that an async+wait response has fetch status 'completed'."""
    fetch = response.get("fetch")
    assert fetch is not None, (
        f"{adapter_id}: no 'fetch' key in response — job may have failed or timed out.\n"
        f"job_status={response.get('job_status')}\n"
        f"submission={response.get('submission')}"
    )
    assert fetch["status"] == "completed", (
        f"{adapter_id}: fetch status={fetch['status']!r}, "
        f"error_code={fetch.get('error_code')!r}"
    )


# ---------------------------------------------------------------------------
# CPU adapters
# ---------------------------------------------------------------------------


def test_hhblits(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """hhblits MSA search — CPU, ~5-10 min."""
    params = {
        "query_fasta": str(FIXTURES / "hhblits" / "query.fasta"),
        "db_prefix": "UniRef30_2023_02",
        "iterations": 1,
    }
    response = _run_e2e(
        "hhblits", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
    )
    _assert_completed(response, "hhblits")


def test_fpocket(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """fpocket pocket detection — CPU, fast (<1 min)."""
    params = {
        "structure_path": str(FIXTURES / "fpocket" / "protein.pdb"),
    }
    response = _run_e2e(
        "fpocket", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
    )
    _assert_completed(response, "fpocket")


def test_tunnels_detect(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """CAVER tunnel detection on crambin (1crn) — CPU, fast (<2 min).

    Starting point coordinates are the approximate centroid of 1crn.
    """
    params = {
        "structure_path": str(FIXTURES / "tunnels_detect" / "target.pdb"),
        "mode": "detect",
        "starting_point_x": 9.269,
        "starting_point_y": 9.787,
        "starting_point_z": 6.967,
    }
    response = _run_e2e(
        "tunnels", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
    )
    _assert_completed(response, "tunnels")


def test_vina(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """AutoDock Vina docking on 1IEP receptor+ligand — CPU, fast (<2 min).

    Box centered on the known binding site of imatinib in Abl kinase (1IEP).
    """
    params = {
        "receptor_path": str(FIXTURES / "vina" / "receptor.pdbqt"),
        "ligand_path": str(FIXTURES / "vina" / "ligand.pdbqt"),
        "center_x": 15.190,
        "center_y": 53.903,
        "center_z": 16.917,
        "size_x": 20,
        "size_y": 20,
        "size_z": 20,
    }
    response = _run_e2e(
        "vina", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
    )
    _assert_completed(response, "vina")


# ---------------------------------------------------------------------------
# GPU adapters (marked slow — require GPU partition, ~5-25 min each)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_chai_fold(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """chai-lab structure prediction of villin HP35 — GPU, ~5 min.

    FASTA must use chai-lab's typed header format: >protein|name=<id>
    """
    params = {
        "input_fasta": str(FIXTURES / "chai_fold" / "input.fasta"),
    }
    response = _run_e2e(
        "chai_fold", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
        gpu=True,
    )
    _assert_completed(response, "chai_fold")


@pytest.mark.slow
def test_colabfold(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """ColabFold structure prediction of villin HP35 — GPU, ~5 min."""
    params = {
        "input_fasta": str(FIXTURES / "colabfold" / "input.fasta"),
    }
    response = _run_e2e(
        "colabfold", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
        gpu=True,
    )
    _assert_completed(response, "colabfold")


@pytest.mark.slow
def test_alphafold3(
    runner_config, cluster_profile: ClusterProfile, runner_client: RunnerClient
) -> None:
    """AlphaFold3 structure prediction of villin HP35 — GPU, ~20-25 min."""
    params = {
        "input_json": str(FIXTURES / "alphafold3" / "input.json"),
    }
    response = _run_e2e(
        "alphafold3", params,
        runner_config=runner_config,
        cluster_profile=cluster_profile,
        runner_client=runner_client,
        gpu=True,
    )
    _assert_completed(response, "alphafold3")
