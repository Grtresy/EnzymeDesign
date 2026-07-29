"""Phase-0 collection and exact legacy coverage shadow closure."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import TestGateConfig
from .model import (
    PYTEST_OBSERVATION_SCHEMA_ID,
    SHADOW_COVERAGE_SCHEMA_ID,
    STAGE_RESULT_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
)
from .runner import (
    ProcessResult,
    create_new_output_root,
    publish_no_replace,
    run_command,
)
from .source import SourceIdentity, collect_source_identity

ARCHITECTURE_TEST_ROOT = "apps/openzyme-host-api/tests/architecture_qualification"
ARCHITECTURE_SCENARIO_ROOT = f"{ARCHITECTURE_TEST_ROOT}/scenarios"
ARCHITECTURE_COLLECTION_SCHEMA_ID = (
    "openzyme_v3_architecture_pytest_collection@1"
)
ARCHITECTURE_REGISTRY_SCHEMA_ID = (
    "openzyme_v3_architecture_invariant_registry@1"
)
ARCHITECTURE_REGISTRY_PATH = (
    "docs/v3/architecture-qualification/invariant-registry.json"
)
ARCHITECTURE_SCENARIO_MARKER = "architecture_qualification_scenario"
ARCHITECTURE_COLLECTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_COLLECTION_OUTPUT"
FORBIDDEN_NON_LIVE_MARKERS = frozenset(
    {
        "integration",
        "live_llm",
        "live_tavily",
        "live_hpc",
        "live_e2e",
        "seeded_live_smoke",
        "quality_eval",
    }
)
_SENSITIVE_ENV_PARTS = (
    "API_KEY",
    "AUTH_TOKEN",
    "CREDENTIAL",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
)
_LIVE_ENV_PARTS = (
    "LIVE_E2E",
    "LIVE_HPC",
    "LIVE_LLM",
    "LIVE_TAVILY",
    "RUN_AOX",
    "RUN_LIVE",
)
_EXTERNAL_ENV_PARTS = (
    "ANTHROPIC",
    "CDP",
    "CHROME",
    "GEMINI",
    "HPC",
    "MICU",
    "OPENAI",
    "SLURM",
    "SSH",
    "TAVILY",
)
_PROXY_ENV_KEYS = frozenset(
    {
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    }
)


class ShadowCollectionError(RuntimeError):
    """Raised when shadow collection cannot produce closed evidence."""


class ShadowCoverageError(RuntimeError):
    """Raised when shadow collection does not close exact legacy coverage."""

    def __init__(self, reasons: Sequence[str], document: Mapping[str, Any]) -> None:
        self.reasons = tuple(reasons)
        self.document = dict(document)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class CollectionSnapshot:
    invocation_id: str
    role: str
    nodes: tuple[str, ...]
    markers: tuple[tuple[str, tuple[str, ...]], ...]
    digest: str
    deselected_markers: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def markers_by_node(self) -> dict[str, tuple[str, ...]]:
        return dict(self.markers)

    def deselected_markers_by_node(self) -> dict[str, tuple[str, ...]]:
        return dict(self.deselected_markers)


@dataclass(frozen=True)
class ShadowCollectionResult:
    output_root: Path
    source_identity: SourceIdentity
    general: CollectionSnapshot
    qualification_harness: CollectionSnapshot
    qualification_scenarios: CollectionSnapshot
    coverage_document: Mapping[str, Any]


def _closed_record(
    value: Any,
    *,
    fields: set[str],
    context: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ShadowCollectionError(
            f"{context} must contain exactly {sorted(fields)!r}"
        )
    return value


def _sorted_unique_strings(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ShadowCollectionError(f"{context} must be an array of strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise ShadowCollectionError(f"{context} must be sorted and unique")
    return result


def load_pytest_observation(
    path: Path,
    *,
    expected_invocation_id: str | None = None,
    expected_role: str | None = None,
    expected_mode: str | None = None,
) -> CollectionSnapshot:
    """Load and close one canonical pytest observation."""

    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ShadowCollectionError(f"invalid pytest observation {path}: {exc}") from exc
    if document["schema_id"] != PYTEST_OBSERVATION_SCHEMA_ID:
        raise ShadowCollectionError(
            f"unexpected pytest observation schema: {document['schema_id']!r}"
        )
    invocation_id = document["invocation_id"]
    role = document["role"]
    mode = document["mode"]
    if not all(isinstance(value, str) and value for value in (invocation_id, role, mode)):
        raise ShadowCollectionError("pytest observation identities must be strings")
    if expected_invocation_id is not None and invocation_id != expected_invocation_id:
        raise ShadowCollectionError(
            "pytest observation belongs to a prior or different invocation"
        )
    if expected_role is not None and role != expected_role:
        raise ShadowCollectionError(
            f"pytest observation role drifted: expected {expected_role!r}, got {role!r}"
        )
    if expected_mode is not None and mode != expected_mode:
        raise ShadowCollectionError(
            f"pytest observation mode drifted: expected {expected_mode!r}, got {mode!r}"
        )

    raw_collection = document["collection"]
    if not isinstance(raw_collection, list):
        raise ShadowCollectionError("pytest observation collection must be an array")
    nodes: list[str] = []
    markers: list[tuple[str, tuple[str, ...]]] = []
    canonical_collection: list[dict[str, object]] = []
    for index, item in enumerate(raw_collection):
        record = _closed_record(
            item,
            fields={"node_id", "markers"},
            context=f"collection[{index}]",
        )
        node_id = record["node_id"]
        if not isinstance(node_id, str) or not node_id:
            raise ShadowCollectionError(
                f"collection[{index}].node_id must be a nonempty string"
            )
        marker_names = _sorted_unique_strings(
            record["markers"],
            context=f"collection[{index}].markers",
        )
        nodes.append(node_id)
        markers.append((node_id, marker_names))
        canonical_collection.append(
            {"node_id": node_id, "markers": list(marker_names)}
        )
    if tuple(nodes) != tuple(sorted(set(nodes))):
        raise ShadowCollectionError("pytest collection node ids must be sorted and unique")
    deselected = _sorted_unique_strings(
        document["deselected"],
        context="deselected",
    )
    if set(nodes) & set(deselected):
        raise ShadowCollectionError(
            "pytest observation selected and deselected sets overlap"
        )
    deselected_markers: list[tuple[str, tuple[str, ...]]] = []
    raw_deselected_markers = document.get("deselected_markers")
    if raw_deselected_markers is not None:
        if not isinstance(raw_deselected_markers, list):
            raise ShadowCollectionError(
                "deselected_markers must be an array"
            )
        for index, item in enumerate(raw_deselected_markers):
            record = _closed_record(
                item,
                fields={"node_id", "markers"},
                context=f"deselected_markers[{index}]",
            )
            node_id = record["node_id"]
            if not isinstance(node_id, str) or not node_id:
                raise ShadowCollectionError(
                    f"deselected_markers[{index}].node_id must be nonempty"
                )
            marker_names = _sorted_unique_strings(
                record["markers"],
                context=f"deselected_markers[{index}].markers",
            )
            deselected_markers.append((node_id, marker_names))
        deselected_marker_ids = tuple(
            node_id for node_id, _ in deselected_markers
        )
        if deselected_marker_ids != tuple(sorted(set(deselected_marker_ids))):
            raise ShadowCollectionError(
                "deselected marker node ids must be sorted and unique"
            )
        if deselected_marker_ids != deselected:
            raise ShadowCollectionError(
                "deselected marker records do not close deselected node ids"
            )
    raw_results = document["node_results"]
    if not isinstance(raw_results, list):
        raise ShadowCollectionError("pytest observation node_results must be an array")
    result_node_ids: list[str] = []
    for index, item in enumerate(raw_results):
        record = _closed_record(
            item,
            fields={"node_id", "outcome", "duration_ns", "phases"},
            context=f"node_results[{index}]",
        )
        node_id = record["node_id"]
        if not isinstance(node_id, str) or not node_id:
            raise ShadowCollectionError(
                f"node_results[{index}].node_id must be a nonempty string"
            )
        if record["outcome"] not in {
            "pass",
            "fail",
            "skip",
            "xfail",
            "xpass",
            "timeout",
            "error",
        }:
            raise ShadowCollectionError(
                f"node_results[{index}].outcome is invalid"
            )
        if type(record["duration_ns"]) is not int or record["duration_ns"] < 0:
            raise ShadowCollectionError(
                f"node_results[{index}].duration_ns is invalid"
            )
        phases = record["phases"]
        if not isinstance(phases, list) or not phases:
            raise ShadowCollectionError(
                f"node_results[{index}].phases must be a nonempty array"
            )
        for phase_index, phase in enumerate(phases):
            phase_record = _closed_record(
                phase,
                fields={
                    "phase",
                    "outcome",
                    "duration_ns",
                    "was_xfail",
                    "failure_digest",
                },
                context=f"node_results[{index}].phases[{phase_index}]",
            )
            if phase_record["phase"] not in {"setup", "call", "teardown"}:
                raise ShadowCollectionError(
                    f"node_results[{index}].phases[{phase_index}].phase is invalid"
                )
            if phase_record["outcome"] not in {"passed", "failed", "skipped"}:
                raise ShadowCollectionError(
                    f"node_results[{index}].phases[{phase_index}].outcome is invalid"
                )
            if (
                type(phase_record["duration_ns"]) is not int
                or phase_record["duration_ns"] < 0
            ):
                raise ShadowCollectionError(
                    f"node_results[{index}].phases[{phase_index}].duration_ns "
                    "is invalid"
                )
            if type(phase_record["was_xfail"]) is not bool:
                raise ShadowCollectionError(
                    f"node_results[{index}].phases[{phase_index}].was_xfail "
                    "is invalid"
                )
            failure_digest = phase_record["failure_digest"]
            if failure_digest is not None and (
                not isinstance(failure_digest, str)
                or not failure_digest.startswith("sha256:")
            ):
                raise ShadowCollectionError(
                    f"node_results[{index}].phases[{phase_index}].failure_digest "
                    "is invalid"
                )
        result_node_ids.append(node_id)
    if tuple(result_node_ids) != tuple(sorted(set(result_node_ids))):
        raise ShadowCollectionError("node result ids must be sorted and unique")
    if not set(result_node_ids) <= set(nodes):
        raise ShadowCollectionError("node results contain ids outside collection")
    if mode == "collect" and raw_results:
        raise ShadowCollectionError("collection-only observation contains node results")
    if type(document["session_exit_code"]) is not int:
        raise ShadowCollectionError("session_exit_code must be an integer")
    if (
        type(document["started_monotonic_ns"]) is not int
        or document["started_monotonic_ns"] < 0
        or type(document["duration_ns"]) is not int
        or document["duration_ns"] < 0
    ):
        raise ShadowCollectionError("pytest observation timing fields are invalid")
    if not isinstance(document["pytest_argv"], list) or any(
        not isinstance(item, str) for item in document["pytest_argv"]
    ):
        raise ShadowCollectionError("pytest_argv must be an array of strings")
    if not isinstance(document["cwd"], str) or not document["cwd"]:
        raise ShadowCollectionError("pytest observation cwd must be a string")

    return CollectionSnapshot(
        invocation_id=invocation_id,
        role=role,
        nodes=tuple(nodes),
        markers=tuple(markers),
        digest=sha256_digest(canonical_json_bytes(canonical_collection)),
        deselected_markers=tuple(deselected_markers),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ShadowCollectionError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ShadowCollectionError(f"non-finite JSON constant: {value}")


def _load_existing_canonical_json(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
        parsed = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowCollectionError(f"invalid canonical JSON {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ShadowCollectionError(f"canonical JSON must be an object: {path}")
    if content != canonical_json_bytes(parsed) + b"\n":
        raise ShadowCollectionError(f"JSON is not canonical: {path}")
    return parsed


def load_qualification_scenario_collection(
    collection_path: Path,
    *,
    registry_path: Path,
    invocation_id: str,
    selection_id: str = "premerge_subset",
) -> CollectionSnapshot:
    """Close qualification scenario collection against the canonical registry."""

    collection = _load_existing_canonical_json(collection_path)
    if set(collection) != {"schema_id", "scenarios"}:
        raise ShadowCollectionError("qualification collection is not closed")
    if collection["schema_id"] != ARCHITECTURE_COLLECTION_SCHEMA_ID:
        raise ShadowCollectionError("qualification collection schema drifted")
    raw_scenarios = collection["scenarios"]
    if not isinstance(raw_scenarios, list):
        raise ShadowCollectionError("qualification scenarios must be an array")

    registry = _load_existing_canonical_json(registry_path)
    if registry.get("schema_id") != ARCHITECTURE_REGISTRY_SCHEMA_ID:
        raise ShadowCollectionError("qualification registry schema drifted")
    registry_scenarios = registry.get("scenarios")
    required_scenario_ids = registry.get("required_scenario_ids")
    if not isinstance(registry_scenarios, list) or not isinstance(
        required_scenario_ids,
        list,
    ):
        raise ShadowCollectionError("qualification registry scenario closure is invalid")
    registered: dict[str, Mapping[str, Any]] = {}
    for raw in registry_scenarios:
        if not isinstance(raw, dict) or not isinstance(raw.get("scenario_id"), str):
            raise ShadowCollectionError("qualification registry contains invalid scenario")
        scenario_id = raw["scenario_id"]
        if scenario_id in registered:
            raise ShadowCollectionError(
                f"qualification registry duplicates scenario {scenario_id!r}"
            )
        registered[scenario_id] = raw
    if required_scenario_ids != sorted(registered):
        raise ShadowCollectionError(
            "qualification required_scenario_ids do not close the registry"
        )

    collected: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_scenarios):
        record = _closed_record(
            raw,
            fields={
                "family",
                "node_id",
                "scenario_id",
                "selections",
                "source_file",
            },
            context=f"qualification scenarios[{index}]",
        )
        scenario_id = record["scenario_id"]
        if not isinstance(scenario_id, str) or scenario_id in collected:
            raise ShadowCollectionError("qualification scenario ids must be unique strings")
        collected[scenario_id] = record
    if set(collected) != set(registered):
        raise ShadowCollectionError(
            "qualification collection and registry scenario sets drifted"
        )

    selected_nodes: list[str] = []
    for scenario_id in sorted(registered):
        expected = registered[scenario_id]
        actual = collected[scenario_id]
        expected_sources = expected.get("source_files")
        if (
            actual["family"] != expected.get("family")
            or actual["node_id"] != expected.get("test_selector")
            or actual["selections"] != expected.get("selections")
            or not isinstance(expected_sources, list)
            or actual["source_file"] not in expected_sources
        ):
            raise ShadowCollectionError(
                f"qualification scenario {scenario_id!r} drifted from registry"
            )
        selections = actual["selections"]
        if not isinstance(selections, list) or any(
            not isinstance(item, str) for item in selections
        ):
            raise ShadowCollectionError(
                f"qualification scenario {scenario_id!r} selections are invalid"
            )
        if selection_id in selections:
            node_id = actual["node_id"]
            if not isinstance(node_id, str):
                raise ShadowCollectionError(
                    f"qualification scenario {scenario_id!r} node id is invalid"
                )
            selected_nodes.append(node_id)
    nodes = tuple(sorted(selected_nodes))
    if len(nodes) != len(set(nodes)):
        raise ShadowCollectionError("qualification selected node ids are duplicated")
    canonical_collection = [
        {"node_id": node_id, "markers": [ARCHITECTURE_SCENARIO_MARKER]}
        for node_id in nodes
    ]
    return CollectionSnapshot(
        invocation_id=invocation_id,
        role="qualification_scenario",
        nodes=nodes,
        markers=tuple(
            (node_id, (ARCHITECTURE_SCENARIO_MARKER,)) for node_id in nodes
        ),
        digest=sha256_digest(canonical_json_bytes(canonical_collection)),
    )


def assert_source_stable(before: SourceIdentity, after: SourceIdentity) -> None:
    if before.digest != after.digest:
        raise ShadowCollectionError(
            f"source identity drifted during shadow collection: "
            f"{before.digest} != {after.digest}"
        )


def close_shadow_coverage(
    *,
    invocation_id: str,
    source_identity_digest: str,
    general: CollectionSnapshot,
    qualification_harness: CollectionSnapshot,
    qualification_scenarios: CollectionSnapshot,
    frontend_commands: Sequence[Mapping[str, object]] = (),
    expected_collection_digests: Mapping[str, str] | None = None,
    expected_required_nodes: Sequence[str] = (),
) -> dict[str, Any]:
    """Close the legacy multiset and one-owner distinct shadow plan."""

    reasons: list[str] = []
    snapshots = (general, qualification_harness, qualification_scenarios)
    expected_roles = (
        "legacy_general",
        "qualification_harness",
        "qualification_scenario",
    )
    for snapshot, expected_role in zip(snapshots, expected_roles, strict=True):
        if snapshot.invocation_id != invocation_id:
            reasons.append(
                f"{snapshot.role} belongs to prior invocation "
                f"{snapshot.invocation_id!r}"
            )
        if snapshot.role != expected_role:
            reasons.append(
                f"shadow role drifted: expected {expected_role!r}, "
                f"got {snapshot.role!r}"
            )
        if snapshot.nodes != tuple(sorted(set(snapshot.nodes))):
            reasons.append(f"{snapshot.role} contains duplicate or unsorted node ids")
        marker_nodes = tuple(node_id for node_id, _ in snapshot.markers)
        if marker_nodes != snapshot.nodes:
            reasons.append(
                f"{snapshot.role} marker inventory does not close its node set"
            )
    if len({snapshot.role for snapshot in snapshots}) != len(snapshots):
        reasons.append("shadow collection roles must be unique")

    expected_collection_digests = expected_collection_digests or {}
    for snapshot in snapshots:
        expected = expected_collection_digests.get(snapshot.role)
        if expected is not None and snapshot.digest != expected:
            reasons.append(
                f"{snapshot.role} collection drifted: "
                f"expected {expected}, got {snapshot.digest}"
            )

    forbidden_nodes: list[dict[str, object]] = []
    for snapshot in snapshots:
        for node_id, markers in snapshot.markers:
            forbidden = sorted(set(markers) & FORBIDDEN_NON_LIVE_MARKERS)
            if forbidden:
                forbidden_nodes.append(
                    {
                        "node_id": node_id,
                        "role": snapshot.role,
                        "markers": forbidden,
                    }
                )
    if forbidden_nodes:
        reasons.append("forbidden live/integration markers entered shadow collection")

    general_nodes = set(general.nodes)
    harness_nodes = set(qualification_harness.nodes)
    scenario_nodes = set(qualification_scenarios.nodes)
    qualification_overlap = sorted(harness_nodes & scenario_nodes)
    if qualification_overlap:
        reasons.append(
            "qualification harness and scenario owners overlap: "
            + ", ".join(qualification_overlap)
        )
    qualification_nodes = harness_nodes | scenario_nodes
    qualification_missing_from_general = sorted(
        qualification_nodes - general_nodes
    )
    if qualification_missing_from_general:
        reasons.append(
            "qualification-owned nodes are not present in the general "
            "non-live collection: "
            + ", ".join(qualification_missing_from_general)
        )
    distinct_nodes = tuple(sorted(general_nodes | qualification_nodes))
    expected_nodes = set(expected_required_nodes)
    missing_expected = sorted(expected_nodes - set(distinct_nodes))
    if missing_expected:
        reasons.append("required nodes have no owner: " + ", ".join(missing_expected))

    shadow_owners: list[dict[str, str]] = []
    for node_id in sorted(qualification_nodes):
        shadow_owners.append(
            {
                "node_id": node_id,
                "owner": "architecture_qualification_premerge",
            }
        )
    for node_id in sorted(general_nodes - qualification_nodes):
        shadow_owners.append(
            {"node_id": node_id, "owner": "general_non_live_pytest"}
        )
    owner_counts: dict[str, int] = {}
    for owner in shadow_owners:
        node_id = owner["node_id"]
        owner_counts[node_id] = owner_counts.get(node_id, 0) + 1
    invalid_owner_counts = sorted(
        node_id for node_id, count in owner_counts.items() if count != 1
    )
    if invalid_owner_counts:
        reasons.append(
            "nodes have invalid shadow owner counts: "
            + ", ".join(invalid_owner_counts)
        )

    legacy_multiset = [
        {"node_id": node_id, "stage_id": "general_non_live_pytest"}
        for node_id in general.nodes
    ]
    legacy_multiset.extend(
        {
            "node_id": node_id,
            "stage_id": "architecture_qualification_harness",
        }
        for node_id in qualification_harness.nodes
    )
    legacy_multiset.extend(
        {
            "node_id": node_id,
            "stage_id": "architecture_qualification_scenario",
        }
        for node_id in qualification_scenarios.nodes
    )
    legacy_multiset.sort(key=lambda item: (item["node_id"], item["stage_id"]))
    structural_duplicates = [
        {
            "node_id": node_id,
            "legacy_stage_ids": [
                item["stage_id"]
                for item in legacy_multiset
                if item["node_id"] == node_id
            ],
        }
        for node_id in sorted(general_nodes & qualification_nodes)
    ]
    document = seal_document(
        SHADOW_COVERAGE_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "source_identity_digest": source_identity_digest,
            "general_collection_digest": general.digest,
            "qualification_harness_collection_digest": qualification_harness.digest,
            "qualification_scenario_collection_digest": qualification_scenarios.digest,
            "legacy_execution_multiset": legacy_multiset,
            "legacy_execution_multiset_digest": sha256_digest(
                canonical_json_bytes(legacy_multiset)
            ),
            "distinct_required_nodes": list(distinct_nodes),
            "distinct_coverage_digest": sha256_digest(
                canonical_json_bytes(list(distinct_nodes))
            ),
            "structural_duplicates": structural_duplicates,
            "shadow_owners": sorted(
                shadow_owners,
                key=lambda item: (item["node_id"], item["owner"]),
            ),
            "forbidden_nodes": forbidden_nodes,
            "terminal_status": "fail" if reasons else "pass",
            "failure_reasons": reasons,
            "frontend_commands": [dict(item) for item in frontend_commands],
        },
    )
    if reasons:
        raise ShadowCoverageError(reasons, document)
    return document


def closed_non_live_environment(
    source: Mapping[str, str] | None = None,
    *,
    qualification: bool,
) -> dict[str, str]:
    """Mirror the qualification sanitizer without importing product packages."""

    environment = dict(os.environ if source is None else source)
    for key in tuple(environment):
        upper = key.upper()
        if (
            key in {
                ARCHITECTURE_COLLECTION_OUTPUT_ENV,
                "OPENZYME_ARCHITECTURE_EXECUTION_OUTPUT",
                "PYTEST_ADDOPTS",
            }
            or any(part in upper for part in _SENSITIVE_ENV_PARTS)
            or any(part in upper for part in _LIVE_ENV_PARTS)
            or any(part in upper for part in _EXTERNAL_ENV_PARTS)
            or upper in {"SSH_AUTH_SOCK", "SSH_AGENT_PID"}
            or upper in _PROXY_ENV_KEYS
        ):
            environment.pop(key, None)
    environment.update(
        {
            "OPENZYME_LOAD_ENV_FILES": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if qualification:
        environment["OPENZYME_ARCHITECTURE_QUALIFICATION"] = "1"
    else:
        environment.pop("OPENZYME_ARCHITECTURE_QUALIFICATION", None)
    return environment


def _observation_arguments(
    *,
    output_path: Path,
    invocation_id: str,
    role: str,
) -> tuple[str, ...]:
    return (
        "-p",
        "test_gate.pytest_plugin",
        "--test-gate-observation",
        str(output_path),
        "--test-gate-invocation-id",
        invocation_id,
        "--test-gate-role",
        role,
        "--test-gate-observation-mode",
        "collect",
    )


def _publish_collection_stage(
    *,
    output_path: Path,
    invocation_id: str,
    plan_digest: str,
    stage_id: str,
    environment_digest: str,
    result: ProcessResult,
) -> None:
    document = seal_document(
        STAGE_RESULT_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "plan_digest": plan_digest,
            "stage_id": stage_id,
            "argv": list(result.argv),
            "cwd": result.cwd,
            "environment_digest": environment_digest,
            "outcome": result.outcome,
            "started_monotonic_ns": result.started_monotonic_ns,
            "duration_ns": result.duration_ns,
            "exit_code": result.exit_code,
            "stdout_digest": result.stdout.digest,
            "stdout_tail": result.stdout.tail,
            "stderr_digest": result.stderr.digest,
            "stderr_tail": result.stderr.tail,
            "timed_out": result.timed_out,
            "retirement": {
                "term_sent": result.term_sent,
                "kill_sent": result.kill_sent,
                "error": result.error,
            },
        },
    )
    publish_no_replace(output_path, canonical_document_bytes(document))


def _run_collection_process(
    *,
    stage_id: str,
    argv: Sequence[str],
    repo_root: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_root: Path,
    invocation_id: str,
    plan_digest: str,
) -> ProcessResult:
    result = run_command(
        argv,
        cwd=repo_root,
        environment=environment,
        timeout_seconds=timeout_seconds,
    )
    environment_digest = sha256_digest(canonical_json_bytes(dict(environment)))
    _publish_collection_stage(
        output_path=output_root / f"{stage_id}-stage.json",
        invocation_id=invocation_id,
        plan_digest=plan_digest,
        stage_id=stage_id,
        environment_digest=environment_digest,
        result=result,
    )
    if result.outcome != "pass":
        raise ShadowCollectionError(
            f"{stage_id} collection failed with {result.outcome}: "
            f"{result.stderr.tail}"
        )
    return result


def run_shadow_collection(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
) -> ShadowCollectionResult:
    """Collect G/Qh/Qs and publish a source-bound shadow closure."""

    root = repo_root.resolve(strict=True)
    evidence_root = create_new_output_root(root, output_root)
    source_before = collect_source_identity(root)
    plan_digest = sha256_digest(
        canonical_json_bytes(
            {
                "invocation_id": invocation_id,
                "config_digest": config.digest,
                "source_identity_digest": source_before.digest,
                "operation": "shadow_collection",
            }
        )
    )

    general_observation = evidence_root / "general-collection.json"
    general_environment = closed_non_live_environment(qualification=False)
    general_environment["PYTHONPATH"] = str(root / "scripts")
    general_command = (
        "uv",
        "run",
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        config.stage("general_non_live_pytest").argv[-1],
        *_observation_arguments(
            output_path=general_observation,
            invocation_id=invocation_id,
            role="legacy_general",
        ),
    )
    _run_collection_process(
        stage_id="general_collection",
        argv=general_command,
        repo_root=root,
        environment=general_environment,
        timeout_seconds=180.0,
        output_root=evidence_root,
        invocation_id=invocation_id,
        plan_digest=plan_digest,
    )
    general = load_pytest_observation(
        general_observation,
        expected_invocation_id=invocation_id,
        expected_role="legacy_general",
        expected_mode="collect",
    )

    qualification_environment = closed_non_live_environment(qualification=True)
    qualification_environment["PYTHONPATH"] = str(root / "scripts")
    harness_observation = evidence_root / "qualification-harness-collection.json"
    harness_command = (
        sys.executable,
        "-m",
        "pytest",
        ARCHITECTURE_TEST_ROOT,
        f"--ignore={ARCHITECTURE_SCENARIO_ROOT}",
        "--rootdir=.",
        "-q",
        "-p",
        "no:cacheprovider",
        "--collect-only",
        *_observation_arguments(
            output_path=harness_observation,
            invocation_id=invocation_id,
            role="qualification_harness",
        ),
    )
    _run_collection_process(
        stage_id="qualification_harness_collection",
        argv=harness_command,
        repo_root=root,
        environment=qualification_environment,
        timeout_seconds=120.0,
        output_root=evidence_root,
        invocation_id=invocation_id,
        plan_digest=plan_digest,
    )
    harness = load_pytest_observation(
        harness_observation,
        expected_invocation_id=invocation_id,
        expected_role="qualification_harness",
        expected_mode="collect",
    )

    scenario_observation = evidence_root / "qualification-scenario-observation.json"
    architecture_collection = evidence_root / "qualification-scenario-collection.json"
    scenario_environment = dict(qualification_environment)
    scenario_environment[ARCHITECTURE_COLLECTION_OUTPUT_ENV] = str(
        architecture_collection
    )
    scenario_command = (
        sys.executable,
        "-m",
        "pytest",
        ARCHITECTURE_SCENARIO_ROOT,
        "--collect-only",
        "--rootdir=.",
        "-q",
        "-p",
        "no:cacheprovider",
        *_observation_arguments(
            output_path=scenario_observation,
            invocation_id=invocation_id,
            role="qualification_scenario",
        ),
    )
    _run_collection_process(
        stage_id="qualification_scenario_collection",
        argv=scenario_command,
        repo_root=root,
        environment=scenario_environment,
        timeout_seconds=120.0,
        output_root=evidence_root,
        invocation_id=invocation_id,
        plan_digest=plan_digest,
    )
    all_scenarios = load_pytest_observation(
        scenario_observation,
        expected_invocation_id=invocation_id,
        expected_role="qualification_scenario",
        expected_mode="collect",
    )
    selected_scenarios = load_qualification_scenario_collection(
        architecture_collection,
        registry_path=root / ARCHITECTURE_REGISTRY_PATH,
        invocation_id=invocation_id,
    )
    registry_collection = _load_existing_canonical_json(architecture_collection)
    registry_node_ids = sorted(
        str(item["node_id"]) for item in registry_collection["scenarios"]
    )
    if tuple(registry_node_ids) != all_scenarios.nodes:
        raise ShadowCollectionError(
            "test-gate plugin and canonical qualification collector disagree"
        )

    source_after = collect_source_identity(root)
    assert_source_stable(source_before, source_after)
    frontend_commands = [
        {
            "stage_id": stage_id,
            "cwd": config.stage(stage_id).cwd,
            "argv": list(config.stage(stage_id).argv),
        }
        for stage_id in ("web_ui_test", "web_ui_build")
    ]
    coverage_document = close_shadow_coverage(
        invocation_id=invocation_id,
        source_identity_digest=source_before.digest,
        general=general,
        qualification_harness=harness,
        qualification_scenarios=selected_scenarios,
        frontend_commands=frontend_commands,
    )
    publish_no_replace(
        evidence_root / "shadow-coverage.json",
        canonical_document_bytes(coverage_document),
    )
    return ShadowCollectionResult(
        output_root=evidence_root,
        source_identity=source_before,
        general=general,
        qualification_harness=harness,
        qualification_scenarios=selected_scenarios,
        coverage_document=coverage_document,
    )
