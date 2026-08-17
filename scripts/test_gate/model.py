"""Strict canonical evidence helpers for repository test-gate files."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

EXECUTION_PLAN_SCHEMA_ID = "openzyme_test_execution_plan@1"
STAGE_RESULT_SCHEMA_ID = "openzyme_test_stage_result@1"
QUALIFICATION_SIDECAR_SCHEMA_ID = "openzyme_test_qualification_execution@1"
RECEIPT_SCHEMA_ID = "openzyme_test_gate_receipt@1"
BENCHMARK_SUMMARY_SCHEMA_ID = "openzyme_test_benchmark_summary@1"
PYTEST_OBSERVATION_SCHEMA_ID = "openzyme_test_pytest_observation@1"
SHADOW_COVERAGE_SCHEMA_ID = "openzyme_test_shadow_coverage@1"
LEGACY_SAMPLE_SCHEMA_ID = "openzyme_test_legacy_sample@1"
LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID = "openzyme_test_legacy_stage_attribution@1"
PYTEST_OBSERVATION_BINDING_SCHEMA_ID = (
    "openzyme_test_pytest_observation_binding@1"
)
PHASE0_BASELINE_SCHEMA_ID = "openzyme_test_phase0_baseline@1"
NODE_MANIFEST_SCHEMA_ID = "openzyme_test_node_manifest@1"
RESOURCE_MANIFEST_SCHEMA_ID = "openzyme_test_resource_manifest@1"
OPTIMIZED_SAMPLE_SCHEMA_ID = "openzyme_test_optimized_sample@1"
REPLAY_CORPUS_SCHEMA_ID = "openzyme_test_replay_corpus@1"


class EvidenceModelError(ValueError):
    """Raised when operator evidence is malformed or non-canonical."""


@dataclass(frozen=True)
class SchemaContract:
    """Closed top-level field contract for one versioned evidence document."""

    schema_id: str
    required_fields: frozenset[str]
    optional_fields: frozenset[str] = frozenset()

    @property
    def allowed_fields(self) -> frozenset[str]:
        return self.required_fields | self.optional_fields


SCHEMA_CONTRACTS: Mapping[str, SchemaContract] = {
    EXECUTION_PLAN_SCHEMA_ID: SchemaContract(
        schema_id=EXECUTION_PLAN_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "profile_id",
                "planner_digest",
                "config_digest",
                "source_identity",
                "toolchains",
                "output_root",
                "stages",
                "node_ownership",
                "expected_coverage_digest",
                "worker_policy",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "authority",
                "collections",
                "diagnostic_selection",
                "legacy_execution_multiset_digest",
                "source_recheck_policy",
            }
        ),
    ),
    STAGE_RESULT_SCHEMA_ID: SchemaContract(
        schema_id=STAGE_RESULT_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "plan_digest",
                "stage_id",
                "argv",
                "cwd",
                "environment_digest",
                "outcome",
                "started_monotonic_ns",
                "duration_ns",
                "exit_code",
                "stdout_digest",
                "stdout_tail",
                "stderr_digest",
                "stderr_tail",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "node_results",
                "retirement",
                "timed_out",
            }
        ),
    ),
    QUALIFICATION_SIDECAR_SCHEMA_ID: SchemaContract(
        schema_id=QUALIFICATION_SIDECAR_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "plan_digest",
                "source_identity_digest",
                "environment_digest",
                "qualification_report_digest",
                "node_results",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "harness_collection",
                "scenario_collection",
                "qualification_mode",
                "qualification_report_path",
            }
        ),
    ),
    RECEIPT_SCHEMA_ID: SchemaContract(
        schema_id=RECEIPT_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "profile_id",
                "authoritative",
                "admission_eligible",
                "live_eligible",
                "plan_digest",
                "source_identity_digest",
                "stages",
                "terminal_status",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "coverage",
                "diagnostic_selection",
                "frontend",
                "qualification",
                "resource_assignments",
                "timing",
            }
        ),
    ),
    BENCHMARK_SUMMARY_SCHEMA_ID: SchemaContract(
        schema_id=BENCHMARK_SUMMARY_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "source_identity_digest",
                "host_identity",
                "toolchain_identity",
                "cache_control",
                "cold_samples",
                "warm_samples",
                "statistics",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "invalid_samples",
                "stage_breakdown",
                "planning_overhead",
                "candidate_profile",
                "baseline_comparison",
                "contention",
            }
        ),
    ),
    OPTIMIZED_SAMPLE_SCHEMA_ID: SchemaContract(
        schema_id=OPTIMIZED_SAMPLE_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "sample_kind",
                "sample_index",
                "cache_control",
                "source_identity",
                "source_identity_digest",
                "source_recheck_digest",
                "source_drift",
                "host_identity",
                "worker_policy",
                "plan_digest",
                "receipt_digest",
                "terminal_status",
                "functional_green",
                "timing",
                "coverage",
                "host_activity",
                "self_digest",
            }
        ),
    ),
    PYTEST_OBSERVATION_SCHEMA_ID: SchemaContract(
        schema_id=PYTEST_OBSERVATION_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "role",
                "mode",
                "pytest_argv",
                "cwd",
                "collection",
                "deselected",
                "node_results",
                "session_exit_code",
                "started_monotonic_ns",
                "duration_ns",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "deselected_markers",
                "partition_observations",
                "planned_deselected",
                "preselection_collection",
                "selection_manifest_digest",
                "worker_allocations",
                "worker_failures",
            }
        ),
    ),
    NODE_MANIFEST_SCHEMA_ID: SchemaContract(
        schema_id=NODE_MANIFEST_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "role",
                "plan_digest",
                "source_identity_digest",
                "full_collection_digest",
                "selected_nodes",
                "selected_nodes_digest",
                "planned_deselected_nodes",
                "planned_deselected_digest",
                "expected_policy_deselected_nodes",
                "expected_policy_deselected_digest",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "resource_manifest_digest",
                "resource_partition",
                "worker_count",
            }
        ),
    ),
    RESOURCE_MANIFEST_SCHEMA_ID: SchemaContract(
        schema_id=RESOURCE_MANIFEST_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "default_class",
                "parallel_eligible_classes",
                "distribution",
                "entries",
                "self_digest",
            }
        ),
    ),
    REPLAY_CORPUS_SCHEMA_ID: SchemaContract(
        schema_id=REPLAY_CORPUS_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "corpus_id",
                "equivalence_basis",
                "cases",
                "self_digest",
            }
        ),
    ),
    SHADOW_COVERAGE_SCHEMA_ID: SchemaContract(
        schema_id=SHADOW_COVERAGE_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "source_identity_digest",
                "general_collection_digest",
                "qualification_harness_collection_digest",
                "qualification_scenario_collection_digest",
                "legacy_execution_multiset",
                "legacy_execution_multiset_digest",
                "distinct_required_nodes",
                "distinct_coverage_digest",
                "structural_duplicates",
                "shadow_owners",
                "forbidden_nodes",
                "terminal_status",
                "self_digest",
            }
        ),
        optional_fields=frozenset({"failure_reasons", "frontend_commands"}),
    ),
    LEGACY_SAMPLE_SCHEMA_ID: SchemaContract(
        schema_id=LEGACY_SAMPLE_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "sample_kind",
                "sample_index",
                "cache_control",
                "source_identity",
                "source_identity_digest",
                "host_identity",
                "command",
                "process_result",
                "functional_green",
                "self_digest",
            }
        ),
    ),
    LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID: SchemaContract(
        schema_id=LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "source_identity_digest",
                "stages",
                "terminal_status",
                "self_digest",
            }
        ),
        optional_fields=frozenset(
            {
                "first_failing_stage",
                "qualification_report",
                "pytest_observation",
            }
        ),
    ),
    PYTEST_OBSERVATION_BINDING_SCHEMA_ID: SchemaContract(
        schema_id=PYTEST_OBSERVATION_BINDING_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "invocation_id",
                "source_identity",
                "source_identity_digest",
                "observation_self_digest",
                "observation_document_digest",
                "collection_digest",
                "pytest_argv",
                "binding_basis",
                "self_digest",
            }
        ),
    ),
    PHASE0_BASELINE_SCHEMA_ID: SchemaContract(
        schema_id=PHASE0_BASELINE_SCHEMA_ID,
        required_fields=frozenset(
            {
                "schema_id",
                "phase_id",
                "source_identity_digest",
                "host_identity",
                "toolchain_identity",
                "cache_control",
                "legacy_baseline",
                "stage_breakdown",
                "collection_closure",
                "node_critical_paths",
                "duplicate_node_cost",
                "critical_path_assessment",
                "raw_evidence",
                "self_digest",
            }
        ),
    ),
}


def sha256_digest(data: bytes) -> str:
    """Return a tagged SHA-256 digest."""

    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _validate_json_value(value: Any, *, location: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceModelError(f"{location} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, location=f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvidenceModelError(f"{location} contains a non-string object key")
            _validate_json_value(item, location=f"{location}.{key}")
        return
    raise EvidenceModelError(
        f"{location} contains unsupported JSON value {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON value with one deterministic UTF-8 representation."""

    _validate_json_value(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return encoded.encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise EvidenceModelError(f"value cannot be canonically encoded: {exc}") from exc


def canonical_document_bytes(document: Mapping[str, Any]) -> bytes:
    """Encode one canonical document, including its required trailing newline."""

    return canonical_json_bytes(dict(document)) + b"\n"


def _contract_for(schema_id: str) -> SchemaContract:
    try:
        return SCHEMA_CONTRACTS[schema_id]
    except KeyError as exc:
        raise EvidenceModelError(f"unknown evidence schema: {schema_id!r}") from exc


def _validate_document_fields(
    document: Mapping[str, Any],
    *,
    require_self_digest: bool,
) -> SchemaContract:
    schema_id = document.get("schema_id")
    if not isinstance(schema_id, str):
        raise EvidenceModelError("document schema_id must be a string")
    contract = _contract_for(schema_id)
    actual = frozenset(document)
    required = contract.required_fields
    if not require_self_digest:
        required = required - {"self_digest"}
    missing = sorted(required - actual)
    unexpected = sorted(actual - contract.allowed_fields)
    if missing:
        raise EvidenceModelError(
            f"{schema_id} is missing required fields: {', '.join(missing)}"
        )
    if unexpected:
        raise EvidenceModelError(
            f"{schema_id} has unknown fields: {', '.join(unexpected)}"
        )
    if require_self_digest and "self_digest" not in actual:
        raise EvidenceModelError(f"{schema_id} is missing required field: self_digest")
    _validate_json_value(dict(document))
    return contract


def compute_self_digest(document: Mapping[str, Any]) -> str:
    """Compute the self digest over the document with ``self_digest`` omitted."""

    payload = dict(document)
    payload.pop("self_digest", None)
    return sha256_digest(canonical_json_bytes(payload))


def seal_document(schema_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Create a closed, self-digested evidence document."""

    if "schema_id" in fields or "self_digest" in fields:
        raise EvidenceModelError(
            "seal_document fields must not contain schema_id or self_digest"
        )
    document: dict[str, Any] = {"schema_id": schema_id, **dict(fields)}
    _validate_document_fields(document, require_self_digest=False)
    document["self_digest"] = compute_self_digest(document)
    _validate_document_fields(document, require_self_digest=True)
    return document


def verify_sealed_document(document: Mapping[str, Any]) -> None:
    """Validate schema closure and the document's self digest."""

    _validate_document_fields(document, require_self_digest=True)
    actual_digest = document.get("self_digest")
    if not isinstance(actual_digest, str):
        raise EvidenceModelError("self_digest must be a string")
    expected_digest = compute_self_digest(document)
    if actual_digest != expected_digest:
        raise EvidenceModelError(
            f"self_digest mismatch: expected {expected_digest}, got {actual_digest}"
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceModelError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> None:
    raise EvidenceModelError(f"non-finite JSON number is forbidden: {token}")


def load_canonical_document_bytes(data: bytes) -> dict[str, Any]:
    """Strictly load canonical bytes and reject aliases or duplicate keys."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceModelError("evidence is not valid UTF-8") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except EvidenceModelError:
        raise
    except json.JSONDecodeError as exc:
        raise EvidenceModelError(f"invalid JSON evidence: {exc}") from exc
    if not isinstance(parsed, dict):
        raise EvidenceModelError("evidence document must be a JSON object")
    verify_sealed_document(parsed)
    expected = canonical_document_bytes(parsed)
    if data != expected:
        raise EvidenceModelError(
            "evidence bytes are not the unique canonical representation"
        )
    return parsed
