"""Exact serial/parallel execution of the already-qualified general residual."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import TestGateConfig
from .model import (
    NODE_MANIFEST_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
    verify_sealed_document,
)
from .resource import (
    PARALLEL_DISTRIBUTION,
    load_resource_manifest,
    probe_xdist_identity,
    resource_partition,
    validate_worker_count,
)
from .runner import ProcessResult, publish_no_replace, run_command

SERIAL_MANIFEST_FILENAME = "general-serial-manifest.json"
PARALLEL_MANIFEST_FILENAME = "general-parallel-manifest.json"
SERIAL_OBSERVATION_FILENAME = "general-serial-observation.json"
PARALLEL_OBSERVATION_FILENAME = "general-parallel-observation.json"
MERGED_OBSERVATION_FILENAME = "general-residual-observation.json"
WORKER_RUNTIME_BASE = Path("/tmp")
WORKER_RUNTIME_PREFIX = "ozg-"
WORKER_RUNTIME_TOKEN_LENGTH = 24
MAX_WORKER_RUNTIME_ROOT_BYTES = 48
_PARTITION_ROLES = {
    "serial": "general_serial",
    "parallel": "general_parallel",
}


class GeneralPartitionError(RuntimeError):
    """Raised when exact fixed-worker execution cannot be proven."""


def _sorted_unique_strings(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise GeneralPartitionError(f"{context} must be an array of strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise GeneralPartitionError(f"{context} must be sorted and unique")
    return result


def _nodes_digest(nodes: Sequence[str]) -> str:
    return sha256_digest(canonical_json_bytes(list(nodes)))


def _source_digest(plan: Mapping[str, Any]) -> str:
    return sha256_digest(canonical_json_bytes(plan["source_identity"]))


def _general_records(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": str(item["node_id"]),
            "markers": list(item["markers"]),
        }
        for item in plan["collections"]["general"]["markers"]
    ]


def _policy_records(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in plan["collections"]["general"]["policy_deselected_nodes"]
    ]


def build_partition_manifest(
    *,
    plan: Mapping[str, Any],
    selected_nodes: Sequence[str],
    partition: str,
    resource_manifest_digest: str,
    workers: int,
) -> dict[str, Any]:
    """Build one exact partition selector over the full current G collection."""

    if partition not in _PARTITION_ROLES:
        raise GeneralPartitionError(f"unknown resource partition {partition!r}")
    selected = tuple(selected_nodes)
    if selected != tuple(sorted(set(selected))):
        raise GeneralPartitionError("partition selected nodes are not canonical")
    general_nodes = tuple(plan["collections"]["general"]["nodes"])
    if set(selected) - set(general_nodes):
        raise GeneralPartitionError("partition selects a node outside G")
    planned_deselected = tuple(sorted(set(general_nodes) - set(selected)))
    policy_nodes = tuple(
        item["node_id"] for item in _policy_records(plan)
    )
    return seal_document(
        NODE_MANIFEST_SCHEMA_ID,
        {
            "invocation_id": plan["invocation_id"],
            "role": _PARTITION_ROLES[partition],
            "plan_digest": plan["self_digest"],
            "source_identity_digest": _source_digest(plan),
            "full_collection_digest": plan["collections"]["general"][
                "collection_digest"
            ],
            "selected_nodes": list(selected),
            "selected_nodes_digest": _nodes_digest(selected),
            "planned_deselected_nodes": list(planned_deselected),
            "planned_deselected_digest": _nodes_digest(planned_deselected),
            "expected_policy_deselected_nodes": list(policy_nodes),
            "expected_policy_deselected_digest": _nodes_digest(policy_nodes),
            "resource_manifest_digest": resource_manifest_digest,
            "resource_partition": partition,
            "worker_count": workers if partition == "parallel" else 1,
        },
    )


def verify_partition_manifest(
    manifest: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    selected_nodes: Sequence[str],
    partition: str,
    resource_manifest_digest: str,
    workers: int,
) -> None:
    """Purely verify one generated exact resource partition."""

    expected = build_partition_manifest(
        plan=plan,
        selected_nodes=selected_nodes,
        partition=partition,
        resource_manifest_digest=resource_manifest_digest,
        workers=workers,
    )
    if dict(manifest) != expected:
        raise GeneralPartitionError(
            f"{partition} node manifest drifted from the resource plan"
        )


def _observation_arguments(
    *,
    output_path: Path,
    invocation_id: str,
    role: str,
    manifest_path: Path,
) -> tuple[str, ...]:
    return (
        "-p",
        "scripts.test_gate.pytest_plugin",
        "--test-gate-observation",
        str(output_path),
        "--test-gate-invocation-id",
        invocation_id,
        "--test-gate-role",
        role,
        "--test-gate-observation-mode",
        "execute",
        "--test-gate-node-manifest",
        str(manifest_path),
    )


def _base_pytest_argv(
    *,
    config: TestGateConfig,
) -> tuple[str, ...]:
    return (
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        "-c",
        "pytest.ini",
        "apps",
        "packages",
        "-m",
        config.pytest_contract.marker_expression,
        "--rootdir=.",
    )


def partition_argv(
    *,
    config: TestGateConfig,
    output_root: Path,
    worker_root: Path | None,
    invocation_id: str,
    partition: str,
    workers: int,
) -> tuple[str, ...]:
    """Return the closed pytest command for one exact partition."""

    if partition == "serial":
        return (
            *_base_pytest_argv(config=config),
            *_observation_arguments(
                output_path=output_root / SERIAL_OBSERVATION_FILENAME,
                invocation_id=invocation_id,
                role=_PARTITION_ROLES[partition],
                manifest_path=output_root / SERIAL_MANIFEST_FILENAME,
            ),
            "-p",
            "no:cacheprovider",
        )
    if partition != "parallel":
        raise GeneralPartitionError(f"unknown resource partition {partition!r}")
    if worker_root is None:
        raise GeneralPartitionError("parallel worker runtime root is missing")
    return (
        *_base_pytest_argv(config=config),
        *_observation_arguments(
            output_path=output_root / PARALLEL_OBSERVATION_FILENAME,
            invocation_id=invocation_id,
            role=_PARTITION_ROLES[partition],
            manifest_path=output_root / PARALLEL_MANIFEST_FILENAME,
        ),
        "--test-gate-worker-root",
        str(worker_root),
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(worker_root / "basetemp"),
        "-n",
        str(workers),
        "--dist",
        PARALLEL_DISTRIBUTION,
        "--max-worker-restart",
        "0",
    )


def _planned_worker_runtime_root(
    *,
    plan: Mapping[str, Any],
    repo_root: Path,
) -> Path:
    """Derive a short, plan-bound runtime root outside the checkout."""

    plan_digest = plan.get("self_digest")
    if (
        not isinstance(plan_digest, str)
        or not plan_digest.startswith("sha256:")
        or len(plan_digest) != 71
    ):
        raise GeneralPartitionError(
            "cannot derive worker runtime root from an invalid plan digest"
        )
    try:
        base = WORKER_RUNTIME_BASE.resolve(strict=True)
        checkout = repo_root.resolve(strict=True)
    except OSError as exc:
        raise GeneralPartitionError(
            "worker runtime base or checkout is unavailable"
        ) from exc
    if not base.is_dir() or WORKER_RUNTIME_BASE.is_symlink():
        raise GeneralPartitionError("worker runtime base is not a stable directory")
    candidate = base / (
        WORKER_RUNTIME_PREFIX
        + plan_digest.removeprefix("sha256:")[:WORKER_RUNTIME_TOKEN_LENGTH]
    )
    try:
        candidate.relative_to(checkout)
    except ValueError:
        pass
    else:
        raise GeneralPartitionError(
            "worker runtime root must remain outside the checkout"
        )
    if len(str(candidate).encode("utf-8")) > MAX_WORKER_RUNTIME_ROOT_BYTES:
        raise GeneralPartitionError(
            "worker runtime root exceeds the bounded path budget"
        )
    return candidate


def _allocate_worker_runtime_root(
    *,
    plan: Mapping[str, Any],
    repo_root: Path,
) -> Path:
    """Exclusively allocate the short root used by xdist and socket fixtures."""

    candidate = _planned_worker_runtime_root(plan=plan, repo_root=repo_root)
    if candidate.exists() or candidate.is_symlink():
        raise GeneralPartitionError(
            f"worker runtime root already exists: {candidate}"
        )
    try:
        candidate.mkdir(mode=0o700)
    except OSError as exc:
        raise GeneralPartitionError(
            f"cannot allocate worker runtime root: {exc}"
        ) from exc
    return candidate.resolve(strict=True)


def _load_observation(path: Path) -> dict[str, Any]:
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise GeneralPartitionError(
            f"partition observation is invalid or missing: {path}: {exc}"
        ) from exc
    if document.get("schema_id") != PYTEST_OBSERVATION_SCHEMA_ID:
        raise GeneralPartitionError("partition observation schema is invalid")
    return document


def _validate_worker_allocations(
    *,
    document: Mapping[str, Any],
    selected_nodes: Sequence[str],
    worker_root: Path,
    workers: int,
    require_existing_paths: bool = True,
) -> list[dict[str, Any]]:
    failures = document.get("worker_failures")
    if failures != []:
        raise GeneralPartitionError(
            f"parallel worker evidence contains failures: {failures!r}"
        )
    raw_allocations = document.get("worker_allocations")
    if not isinstance(raw_allocations, list) or len(raw_allocations) != workers:
        raise GeneralPartitionError("parallel worker allocation set is incomplete")
    expected_ids = tuple(f"gw{index}" for index in range(workers))
    actual_ids: list[str] = []
    assigned_nodes: list[str] = []
    seen_paths: set[str] = set()
    if worker_root.is_symlink():
        raise GeneralPartitionError(
            "parallel worker runtime root must not be a symlink"
        )
    try:
        root = worker_root.resolve(strict=require_existing_paths)
    except OSError as exc:
        raise GeneralPartitionError(
            "parallel worker runtime root is missing"
        ) from exc
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_allocations):
        if not isinstance(raw, dict) or set(raw) != {
            "worker_id",
            "temp_root",
            "cache_root",
            "pycache_root",
            "executed_nodes",
        }:
            raise GeneralPartitionError(
                f"parallel worker allocation {index} is malformed"
            )
        worker_id = raw["worker_id"]
        executed = _sorted_unique_strings(
            raw["executed_nodes"],
            context=f"worker {worker_id} executed nodes",
        )
        if not isinstance(worker_id, str):
            raise GeneralPartitionError("parallel worker id is invalid")
        actual_ids.append(worker_id)
        assigned_nodes.extend(executed)
        expected_paths = {
            "temp_root": root / worker_id / "tmp",
            "cache_root": root / worker_id / "cache",
            "pycache_root": root / worker_id / "pycache",
        }
        for field in ("temp_root", "cache_root", "pycache_root"):
            raw_path = raw[field]
            if not isinstance(raw_path, str) or raw_path in seen_paths:
                raise GeneralPartitionError(
                    f"parallel worker {field} is missing or shared"
                )
            seen_paths.add(raw_path)
            try:
                candidate = Path(raw_path)
                if candidate.is_symlink():
                    raise OSError("worker allocation path is a symlink")
                resolved = candidate.resolve(strict=require_existing_paths)
                resolved.relative_to(root)
            except (OSError, ValueError) as exc:
                raise GeneralPartitionError(
                    f"parallel worker {field} escaped its external root"
                ) from exc
            if resolved != expected_paths[field]:
                raise GeneralPartitionError(
                    f"parallel worker {field} drifted from its allocation"
                )
            if require_existing_paths and not resolved.is_dir():
                raise GeneralPartitionError(
                    f"parallel worker {field} is not a directory"
                )
        normalized.append(dict(raw))
    if tuple(actual_ids) != expected_ids:
        raise GeneralPartitionError("parallel worker ids drifted")
    if tuple(sorted(assigned_nodes)) != tuple(selected_nodes):
        raise GeneralPartitionError(
            "parallel workers did not execute each selected node exactly once"
        )
    if len(assigned_nodes) != len(set(assigned_nodes)):
        raise GeneralPartitionError(
            "parallel worker assignments contain duplicate nodes"
        )
    return normalized


def verify_partition_observation(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    observation_path: Path,
    partition: str,
    worker_root: Path | None,
    workers: int,
    require_worker_paths: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Close one partition's collection, deselection, outcomes, and workers."""

    document = _load_observation(observation_path)
    expected_role = _PARTITION_ROLES[partition]
    if (
        document.get("invocation_id") != plan["invocation_id"]
        or document.get("role") != expected_role
        or document.get("mode") != "execute"
        or document.get("selection_manifest_digest") != manifest["self_digest"]
        or document.get("session_exit_code") != 0
    ):
        raise GeneralPartitionError(
            f"{partition} observation identity or exit status drifted"
        )
    general_records = _general_records(plan)
    markers = {
        str(item["node_id"]): list(item["markers"])
        for item in general_records
    }
    selected = tuple(manifest["selected_nodes"])
    planned = tuple(manifest["planned_deselected_nodes"])
    selected_records = [
        {"node_id": node_id, "markers": markers[node_id]}
        for node_id in selected
    ]
    planned_records = [
        {"node_id": node_id, "markers": markers[node_id]}
        for node_id in planned
    ]
    expected_deselected_records = sorted(
        [*_policy_records(plan), *planned_records],
        key=lambda item: str(item["node_id"]),
    )
    if (
        document.get("preselection_collection") != general_records
        or document.get("collection") != selected_records
        or document.get("planned_deselected") != list(planned)
        or document.get("deselected_markers") != expected_deselected_records
        or document.get("deselected")
        != [str(item["node_id"]) for item in expected_deselected_records]
    ):
        raise GeneralPartitionError(
            f"{partition} observation collection or deselection drifted"
        )
    raw_results = document.get("node_results")
    if not isinstance(raw_results, list):
        raise GeneralPartitionError(f"{partition} node results are missing")
    result_nodes = tuple(str(item.get("node_id")) for item in raw_results)
    if result_nodes != selected or any(
        not isinstance(item, dict)
        or set(item) != {"node_id", "outcome", "duration_ns", "phases"}
        or item["outcome"] not in {"pass", "skip", "xfail", "xpass"}
        or type(item["duration_ns"]) is not int
        or item["duration_ns"] < 0
        or not isinstance(item["phases"], list)
        for item in raw_results
    ):
        raise GeneralPartitionError(
            f"{partition} node outcomes are missing, unordered, or non-green"
        )
    allocations: list[dict[str, Any]] = []
    if partition == "parallel":
        if worker_root is None:
            raise GeneralPartitionError("parallel worker root is missing")
        allocations = _validate_worker_allocations(
            document=document,
            selected_nodes=selected,
            worker_root=worker_root,
            workers=workers,
            require_existing_paths=require_worker_paths,
        )
    elif any(
        field in document for field in ("worker_allocations", "worker_failures")
    ):
        raise GeneralPartitionError("serial partition contains worker evidence")
    return document, allocations


