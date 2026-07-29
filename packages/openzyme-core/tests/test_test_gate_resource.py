from __future__ import annotations

import hashlib
import importlib.metadata
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.config import load_config  # noqa: E402
from scripts.test_gate.model import seal_document  # noqa: E402
from scripts.test_gate.partition import (  # noqa: E402
    GeneralPartitionError,
    MAX_WORKER_RUNTIME_ROOT_BYTES,
    _allocate_worker_runtime_root,
    _planned_worker_runtime_root,
    _process_failure,
    _validate_worker_allocations,
)
from scripts.test_gate.runner import ProcessResult, StreamCapture  # noqa: E402
from scripts.test_gate.resource import (  # noqa: E402
    INITIAL_RESOURCE_ENTRY_SPECS,
    ResourceEntrySpec,
    ResourceManifestError,
    audit_parallel_candidate_source,
    build_resource_manifest,
    probe_xdist_identity,
    resource_partition,
    validate_worker_count,
    verify_resource_manifest,
)

CONFIG_PATH = REPOSITORY_ROOT / "scripts/test-gate.toml"
PROOF_NODE = (
    "tests/test_resource_proof.py"
    "::test_initial_resource_entries_bind_exact_modules_and_safe_closure"
)


def _audit_records() -> tuple[tuple[str, str, str], ...]:
    return (
        ("cache", "worker_isolated", "proof"),
        ("cwd", "process_local", "proof"),
        ("environment", "worker_process_local", "proof"),
        ("filesystem", "test_temp_root", "proof"),
        ("micu", "forbidden", "proof"),
        ("port", "forbidden", "proof"),
        ("process", "none", "proof"),
        ("qualification", "forbidden", "proof"),
        ("sandbox", "forbidden", "proof"),
        ("signal", "forbidden", "proof"),
        ("sqlite", "memory_or_test_temp_root", "proof"),
    )


