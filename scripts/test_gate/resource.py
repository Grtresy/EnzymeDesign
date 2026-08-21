"""Exact resource classification and fixed pytest-xdist implementation identity."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .config import RESOURCE_CLASSES, TestGateConfig
from .model import (
    RESOURCE_MANIFEST_SCHEMA_ID,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
    verify_sealed_document,
)

DEFAULT_RESOURCE_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "test-resource-manifest.json"
)
PINNED_PYTEST_XDIST_VERSION = "3.8.0"
PINNED_EXECNET_VERSION = "2.1.2"
PARALLEL_DISTRIBUTION = "loadfile"

_ENTRY_FIELDS = {
    "entry_id",
    "module_path",
    "resource_class",
    "collection_digest",
    "source_closure",
    "fixture_closure",
    "proof_node_ids",
    "audited_resources",
}
_FILE_RECORD_FIELDS = {"path", "digest"}
_AUDIT_FIELDS = {"resource", "disposition", "evidence"}
_AUDITED_RESOURCE_NAMES = (
    "cache",
    "cwd",
    "environment",
    "filesystem",
    "micu",
    "port",
    "process",
    "qualification",
    "sandbox",
    "signal",
    "sqlite",
)
_TOP_LEVEL_FIELDS = {
    "schema_id",
    "default_class",
    "parallel_eligible_classes",
    "distribution",
    "entries",
    "self_digest",
}
_MANIFEST_RESOURCE_CLASSES = frozenset(
    {"parallel_pure", "parallel_temp_root", "bounded_service"}
)


class ResourceManifestError(RuntimeError):
    """Raised when parallel resource evidence is stale or unsafe."""


@dataclass(frozen=True)
class ResourceEntrySpec:
    """Repository-maintained input for generating an exact manifest entry."""

    entry_id: str
    module_path: str
    resource_class: str
    fixture_paths: tuple[str, ...]
    proof_node_ids: tuple[str, ...]
    audited_resources: tuple[tuple[str, str, str], ...]


def _common_audit(
    *,
    filesystem: str,
    sqlite: str,
    environment: str,
    process: str,
    micu: str = "forbidden",
    micu_evidence: str = "no MICU ledger or token consumer",
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                ("cache", "worker_isolated", "cache provider disabled; worker cache root"),
                ("cwd", "process_local", "tests do not change process cwd"),
                ("environment", environment, "worker process plus monkeypatch cleanup"),
                ("filesystem", filesystem, "source audit and exact module inspection"),
                ("micu", micu, micu_evidence),
                ("port", "forbidden", "no bound/listening socket or fixed Host port"),
                ("process", process, "bounded in-process lifecycle only"),
                ("qualification", "forbidden", "no qualification output or admission consumer"),
                ("sandbox", "forbidden", "no live sandbox or HPC workspace"),
                ("signal", "forbidden", "no process signal or process-group operation"),
                ("sqlite", sqlite, "memory or test-exclusive temporary path"),
            )
        )
    )


_HYPOTHESIS_STORAGE_FIXTURE = "scripts/test_gate/hypothesis_storage.py"
_HOST_FIXTURES = (
    "conftest.py",
    _HYPOTHESIS_STORAGE_FIXTURE,
)
_ROOT_FIXTURES = ("conftest.py", _HYPOTHESIS_STORAGE_FIXTURE)
_RESOURCE_PROOF_NODE = (
    "packages/openzyme-kernel/tests/test_test_gate_resource.py"
    "::test_initial_resource_entries_bind_exact_modules_and_safe_closure"
)
_WORKER_PROOF_NODE = (
    "packages/openzyme-kernel/tests/test_test_gate_resource.py"
    "::test_xdist_worker_allocations_are_unique_and_checkout_external"
)


def _parallel_temp_root_entry(
    *,
    entry_id: str,
    module_path: str,
    fixture_paths: tuple[str, ...],
    filesystem: str = "test_temp_root_or_immutable_checkout_read",
    sqlite: str = "memory_or_test_temp_root",
    environment: str = "worker_process_local_with_monkeypatch_cleanup",
    process: str = "none",
    micu: str = "forbidden",
    micu_evidence: str = "no MICU ledger or token consumer",
) -> ResourceEntrySpec:
    return ResourceEntrySpec(
        entry_id=entry_id,
        module_path=module_path,
        resource_class="parallel_temp_root",
        fixture_paths=fixture_paths,
        proof_node_ids=(_RESOURCE_PROOF_NODE, _WORKER_PROOF_NODE),
        audited_resources=_common_audit(
            filesystem=filesystem,
            sqlite=sqlite,
            environment=environment,
            process=process,
            micu=micu,
            micu_evidence=micu_evidence,
        ),
    )


INITIAL_RESOURCE_ENTRY_SPECS: tuple[ResourceEntrySpec, ...] = (
    ResourceEntrySpec(
        entry_id="host_api_v2_adapter_process_local",
        module_path="apps/openzyme-host-api/tests/test_v2_app.py",
        resource_class="bounded_service",
        fixture_paths=_HOST_FIXTURES,
        proof_node_ids=(_RESOURCE_PROOF_NODE,),
        audited_resources=_common_audit(
            filesystem="none",
            sqlite="none",
            environment="worker_process_local",
            process="bounded_subprocess_and_asgi_lifespan",
        ),
    ),
    _parallel_temp_root_entry(
        entry_id="kernel_test_gate_resource_worker_local",
        module_path="packages/openzyme-kernel/tests/test_test_gate_resource.py",
        fixture_paths=_ROOT_FIXTURES,
        filesystem="immutable_checkout_read",
        sqlite="none",
    ),
    _parallel_temp_root_entry(
        entry_id="kernel_compat_caller_audit_temp_root",
        module_path="packages/openzyme-kernel/tests/test_compat_caller_audit.py",
        fixture_paths=_ROOT_FIXTURES,
        filesystem="immutable_checkout_read_and_test_temp_root",
        sqlite="none",
    ),
    _parallel_temp_root_entry(
        entry_id="enzymedesign_aox_similarity_worker_local",
        module_path="packages/enzymedesign-aox-executor/tests/test_aox_similarity.py",
        fixture_paths=_ROOT_FIXTURES,
        filesystem="none",
        sqlite="none",
    ),
)


def _strict_mapping(
    value: Any,
    *,
    fields: set[str],
    context: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ResourceManifestError(
            f"{context} must contain exactly {sorted(fields)!r}"
        )
    return value


def _sorted_unique_strings(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ResourceManifestError(f"{context} must be an array of strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise ResourceManifestError(f"{context} must be sorted and unique")
    return result


def _relative_file(repo_root: Path, raw_path: str, *, context: str) -> Path:
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ResourceManifestError(f"{context} path is unsafe: {raw_path!r}")
    path = repo_root / pure
    if path.is_symlink() or not path.is_file():
        raise ResourceManifestError(
            f"{context} path is not a regular repository file: {raw_path!r}"
        )
    return path


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def audit_parallel_candidate_source(path: Path) -> None:
    """Reject direct shared-resource operations from a promoted test module."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ResourceManifestError(
            f"cannot audit parallel candidate source {path}: {exc}"
        ) from exc
    forbidden_calls = {
        "multiprocessing.Process",
        "os.chdir",
        "os.kill",
        "os.killpg",
        "signal.kill",
        "signal.pthread_kill",
        "socket.socket",
        "subprocess.Popen",
    }
    write_methods = {
        "mkdir",
        "open",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }

    def call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = call_name(node.value)
            return node.attr if owner is None else f"{owner}.{node.attr}"
        return None

    def absolute_literal_path(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return Path(node.value).is_absolute()
        if (
            isinstance(node, ast.Call)
            and call_name(node.func) == "Path"
            and node.args
        ):
            return absolute_literal_path(node.args[0])
        return False

    failures: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func)
        if name in forbidden_calls:
            failures.append(f"line {node.lineno}: forbidden call {name}")
        if name in {"open", "io.open"} and node.args and absolute_literal_path(
            node.args[0]
        ):
            failures.append(
                f"line {node.lineno}: fixed absolute file open"
            )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in write_methods
            and absolute_literal_path(node.func.value)
        ):
            failures.append(
                f"line {node.lineno}: fixed absolute filesystem mutation"
            )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"bind", "listen"}
        ):
            failures.append(
                f"line {node.lineno}: unbrokered service socket"
            )
        if name in {"monkeypatch.chdir", "pytest.MonkeyPatch.chdir"}:
            failures.append(f"line {node.lineno}: process cwd mutation")
    if failures:
        raise ResourceManifestError(
            f"parallel candidate source audit failed for {path}: {failures[0]}"
        )


