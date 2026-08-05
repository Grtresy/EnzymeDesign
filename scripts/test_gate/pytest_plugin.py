"""Pytest observation plugin for exact collection, outcomes, and timing."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import pytest

from .model import (
    NODE_MANIFEST_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
)
from .hypothesis_storage import configure_hypothesis_storage
from .runner import TestGateRunnerError, publish_no_replace

_PLUGIN_NAME = "openzyme-test-gate-observation"
_ROLES = {
    "legacy_general",
    "qualification_harness",
    "qualification_scenario",
    "general_parallel",
    "general_residual",
    "general_serial",
    "focused_diagnostic",
    "affected_scope_diagnostic",
}
_PARTITION_ROLES = {"general_parallel", "general_serial"}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("openzyme-test-gate")
    group.addoption(
        "--test-gate-observation",
        type=Path,
        help="absolute, new output path for canonical pytest observation",
    )
    group.addoption(
        "--test-gate-invocation-id",
        help="test-gate invocation id bound into the observation",
    )
    group.addoption(
        "--test-gate-role",
        choices=sorted(_ROLES),
        help="closed owner role for this pytest process",
    )
    group.addoption(
        "--test-gate-observation-mode",
        choices=("collect", "execute"),
        default="execute",
        help="whether this process is collection-only or executing nodes",
    )
    group.addoption(
        "--test-gate-node-manifest",
        type=Path,
        help=(
            "absolute canonical manifest selecting exact nodes after the full "
            "non-live collection has been revalidated"
        ),
    )
    group.addoption(
        "--test-gate-worker-root",
        type=Path,
        help="absolute external root for fixed xdist worker isolation",
    )


def _sorted_unique_strings(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise pytest.UsageError(f"node manifest {field} must be strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise pytest.UsageError(
            f"node manifest {field} must be sorted and unique"
        )
    return result


def _load_node_manifest(
    path: Path,
    *,
    invocation_id: str,
    role: str,
) -> Mapping[str, Any]:
    if not path.is_absolute():
        raise pytest.UsageError("test-gate node manifest path must be absolute")
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise pytest.UsageError(f"cannot load test-gate node manifest: {exc}") from exc
    if document["schema_id"] != NODE_MANIFEST_SCHEMA_ID:
        raise pytest.UsageError("test-gate node manifest schema is invalid")
    if document["invocation_id"] != invocation_id:
        raise pytest.UsageError(
            "test-gate node manifest belongs to a different invocation"
        )
    if document["role"] != role or role not in {
        "general_residual",
        *_PARTITION_ROLES,
    }:
        raise pytest.UsageError("test-gate node manifest role is invalid")
    if role in _PARTITION_ROLES:
        expected_partition = role.removeprefix("general_")
        if (
            document.get("resource_partition") != expected_partition
            or type(document.get("worker_count")) is not int
            or not isinstance(document.get("resource_manifest_digest"), str)
        ):
            raise pytest.UsageError(
                "test-gate partition manifest lacks its resource binding"
            )
    for field, digest_field in (
        ("selected_nodes", "selected_nodes_digest"),
        ("planned_deselected_nodes", "planned_deselected_digest"),
        (
            "expected_policy_deselected_nodes",
            "expected_policy_deselected_digest",
        ),
    ):
        nodes = _sorted_unique_strings(document[field], field=field)
        expected_digest = sha256_digest(canonical_json_bytes(list(nodes)))
        if document[digest_field] != expected_digest:
            raise pytest.UsageError(
                f"test-gate node manifest {field} digest mismatch"
            )
    return document


def _activate_worker_allocation(allocation: Mapping[str, Any]) -> None:
    required = {
        "worker_id",
        "temp_root",
        "cache_root",
        "pycache_root",
    }
    if set(allocation) != required:
        raise pytest.UsageError("xdist worker allocation fields are not closed")
    for field in ("temp_root", "cache_root", "pycache_root"):
        raw_path = allocation[field]
        if not isinstance(raw_path, str):
            raise pytest.UsageError("xdist worker allocation path is invalid")
        path = Path(raw_path)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise pytest.UsageError(
                f"xdist worker allocation {field} is not an isolated directory"
            )
    worker_id = allocation["worker_id"]
    if not isinstance(worker_id, str) or not worker_id.startswith("gw"):
        raise pytest.UsageError("xdist worker id is invalid")
    os.environ.update(
        {
            "TMPDIR": str(allocation["temp_root"]),
            "TMP": str(allocation["temp_root"]),
            "TEMP": str(allocation["temp_root"]),
            "XDG_CACHE_HOME": str(allocation["cache_root"]),
            "PYTHONPYCACHEPREFIX": str(allocation["pycache_root"]),
            "OPENZYME_TEST_WORKER_ID": worker_id,
        }
    )
    configure_hypothesis_storage(
        repo_root=Path(__file__).resolve().parents[2],
        storage_path=Path(allocation["cache_root"]) / "hypothesis",
    )
    tempfile.tempdir = None
    sys.pycache_prefix = str(allocation["pycache_root"])


def pytest_configure(config: pytest.Config) -> None:
    output_path = config.getoption("--test-gate-observation")
    invocation_id = config.getoption("--test-gate-invocation-id")
    role = config.getoption("--test-gate-role")
    manifest_path = config.getoption("--test-gate-node-manifest")
    worker_root = config.getoption("--test-gate-worker-root")
    if (
        output_path is None
        and invocation_id is None
        and role is None
        and manifest_path is None
        and worker_root is None
    ):
        return
    if output_path is None or invocation_id is None or role is None:
        raise pytest.UsageError(
            "test-gate observation path, invocation id, and role are all required"
        )
    if not output_path.is_absolute():
        raise pytest.UsageError("test-gate observation path must be absolute")
    if output_path.exists() or output_path.is_symlink():
        raise pytest.UsageError("test-gate observation output must not exist")
    if worker_root is not None and (
        not worker_root.is_absolute()
        or worker_root.is_symlink()
        or not worker_root.is_dir()
    ):
        raise pytest.UsageError(
            "test-gate worker root must be an absolute existing directory"
        )
    mode = config.getoption("--test-gate-observation-mode")
    manifest = None
    if manifest_path is not None:
        if mode != "execute":
            raise pytest.UsageError(
                "test-gate node manifest requires execute observation mode"
            )
        manifest = _load_node_manifest(
            manifest_path,
            invocation_id=invocation_id,
            role=role,
        )
    is_worker = hasattr(config, "workerinput")
    worker_allocation: Mapping[str, Any] | None = None
    if is_worker:
        raw_allocation = config.workerinput.get(
            "openzyme_test_gate_worker_allocation"
        )
        if raw_allocation is not None:
            if not isinstance(raw_allocation, dict):
                raise pytest.UsageError("xdist worker allocation is malformed")
            worker_allocation = raw_allocation
            _activate_worker_allocation(worker_allocation)
    plugin = ObservationPlugin(
        config=config,
        output_path=output_path,
        invocation_id=invocation_id,
        role=role,
        mode=mode,
        selection_manifest=manifest,
        worker_root=worker_root,
        worker_allocation=worker_allocation,
        is_worker=is_worker,
    )
    config.pluginmanager.register(plugin, _PLUGIN_NAME)


class ObservationPlugin:
    """Per-process pytest observer with deterministic final reduction."""

    def __init__(
        self,
        *,
        config: pytest.Config,
        output_path: Path,
        invocation_id: str,
        role: str,
        mode: str,
        selection_manifest: Mapping[str, Any] | None = None,
        worker_root: Path | None = None,
        worker_allocation: Mapping[str, Any] | None = None,
        is_worker: bool = False,
    ) -> None:
        self.config = config
        self.output_path = output_path
        self.invocation_id = invocation_id
        self.role = role
        self.mode = mode
        self.selection_manifest = selection_manifest
        self.worker_root = worker_root
        self.worker_allocation = worker_allocation
        self.is_worker = is_worker
        self.is_xdist_controller = (
            not is_worker
            and type(getattr(config.option, "numprocesses", None)) is int
            and int(config.option.numprocesses) > 0
        )
        self.started_monotonic_ns = 0
        self.collection: dict[str, tuple[str, ...]] = {}
        self.preselection_collection: dict[str, tuple[str, ...]] = {}
        self.deselected: set[str] = set()
        self.deselected_markers: dict[str, tuple[str, ...]] = {}
        self.planned_deselected: set[str] = set()
        self.phases: dict[str, list[dict[str, object]]] = {}
        self.node_started: dict[str, int] = {}
        self.node_duration: dict[str, int] = {}
        self.node_workers: dict[str, str] = {}
        self.worker_collections: dict[str, tuple[str, ...]] = {}
        self.worker_metadata: dict[str, Mapping[str, Any]] = {}
        self.worker_failures: list[str] = []
        self.configured_workers: set[str] = set()
        self.expected_allocations: dict[str, Mapping[str, str]] = {}

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        if not self.is_xdist_controller:
            return
        if self.role != "general_parallel" or self.worker_root is None:
            raise pytest.UsageError(
                "xdist is restricted to the resource-bound parallel partition"
            )
        worker_id = str(node.gateway.id)
        if worker_id in self.configured_workers:
            raise pytest.UsageError(f"duplicate xdist worker id {worker_id!r}")
        expected_workers = int(self.selection_manifest["worker_count"])
        if len(self.configured_workers) >= expected_workers:
            raise pytest.UsageError(
                "xdist attempted to replace or exceed the fixed worker set"
            )
        allocation_root = self.worker_root / worker_id
        try:
            allocation_root.mkdir()
            temp_root = allocation_root / "tmp"
            cache_root = allocation_root / "cache"
            pycache_root = allocation_root / "pycache"
            for path in (temp_root, cache_root, pycache_root):
                path.mkdir()
        except OSError as exc:
            raise pytest.UsageError(
                f"cannot allocate isolated xdist worker root: {exc}"
            ) from exc
        allocation = {
            "worker_id": worker_id,
            "temp_root": str(temp_root),
            "cache_root": str(cache_root),
            "pycache_root": str(pycache_root),
        }
        node.workerinput["openzyme_test_gate_worker_allocation"] = allocation
        self.configured_workers.add(worker_id)
        self.expected_allocations[worker_id] = allocation

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(
        self,
        node: Any,
        ids: list[str],
    ) -> None:
        if not self.is_xdist_controller:
            return
        worker_id = str(node.gateway.id)
        collection = tuple(str(item) for item in ids)
        selected_nodes = tuple(self.selection_manifest["selected_nodes"])
        if (
            len(collection) != len(set(collection))
            or set(collection) != set(selected_nodes)
        ):
            self.worker_failures.append(
                f"{worker_id}:collection_drift"
            )
        self.worker_collections[worker_id] = collection

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        if not self.is_xdist_controller:
            return
        worker_id = str(node.gateway.id)
        if error is not None:
            self.worker_failures.append(f"{worker_id}:worker_crash")
        raw_output = getattr(node, "workeroutput", None)
        metadata = (
            raw_output.get("openzyme_test_gate")
            if isinstance(raw_output, dict)
            else None
        )
        if not isinstance(metadata, dict):
            self.worker_failures.append(f"{worker_id}:missing_worker_output")
            return
        self.worker_metadata[worker_id] = metadata

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        del session
        self.started_monotonic_ns = time.monotonic_ns()

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(
        self,
        session: pytest.Session,
        config: pytest.Config,
        items: list[pytest.Item],
    ) -> None:
        del session
        preselection: dict[str, tuple[str, ...]] = {}
        for item in items:
            node_id = str(item.nodeid)
            if node_id in preselection:
                raise pytest.UsageError(
                    f"test-gate collection contains duplicate node id {node_id!r}"
                )
            preselection[node_id] = tuple(
                sorted({marker.name for marker in item.iter_markers()})
            )
        if self.selection_manifest is not None:
            manifest = self.selection_manifest
            canonical_preselection = [
                {
                    "node_id": node_id,
                    "markers": list(preselection[node_id]),
                }
                for node_id in sorted(preselection)
            ]
            actual_digest = sha256_digest(
                canonical_json_bytes(canonical_preselection)
            )
            if actual_digest != manifest["full_collection_digest"]:
                raise pytest.UsageError(
                    "test-gate full collection drifted from the node manifest"
                )
            expected_policy_deselected = tuple(
                manifest["expected_policy_deselected_nodes"]
            )
            if tuple(sorted(self.deselected)) != expected_policy_deselected:
                raise pytest.UsageError(
                    "test-gate policy deselection drifted from the node manifest"
                )
            selected_nodes = tuple(manifest["selected_nodes"])
            planned_deselected_nodes = tuple(
                manifest["planned_deselected_nodes"]
            )
            if set(selected_nodes) & set(planned_deselected_nodes):
                raise pytest.UsageError(
                    "test-gate selected and planned-deselected nodes overlap"
                )
            if set(selected_nodes) | set(planned_deselected_nodes) != set(
                preselection
            ):
                raise pytest.UsageError(
                    "test-gate node manifest does not partition the full collection"
                )
            selected_set = set(selected_nodes)
            selected_items = [
                item for item in items if str(item.nodeid) in selected_set
            ]
            planned_items = [
                item for item in items if str(item.nodeid) not in selected_set
            ]
            if tuple(sorted(str(item.nodeid) for item in selected_items)) != (
                selected_nodes
            ):
                raise pytest.UsageError(
                    "test-gate manifest selected nodes are missing from collection"
                )
            if tuple(sorted(str(item.nodeid) for item in planned_items)) != (
                planned_deselected_nodes
            ):
                raise pytest.UsageError(
                    "test-gate planned deselection drifted from collection"
                )
            self.preselection_collection = preselection
            self.planned_deselected = set(planned_deselected_nodes)
            items[:] = selected_items
            if planned_items:
                config.hook.pytest_deselected(items=planned_items)
        collection: dict[str, tuple[str, ...]] = {}
        for item in items:
            node_id = str(item.nodeid)
            collection[node_id] = tuple(
                sorted({marker.name for marker in item.iter_markers()})
            )
        self.collection = collection

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        for item in items:
            node_id = str(item.nodeid)
            if node_id in self.deselected:
                raise pytest.UsageError(
                    f"test-gate observed duplicate deselection {node_id!r}"
                )
            self.deselected.add(node_id)
            self.deselected_markers[node_id] = tuple(
                sorted({marker.name for marker in item.iter_markers()})
            )

    def pytest_runtest_logstart(
        self,
        nodeid: str,
        location: tuple[str, int | None, str],
    ) -> None:
        del location
        self.node_started[nodeid] = time.monotonic_ns()

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        worker_id = getattr(report, "worker_id", None)
        if worker_id is None:
            report_node = getattr(report, "node", None)
            gateway = getattr(report_node, "gateway", None)
            worker_id = getattr(gateway, "id", None)
        if worker_id is not None:
            previous = self.node_workers.setdefault(
                str(report.nodeid),
                str(worker_id),
            )
            if previous != str(worker_id):
                self.worker_failures.append(
                    f"{report.nodeid}:multiple_workers"
                )
        longrepr = "" if report.passed else str(report.longrepr)
        phase = {
            "phase": str(report.when),
            "outcome": str(report.outcome),
            "duration_ns": max(0, round(float(report.duration) * 1_000_000_000)),
            "was_xfail": bool(getattr(report, "wasxfail", False)),
            "failure_digest": (
                None
                if not longrepr
                else f"sha256:{hashlib.sha256(longrepr.encode('utf-8')).hexdigest()}"
            ),
        }
        if worker_id is not None:
            phase["worker_id"] = str(worker_id)
        self.phases.setdefault(str(report.nodeid), []).append(phase)

    def pytest_runtest_logfinish(
        self,
        nodeid: str,
        location: tuple[str, int | None, str],
    ) -> None:
        del location
        started = self.node_started.get(nodeid)
        if started is not None:
            self.node_duration[nodeid] = max(0, time.monotonic_ns() - started)

    def _node_outcome(self, phases: list[dict[str, object]]) -> str:
        for phase in phases:
            if phase["was_xfail"] and phase["outcome"] == "passed":
                return "xpass"
            if phase["was_xfail"]:
                return "xfail"
        if any(
            phase["phase"] in {"setup", "teardown"}
            and phase["outcome"] == "failed"
            for phase in phases
        ):
            return "error"
        if any(phase["outcome"] == "skipped" for phase in phases):
            return "skip"
        if any(
            phase["phase"] == "call" and phase["outcome"] == "failed"
            for phase in phases
        ):
            return "fail"
        if any(
            phase["phase"] == "call" and phase["outcome"] == "passed"
            for phase in phases
        ):
            return "pass"
        return "error"

    def _node_results(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for node_id in sorted(self.phases):
            phases = self.phases[node_id]
            results.append(
                {
                    "node_id": node_id,
                    "outcome": self._node_outcome(phases),
                    "duration_ns": self.node_duration.get(
                        node_id,
                        sum(int(phase["duration_ns"]) for phase in phases),
                    ),
                    "phases": phases,
                }
            )
        return results

    def _worker_session_metadata(
        self,
        *,
        exitstatus: int | pytest.ExitCode,
    ) -> dict[str, Any]:
        active_children = [
            {
                "name": str(child.name),
                "pid": child.pid,
            }
            for child in multiprocessing.active_children()
            if child.is_alive()
        ]
        return {
            "allocation": (
                None
                if self.worker_allocation is None
                else dict(self.worker_allocation)
            ),
            "collection": [
                {"node_id": node_id, "markers": list(self.collection[node_id])}
                for node_id in sorted(self.collection)
            ],
            "preselection_collection": [
                {
                    "node_id": node_id,
                    "markers": list(self.preselection_collection[node_id]),
                }
                for node_id in sorted(self.preselection_collection)
            ],
            "deselected": sorted(self.deselected),
            "deselected_markers": [
                {
                    "node_id": node_id,
                    "markers": list(self.deselected_markers[node_id]),
                }
                for node_id in sorted(self.deselected_markers)
            ],
            "planned_deselected": sorted(self.planned_deselected),
            "session_exit_code": int(exitstatus),
            "active_children": active_children,
        }

    def _close_xdist_worker_evidence(self) -> list[dict[str, Any]]:
        expected_workers = int(self.selection_manifest["worker_count"])
        expected_ids = tuple(f"gw{index}" for index in range(expected_workers))
        if tuple(sorted(self.configured_workers)) != expected_ids:
            self.worker_failures.append("configured_worker_set_drift")
        if tuple(sorted(self.worker_collections)) != expected_ids:
            self.worker_failures.append("collection_worker_set_drift")
        if tuple(sorted(self.worker_metadata)) != expected_ids:
            self.worker_failures.append("metadata_worker_set_drift")
        reference: Mapping[str, Any] | None = None
        allocations: list[dict[str, Any]] = []
        for worker_id in expected_ids:
            metadata = self.worker_metadata.get(worker_id)
            if metadata is None:
                continue
            allocation = metadata.get("allocation")
            if allocation != self.expected_allocations.get(worker_id):
                self.worker_failures.append(f"{worker_id}:allocation_drift")
            if isinstance(allocation, dict):
                allocation_record = dict(allocation)
                allocation_record["executed_nodes"] = sorted(
                    node_id
                    for node_id, owner_worker in self.node_workers.items()
                    if owner_worker == worker_id
                )
                allocations.append(allocation_record)
            active_children = metadata.get("active_children")
            if active_children != []:
                self.worker_failures.append(f"{worker_id}:leaked_process")
            if metadata.get("session_exit_code") != 0:
                self.worker_failures.append(f"{worker_id}:nonzero_session")
            comparable = {
                key: metadata.get(key)
                for key in (
                    "collection",
                    "preselection_collection",
                    "deselected",
                    "deselected_markers",
                    "planned_deselected",
                )
            }
            if reference is None:
                reference = comparable
            elif comparable != reference:
                self.worker_failures.append(
                    f"{worker_id}:worker_collection_disagreement"
                )
        if reference is None:
            self.worker_failures.append("missing_worker_collection_evidence")
            return allocations
        self.collection = {
            str(item["node_id"]): tuple(item["markers"])
            for item in reference["collection"]
        }
        self.preselection_collection = {
            str(item["node_id"]): tuple(item["markers"])
            for item in reference["preselection_collection"]
        }
        self.deselected = set(reference["deselected"])
        self.deselected_markers = {
            str(item["node_id"]): tuple(item["markers"])
            for item in reference["deselected_markers"]
        }
        self.planned_deselected = set(reference["planned_deselected"])
        expected_selected = set(self.selection_manifest["selected_nodes"])
        if set(self.phases) != expected_selected:
            self.worker_failures.append("executed_node_set_drift")
        if set(self.node_workers) != expected_selected:
            self.worker_failures.append("worker_assignment_set_drift")
        return allocations

    def pytest_sessionfinish(
        self,
        session: pytest.Session,
        exitstatus: int | pytest.ExitCode,
    ) -> None:
        if self.is_worker:
            self.config.workeroutput["openzyme_test_gate"] = (
                self._worker_session_metadata(exitstatus=exitstatus)
            )
            return
        finished = time.monotonic_ns()
        worker_allocations: list[dict[str, Any]] | None = None
        if self.is_xdist_controller:
            worker_allocations = self._close_xdist_worker_evidence()
            if self.worker_failures:
                session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
                exitstatus = pytest.ExitCode.INTERNAL_ERROR
        fields: dict[str, Any] = {
                "invocation_id": self.invocation_id,
                "role": self.role,
                "mode": self.mode,
                "pytest_argv": list(sys.argv),
                "cwd": str(Path.cwd().resolve()),
                "collection": [
                    {"node_id": node_id, "markers": list(self.collection[node_id])}
                    for node_id in sorted(self.collection)
                ],
                "deselected": sorted(self.deselected),
                "deselected_markers": [
                    {
                        "node_id": node_id,
                        "markers": list(self.deselected_markers[node_id]),
                    }
                    for node_id in sorted(self.deselected_markers)
                ],
                "node_results": self._node_results(),
                "session_exit_code": int(exitstatus),
                "started_monotonic_ns": self.started_monotonic_ns,
                "duration_ns": max(0, finished - self.started_monotonic_ns),
        }
        if self.selection_manifest is not None:
            fields.update(
                {
                    "preselection_collection": [
                        {
                            "node_id": node_id,
                            "markers": list(
                                self.preselection_collection[node_id]
                            ),
                        }
                        for node_id in sorted(self.preselection_collection)
                    ],
                    "planned_deselected": sorted(self.planned_deselected),
                    "selection_manifest_digest": self.selection_manifest[
                        "self_digest"
                    ],
                }
            )
        if worker_allocations is not None:
            fields.update(
                {
                    "worker_allocations": worker_allocations,
                    "worker_failures": sorted(set(self.worker_failures)),
                }
            )
        document = seal_document(PYTEST_OBSERVATION_SCHEMA_ID, fields)
        try:
            publish_no_replace(
                self.output_path,
                canonical_document_bytes(document),
            )
        except TestGateRunnerError as exc:
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
            raise pytest.UsageError(
                f"cannot publish test-gate observation: {exc}"
            ) from exc