def _synthetic_resource_fixture(
    tmp_path: Path,
) -> tuple[Path, list[dict[str, object]], ResourceEntrySpec]:
    repo_root = tmp_path / "repo"
    module_path = "tests/test_candidate.py"
    fixture_path = "conftest.py"
    proof_path = "tests/test_resource_proof.py"
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / module_path).write_text(
        "def test_a(tmp_path):\n"
        "    (tmp_path / 'a.txt').write_text('a')\n"
        "\n"
        "def test_b():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (repo_root / fixture_path).write_text("", encoding="utf-8")
    (repo_root / proof_path).write_text(
        "def test_initial_resource_entries_bind_exact_modules_and_safe_closure():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    collection = [
        {"node_id": f"{module_path}::test_a", "markers": []},
        {"node_id": f"{module_path}::test_b", "markers": []},
        {"node_id": PROOF_NODE, "markers": []},
    ]
    collection.sort(key=lambda item: str(item["node_id"]))
    spec = ResourceEntrySpec(
        entry_id="candidate",
        module_path=module_path,
        resource_class="parallel_temp_root",
        fixture_paths=(fixture_path,),
        proof_node_ids=(PROOF_NODE,),
        audited_resources=_audit_records(),
    )
    return repo_root, collection, spec


def _reseal(document: dict[str, object]) -> dict[str, object]:
    fields = dict(document)
    schema_id = str(fields.pop("schema_id"))
    fields.pop("self_digest")
    return seal_document(schema_id, fields)


def test_initial_resource_entries_bind_exact_modules_and_safe_closure() -> None:
    module_paths = tuple(spec.module_path for spec in INITIAL_RESOURCE_ENTRY_SPECS)
    assert len(module_paths) == len(set(module_paths))
    assert all(
        spec.resource_class in {"parallel_pure", "parallel_temp_root"}
        for spec in INITIAL_RESOURCE_ENTRY_SPECS
    )
    for spec in INITIAL_RESOURCE_ENTRY_SPECS:
        source = REPOSITORY_ROOT / spec.module_path
        assert source.is_file()
        audit_parallel_candidate_source(source)
        assert spec.fixture_paths
        assert all((REPOSITORY_ROOT / path).is_file() for path in spec.fixture_paths)
        assert spec.proof_node_ids


def test_resource_manifest_rejects_stale_source_new_node_and_missing_proof(
    tmp_path: Path,
) -> None:
    repo_root, collection, spec = _synthetic_resource_fixture(tmp_path)
    config = load_config(CONFIG_PATH)
    manifest = build_resource_manifest(
        repo_root=repo_root,
        collection_records=collection,
        specs=(spec,),
    )
    assignments = verify_resource_manifest(
        manifest,
        repo_root=repo_root,
        collection_records=collection,
        config=config,
    )
    assert assignments == {
        "tests/test_candidate.py::test_a": "parallel_temp_root",
        "tests/test_candidate.py::test_b": "parallel_temp_root",
    }

    changed_source = repo_root / spec.module_path
    changed_source.write_text(
        changed_source.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    with pytest.raises(ResourceManifestError, match="digest drifted"):
        verify_resource_manifest(
            manifest,
            repo_root=repo_root,
            collection_records=collection,
            config=config,
        )

    refreshed = build_resource_manifest(
        repo_root=repo_root,
        collection_records=collection,
        specs=(spec,),
    )
    with pytest.raises(ResourceManifestError, match="collection digest drifted"):
        verify_resource_manifest(
            refreshed,
            repo_root=repo_root,
            collection_records=[
                *collection,
                {
                    "node_id": "tests/test_candidate.py::test_new",
                    "markers": [],
                },
            ],
            config=config,
        )

    missing_proof = dict(refreshed)
    missing_proof["entries"] = [dict(refreshed["entries"][0])]
    missing_proof["entries"][0]["proof_node_ids"] = [
        "tests/test_resource_proof.py::test_missing"
    ]
    missing_proof = _reseal(missing_proof)
    with pytest.raises(ResourceManifestError, match="missing proof"):
        verify_resource_manifest(
            missing_proof,
            repo_root=repo_root,
            collection_records=collection,
            config=config,
        )


def test_resource_source_audit_rejects_forbidden_shared_resources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "test_unsafe.py"
    source.write_text(
        "from pathlib import Path\n"
        "def test_unsafe():\n"
        "    Path('/tmp/openzyme-shared').write_text('unsafe')\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ResourceManifestError,
        match="fixed absolute filesystem mutation",
    ):
        audit_parallel_candidate_source(source)


@pytest.mark.parametrize("workers", (0, 5, -1, True, "4"))
def test_fixed_worker_count_rejects_auto_or_out_of_range(workers: object) -> None:
    with pytest.raises(ResourceManifestError, match="explicit integer"):
        validate_worker_count(workers, hard_max=4)  # type: ignore[arg-type]


def test_unclassified_nodes_remain_serial_unknown() -> None:
    config = load_config(CONFIG_PATH)
    serial, parallel = resource_partition(
        residual_nodes=("test_a.py::test_a", "test_b.py::test_b"),
        assignments={"test_a.py::test_a": "parallel_temp_root"},
        config=config,
    )
    assert serial == ("test_b.py::test_b",)
    assert parallel == ("test_a.py::test_a",)


def test_parallel_mode_fails_when_pinned_xdist_is_absent(monkeypatch) -> None:
    def missing_version(name: str) -> str:
        del name
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing_version)
    with pytest.raises(ResourceManifestError, match="requires locked pytest-xdist"):
        probe_xdist_identity()


def test_xdist_worker_allocations_are_unique_and_checkout_external(
    tmp_path: Path,
) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    selected = ("test_a.py::test_a", "test_b.py::test_b")
    allocations: list[dict[str, object]] = []
    for index, node_id in enumerate(selected):
        allocation_root = worker_root / f"gw{index}"
        paths = {
            name: allocation_root / name
            for name in ("tmp", "cache", "pycache")
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        allocations.append(
            {
                "worker_id": f"gw{index}",
                "temp_root": str(paths["tmp"]),
                "cache_root": str(paths["cache"]),
                "pycache_root": str(paths["pycache"]),
                "executed_nodes": [node_id],
            }
        )
    document = {
        "worker_failures": [],
        "worker_allocations": allocations,
    }
    normalized = _validate_worker_allocations(
        document=document,
        selected_nodes=selected,
        worker_root=worker_root,
        workers=2,
    )
    assert normalized == allocations

    allocations[1]["cache_root"] = allocations[0]["cache_root"]
    with pytest.raises(GeneralPartitionError, match="missing or shared"):
        _validate_worker_allocations(
            document=document,
            selected_nodes=selected,
            worker_root=worker_root,
            workers=2,
        )


def test_archived_worker_allocations_verify_without_mutable_runtime_dirs(
    tmp_path: Path,
) -> None:
    worker_root = tmp_path / "archived-workers"
    selected = ("test_a.py::test_a", "test_b.py::test_b")
    allocations = [
        {
            "worker_id": f"gw{index}",
            "temp_root": str(worker_root / f"gw{index}" / "tmp"),
            "cache_root": str(worker_root / f"gw{index}" / "cache"),
            "pycache_root": str(worker_root / f"gw{index}" / "pycache"),
            "executed_nodes": [node_id],
        }
        for index, node_id in enumerate(selected)
    ]
    document = {
        "worker_failures": [],
        "worker_allocations": allocations,
    }

    assert _validate_worker_allocations(
        document=document,
        selected_nodes=selected,
        worker_root=worker_root,
        workers=2,
        require_existing_paths=False,
    ) == allocations
    with pytest.raises(
        GeneralPartitionError,
        match="runtime root is missing",
    ):
        _validate_worker_allocations(
            document=document,
            selected_nodes=selected,
            worker_root=worker_root,
            workers=2,
        )


@pytest.mark.parametrize(
    "failure",
    (
        "gw0:worker_crash",
        "gw0:leaked_process",
        "gw0:unknown_result",
        "gw0:allocation_failure",
    ),
)
def test_worker_crash_leak_and_unknown_outcome_fail_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    with pytest.raises(GeneralPartitionError, match="contains failures"):
        _validate_worker_allocations(
            document={
                "worker_failures": [failure],
                "worker_allocations": [],
            },
            selected_nodes=("test_a.py::test_a",),
            worker_root=worker_root,
            workers=1,
        )


def test_partition_process_failure_preserves_bounded_stream_tails(
    tmp_path: Path,
) -> None:
    result = ProcessResult(
        argv=("pytest",),
        cwd=str(tmp_path),
        outcome="fail",
        exit_code=1,
        started_monotonic_ns=1,
        duration_ns=2,
        stdout=StreamCapture(
            digest="sha256:" + "1" * 64,
            total_bytes=6,
            tail="stdout",
        ),
        stderr=StreamCapture(
            digest="sha256:" + "2" * 64,
            total_bytes=6,
            tail="stderr",
        ),
        timed_out=False,
        term_sent=False,
        kill_sent=False,
        error=None,
    )

    error = _process_failure("parallel", result)

    assert "stdout='stdout'" in str(error)
    assert "stderr='stderr'" in str(error)


def test_worker_runtime_root_is_short_plan_bound_and_exclusive(
    tmp_path: Path,
) -> None:
    token = hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()
    plan = {"self_digest": f"sha256:{token}"}

    planned = _planned_worker_runtime_root(
        plan=plan,
        repo_root=REPOSITORY_ROOT,
    )

    assert planned.parent == Path("/tmp")
    assert len(str(planned).encode("utf-8")) <= MAX_WORKER_RUNTIME_ROOT_BYTES
    allocated = _allocate_worker_runtime_root(
        plan=plan,
        repo_root=REPOSITORY_ROOT,
    )
    assert allocated == planned
    assert allocated.is_dir()
    with pytest.raises(GeneralPartitionError, match="already exists"):
        _allocate_worker_runtime_root(
            plan=plan,
            repo_root=REPOSITORY_ROOT,
        )
    allocated.rmdir()