def _file_records(repo_root: Path, paths: Sequence[str]) -> list[dict[str, str]]:
    records = []
    for raw_path in sorted(set(paths)):
        path = _relative_file(repo_root, raw_path, context="resource closure")
        records.append({"path": raw_path, "digest": _file_digest(path)})
    return records


def _records_digest(records: Sequence[Mapping[str, Any]]) -> str:
    return sha256_digest(canonical_json_bytes(list(records)))


def _module_nodes(
    collection_records: Sequence[Mapping[str, Any]],
    module_path: str,
) -> tuple[str, ...]:
    prefix = f"{module_path}::"
    return tuple(
        sorted(
            str(item["node_id"])
            for item in collection_records
            if str(item.get("node_id", "")).startswith(prefix)
        )
    )


def build_resource_manifest(
    *,
    repo_root: Path,
    collection_records: Sequence[Mapping[str, Any]],
    specs: Sequence[ResourceEntrySpec] = INITIAL_RESOURCE_ENTRY_SPECS,
) -> dict[str, Any]:
    """Build an exact manifest; publication remains an explicit repository edit."""

    root = repo_root.resolve(strict=True)
    all_nodes = {
        str(item["node_id"])
        for item in collection_records
        if isinstance(item, Mapping) and isinstance(item.get("node_id"), str)
    }
    entries: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    normalized_specs = tuple(sorted(specs, key=lambda item: item.entry_id))
    entry_ids = tuple(spec.entry_id for spec in normalized_specs)
    if len(entry_ids) != len(set(entry_ids)):
        raise ResourceManifestError("resource entry specs must be unique")
    for spec in normalized_specs:
        if spec.resource_class not in _MANIFEST_RESOURCE_CLASSES:
            raise ResourceManifestError(
                f"entry {spec.entry_id!r} has no manifest resource class"
            )
        module_nodes = _module_nodes(collection_records, spec.module_path)
        if not module_nodes:
            raise ResourceManifestError(
                f"entry {spec.entry_id!r} selected no current nodes"
            )
        overlap = seen_nodes & set(module_nodes)
        if overlap:
            raise ResourceManifestError(
                f"resource entries overlap at {sorted(overlap)[0]!r}"
            )
        seen_nodes.update(module_nodes)
        proof_nodes = tuple(sorted(set(spec.proof_node_ids)))
        missing_proofs = set(proof_nodes) - all_nodes
        if missing_proofs:
            raise ResourceManifestError(
                f"entry {spec.entry_id!r} proof is absent from G: "
                f"{sorted(missing_proofs)[0]!r}"
            )
        audited_resources = [
            {
                "resource": resource,
                "disposition": disposition,
                "evidence": evidence,
            }
            for resource, disposition, evidence in spec.audited_resources
        ]
        if tuple(item["resource"] for item in audited_resources) != (
            _AUDITED_RESOURCE_NAMES
        ):
            raise ResourceManifestError(
                f"entry {spec.entry_id!r} audit does not close every resource"
            )
        entries.append(
            {
                "entry_id": spec.entry_id,
                "module_path": spec.module_path,
                "resource_class": spec.resource_class,
                "collection_digest": sha256_digest(
                    canonical_json_bytes(list(module_nodes))
                ),
                "source_closure": _file_records(root, (spec.module_path,)),
                "fixture_closure": _file_records(root, spec.fixture_paths),
                "proof_node_ids": list(proof_nodes),
                "audited_resources": audited_resources,
            }
        )
    return seal_document(
        RESOURCE_MANIFEST_SCHEMA_ID,
        {
            "default_class": "serial_unknown",
            "parallel_eligible_classes": [
                "parallel_pure",
                "parallel_temp_root",
            ],
            "distribution": PARALLEL_DISTRIBUTION,
            "entries": entries,
        },
    )