def merge_partition_observations(
    *,
    plan: Mapping[str, Any],
    general_manifest: Mapping[str, Any],
    serial_observation: Mapping[str, Any],
    parallel_observation: Mapping[str, Any],
    worker_allocations: Sequence[Mapping[str, Any]],
    started_monotonic_ns: int,
) -> dict[str, Any]:
    """Produce the existing whole-residual observation contract from two proofs."""

    general_records = _general_records(plan)
    markers = {
        str(item["node_id"]): list(item["markers"])
        for item in general_records
    }
    residual_nodes = tuple(general_manifest["selected_nodes"])
    qualification_nodes = tuple(general_manifest["planned_deselected_nodes"])
    results = [
        *serial_observation["node_results"],
        *parallel_observation["node_results"],
    ]
    results.sort(key=lambda item: str(item["node_id"]))
    if tuple(str(item["node_id"]) for item in results) != residual_nodes:
        raise GeneralPartitionError(
            "serial/parallel observations do not close the residual exactly"
        )
    expected_deselected_records = sorted(
        [
            *_policy_records(plan),
            *(
                {"node_id": node_id, "markers": markers[node_id]}
                for node_id in qualification_nodes
            ),
        ],
        key=lambda item: str(item["node_id"]),
    )
    finished = time.monotonic_ns()
    return seal_document(
        PYTEST_OBSERVATION_SCHEMA_ID,
        {
            "invocation_id": plan["invocation_id"],
            "role": "general_residual",
            "mode": "execute",
            "pytest_argv": [
                "openzyme-test-gate",
                "exact-resource-partitions",
                "--dist",
                PARALLEL_DISTRIBUTION,
                "--workers",
                str(plan["worker_policy"]["workers"]),
            ],
            "cwd": plan["stages"][4]["cwd"],
            "collection": [
                {"node_id": node_id, "markers": markers[node_id]}
                for node_id in residual_nodes
            ],
            "deselected": [
                str(item["node_id"]) for item in expected_deselected_records
            ],
            "deselected_markers": expected_deselected_records,
            "node_results": results,
            "session_exit_code": 0,
            "started_monotonic_ns": started_monotonic_ns,
            "duration_ns": max(0, finished - started_monotonic_ns),
            "preselection_collection": general_records,
            "planned_deselected": list(qualification_nodes),
            "selection_manifest_digest": general_manifest["self_digest"],
            "partition_observations": [
                {
                    "partition": "parallel",
                    "observation_digest": parallel_observation["self_digest"],
                },
                {
                    "partition": "serial",
                    "observation_digest": serial_observation["self_digest"],
                },
            ],
            "worker_allocations": [dict(item) for item in worker_allocations],
            "worker_failures": [],
        },
    )


