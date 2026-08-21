from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.model import (  # noqa: E402
    NODE_MANIFEST_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
)


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "scripts")
    return environment


def _run_observed_pytest(
    test_path: Path,
    output_path: Path,
    *,
    mode: str,
    extra_args: tuple[str, ...] = (),
    role: str = "legacy_general",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "--rootdir",
        str(test_path.parent),
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "test_gate.pytest_plugin",
        "--test-gate-observation",
        str(output_path),
        "--test-gate-invocation-id",
        "plugin-fixture-invocation",
        "--test-gate-role",
        role,
        "--test-gate-observation-mode",
        mode,
        *extra_args,
    ]
    if mode == "collect":
        command.append("--collect-only")
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=_environment(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )


def test_pytest_plugin_records_exact_collection_outcomes_and_phases(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_observed.py"
    test_path.write_text(
        """
import pytest


def test_pass():
    assert True


@pytest.mark.skip(reason="fixture skip")
def test_skip():
    raise AssertionError("must not execute")


@pytest.mark.xfail(reason="fixture xfail")
def test_xfail():
    assert False


@pytest.mark.xfail(reason="fixture xpass")
def test_xpass():
    assert True
""".lstrip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "observation.json"
    completed = _run_observed_pytest(test_path, output_path, mode="execute")
    assert completed.returncode == 0, completed.stderr

    document = load_canonical_document_bytes(output_path.read_bytes())
    assert document["schema_id"] == PYTEST_OBSERVATION_SCHEMA_ID
    assert document["invocation_id"] == "plugin-fixture-invocation"
    assert document["role"] == "legacy_general"
    assert document["mode"] == "execute"
    assert document["deselected"] == []
    node_ids = [item["node_id"] for item in document["collection"]]
    assert node_ids == sorted(node_ids)
    assert len(node_ids) == 4
    outcomes = {
        item["node_id"].rsplit("::", 1)[-1]: item["outcome"]
        for item in document["node_results"]
    }
    assert outcomes == {
        "test_pass": "pass",
        "test_skip": "skip",
        "test_xfail": "xfail",
        "test_xpass": "xpass",
    }
    for result in document["node_results"]:
        assert result["duration_ns"] >= 0
        assert result["phases"]
        assert all(phase["duration_ns"] >= 0 for phase in result["phases"])


def test_pytest_plugin_collection_mode_is_canonical_and_no_replace(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_collection.py"
    test_path.write_text(
        """
import pytest


@pytest.mark.slow
def test_collected():
    assert True
""".lstrip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "collection.json"
    completed = _run_observed_pytest(test_path, output_path, mode="collect")
    assert completed.returncode == 0, completed.stderr

    document = load_canonical_document_bytes(output_path.read_bytes())
    assert document["mode"] == "collect"
    assert document["node_results"] == []
    assert len(document["collection"]) == 1
    assert document["collection"][0]["markers"] == ["slow"]

    repeated = _run_observed_pytest(test_path, output_path, mode="collect")
    assert repeated.returncode != 0
    assert "observation output must not exist" in repeated.stderr


def test_pytest_plugin_records_markers_for_policy_deselection(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_policy.py"
    test_path.write_text(
        """
import pytest


def test_safe():
    assert True


@pytest.mark.integration
@pytest.mark.live_hpc
def test_live():
    raise AssertionError("must be deselected")
""".lstrip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "policy-collection.json"
    completed = _run_observed_pytest(
        test_path,
        output_path,
        mode="collect",
        extra_args=("-m", "not integration and not live_hpc"),
    )
    assert completed.returncode == 0, completed.stderr

    document = load_canonical_document_bytes(output_path.read_bytes())
    assert [item["node_id"].rsplit("::", 1)[-1] for item in document["collection"]] == [
        "test_safe"
    ]
    assert document["deselected"] == [
        f"{test_path.name}::test_live"
    ]
    assert document["deselected_markers"] == [
        {
            "node_id": f"{test_path.name}::test_live",
            "markers": ["integration", "live_hpc"],
        }
    ]


def test_pytest_plugin_executes_exact_manifest_partition(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_manifest.py"
    test_path.write_text(
        """
import pytest


def test_selected():
    assert True


def test_qualification_owned():
    raise AssertionError("must be owned by qualification")


@pytest.mark.integration
def test_policy_excluded():
    raise AssertionError("must be excluded by policy")
""".lstrip(),
        encoding="utf-8",
    )
    selected = f"{test_path.name}::test_selected"
    qualification_owned = (
        f"{test_path.name}::test_qualification_owned"
    )
    policy_excluded = f"{test_path.name}::test_policy_excluded"
    preselection = [
        {"node_id": selected, "markers": []},
        {"node_id": qualification_owned, "markers": []},
    ]
    preselection.sort(key=lambda item: item["node_id"])
    selected_nodes = [selected]
    planned_deselected = [qualification_owned]
    policy_deselected = [policy_excluded]
    manifest = seal_document(
        NODE_MANIFEST_SCHEMA_ID,
        {
            "invocation_id": "plugin-fixture-invocation",
            "role": "general_residual",
            "plan_digest": "sha256:" + "1" * 64,
            "source_identity_digest": "sha256:" + "2" * 64,
            "full_collection_digest": sha256_digest(
                canonical_json_bytes(preselection)
            ),
            "selected_nodes": selected_nodes,
            "selected_nodes_digest": sha256_digest(
                canonical_json_bytes(selected_nodes)
            ),
            "planned_deselected_nodes": planned_deselected,
            "planned_deselected_digest": sha256_digest(
                canonical_json_bytes(planned_deselected)
            ),
            "expected_policy_deselected_nodes": policy_deselected,
            "expected_policy_deselected_digest": sha256_digest(
                canonical_json_bytes(policy_deselected)
            ),
        },
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(canonical_document_bytes(manifest))
    output_path = tmp_path / "manifest-observation.json"

    completed = _run_observed_pytest(
        test_path,
        output_path,
        mode="execute",
        role="general_residual",
        extra_args=(
            "-m",
            "not integration",
            "--test-gate-node-manifest",
            str(manifest_path),
        ),
    )
    assert completed.returncode == 0, completed.stderr

    document = load_canonical_document_bytes(output_path.read_bytes())
    assert [item["node_id"] for item in document["preselection_collection"]] == [
        qualification_owned,
        selected,
    ]
    assert [item["node_id"] for item in document["collection"]] == [
        selected
    ]
    assert document["planned_deselected"] == planned_deselected
    assert document["deselected"] == sorted(
        [qualification_owned, policy_excluded]
    )
    assert [
        item["node_id"] for item in document["node_results"]
    ] == [selected]
    assert document["selection_manifest_digest"] == manifest["self_digest"]


def test_pytest_plugin_closes_fixed_xdist_workers_and_exact_results(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "suite"
    test_root.mkdir()
    (test_root / "test_one.py").write_text(
        "def test_z_last_lexically(tmp_path):\n"
        "    (tmp_path / 'z.txt').write_text('z')\n"
        "\n"
        "def test_a_first_lexically(tmp_path):\n"
        "    (tmp_path / 'a.txt').write_text('a')\n",
        encoding="utf-8",
    )
    (test_root / "test_two.py").write_text(
        "def test_two(tmp_path):\n"
        "    (tmp_path / 'two.txt').write_text('two')\n",
        encoding="utf-8",
    )
    selected_nodes = sorted(
        [
            "suite/test_one.py::test_z_last_lexically",
            "suite/test_one.py::test_a_first_lexically",
            "suite/test_two.py::test_two",
        ]
    )
    collection = [
        {"node_id": node_id, "markers": []} for node_id in selected_nodes
    ]
    manifest = seal_document(
        NODE_MANIFEST_SCHEMA_ID,
        {
            "invocation_id": "plugin-fixture-invocation",
            "role": "general_parallel",
            "plan_digest": "sha256:" + "1" * 64,
            "source_identity_digest": "sha256:" + "2" * 64,
            "full_collection_digest": sha256_digest(
                canonical_json_bytes(collection)
            ),
            "selected_nodes": selected_nodes,
            "selected_nodes_digest": sha256_digest(
                canonical_json_bytes(selected_nodes)
            ),
            "planned_deselected_nodes": [],
            "planned_deselected_digest": sha256_digest(
                canonical_json_bytes([])
            ),
            "expected_policy_deselected_nodes": [],
            "expected_policy_deselected_digest": sha256_digest(
                canonical_json_bytes([])
            ),
            "resource_manifest_digest": "sha256:" + "3" * 64,
            "resource_partition": "parallel",
            "worker_count": 2,
        },
    )
    manifest_path = tmp_path / "parallel-manifest.json"
    manifest_path.write_bytes(canonical_document_bytes(manifest))
    output_path = tmp_path / "parallel-observation.json"
    worker_root = tmp_path / "worker-roots"
    worker_root.mkdir()
    completed = _run_observed_pytest(
        test_root,
        output_path,
        mode="execute",
        role="general_parallel",
        extra_args=(
            "--test-gate-node-manifest",
            str(manifest_path),
            "--test-gate-worker-root",
            str(worker_root),
            "--basetemp",
            str(worker_root / "basetemp"),
            "-n",
            "2",
            "--dist",
            "loadfile",
            "--max-worker-restart",
            "0",
        ),
    )
    assert completed.returncode == 0, completed.stderr
    document = load_canonical_document_bytes(output_path.read_bytes())
    assert document["worker_failures"] == []
    assert [item["worker_id"] for item in document["worker_allocations"]] == [
        "gw0",
        "gw1",
    ]
    assert sorted(
        node_id
        for allocation in document["worker_allocations"]
        for node_id in allocation["executed_nodes"]
    ) == selected_nodes
    assert [item["node_id"] for item in document["node_results"]] == selected_nodes
    assert all(item["outcome"] == "pass" for item in document["node_results"])