def _verify_file_records(
    value: Any,
    *,
    repo_root: Path,
    context: str,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ResourceManifestError(f"{context} must be a nonempty array")
    paths: list[str] = []
    for index, raw in enumerate(value):
        record = _strict_mapping(
            raw,
            fields=_FILE_RECORD_FIELDS,
            context=f"{context}[{index}]",
        )
        raw_path = record["path"]
        digest = record["digest"]
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise ResourceManifestError(f"{context}[{index}] is invalid")
        path = _relative_file(repo_root, raw_path, context=context)
        if _file_digest(path) != digest:
            raise ResourceManifestError(
                f"{context} digest drifted for {raw_path!r}"
            )
        paths.append(raw_path)
    if tuple(paths) != tuple(sorted(set(paths))):
        raise ResourceManifestError(f"{context} paths must be sorted and unique")
    return tuple(paths)


def verify_resource_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
    collection_records: Sequence[Mapping[str, Any]],
    config: TestGateConfig,
    allow_stale_as_serial: bool = False,
) -> dict[str, str]:
    """Verify exact node, source, fixture, proof, and closed resource bindings."""

    try:
        verify_sealed_document(manifest)
    except ValueError as exc:
        raise ResourceManifestError(f"resource manifest is invalid: {exc}") from exc
    _strict_mapping(manifest, fields=_TOP_LEVEL_FIELDS, context="resource manifest")
    if manifest.get("schema_id") != RESOURCE_MANIFEST_SCHEMA_ID:
        raise ResourceManifestError("resource manifest schema is invalid")
    if manifest.get("default_class") != config.resource_policy.default_class:
        raise ResourceManifestError("resource manifest default class drifted")
    if manifest.get("parallel_eligible_classes") != list(
        config.resource_policy.parallel_eligible_classes
    ):
        raise ResourceManifestError("parallel eligible classes drifted")
    if manifest.get("distribution") != PARALLEL_DISTRIBUTION:
        raise ResourceManifestError("resource distribution must be fixed loadfile")
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ResourceManifestError("resource manifest entries are missing")
    all_nodes = {
        str(item["node_id"])
        for item in collection_records
        if isinstance(item, Mapping) and isinstance(item.get("node_id"), str)
    }
    assignments: dict[str, str] = {}
    entry_ids: list[str] = []
    root = repo_root.resolve(strict=True)
    for index, raw in enumerate(raw_entries):
        entry = _strict_mapping(
            raw,
            fields=_ENTRY_FIELDS,
            context=f"resource entries[{index}]",
        )
        entry_id = entry["entry_id"]
        module_path = entry["module_path"]
        resource_class = entry["resource_class"]
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(module_path, str)
            or resource_class not in _MANIFEST_RESOURCE_CLASSES
            or resource_class not in RESOURCE_CLASSES
        ):
            raise ResourceManifestError(f"resource entry {index} identity is invalid")
        entry_ids.append(entry_id)
        nodes = _module_nodes(collection_records, module_path)
        if not nodes:
            if allow_stale_as_serial:
                continue
            raise ResourceManifestError(
                f"resource entry {entry_id!r} selected no current nodes"
            )
        if entry["collection_digest"] != sha256_digest(
            canonical_json_bytes(list(nodes))
        ):
            if allow_stale_as_serial:
                continue
            raise ResourceManifestError(
                f"resource entry {entry_id!r} collection digest drifted"
            )
        if set(nodes) - all_nodes:
            raise ResourceManifestError(
                f"resource entry {entry_id!r} contains a newly absent node"
            )
        source_paths = _verify_file_records(
            entry["source_closure"],
            repo_root=root,
            context=f"resource entry {entry_id} source closure",
        )
        if source_paths != (module_path,):
            raise ResourceManifestError(
                f"resource entry {entry_id!r} source closure is not exact"
            )
        if resource_class in config.resource_policy.parallel_eligible_classes:
            audit_parallel_candidate_source(root / module_path)
        _verify_file_records(
            entry["fixture_closure"],
            repo_root=root,
            context=f"resource entry {entry_id} fixture closure",
        )
        proof_nodes = _sorted_unique_strings(
            entry["proof_node_ids"],
            context=f"resource entry {entry_id} proof nodes",
        )
        if not proof_nodes or set(proof_nodes) - all_nodes:
            raise ResourceManifestError(
                f"resource entry {entry_id!r} has a missing proof"
            )
        audits = entry["audited_resources"]
        if not isinstance(audits, list):
            raise ResourceManifestError(
                f"resource entry {entry_id!r} audit is missing"
            )
        audit_names: list[str] = []
        for audit_index, raw_audit in enumerate(audits):
            audit = _strict_mapping(
                raw_audit,
                fields=_AUDIT_FIELDS,
                context=f"resource entry {entry_id} audit[{audit_index}]",
            )
            if any(
                not isinstance(audit[field], str) or not audit[field]
                for field in _AUDIT_FIELDS
            ):
                raise ResourceManifestError(
                    f"resource entry {entry_id!r} audit is invalid"
                )
            audit_names.append(str(audit["resource"]))
        if tuple(audit_names) != _AUDITED_RESOURCE_NAMES:
            raise ResourceManifestError(
                f"resource entry {entry_id!r} audit is not closed"
            )
        for node_id in nodes:
            if node_id in assignments:
                raise ResourceManifestError(
                    f"resource node {node_id!r} has duplicate classifications"
                )
            assignments[node_id] = str(resource_class)
    if tuple(entry_ids) != tuple(sorted(set(entry_ids))):
        raise ResourceManifestError("resource entries must be sorted and unique")
    return assignments


