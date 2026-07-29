"""Closed authoritative-mainline planning and exact node-manifest contracts."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import (
    LEGACY_MAINLINE_STAGE_ORDER,
    RESOURCE_CLASSES,
    StageDefinition,
    TestGateConfig,
)
from .model import (
    EXECUTION_PLAN_SCHEMA_ID,
    NODE_MANIFEST_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
    verify_sealed_document,
)
from .runner import publish_no_replace
from .resource import (
    DEFAULT_RESOURCE_MANIFEST_PATH,
    PARALLEL_DISTRIBUTION,
    RESOURCE_MANIFEST_SCHEMA_ID,
    ResourceManifestError,
    load_resource_manifest,
    probe_xdist_identity,
    resource_partition,
    validate_worker_count,
)
from .shadow import (
    CollectionSnapshot,
    ShadowCollectionResult,
    run_shadow_collection,
)
from .source import SourceIdentity, collect_source_identity

PLAN_FILENAME = "mainline-shadow-plan.json"
MAINLINE_AUTHORITATIVE_PLAN_FILENAME = "mainline-authoritative-plan.json"
NODE_MANIFEST_FILENAME = "general-residual-manifest.json"
GENERAL_RECHECK_OBSERVATION_FILENAME = "general-recheck-observation.json"
GENERAL_RECHECK_STAGE_FILENAME = "general-recheck-stage.json"
GENERAL_EXECUTION_OBSERVATION_FILENAME = "general-residual-observation.json"
QUALIFICATION_OUTPUT_DIRECTORY = "qualification-report"
QUALIFICATION_REPORT_FILENAME = "architecture-qualification-report.json"
QUALIFICATION_SIDECAR_FILENAME = "qualification-execution.json"
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_AUTHORITY_FIELDS = {
    "authoritative",
    "profile_contract_authoritative",
    "admission_eligible",
    "live_eligible",
    "authority_domain",
    "current_authoritative_entry",
}
_STAGE_FIELDS = {
    "stage_id",
    "configured_argv",
    "argv",
    "cwd",
    "environment_policy",
    "environment_digest",
    "deadline_seconds",
    "resource_class",
    "depends_on",
    "execution_kind",
    "expected_nodes_digest",
}
_SNAPSHOT_FIELDS = {
    "role",
    "nodes",
    "markers",
    "collection_digest",
    "policy_deselected_nodes",
}
_MANIFEST_DESCRIPTOR_FIELDS = {
    "schema_id",
    "path",
    "selected_nodes_digest",
    "planned_deselected_digest",
    "expected_policy_deselected_digest",
}
_GENERAL_RECHECK_FIELDS = {
    "argv",
    "cwd",
    "environment_policy",
    "environment_digest",
    "deadline_seconds",
    "observation_path",
    "stage_result_path",
    "expected_collection_digest",
    "expected_policy_deselected_digest",
}
_QUALIFICATION_SIDECAR_DESCRIPTOR_FIELDS = {
    "schema_id",
    "path",
    "qualification_mode",
    "report_path",
}
_RESOURCE_MANIFEST_DESCRIPTOR_FIELDS = {
    "schema_id",
    "path",
    "digest",
    "parallel_nodes_digest",
    "serial_nodes_digest",
}
_WORKER_POLICY_FIELDS = {
    "mode",
    "workers",
    "hard_max",
    "parallel_eligible_classes",
    "unclassified_default",
    "distribution",
    "resource_manifest_digest",
    "xdist_identity",
}


class AuthoritativePlanError(RuntimeError):
    """Raised when a mainline candidate plan or manifest is not closed."""


@dataclass(frozen=True)
class AuthoritativePlanResult:
    """Published shadow plan plus its plan-bound exact residual manifest."""

    output_root: Path
    source_identity: SourceIdentity
    plan: Mapping[str, Any]
    manifest: Mapping[str, Any]


def _strict_mapping(
    value: Any,
    *,
    fields: set[str],
    context: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AuthoritativePlanError(
            f"{context} must contain exactly {sorted(fields)!r}"
        )
    return value


def _sorted_unique_strings(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AuthoritativePlanError(f"{context} must be an array of strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise AuthoritativePlanError(f"{context} must be sorted and unique")
    return result


def _assert_digest(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise AuthoritativePlanError(f"{context} must be a canonical SHA-256 digest")
    return value


def _planner_digest() -> str:
    return sha256_digest(Path(__file__).read_bytes())


def _environment_for_stage(
    *,
    config: TestGateConfig,
    stage: StageDefinition,
    repo_root: Path,
    source: Mapping[str, str],
) -> dict[str, str]:
    policy = config.environment_policy(stage.environment_policy)
    environment = dict(source)
    for key in policy.unset:
        environment.pop(key, None)
    environment.update(dict(policy.set_values))
    cwd = (repo_root / stage.cwd).resolve(strict=True)
    environment["PWD"] = str(cwd)
    return environment


def stage_environments(
    *,
    config: TestGateConfig,
    repo_root: Path,
    source: Mapping[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Materialize the exact environment each configured stage will receive."""

    ambient = dict(os.environ if source is None else source)
    if ambient.get("PYTEST_ADDOPTS"):
        raise AuthoritativePlanError(
            "authoritative planning rejects ambient PYTEST_ADDOPTS"
        )
    if ambient.get("PYTEST_PLUGINS"):
        raise AuthoritativePlanError(
            "authoritative planning rejects ambient PYTEST_PLUGINS"
        )
    return {
        stage.id: _environment_for_stage(
            config=config,
            stage=stage,
            repo_root=repo_root,
            source=ambient,
        )
        for stage in config.stages
    }


def _environment_digest(environment: Mapping[str, str]) -> str:
    return sha256_digest(canonical_json_bytes(dict(environment)))


def _observation_arguments(
    *,
    output_path: Path,
    invocation_id: str,
    role: str,
    mode: str,
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
        mode,
    )


def _policy_deselected_records(
    snapshot: CollectionSnapshot,
) -> list[dict[str, object]]:
    return [
        {"node_id": node_id, "markers": list(markers)}
        for node_id, markers in snapshot.deselected_markers
    ]