def _process_failure(partition: str, result: ProcessResult) -> GeneralPartitionError:
    return GeneralPartitionError(
        f"{partition} pytest failed with {result.outcome}: "
        f"stdout={result.stdout.tail[-2000:]!r} "
        f"stderr={result.stderr.tail[-2000:]!r}"
    )


def execute_general_partitions(
    *,
    repo_root: Path,
    output_root: Path,
    plan: Mapping[str, Any],
    general_manifest: Mapping[str, Any],
    resource_manifest_path: Path,
    config: TestGateConfig,
    environment: Mapping[str, str],
    process_runner=run_command,
) -> dict[str, Any]:
    """Run the eligible loadfile partition, then the serial-unknown fallback."""

    started = time.monotonic_ns()
    root = repo_root.resolve(strict=True)
    evidence_root = output_root.resolve(strict=True)
    if str(evidence_root) != plan.get("output_root"):
        raise GeneralPartitionError("partition output root drifted from the plan")
    workers = validate_worker_count(
        plan["worker_policy"]["workers"],
        hard_max=config.worker_hard_max,
    )
    xdist_identity = probe_xdist_identity()
    if plan["worker_policy"].get("xdist_identity") != xdist_identity:
        raise GeneralPartitionError("pytest-xdist implementation identity drifted")
    resource_document, assignments = load_resource_manifest(
        resource_manifest_path,
        repo_root=root,
        collection_records=_general_records(plan),
        config=config,
    )
    if plan["worker_policy"].get("resource_manifest_digest") != (
        resource_document["self_digest"]
    ):
        raise GeneralPartitionError("resource manifest plan binding drifted")
    serial_nodes, parallel_nodes = resource_partition(
        residual_nodes=general_manifest["selected_nodes"],
        assignments=assignments,
        config=config,
    )
    if not parallel_nodes:
        raise GeneralPartitionError("parallel partition unexpectedly selected zero nodes")
    manifests = {
        "parallel": build_partition_manifest(
            plan=plan,
            selected_nodes=parallel_nodes,
            partition="parallel",
            resource_manifest_digest=resource_document["self_digest"],
            workers=workers,
        ),
        "serial": build_partition_manifest(
            plan=plan,
            selected_nodes=serial_nodes,
            partition="serial",
            resource_manifest_digest=resource_document["self_digest"],
            workers=workers,
        ),
    }
    for partition, filename in (
        ("parallel", PARALLEL_MANIFEST_FILENAME),
        ("serial", SERIAL_MANIFEST_FILENAME),
    ):
        verify_partition_manifest(
            manifests[partition],
            plan=plan,
            selected_nodes=(
                parallel_nodes if partition == "parallel" else serial_nodes
            ),
            partition=partition,
            resource_manifest_digest=resource_document["self_digest"],
            workers=workers,
        )
        publish_no_replace(
            evidence_root / filename,
            canonical_document_bytes(manifests[partition]),
        )
    worker_root = _allocate_worker_runtime_root(
        plan=plan,
        repo_root=root,
    )
    parallel_result = process_runner(
        partition_argv(
            config=config,
            output_root=evidence_root,
            worker_root=worker_root,
            invocation_id=str(plan["invocation_id"]),
            partition="parallel",
            workers=workers,
        ),
        cwd=root,
        environment=environment,
        timeout_seconds=float(plan["stages"][4]["deadline_seconds"]),
    )
    if parallel_result.outcome != "pass":
        raise _process_failure("parallel", parallel_result)
    parallel_observation, allocations = verify_partition_observation(
        plan=plan,
        manifest=manifests["parallel"],
        observation_path=evidence_root / PARALLEL_OBSERVATION_FILENAME,
        partition="parallel",
        worker_root=worker_root,
        workers=workers,
    )
    serial_result = process_runner(
        partition_argv(
            config=config,
            output_root=evidence_root,
            worker_root=None,
            invocation_id=str(plan["invocation_id"]),
            partition="serial",
            workers=workers,
        ),
        cwd=root,
        environment=environment,
        timeout_seconds=float(plan["stages"][4]["deadline_seconds"]),
    )
    if serial_result.outcome != "pass":
        raise _process_failure("serial", serial_result)
    serial_observation, _ = verify_partition_observation(
        plan=plan,
        manifest=manifests["serial"],
        observation_path=evidence_root / SERIAL_OBSERVATION_FILENAME,
        partition="serial",
        worker_root=None,
        workers=1,
    )
    merged = merge_partition_observations(
        plan=plan,
        general_manifest=general_manifest,
        serial_observation=serial_observation,
        parallel_observation=parallel_observation,
        worker_allocations=allocations,
        started_monotonic_ns=started,
    )
    publish_no_replace(
        evidence_root / MERGED_OBSERVATION_FILENAME,
        canonical_document_bytes(merged),
    )
    return merged