def load_resource_manifest(
    path: Path,
    *,
    repo_root: Path,
    collection_records: Sequence[Mapping[str, Any]],
    config: TestGateConfig,
    allow_stale_as_serial: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Load canonical resource evidence and return exact promoted assignments."""

    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ResourceManifestError(
            f"cannot load resource manifest {path}: {exc}"
        ) from exc
    assignments = verify_resource_manifest(
        document,
        repo_root=repo_root,
        collection_records=collection_records,
        config=config,
        allow_stale_as_serial=allow_stale_as_serial,
    )
    return document, assignments


def _distribution_implementation_digest(distribution_name: str) -> str:
    distribution = importlib.metadata.distribution(distribution_name)
    records: list[dict[str, str]] = []
    for relative in sorted(
        str(item)
        for item in (distribution.files or ())
        if str(item).endswith(".py")
    ):
        path = Path(distribution.locate_file(relative))
        if not path.is_file():
            raise ResourceManifestError(
                f"{distribution_name} implementation file is missing: {relative}"
            )
        records.append({"path": relative, "digest": _file_digest(path)})
    if not records:
        raise ResourceManifestError(
            f"{distribution_name} implementation contains no Python files"
        )
    return _records_digest(records)


def probe_xdist_identity() -> dict[str, str]:
    """Fail closed unless the root lock's exact xdist implementation is present."""

    try:
        xdist_version = importlib.metadata.version("pytest-xdist")
        execnet_version = importlib.metadata.version("execnet")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ResourceManifestError(
            "optimized parallel mode requires locked pytest-xdist"
        ) from exc
    if xdist_version != PINNED_PYTEST_XDIST_VERSION:
        raise ResourceManifestError(
            "pytest-xdist version drifted from the root dependency lock"
        )
    if execnet_version != PINNED_EXECNET_VERSION:
        raise ResourceManifestError(
            "execnet version drifted from the root dependency lock"
        )
    return {
        "distribution": "pytest-xdist",
        "version": xdist_version,
        "implementation_digest": _distribution_implementation_digest(
            "pytest-xdist"
        ),
        "execnet_version": execnet_version,
        "execnet_implementation_digest": _distribution_implementation_digest(
            "execnet"
        ),
    }


def validate_worker_count(workers: int, *, hard_max: int) -> int:
    """Accept only explicit fixed workers; CPU-derived or bool values are invalid."""

    if type(workers) is not int or not 1 <= workers <= hard_max:
        raise ResourceManifestError(
            f"worker count must be an explicit integer in 1..{hard_max}"
        )
    return workers


def resource_partition(
    *,
    residual_nodes: Sequence[str],
    assignments: Mapping[str, str],
    config: TestGateConfig,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return exact serial/parallel nodes with unknown nodes kept serial."""

    residual = tuple(residual_nodes)
    if residual != tuple(sorted(set(residual))):
        raise ResourceManifestError("residual nodes must be sorted and unique")
    parallel = tuple(
        node_id
        for node_id in residual
        if assignments.get(node_id, config.resource_policy.default_class)
        in config.resource_policy.parallel_eligible_classes
    )
    serial = tuple(node_id for node_id in residual if node_id not in set(parallel))
    if set(serial) & set(parallel) or set(serial) | set(parallel) != set(residual):
        raise ResourceManifestError("resource partition does not close residual nodes")
    return serial, parallel