def _snapshot_record(snapshot: CollectionSnapshot) -> dict[str, object]:
    return {
        "role": snapshot.role,
        "nodes": list(snapshot.nodes),
        "markers": [
            {"node_id": node_id, "markers": list(markers)}
            for node_id, markers in snapshot.markers
        ],
        "collection_digest": snapshot.digest,
        "policy_deselected_nodes": _policy_deselected_records(snapshot),
    }


def _nodes_digest(nodes: Sequence[str]) -> str:
    return sha256_digest(canonical_json_bytes(list(nodes)))


def _legacy_multiset_digest(
    *,
    general_nodes: Sequence[str],
    harness_nodes: Sequence[str],
    scenario_nodes: Sequence[str],
) -> str:
    multiset = [
        {"node_id": node_id, "stage_id": "general_non_live_pytest"}
        for node_id in general_nodes
    ]
    multiset.extend(
        {
            "node_id": node_id,
            "stage_id": "architecture_qualification_harness",
        }
        for node_id in harness_nodes
    )
    multiset.extend(
        {
            "node_id": node_id,
            "stage_id": "architecture_qualification_scenario",
        }
        for node_id in scenario_nodes
    )
    multiset.sort(key=lambda item: (item["node_id"], item["stage_id"]))
    return sha256_digest(canonical_json_bytes(multiset))


def _resolved_stage_cwd(repo_root: Path, stage: StageDefinition) -> Path:
    try:
        cwd = (repo_root / stage.cwd).resolve(strict=True)
    except OSError as exc:
        raise AuthoritativePlanError(
            f"configured stage cwd does not exist for {stage.id}: {stage.cwd}"
        ) from exc
    if not cwd.is_dir():
        raise AuthoritativePlanError(
            f"configured stage cwd is not a directory for {stage.id}: {cwd}"
        )
    return cwd


def _candidate_argv(
    *,
    stage: StageDefinition,
    repo_root: Path,
    output_root: Path,
    invocation_id: str,
    resource_manifest_path: Path,
    plan_filename: str,
    expected_authoritative: bool,
) -> tuple[str, ...]:
    if stage.id == "architecture_qualification_premerge":
        return tuple(
            str(output_root / QUALIFICATION_OUTPUT_DIRECTORY)
            if argument == "{qualification_output_root}"
            else argument
            for argument in stage.argv
        )
    if stage.id == "general_non_live_pytest":
        if stage.argv[:3] != ("uv", "run", "pytest"):
            raise AuthoritativePlanError(
                "general pytest configured argv prefix drifted"
            )
        interpreter = Path(sys.executable)
        if not interpreter.is_absolute() or not interpreter.is_file():
            raise AuthoritativePlanError(
                "current Python virtual-environment entry is unavailable"
            )
        argv = (
            str(interpreter),
            "scripts/run-test-gate.py",
            "execute-general-plan",
            str(output_root / plan_filename),
            str(output_root / NODE_MANIFEST_FILENAME),
            "--resource-manifest",
            str(resource_manifest_path),
            "--repo-root",
            str(repo_root),
        )
        if expected_authoritative:
            return (*argv, "--authoritative-mainline")
        return argv
    return stage.argv


