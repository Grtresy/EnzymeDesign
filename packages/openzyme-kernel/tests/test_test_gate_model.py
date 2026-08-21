from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.model import (  # noqa: E402
    BENCHMARK_SUMMARY_SCHEMA_ID,
    EXECUTION_PLAN_SCHEMA_ID,
    LEGACY_SAMPLE_SCHEMA_ID,
    LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
    NODE_MANIFEST_SCHEMA_ID,
    OPTIMIZED_SAMPLE_SCHEMA_ID,
    PHASE0_BASELINE_SCHEMA_ID,
    QUALIFICATION_SIDECAR_SCHEMA_ID,
    PYTEST_OBSERVATION_BINDING_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    RECEIPT_SCHEMA_ID,
    REPLAY_CORPUS_SCHEMA_ID,
    SHADOW_COVERAGE_SCHEMA_ID,
    STAGE_RESULT_SCHEMA_ID,
    EvidenceModelError,
    canonical_document_bytes,
    load_canonical_document_bytes,
    seal_document,
)


def _sample_documents() -> tuple[tuple[str, dict[str, object]], ...]:
    return (
        (
            EXECUTION_PLAN_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "profile_id": "mainline_authoritative",
                "planner_digest": "sha256:planner",
                "config_digest": "sha256:config",
                "source_identity": {},
                "toolchains": [],
                "output_root": "/tmp/output",
                "stages": [],
                "node_ownership": {},
                "expected_coverage_digest": "sha256:coverage",
                "worker_policy": {"hard_max": 4},
            },
        ),
        (
            STAGE_RESULT_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "plan_digest": "sha256:plan",
                "stage_id": "ruff_source",
                "argv": ["uv", "run", "ruff"],
                "cwd": ".",
                "environment_digest": "sha256:environment",
                "outcome": "pass",
                "started_monotonic_ns": 100,
                "duration_ns": 200,
                "exit_code": 0,
                "stdout_digest": "sha256:stdout",
                "stdout_tail": "",
                "stderr_digest": "sha256:stderr",
                "stderr_tail": "",
            },
        ),
        (
            QUALIFICATION_SIDECAR_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "plan_digest": "sha256:plan",
                "source_identity_digest": "sha256:source",
                "environment_digest": "sha256:environment",
                "qualification_report_digest": "sha256:report",
                "node_results": [],
            },
        ),
        (
            RECEIPT_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "profile_id": "focused_diagnostic",
                "authoritative": False,
                "admission_eligible": False,
                "live_eligible": False,
                "plan_digest": "sha256:plan",
                "source_identity_digest": "sha256:source",
                "stages": [],
                "terminal_status": "pass",
            },
        ),
        (
            BENCHMARK_SUMMARY_SCHEMA_ID,
            {
                "source_identity_digest": "sha256:source",
                "host_identity": {},
                "toolchain_identity": {},
                "cache_control": "process_only",
                "cold_samples": [],
                "warm_samples": [],
                "statistics": {},
            },
        ),
        (
            PYTEST_OBSERVATION_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "role": "legacy_general",
                "mode": "collect",
                "pytest_argv": ["pytest", "--collect-only"],
                "cwd": "/tmp",
                "collection": [],
                "deselected": [],
                "node_results": [],
                "session_exit_code": 0,
                "started_monotonic_ns": 1,
                "duration_ns": 2,
            },
        ),
        (
            NODE_MANIFEST_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "role": "general_residual",
                "plan_digest": "sha256:plan",
                "source_identity_digest": "sha256:source",
                "full_collection_digest": "sha256:full",
                "selected_nodes": ["node-a"],
                "selected_nodes_digest": "sha256:selected",
                "planned_deselected_nodes": ["node-b"],
                "planned_deselected_digest": "sha256:planned",
                "expected_policy_deselected_nodes": ["node-live"],
                "expected_policy_deselected_digest": "sha256:policy",
            },
        ),
        (
            SHADOW_COVERAGE_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "source_identity_digest": "sha256:source",
                "general_collection_digest": "sha256:general",
                "qualification_harness_collection_digest": "sha256:harness",
                "qualification_scenario_collection_digest": "sha256:scenario",
                "legacy_execution_multiset": [],
                "legacy_execution_multiset_digest": "sha256:multiset",
                "distinct_required_nodes": [],
                "distinct_coverage_digest": "sha256:coverage",
                "structural_duplicates": [],
                "shadow_owners": [],
                "forbidden_nodes": [],
                "terminal_status": "pass",
            },
        ),
        (
            LEGACY_SAMPLE_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "sample_kind": "cold",
                "sample_index": 1,
                "cache_control": "process_only",
                "source_identity": {},
                "source_identity_digest": "sha256:source",
                "host_identity": {},
                "command": ["./scripts/check-mainline.sh"],
                "process_result": {},
                "functional_green": True,
            },
        ),
        (
            LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "source_identity_digest": "sha256:source",
                "stages": [],
                "terminal_status": "pass",
            },
        ),
        (
            OPTIMIZED_SAMPLE_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "sample_kind": "cold",
                "sample_index": 1,
                "cache_control": "process_only",
                "source_identity": {},
                "source_identity_digest": "sha256:source",
                "source_recheck_digest": "sha256:source",
                "source_drift": False,
                "host_identity": {},
                "worker_policy": {"workers": 3},
                "plan_digest": "sha256:plan",
                "receipt_digest": "sha256:receipt",
                "terminal_status": "pass",
                "functional_green": True,
                "timing": {},
                "coverage": {},
                "host_activity": {},
            },
        ),
        (
            PYTEST_OBSERVATION_BINDING_SCHEMA_ID,
            {
                "invocation_id": "invocation-1",
                "source_identity": {},
                "source_identity_digest": "sha256:source",
                "observation_self_digest": "sha256:observation",
                "observation_document_digest": "sha256:document",
                "collection_digest": "sha256:collection",
                "pytest_argv": ["pytest"],
                "binding_basis": "frozen_source_recheck",
            },
        ),
        (
            PHASE0_BASELINE_SCHEMA_ID,
            {
                "phase_id": "phase0",
                "source_identity_digest": "sha256:source",
                "host_identity": {},
                "toolchain_identity": {},
                "cache_control": "process_only",
                "legacy_baseline": {},
                "stage_breakdown": [],
                "collection_closure": {},
                "node_critical_paths": {},
                "duplicate_node_cost": {},
                "critical_path_assessment": {},
                "raw_evidence": {},
            },
        ),
        (
            REPLAY_CORPUS_SCHEMA_ID,
            {
                "corpus_id": "corpus-1",
                "equivalence_basis": "explicitly agreed immutable replay",
                "cases": [],
            },
        ),
    )