def _load_partition_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise GeneralPartitionError(
            f"partition manifest must not be a symlink: {path}"
        )
    try:
        document = load_canonical_document_bytes(path.read_bytes())
        verify_sealed_document(document)
    except (OSError, ValueError) as exc:
        raise GeneralPartitionError(
            f"partition manifest is invalid or missing: {path}: {exc}"
        ) from exc
    if document.get("schema_id") != NODE_MANIFEST_SCHEMA_ID:
        raise GeneralPartitionError("partition manifest schema is invalid")
    return document


def verify_general_partition_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    plan: Mapping[str, Any],
    general_manifest: Mapping[str, Any],
    resource_manifest_path: Path,
    config: TestGateConfig,
    require_worker_paths: bool = False,
) -> dict[str, Any]:
    """Purely close the exact serial/parallel evidence below merged general G."""

    root = repo_root.resolve(strict=True)
    evidence_root = output_root.resolve(strict=True)
    if str(evidence_root) != plan.get("output_root"):
        raise GeneralPartitionError(
            "partition evidence root drifted from the plan"
        )
    workers = validate_worker_count(
        plan["worker_policy"]["workers"],
        hard_max=config.worker_hard_max,
    )
    resource_document, assignments = load_resource_manifest(
        resource_manifest_path,
        repo_root=root,
        collection_records=_general_records(plan),
        config=config,
        allow_stale_as_serial=workers == 1,
    )
    if plan["worker_policy"].get("resource_manifest_digest") != (
        resource_document["self_digest"]
    ):
        raise GeneralPartitionError(
            "partition resource manifest binding drifted"
        )
    serial_nodes, parallel_nodes = resource_partition(
        residual_nodes=general_manifest["selected_nodes"],
        assignments=assignments,
        config=config,
    )
    if not parallel_nodes:
        raise GeneralPartitionError(
            "partition bundle has no proven parallel-eligible nodes"
        )
    parallel_manifest = _load_partition_manifest(
        evidence_root / PARALLEL_MANIFEST_FILENAME
    )
    serial_manifest = _load_partition_manifest(
        evidence_root / SERIAL_MANIFEST_FILENAME
    )
    verify_partition_manifest(
        parallel_manifest,
        plan=plan,
        selected_nodes=parallel_nodes,
        partition="parallel",
        resource_manifest_digest=resource_document["self_digest"],
        workers=workers,
    )
    verify_partition_manifest(
        serial_manifest,
        plan=plan,
        selected_nodes=serial_nodes,
        partition="serial",
        resource_manifest_digest=resource_document["self_digest"],
        workers=workers,
    )
    worker_root = _planned_worker_runtime_root(
        plan=plan,
        repo_root=root,
    )
    parallel_observation, allocations = verify_partition_observation(
        plan=plan,
        manifest=parallel_manifest,
        observation_path=evidence_root / PARALLEL_OBSERVATION_FILENAME,
        partition="parallel",
        worker_root=worker_root,
        workers=workers,
        require_worker_paths=require_worker_paths,
    )
    serial_observation, _ = verify_partition_observation(
        plan=plan,
        manifest=serial_manifest,
        observation_path=evidence_root / SERIAL_OBSERVATION_FILENAME,
        partition="serial",
        worker_root=None,
        workers=1,
        require_worker_paths=require_worker_paths,
    )
    merged = _load_observation(evidence_root / MERGED_OBSERVATION_FILENAME)
    if merged.get("partition_observations") != [
        {
            "partition": "parallel",
            "observation_digest": parallel_observation["self_digest"],
        },
        {
            "partition": "serial",
            "observation_digest": serial_observation["self_digest"],
        },
    ]:
        raise GeneralPartitionError(
            "merged observation partition digests drifted"
        )
    if (
        merged.get("worker_allocations") != allocations
        or merged.get("worker_failures") != []
    ):
        raise GeneralPartitionError(
            "merged observation worker evidence drifted"
        )
    partition_results = sorted(
        [
            *parallel_observation["node_results"],
            *serial_observation["node_results"],
        ],
        key=lambda item: str(item["node_id"]),
    )
    if merged.get("node_results") != partition_results:
        raise GeneralPartitionError(
            "merged observation results drifted from its partitions"
        )
    return {
        "parallel_manifest_digest": parallel_manifest["self_digest"],
        "serial_manifest_digest": serial_manifest["self_digest"],
        "parallel_observation_digest": parallel_observation["self_digest"],
        "serial_observation_digest": serial_observation["self_digest"],
        "merged_observation_digest": merged["self_digest"],
        "workers": workers,
    }


def load_partition_inputs(
    *,
    plan_path: Path,
    general_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Strictly load the sealed plan and whole-residual manifest for the CLI."""

    try:
        plan = load_canonical_document_bytes(plan_path.read_bytes())
        manifest = load_canonical_document_bytes(general_manifest_path.read_bytes())
        verify_sealed_document(plan)
        verify_sealed_document(manifest)
    except (OSError, ValueError) as exc:
        raise GeneralPartitionError(
            f"cannot load partition plan inputs: {exc}"
        ) from exc
    if (
        manifest.get("schema_id") != NODE_MANIFEST_SCHEMA_ID
        or manifest.get("role") != "general_residual"
        or manifest.get("plan_digest") != plan.get("self_digest")
    ):
        raise GeneralPartitionError("whole-residual manifest binding is invalid")
    return plan, manifest