def _stage_records(
    *,
    config: TestGateConfig,
    repo_root: Path,
    output_root: Path,
    invocation_id: str,
    environments: Mapping[str, Mapping[str, str]],
    qualification_nodes: Sequence[str],
    residual_nodes: Sequence[str],
    resource_manifest_path: Path,
    plan_filename: str,
    expected_authoritative: bool,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    previous: str | None = None
    empty_digest = _nodes_digest(())
    qualification_digest = _nodes_digest(qualification_nodes)
    residual_digest = _nodes_digest(residual_nodes)
    for stage_id in LEGACY_MAINLINE_STAGE_ORDER:
        stage = config.stage(stage_id)
        if stage_id not in environments:
            raise AuthoritativePlanError(
                f"stage environment is missing for {stage_id}"
            )
        if stage_id == "architecture_qualification_premerge":
            execution_kind = "qualification_premerge"
            expected_nodes_digest = qualification_digest
        elif stage_id == "general_non_live_pytest":
            execution_kind = "pytest_exact_resource_partitions"
            expected_nodes_digest = residual_digest
        else:
            execution_kind = "process"
            expected_nodes_digest = empty_digest
        records.append(
            {
                "stage_id": stage_id,
                "configured_argv": list(stage.argv),
                "argv": list(
                    _candidate_argv(
                        stage=stage,
                        repo_root=repo_root,
                        output_root=output_root,
                        invocation_id=invocation_id,
                        resource_manifest_path=resource_manifest_path,
                        plan_filename=plan_filename,
                        expected_authoritative=expected_authoritative,
                    )
                ),
                "cwd": str(_resolved_stage_cwd(repo_root, stage)),
                "environment_policy": stage.environment_policy,
                "environment_digest": _environment_digest(
                    environments[stage_id]
                ),
                "deadline_seconds": stage.deadline_seconds,
                "resource_class": stage.resource_class,
                "depends_on": [] if previous is None else [previous],
                "execution_kind": execution_kind,
                "expected_nodes_digest": expected_nodes_digest,
            }
        )
        previous = stage_id
    return records


def _general_recheck_record(
    *,
    config: TestGateConfig,
    repo_root: Path,
    output_root: Path,
    invocation_id: str,
    environment: Mapping[str, str],
    general: CollectionSnapshot,
) -> dict[str, object]:
    stage = config.stage("general_non_live_pytest")
    policy_nodes = tuple(
        node_id for node_id, _ in general.deselected_markers
    )
    argv = (
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        "-c",
        "pytest.ini",
        "apps",
        "packages",
        "--collect-only",
        "-q",
        "--rootdir=.",
        "-m",
        config.pytest_contract.marker_expression,
        *_observation_arguments(
            output_path=output_root / GENERAL_RECHECK_OBSERVATION_FILENAME,
            invocation_id=invocation_id,
            role="legacy_general",
            mode="collect",
        ),
    )
    return {
        "argv": list(argv),
        "cwd": str(repo_root),
        "environment_policy": stage.environment_policy,
        "environment_digest": _environment_digest(environment),
        "deadline_seconds": min(stage.deadline_seconds, 300),
        "observation_path": GENERAL_RECHECK_OBSERVATION_FILENAME,
        "stage_result_path": GENERAL_RECHECK_STAGE_FILENAME,
        "expected_collection_digest": general.digest,
        "expected_policy_deselected_digest": _nodes_digest(policy_nodes),
    }


def _manifest_descriptor(
    *,
    residual_nodes: Sequence[str],
    qualification_nodes: Sequence[str],
    policy_deselected_nodes: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_id": NODE_MANIFEST_SCHEMA_ID,
        "path": NODE_MANIFEST_FILENAME,
        "selected_nodes_digest": _nodes_digest(residual_nodes),
        "planned_deselected_digest": _nodes_digest(qualification_nodes),
        "expected_policy_deselected_digest": _nodes_digest(
            policy_deselected_nodes
        ),
    }


def _validate_existing_external_root(repo_root: Path, output_root: Path) -> Path:
    if not output_root.is_absolute():
        raise AuthoritativePlanError("plan output root must be absolute")
    try:
        root = repo_root.resolve(strict=True)
        candidate = output_root.resolve(strict=True)
    except OSError as exc:
        raise AuthoritativePlanError(
            f"plan output root does not exist: {output_root}"
        ) from exc
    if not candidate.is_dir() or output_root.is_symlink():
        raise AuthoritativePlanError(
            "plan output root must be a real existing directory"
        )
    try:
        inside = os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError as exc:
        raise AuthoritativePlanError(
            f"cannot compare repository and output roots: {exc}"
        ) from exc
    if inside:
        raise AuthoritativePlanError("plan output root must be outside the checkout")
    if str(candidate) != str(output_root):
        raise AuthoritativePlanError(
            "plan output root must use its canonical absolute path"
        )
    return candidate


def _assert_shadow_inputs(
    *,
    shadow: ShadowCollectionResult,
    config: TestGateConfig,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if shadow.coverage_document.get("terminal_status") != "pass":
        raise AuthoritativePlanError("shadow coverage is not green")
    general = shadow.general.nodes
    harness = shadow.qualification_harness.nodes
    scenarios = shadow.qualification_scenarios.nodes
    general_set = set(general)
    harness_set = set(harness)
    scenario_set = set(scenarios)
    if harness_set & scenario_set:
        raise AuthoritativePlanError(
            "qualification harness and scenario node sets overlap"
        )
    qualification_set = harness_set | scenario_set
    missing_from_general = sorted(qualification_set - general_set)
    if missing_from_general:
        raise AuthoritativePlanError(
            "qualification-owned nodes are missing from G: "
            + ", ".join(missing_from_general)
        )
    allowed = set(config.pytest_contract.allowed_non_live_markers)
    forbidden = set(config.pytest_contract.forbidden_non_live_markers)
    for snapshot in (
        shadow.general,
        shadow.qualification_harness,
        shadow.qualification_scenarios,
    ):
        for node_id, markers in snapshot.markers:
            unknown = sorted(set(markers) - allowed)
            if unknown:
                raise AuthoritativePlanError(
                    f"{snapshot.role} node {node_id!r} has unknown or forbidden "
                    f"markers: {', '.join(unknown)}"
                )
        for node_id, markers in snapshot.deselected_markers:
            marker_set = set(markers)
            unknown = sorted(marker_set - allowed - forbidden)
            if unknown or not marker_set & forbidden:
                raise AuthoritativePlanError(
                    f"{snapshot.role} deselection {node_id!r} is not explained "
                    "by the closed forbidden-marker policy"
                )
    return (
        tuple(sorted(general_set)),
        tuple(sorted(qualification_set)),
        tuple(sorted(general_set - qualification_set)),
    )


def _build_authoritative_plan(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    shadow: ShadowCollectionResult,
    environments: Mapping[str, Mapping[str, str]],
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
    expected_authoritative: bool,
    plan_filename: str,
) -> dict[str, Any]:
    """Build one exact mainline plan in the explicitly selected authority mode."""

    root = repo_root.resolve(strict=True)
    evidence_root = _validate_existing_external_root(root, output_root)
    if shadow.output_root.resolve(strict=True) != evidence_root:
        raise AuthoritativePlanError("shadow evidence belongs to another output root")
    general_nodes, qualification_nodes, residual_nodes = _assert_shadow_inputs(
        shadow=shadow,
        config=config,
    )
    try:
        fixed_workers = validate_worker_count(
            workers,
            hard_max=config.worker_hard_max,
        )
    except ResourceManifestError as exc:
        raise AuthoritativePlanError(str(exc)) from exc
    try:
        resolved_resource_path = resource_manifest_path.resolve(strict=True)
        resource_relative_path = resolved_resource_path.relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise AuthoritativePlanError(
            "resource manifest must be a regular repository file"
        ) from exc
    try:
        resource_document, resource_assignments = load_resource_manifest(
            resolved_resource_path,
            repo_root=root,
            collection_records=[
                {"node_id": node_id, "markers": list(markers)}
                for node_id, markers in shadow.general.markers
            ],
            config=config,
            allow_stale_as_serial=fixed_workers == 1,
        )
        xdist_identity = probe_xdist_identity()
        serial_nodes, parallel_nodes = resource_partition(
            residual_nodes=residual_nodes,
            assignments=resource_assignments,
            config=config,
        )
    except ResourceManifestError as exc:
        raise AuthoritativePlanError(
            f"resource planning failed: {exc}"
        ) from exc
    if set(qualification_nodes) & set(resource_assignments):
        raise AuthoritativePlanError(
            "qualification-owned nodes cannot enter a parallel resource entry"
        )
    if shadow.source_identity.digest != shadow.coverage_document.get(
        "source_identity_digest"
    ):
        raise AuthoritativePlanError("shadow source identity binding drifted")
    expected_legacy_digest = _legacy_multiset_digest(
        general_nodes=shadow.general.nodes,
        harness_nodes=shadow.qualification_harness.nodes,
        scenario_nodes=shadow.qualification_scenarios.nodes,
    )
    if expected_legacy_digest != shadow.coverage_document.get(
        "legacy_execution_multiset_digest"
    ):
        raise AuthoritativePlanError("shadow legacy execution multiset drifted")
    policy_deselected_nodes = tuple(
        node_id for node_id, _ in shadow.general.deselected_markers
    )
    stage_records = _stage_records(
        config=config,
        repo_root=root,
        output_root=evidence_root,
        invocation_id=invocation_id,
        environments=environments,
        qualification_nodes=qualification_nodes,
        residual_nodes=residual_nodes,
        resource_manifest_path=resolved_resource_path,
        plan_filename=plan_filename,
        expected_authoritative=expected_authoritative,
    )
    ownership = [
        {
            "node_id": node_id,
            "owner": (
                "architecture_qualification_premerge"
                if node_id in set(qualification_nodes)
                else "general_non_live_pytest"
            ),
            "resource_class": (
                "serial_qualification"
                if node_id in set(qualification_nodes)
                else resource_assignments.get(
                    node_id,
                    config.resource_policy.default_class,
                )
            ),
        }
        for node_id in general_nodes
    ]
    plan = seal_document(
        EXECUTION_PLAN_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "profile_id": "mainline_authoritative",
            "planner_digest": _planner_digest(),
            "config_digest": config.digest,
            "source_identity": shadow.source_identity.as_dict(),
            "toolchains": [
                toolchain.as_dict()
                for toolchain in shadow.source_identity.toolchains
            ],
            "output_root": str(evidence_root),
            "stages": stage_records,
            "node_ownership": ownership,
            "expected_coverage_digest": _nodes_digest(general_nodes),
            "worker_policy": {
                "mode": (
                    "forced_serial" if fixed_workers == 1 else "fixed_parallel"
                ),
                "workers": fixed_workers,
                "hard_max": config.worker_hard_max,
                "parallel_eligible_classes": list(
                    config.resource_policy.parallel_eligible_classes
                ),
                "unclassified_default": config.resource_policy.default_class,
                "distribution": PARALLEL_DISTRIBUTION,
                "resource_manifest_digest": resource_document["self_digest"],
                "xdist_identity": xdist_identity,
            },
            "authority": _expected_authority(
                authoritative=expected_authoritative
            ),
            "collections": {
                "general": _snapshot_record(shadow.general),
                "qualification_harness": _snapshot_record(
                    shadow.qualification_harness
                ),
                "qualification_scenarios": _snapshot_record(
                    shadow.qualification_scenarios
                ),
                "general_recheck": _general_recheck_record(
                    config=config,
                    repo_root=root,
                    output_root=evidence_root,
                    invocation_id=invocation_id,
                    environment=environments["general_non_live_pytest"],
                    general=shadow.general,
                ),
                "general_manifest": _manifest_descriptor(
                    residual_nodes=residual_nodes,
                    qualification_nodes=qualification_nodes,
                    policy_deselected_nodes=policy_deselected_nodes,
                ),
                "resource_manifest": {
                    "schema_id": RESOURCE_MANIFEST_SCHEMA_ID,
                    "path": resource_relative_path,
                    "digest": resource_document["self_digest"],
                    "parallel_nodes_digest": _nodes_digest(parallel_nodes),
                    "serial_nodes_digest": _nodes_digest(serial_nodes),
                },
                "qualification_sidecar": {
                    "schema_id": "openzyme_test_qualification_execution@1",
                    "path": QUALIFICATION_SIDECAR_FILENAME,
                    "qualification_mode": "premerge_subset",
                    "report_path": (
                        f"{QUALIFICATION_OUTPUT_DIRECTORY}/"
                        f"{QUALIFICATION_REPORT_FILENAME}"
                    ),
                },
            },
            "legacy_execution_multiset_digest": expected_legacy_digest,
            "source_recheck_policy": (
                "before_each_process_stage_after_collection_and_final"
            ),
        },
    )
    return plan


def build_authoritative_shadow_plan(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    shadow: ShadowCollectionResult,
    environments: Mapping[str, Mapping[str, str]],
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
) -> dict[str, Any]:
    """Build, but do not execute or grant authority to, one mainline plan."""

    return _build_authoritative_plan(
        repo_root=repo_root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        shadow=shadow,
        environments=environments,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
        expected_authoritative=False,
        plan_filename=PLAN_FILENAME,
    )


def build_authoritative_mainline_plan(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    shadow: ShadowCollectionResult,
    environments: Mapping[str, Mapping[str, str]],
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
) -> dict[str, Any]:
    """Build the exact non-live merge-authoritative mainline plan."""

    return _build_authoritative_plan(
        repo_root=repo_root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        shadow=shadow,
        environments=environments,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
        expected_authoritative=True,
        plan_filename=MAINLINE_AUTHORITATIVE_PLAN_FILENAME,
    )


def build_node_manifest(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact residual selector bound to one already sealed plan."""

    try:
        verify_sealed_document(plan)
    except ValueError as exc:
        raise AuthoritativePlanError(f"invalid plan for manifest: {exc}") from exc
    collections = plan.get("collections")
    if not isinstance(collections, dict):
        raise AuthoritativePlanError("plan collections are missing")
    general = collections.get("general")
    harness = collections.get("qualification_harness")
    scenarios = collections.get("qualification_scenarios")
    if not all(isinstance(item, dict) for item in (general, harness, scenarios)):
        raise AuthoritativePlanError("plan collection snapshots are missing")
    general_nodes = _sorted_unique_strings(
        general["nodes"],
        context="collections.general.nodes",
    )
    qualification_nodes = tuple(
        sorted(set(harness["nodes"]) | set(scenarios["nodes"]))
    )
    residual_nodes = tuple(sorted(set(general_nodes) - set(qualification_nodes)))
    policy_nodes = tuple(
        item["node_id"] for item in general["policy_deselected_nodes"]
    )
    source_identity = plan.get("source_identity")
    if not isinstance(source_identity, dict):
        raise AuthoritativePlanError("plan source identity is missing")
    return seal_document(
        NODE_MANIFEST_SCHEMA_ID,
        {
            "invocation_id": plan["invocation_id"],
            "role": "general_residual",
            "plan_digest": plan["self_digest"],
            "source_identity_digest": sha256_digest(
                canonical_json_bytes(source_identity)
            ),
            "full_collection_digest": general["collection_digest"],
            "selected_nodes": list(residual_nodes),
            "selected_nodes_digest": _nodes_digest(residual_nodes),
            "planned_deselected_nodes": list(qualification_nodes),
            "planned_deselected_digest": _nodes_digest(qualification_nodes),
            "expected_policy_deselected_nodes": list(policy_nodes),
            "expected_policy_deselected_digest": _nodes_digest(policy_nodes),
        },
    )


def _verify_snapshot(
    value: Any,
    *,
    expected_role: str,
    config: TestGateConfig,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]:
    snapshot = _strict_mapping(
        value,
        fields=_SNAPSHOT_FIELDS,
        context=f"collections.{expected_role}",
    )
    if snapshot["role"] != expected_role:
        raise AuthoritativePlanError(
            f"collection role drifted for {expected_role}"
        )
    nodes = _sorted_unique_strings(
        snapshot["nodes"],
        context=f"collections.{expected_role}.nodes",
    )
    raw_markers = snapshot["markers"]
    if not isinstance(raw_markers, list):
        raise AuthoritativePlanError(
            f"collections.{expected_role}.markers must be an array"
        )
    markers: list[tuple[str, tuple[str, ...]]] = []
    canonical_markers: list[dict[str, object]] = []
    allowed = set(config.pytest_contract.allowed_non_live_markers)
    forbidden = set(config.pytest_contract.forbidden_non_live_markers)
    for index, raw in enumerate(raw_markers):
        record = _strict_mapping(
            raw,
            fields={"node_id", "markers"},
            context=f"collections.{expected_role}.markers[{index}]",
        )
        node_id = record["node_id"]
        if not isinstance(node_id, str) or not node_id:
            raise AuthoritativePlanError("collection marker node id is invalid")
        marker_names = _sorted_unique_strings(
            record["markers"],
            context=f"collections.{expected_role}.markers[{index}].markers",
        )
        unknown = sorted(set(marker_names) - allowed)
        if unknown:
            raise AuthoritativePlanError(
                f"collection node {node_id!r} has unknown or forbidden markers: "
                + ", ".join(unknown)
            )
        markers.append((node_id, marker_names))
        canonical_markers.append(
            {"node_id": node_id, "markers": list(marker_names)}
        )
    if tuple(node_id for node_id, _ in markers) != nodes:
        raise AuthoritativePlanError(
            f"collections.{expected_role} marker inventory does not close nodes"
        )
    expected_collection_digest = sha256_digest(
        canonical_json_bytes(canonical_markers)
    )
    if snapshot["collection_digest"] != expected_collection_digest:
        raise AuthoritativePlanError(
            f"collections.{expected_role} digest mismatch"
        )
    raw_policy = snapshot["policy_deselected_nodes"]
    if not isinstance(raw_policy, list):
        raise AuthoritativePlanError(
            f"collections.{expected_role}.policy_deselected_nodes must be an array"
        )
    policy_nodes: list[str] = []
    for index, raw in enumerate(raw_policy):
        record = _strict_mapping(
            raw,
            fields={"node_id", "markers"},
            context=(
                f"collections.{expected_role}.policy_deselected_nodes[{index}]"
            ),
        )
        node_id = record["node_id"]
        marker_names = _sorted_unique_strings(
            record["markers"],
            context="policy deselection markers",
        )
        if not isinstance(node_id, str) or not node_id:
            raise AuthoritativePlanError("policy deselection node id is invalid")
        marker_set = set(marker_names)
        if (
            marker_set - allowed - forbidden
            or not marker_set & forbidden
        ):
            raise AuthoritativePlanError(
                f"policy deselection {node_id!r} is unexplained"
            )
        policy_nodes.append(node_id)
    if tuple(policy_nodes) != tuple(sorted(set(policy_nodes))):
        raise AuthoritativePlanError(
            f"collections.{expected_role} policy deselections are not sorted"
        )
    if set(policy_nodes) & set(nodes):
        raise AuthoritativePlanError(
            f"collections.{expected_role} selected and deselected nodes overlap"
        )
    if expected_role != "legacy_general" and policy_nodes:
        raise AuthoritativePlanError(
            f"{expected_role} cannot carry policy deselections"
        )
    return nodes, tuple(markers), tuple(policy_nodes)


def _expected_authority(*, authoritative: bool) -> dict[str, object]:
    return {
        "authoritative": authoritative,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "authority_domain": (
            "authoritative_non_live_mainline"
            if authoritative
            else "shadow_candidate_non_live_mainline"
        ),
        "current_authoritative_entry": "scripts/check-mainline.sh",
    }


def verify_authoritative_plan(
    plan: Mapping[str, Any],
    *,
    repo_root: Path,
    config: TestGateConfig,
    current_source_identity_digest: str | None = None,
    current_environments: Mapping[str, Mapping[str, str]] | None = None,
    expected_authoritative: bool = False,
) -> None:
    """Purely close a plan in one explicitly expected authority domain."""

    try:
        verify_sealed_document(plan)
    except ValueError as exc:
        raise AuthoritativePlanError(f"invalid authoritative plan: {exc}") from exc
    if plan.get("schema_id") != EXECUTION_PLAN_SCHEMA_ID:
        raise AuthoritativePlanError("authoritative plan schema is invalid")
    if plan.get("profile_id") != "mainline_authoritative":
        raise AuthoritativePlanError("plan profile is not mainline_authoritative")
    authority = _strict_mapping(
        plan.get("authority"),
        fields=_AUTHORITY_FIELDS,
        context="authority",
    )
    if dict(authority) != _expected_authority(
        authoritative=expected_authoritative
    ):
        raise AuthoritativePlanError(
            "mainline plan authority mode drifted or crossed verifier domains"
        )
    if plan.get("config_digest") != config.digest:
        raise AuthoritativePlanError("authoritative plan config digest drifted")
    if plan.get("planner_digest") != _planner_digest():
        raise AuthoritativePlanError("authoritative planner implementation drifted")
    source_identity = plan.get("source_identity")
    if not isinstance(source_identity, dict):
        raise AuthoritativePlanError("authoritative source identity is missing")
    source_digest = sha256_digest(canonical_json_bytes(source_identity))
    if (
        current_source_identity_digest is not None
        and current_source_identity_digest != source_digest
    ):
        raise AuthoritativePlanError("authoritative plan source identity is stale")
    if plan.get("toolchains") != source_identity.get("toolchains"):
        raise AuthoritativePlanError("authoritative toolchain identity drifted")
    root = repo_root.resolve(strict=True)
    output_root_value = plan.get("output_root")
    if not isinstance(output_root_value, str):
        raise AuthoritativePlanError("authoritative output root is missing")
    output_root = _validate_existing_external_root(
        root,
        Path(output_root_value),
    )
    collections = _strict_mapping(
        plan.get("collections"),
        fields={
            "general",
            "qualification_harness",
            "qualification_scenarios",
            "general_recheck",
            "general_manifest",
            "resource_manifest",
            "qualification_sidecar",
        },
        context="collections",
    )
    general_nodes, _, policy_nodes = _verify_snapshot(
        collections["general"],
        expected_role="legacy_general",
        config=config,
    )
    harness_nodes, _, _ = _verify_snapshot(
        collections["qualification_harness"],
        expected_role="qualification_harness",
        config=config,
    )
    scenario_nodes, _, _ = _verify_snapshot(
        collections["qualification_scenarios"],
        expected_role="qualification_scenario",
        config=config,
    )
    if set(harness_nodes) & set(scenario_nodes):
        raise AuthoritativePlanError(
            "qualification harness and scenario owners overlap"
        )
    qualification_nodes = tuple(
        sorted(set(harness_nodes) | set(scenario_nodes))
    )
    if not set(qualification_nodes) <= set(general_nodes):
        raise AuthoritativePlanError(
            "qualification-owned nodes are not a subset of G"
        )
    residual_nodes = tuple(
        sorted(set(general_nodes) - set(qualification_nodes))
    )
    resource_descriptor = _strict_mapping(
        collections["resource_manifest"],
        fields=_RESOURCE_MANIFEST_DESCRIPTOR_FIELDS,
        context="collections.resource_manifest",
    )
    raw_resource_path = resource_descriptor["path"]
    if not isinstance(raw_resource_path, str):
        raise AuthoritativePlanError("resource manifest path is invalid")
    pure_resource_path = Path(raw_resource_path)
    if (
        pure_resource_path.is_absolute()
        or ".." in pure_resource_path.parts
        or not pure_resource_path.parts
    ):
        raise AuthoritativePlanError("resource manifest path is unsafe")
    resource_path = root / pure_resource_path
    worker_policy = _strict_mapping(
        plan.get("worker_policy"),
        fields=_WORKER_POLICY_FIELDS,
        context="worker_policy",
    )
    try:
        fixed_workers = validate_worker_count(
            worker_policy["workers"],
            hard_max=config.worker_hard_max,
        )
    except (KeyError, ResourceManifestError) as exc:
        raise AuthoritativePlanError("authoritative worker policy drifted") from exc
    if (
        worker_policy["mode"]
        != ("forced_serial" if fixed_workers == 1 else "fixed_parallel")
        or worker_policy["hard_max"] != config.worker_hard_max
        or worker_policy["parallel_eligible_classes"]
        != list(config.resource_policy.parallel_eligible_classes)
        or worker_policy["unclassified_default"]
        != config.resource_policy.default_class
        or worker_policy["distribution"] != PARALLEL_DISTRIBUTION
    ):
        raise AuthoritativePlanError("authoritative worker policy drifted")
    try:
        resource_document, resource_assignments = load_resource_manifest(
            resource_path,
            repo_root=root,
            collection_records=[
                {
                    "node_id": str(item["node_id"]),
                    "markers": list(item["markers"]),
                }
                for item in collections["general"]["markers"]
            ],
            config=config,
            allow_stale_as_serial=fixed_workers == 1,
        )
        serial_nodes, parallel_nodes = resource_partition(
            residual_nodes=residual_nodes,
            assignments=resource_assignments,
            config=config,
        )
        xdist_identity = probe_xdist_identity()
    except (KeyError, TypeError, ResourceManifestError) as exc:
        raise AuthoritativePlanError(
            f"resource plan verification failed: {exc}"
        ) from exc
    expected_resource_descriptor = {
        "schema_id": RESOURCE_MANIFEST_SCHEMA_ID,
        "path": pure_resource_path.as_posix(),
        "digest": resource_document["self_digest"],
        "parallel_nodes_digest": _nodes_digest(parallel_nodes),
        "serial_nodes_digest": _nodes_digest(serial_nodes),
    }
    if dict(resource_descriptor) != expected_resource_descriptor:
        raise AuthoritativePlanError("resource manifest descriptor drifted")
    expected_worker_policy = {
        "mode": (
            "forced_serial" if fixed_workers == 1 else "fixed_parallel"
        ),
        "workers": fixed_workers,
        "hard_max": config.worker_hard_max,
        "parallel_eligible_classes": list(
            config.resource_policy.parallel_eligible_classes
        ),
        "unclassified_default": config.resource_policy.default_class,
        "distribution": PARALLEL_DISTRIBUTION,
        "resource_manifest_digest": resource_document["self_digest"],
        "xdist_identity": xdist_identity,
    }
    if dict(worker_policy) != expected_worker_policy:
        raise AuthoritativePlanError("authoritative worker policy drifted")
    if plan.get("expected_coverage_digest") != _nodes_digest(general_nodes):
        raise AuthoritativePlanError("authoritative expected coverage drifted")
    expected_legacy_digest = _legacy_multiset_digest(
        general_nodes=general_nodes,
        harness_nodes=harness_nodes,
        scenario_nodes=scenario_nodes,
    )
    if plan.get("legacy_execution_multiset_digest") != expected_legacy_digest:
        raise AuthoritativePlanError(
            "authoritative legacy execution multiset drifted"
        )
    raw_ownership = plan.get("node_ownership")
    if not isinstance(raw_ownership, list):
        raise AuthoritativePlanError("authoritative node ownership is missing")
    expected_ownership = [
        {
            "node_id": node_id,
            "owner": (
                "architecture_qualification_premerge"
                if node_id in set(qualification_nodes)
                else "general_non_live_pytest"
            ),
            "resource_class": (
                "serial_qualification"
                if node_id in set(qualification_nodes)
                else resource_assignments.get(
                    node_id,
                    config.resource_policy.default_class,
                )
            ),
        }
        for node_id in general_nodes
    ]
    if raw_ownership != expected_ownership:
        raise AuthoritativePlanError(
            "authoritative nodes do not have exactly one expected owner"
        )
    for item in raw_ownership:
        if item["resource_class"] not in RESOURCE_CLASSES:
            raise AuthoritativePlanError("node ownership has an unknown resource class")

    manifest_descriptor = _strict_mapping(
        collections["general_manifest"],
        fields=_MANIFEST_DESCRIPTOR_FIELDS,
        context="collections.general_manifest",
    )
    expected_descriptor = _manifest_descriptor(
        residual_nodes=residual_nodes,
        qualification_nodes=qualification_nodes,
        policy_deselected_nodes=policy_nodes,
    )
    if dict(manifest_descriptor) != expected_descriptor:
        raise AuthoritativePlanError("general residual manifest descriptor drifted")
    qualification_sidecar = _strict_mapping(
        collections["qualification_sidecar"],
        fields=_QUALIFICATION_SIDECAR_DESCRIPTOR_FIELDS,
        context="collections.qualification_sidecar",
    )
    if dict(qualification_sidecar) != {
        "schema_id": "openzyme_test_qualification_execution@1",
        "path": QUALIFICATION_SIDECAR_FILENAME,
        "qualification_mode": "premerge_subset",
        "report_path": (
            f"{QUALIFICATION_OUTPUT_DIRECTORY}/"
            f"{QUALIFICATION_REPORT_FILENAME}"
        ),
    }:
        raise AuthoritativePlanError(
            "qualification sidecar descriptor drifted"
        )

    recheck = _strict_mapping(
        collections["general_recheck"],
        fields=_GENERAL_RECHECK_FIELDS,
        context="collections.general_recheck",
    )
    stage_environment = (
        None
        if current_environments is None
        else current_environments.get("general_non_live_pytest")
    )
    if current_environments is not None and stage_environment is None:
        raise AuthoritativePlanError(
            "current general pytest environment is missing"
        )
    expected_general_environment_digest = (
        recheck["environment_digest"]
        if stage_environment is None
        else _environment_digest(stage_environment)
    )
    expected_recheck = _general_recheck_record(
        config=config,
        repo_root=root,
        output_root=output_root,
        invocation_id=str(plan["invocation_id"]),
        environment=(
            {"bound": str(recheck["environment_digest"])}
            if stage_environment is None
            else stage_environment
        ),
        general=CollectionSnapshot(
            invocation_id=str(plan["invocation_id"]),
            role="legacy_general",
            nodes=general_nodes,
            markers=tuple(
                (
                    str(item["node_id"]),
                    tuple(str(marker) for marker in item["markers"]),
                )
                for item in collections["general"]["markers"]
            ),
            digest=str(collections["general"]["collection_digest"]),
            deselected_markers=tuple(
                (
                    str(item["node_id"]),
                    tuple(str(marker) for marker in item["markers"]),
                )
                for item in collections["general"]["policy_deselected_nodes"]
            ),
        ),
    )
    expected_recheck["environment_digest"] = expected_general_environment_digest
    if dict(recheck) != expected_recheck:
        raise AuthoritativePlanError(
            "general collection recheck command or environment contract drifted"
        )

    raw_stages = plan.get("stages")
    if not isinstance(raw_stages, list):
        raise AuthoritativePlanError("authoritative stages are missing")
    environment_basis: dict[str, Mapping[str, str]] = {}
    for raw in raw_stages:
        if not isinstance(raw, dict):
            raise AuthoritativePlanError("authoritative stage is not an object")
        stage_id = raw.get("stage_id")
        if not isinstance(stage_id, str):
            raise AuthoritativePlanError("authoritative stage id is invalid")
        current = (
            None
            if current_environments is None
            else current_environments.get(stage_id)
        )
        if current_environments is not None and current is None:
            raise AuthoritativePlanError(
                f"current environment is missing for {stage_id}"
            )
        environment_basis[stage_id] = (
            {"bound": str(raw.get("environment_digest"))}
            if current is None
            else current
        )
    expected_stages = _stage_records(
        config=config,
        repo_root=root,
        output_root=output_root,
        invocation_id=str(plan["invocation_id"]),
        environments=environment_basis,
        qualification_nodes=qualification_nodes,
        residual_nodes=residual_nodes,
        resource_manifest_path=resource_path,
        plan_filename=(
            MAINLINE_AUTHORITATIVE_PLAN_FILENAME
            if expected_authoritative
            else PLAN_FILENAME
        ),
        expected_authoritative=expected_authoritative,
    )
    if current_environments is None:
        for expected, actual in zip(expected_stages, raw_stages, strict=True):
            expected["environment_digest"] = actual.get("environment_digest")
    for raw in raw_stages:
        _strict_mapping(
            raw,
            fields=_STAGE_FIELDS,
            context=f"stage {raw.get('stage_id')!r}",
        )
        _assert_digest(
            raw["environment_digest"],
            context=f"stage {raw['stage_id']} environment_digest",
        )
    if raw_stages != expected_stages:
        raise AuthoritativePlanError(
            "authoritative stage order, command, dependency, or policy drifted"
        )
    if plan.get("source_recheck_policy") != (
        "before_each_process_stage_after_collection_and_final"
    ):
        raise AuthoritativePlanError("authoritative source recheck policy drifted")


def verify_node_manifest(
    manifest: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
) -> None:
    """Purely verify the plan-bound exact residual manifest."""

    try:
        verify_sealed_document(manifest)
    except ValueError as exc:
        raise AuthoritativePlanError(f"invalid node manifest: {exc}") from exc
    if manifest.get("schema_id") != NODE_MANIFEST_SCHEMA_ID:
        raise AuthoritativePlanError("node manifest schema is invalid")
    if manifest.get("invocation_id") != plan.get("invocation_id"):
        raise AuthoritativePlanError("node manifest invocation drifted")
    if manifest.get("role") != "general_residual":
        raise AuthoritativePlanError("node manifest role is invalid")
    if manifest.get("plan_digest") != plan.get("self_digest"):
        raise AuthoritativePlanError("node manifest plan binding drifted")
    source_identity = plan.get("source_identity")
    if not isinstance(source_identity, dict):
        raise AuthoritativePlanError("plan source identity is missing")
    if manifest.get("source_identity_digest") != sha256_digest(
        canonical_json_bytes(source_identity)
    ):
        raise AuthoritativePlanError("node manifest source binding drifted")
    collections = plan.get("collections")
    if not isinstance(collections, dict):
        raise AuthoritativePlanError("plan collections are missing")
    general = collections["general"]
    general_nodes = _sorted_unique_strings(
        general["nodes"],
        context="collections.general.nodes",
    )
    harness_nodes = _sorted_unique_strings(
        collections["qualification_harness"]["nodes"],
        context="collections.qualification_harness.nodes",
    )
    scenario_nodes = _sorted_unique_strings(
        collections["qualification_scenarios"]["nodes"],
        context="collections.qualification_scenarios.nodes",
    )
    qualification_nodes = tuple(
        sorted(set(harness_nodes) | set(scenario_nodes))
    )
    residual_nodes = tuple(
        sorted(set(general_nodes) - set(qualification_nodes))
    )
    policy_nodes = tuple(
        item["node_id"] for item in general["policy_deselected_nodes"]
    )
    expected = {
        "selected_nodes": residual_nodes,
        "selected_nodes_digest": _nodes_digest(residual_nodes),
        "planned_deselected_nodes": qualification_nodes,
        "planned_deselected_digest": _nodes_digest(qualification_nodes),
        "expected_policy_deselected_nodes": policy_nodes,
        "expected_policy_deselected_digest": _nodes_digest(policy_nodes),
        "full_collection_digest": general["collection_digest"],
    }
    for field, value in expected.items():
        actual = manifest.get(field)
        if isinstance(value, tuple):
            actual = _sorted_unique_strings(actual, context=f"manifest.{field}")
        if actual != value:
            raise AuthoritativePlanError(
                f"node manifest field {field!r} drifted"
            )
    descriptor = collections["general_manifest"]
    if (
        descriptor["schema_id"] != manifest["schema_id"]
        or descriptor["path"] != NODE_MANIFEST_FILENAME
        or descriptor["selected_nodes_digest"]
        != manifest["selected_nodes_digest"]
        or descriptor["planned_deselected_digest"]
        != manifest["planned_deselected_digest"]
        or descriptor["expected_policy_deselected_digest"]
        != manifest["expected_policy_deselected_digest"]
    ):
        raise AuthoritativePlanError("node manifest descriptor binding drifted")


def _run_authoritative_plan(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    ambient_environment: Mapping[str, str] | None = None,
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
    expected_authoritative: bool,
    plan_filename: str,
) -> AuthoritativePlanResult:
    """Collect and publish a verified plan in one explicit authority mode."""

    root = repo_root.resolve(strict=True)
    shadow = run_shadow_collection(
        repo_root=root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
    )
    environments = stage_environments(
        config=config,
        repo_root=root,
        source=ambient_environment,
    )
    plan = _build_authoritative_plan(
        repo_root=root,
        output_root=shadow.output_root,
        config=config,
        invocation_id=invocation_id,
        shadow=shadow,
        environments=environments,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
        expected_authoritative=expected_authoritative,
        plan_filename=plan_filename,
    )
    source_after = collect_source_identity(root)
    verify_authoritative_plan(
        plan,
        repo_root=root,
        config=config,
        current_source_identity_digest=source_after.digest,
        current_environments=environments,
        expected_authoritative=expected_authoritative,
    )
    publish_no_replace(
        shadow.output_root / plan_filename,
        canonical_document_bytes(plan),
    )
    manifest = build_node_manifest(plan)
    verify_node_manifest(manifest, plan=plan)
    publish_no_replace(
        shadow.output_root / NODE_MANIFEST_FILENAME,
        canonical_document_bytes(manifest),
    )
    return AuthoritativePlanResult(
        output_root=shadow.output_root,
        source_identity=shadow.source_identity,
        plan=plan,
        manifest=manifest,
    )


def run_authoritative_shadow_plan(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    ambient_environment: Mapping[str, str] | None = None,
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
) -> AuthoritativePlanResult:
    """Collect and publish a verified candidate plan without authority."""

    return _run_authoritative_plan(
        repo_root=repo_root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        ambient_environment=ambient_environment,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
        expected_authoritative=False,
        plan_filename=PLAN_FILENAME,
    )


def run_authoritative_mainline_plan(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    ambient_environment: Mapping[str, str] | None = None,
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
) -> AuthoritativePlanResult:
    """Collect and publish the explicit non-live merge-authority plan."""

    return _run_authoritative_plan(
        repo_root=repo_root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        ambient_environment=ambient_environment,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
        expected_authoritative=True,
        plan_filename=MAINLINE_AUTHORITATIVE_PLAN_FILENAME,
    )


def verify_authoritative_plan_files(
    *,
    plan_path: Path,
    manifest_path: Path,
    repo_root: Path,
    config: TestGateConfig,
    ambient_environment: Mapping[str, str] | None = None,
    expected_authoritative: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and purely verify a plan/manifest pair against current source."""

    try:
        resolved_plan = plan_path.resolve(strict=True)
        resolved_manifest = manifest_path.resolve(strict=True)
    except OSError as exc:
        raise AuthoritativePlanError(
            f"cannot resolve plan or manifest: {exc}"
        ) from exc
    if resolved_plan.parent != resolved_manifest.parent:
        raise AuthoritativePlanError(
            "authoritative plan and manifest must share one output root"
        )
    try:
        plan = load_canonical_document_bytes(resolved_plan.read_bytes())
        manifest = load_canonical_document_bytes(resolved_manifest.read_bytes())
    except (OSError, ValueError) as exc:
        raise AuthoritativePlanError(
            f"cannot load authoritative plan or manifest: {exc}"
        ) from exc
    if plan.get("output_root") != str(resolved_plan.parent):
        raise AuthoritativePlanError(
            "authoritative plan path does not match its output root"
        )
    collections = plan.get("collections")
    if (
        not isinstance(collections, dict)
        or not isinstance(collections.get("general_manifest"), dict)
        or collections["general_manifest"].get("path")
        != resolved_manifest.name
    ):
        raise AuthoritativePlanError(
            "authoritative manifest path does not match the plan"
        )
    root = repo_root.resolve(strict=True)
    current_source = collect_source_identity(root)
    environments = stage_environments(
        config=config,
        repo_root=root,
        source=ambient_environment,
    )
    verify_authoritative_plan(
        plan,
        repo_root=root,
        config=config,
        current_source_identity_digest=current_source.digest,
        current_environments=environments,
        expected_authoritative=expected_authoritative,
    )
    verify_node_manifest(manifest, plan=plan)
    return plan, manifest