@pytest.mark.parametrize(("schema_id", "fields"), _sample_documents())
def test_each_evidence_type_has_one_strict_canonical_round_trip(
    schema_id: str,
    fields: dict[str, object],
) -> None:
    document = seal_document(schema_id, fields)
    encoded = canonical_document_bytes(document)

    assert encoded.endswith(b"\n")
    assert load_canonical_document_bytes(encoded) == document
    assert document["self_digest"].startswith("sha256:")


def test_duplicate_json_keys_are_rejected_before_schema_interpretation() -> None:
    with pytest.raises(EvidenceModelError, match="duplicate JSON object key"):
        load_canonical_document_bytes(
            b'{"schema_id":"one","schema_id":"two"}\n'
        )


def test_unknown_schema_version_and_fields_fail_closed() -> None:
    with pytest.raises(EvidenceModelError, match="unknown evidence schema"):
        seal_document("openzyme_test_gate_receipt@2", {})
    with pytest.raises(EvidenceModelError, match="unknown fields"):
        seal_document(
            RECEIPT_SCHEMA_ID,
            {
                **dict(_sample_documents()[3][1]),
                "product_session_id": "forbidden",
            },
        )


def test_digest_tampering_and_noncanonical_aliases_are_rejected() -> None:
    schema_id, fields = _sample_documents()[3]
    document = seal_document(schema_id, fields)
    tampered = dict(document)
    tampered["terminal_status"] = "fail"
    with pytest.raises(EvidenceModelError, match="self_digest mismatch"):
        load_canonical_document_bytes(canonical_document_bytes(tampered))

    noncanonical = json.dumps(document, sort_keys=False).encode("utf-8") + b"\n"
    with pytest.raises(
        EvidenceModelError,
        match="unique canonical representation",
    ):
        load_canonical_document_bytes(noncanonical)


def test_nonfinite_numbers_are_rejected() -> None:
    schema_id, fields = _sample_documents()[4]
    with pytest.raises(EvidenceModelError, match="non-finite"):
        seal_document(schema_id, {**fields, "statistics": {"median": float("nan")}})
