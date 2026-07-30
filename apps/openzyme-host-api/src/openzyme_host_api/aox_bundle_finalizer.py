from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from openzyme_core import EngineDocumentRecord
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificSelectionState
from openzyme_domain.control_plane import utc_now_iso
from openzyme_pipeline import aox_candidate
from openzyme_pipeline import aox_finalization
from openzyme_runtime import ArtifactBoundaryError

from .aox_final_deliverable_validation import (
    S15_AOX_HMM_FIXED_DELIVERABLES,
)
from .aox_final_deliverable_validation import validate_aox_final_artifacts


AOX_FINALIZATION_DOCUMENT_KIND = "aox_final_deliverable_validation_receipt"
_REQUEST_KEYS = {
    "profile_id",
    "attempt_id",
    "selection_id",
    "execution_task_id",
    "items",
    "calculation_receipts",
}
_ITEM_KEYS = {
    "path",
    "relative_path",
    "kind",
    "format",
    "validation_profile",
    "metadata",
}
_FINALIZATION_RECEIPT_KEYS = {
    "schema_id",
    "calculation_id",
    "calculation_contract_digest",
    "calculation_implementation_digest",
    "serializer_id",
    "deliverable_paths",
    "deliverable_path_digest",
}


class AoxBundleFinalizationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.public_message = message
        self.details = dict(details or {})
        self.hint = (
            "Correct the exact typed calculation or complete 17-file draft "
            "preimage, then submit one new source-bound finalization request."
        )
        self.retryable = False
        self.stage = "aox_finalization"


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise AoxBundleFinalizationError(
            "aox_finalization_payload_invalid",
            "AOX finalization payload is not canonical JSON",
        ) from exc


def _digest(payload: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"


def _value(value: object) -> str:
    return str(getattr(value, "value", value) or "")


def _require_bound_runtime(
    *,
    repositories: Any,
    session_id: str,
    sandbox_workspace_id: str,
    sandbox_run_id: str,
    agent_id: str,
    task_id: str | None,
    lane_id: str | None,
    source_snapshot_artifact_id: str,
    source_tree_digest: str,
    attempt_id: str,
    selection_id: str,
    execution_task_id: str,
) -> tuple[object, object]:
    task = repositories.tasks.get(execution_task_id)
    attempt = repositories.scientific_attempts.get(attempt_id)
    selection = repositories.scientific_selections.get(selection_id)
    run = repositories.sandbox_runs.get(sandbox_run_id)
    if (
        task is None
        or getattr(task, "session_id", None) != session_id
        or task_id != execution_task_id
        or getattr(task, "assigned_ref", None) != agent_id
        or attempt is None
        or attempt.session_id != session_id
        or attempt.task_id != execution_task_id
        or attempt.lane_id != lane_id
        or attempt.scope is not ScientificAttemptScope.FORMAL
        or attempt.status is not ScientificAttemptStatus.ACTIVE
        or selection is None
        or selection.attempt_id != attempt_id
        or selection.state is not ScientificSelectionState.SEALED
        or selection.actor_ref != agent_id
        or selection.workflow_contract_digest
        != attempt.workflow_contract_digest
        or run is None
        or getattr(run, "session_id", None) != session_id
        or getattr(run, "sandbox_workspace_id", None)
        != sandbox_workspace_id
        or getattr(run, "agent_id", None) != agent_id
        or getattr(run, "task_id", None) != execution_task_id
        or getattr(run, "lane_id", None) != lane_id
        or getattr(run, "source_snapshot_artifact_id", None)
        != source_snapshot_artifact_id
        or getattr(run, "source_tree_digest", None) != source_tree_digest
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_source_binding_invalid",
            "AOX finalization identities do not close over one active formal execution",
            details={
                "session_id": session_id,
                "attempt_id": attempt_id,
                "selection_id": selection_id,
                "execution_task_id": execution_task_id,
                "sandbox_run_id": sandbox_run_id,
            },
        )
    return attempt, selection


def _calculation_receipts(
    value: object,
) -> dict[str, dict[str, object]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_calculation_receipt_invalid",
            "AOX finalization calculation receipts must be a JSON object list",
        )
    receipts: dict[str, dict[str, object]] = {}
    for raw in value:
        receipt = dict(raw)
        calculation_id = receipt.get("calculation_id")
        if not isinstance(calculation_id, str) or not calculation_id:
            raise AoxBundleFinalizationError(
                "aox_finalization_calculation_receipt_invalid",
                "AOX calculation receipt lacks a calculation id",
            )
        if calculation_id in receipts:
            raise AoxBundleFinalizationError(
                "aox_finalization_calculation_receipt_duplicate",
                "AOX finalization contains a duplicate calculation receipt",
                details={"calculation_id": calculation_id},
            )
        receipts[calculation_id] = receipt
    allowed = {
        aox_candidate.CALCULATION_ID,
        aox_finalization.FINALIZATION_CALCULATION_ID,
        aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID,
        aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
        aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID,
    }
    unexpected = sorted(set(receipts) - allowed)
    if unexpected:
        raise AoxBundleFinalizationError(
            "aox_finalization_calculation_receipt_unknown",
            (
                "AOX finalization rejects uninstalled calculation identities "
                "and source-snapshot implementation substitutes"
            ),
            details={"calculation_ids": unexpected},
        )
    return receipts


def required_aox_conditional_output_paths(
    validation: Mapping[str, object],
) -> dict[str, str]:
    candidate_count = validation.get("candidate_count")
    branch = str(validation.get("scientific_branch") or "")
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 0
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_validation_projection_invalid",
            "AOX validator returned an invalid candidate count",
        )
    if candidate_count > 0:
        if branch != "nonempty":
            raise AoxBundleFinalizationError(
                "aox_finalization_validation_projection_invalid",
                "AOX non-empty candidate count has an inconsistent branch",
            )
        return {}
    expected: dict[str, str] = {
        aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID: (
            "aox_hmm/AOX_candidates_cdhit85.clusters.csv"
        )
    }
    if branch in {"hmmer_upstream_empty", "length_filter_empty"}:
        expected[
            aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID
        ] = "aox_hmm/AOX_scoring_alignment.fasta"
    if branch == "hmmer_upstream_empty":
        expected[
            aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
        ] = "aox_hmm/target.fasta"
    if branch not in {
        "hmmer_upstream_empty",
        "length_filter_empty",
        "motif_filter_empty",
    }:
        raise AoxBundleFinalizationError(
            "aox_finalization_validation_projection_invalid",
            "AOX zero-candidate validator branch is not installed",
            details={"scientific_branch": branch},
        )
    return expected


def _verify_calculation_receipts(
    *,
    receipts: dict[str, dict[str, object]],
    drafts_by_path: Mapping[str, object],
    validation: Mapping[str, object],
) -> None:
    candidate = receipts.get(aox_candidate.CALCULATION_ID)
    finalization = receipts.get(aox_finalization.FINALIZATION_CALCULATION_ID)
    try:
        if candidate is None:
            raise ValueError("candidate receipt missing")
        aox_candidate.validate_calculation_receipt(candidate)
        expected_candidate = aox_candidate.filter_motif_candidates(
            getattr(drafts_by_path["aox_hmm/target.fasta"], "content"),
            getattr(
                drafts_by_path["aox_hmm/scored_ref_plus_hits.csv"],
                "content",
            ),
        ).calculation_receipt()
    except Exception as exc:
        raise AoxBundleFinalizationError(
            "aox_finalization_candidate_receipt_invalid",
            "AOX candidate receipt is not an exact installed calculation result",
        ) from exc
    if (
        candidate != expected_candidate
        or candidate.get("candidate_count")
        != validation.get("candidate_count")
        or finalization is None
        or set(finalization) != _FINALIZATION_RECEIPT_KEYS
        or finalization
        != aox_finalization.finalization_calculation_receipt()
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_calculation_receipt_invalid",
            "AOX finalization lacks the exact installed candidate/finalizer receipts",
        )
    if (
        candidate.get("output_digest")
        != getattr(
            drafts_by_path["aox_hmm/AOX_candidates.fasta"],
            "content_digest",
        )
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_candidate_receipt_mismatch",
            "candidate calculation receipt does not bind the validated drafts",
        )

    expected_output_paths = required_aox_conditional_output_paths(validation)
    required_empty = set(expected_output_paths)
    observed_empty = set(receipts).intersection(
        aox_finalization.CALCULATION_CONTRACT_DIGESTS
    ) - {aox_finalization.FINALIZATION_CALCULATION_ID}
    if observed_empty != required_empty:
        raise AoxBundleFinalizationError(
            "aox_finalization_conditional_empty_receipt_set_invalid",
            "conditional-empty receipts do not equal the validated scientific branch",
            details={
                "expected": sorted(required_empty),
                "observed": sorted(observed_empty),
            },
        )
    for calculation_id in sorted(required_empty):
        receipt = receipts[calculation_id]
        output_path = expected_output_paths[calculation_id]
        try:
            source = receipt.get("source_calculation")
            if not isinstance(source, dict):
                raise ValueError("conditional source missing")
            if (
                calculation_id
                == aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
            ):
                expected_result = (
                    aox_finalization.materialize_upstream_empty(source)
                )
                if source.get("output_digest") != getattr(
                    drafts_by_path[
                        "aox_hmm/hmmer_score_filtered_accessions.csv"
                    ],
                    "content_digest",
                ):
                    raise ValueError("HMMER zero receipt output drifted")
            elif (
                calculation_id
                == aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID
            ):
                expected_result = (
                    aox_finalization.materialize_reference_only_alignment(
                        getattr(
                            drafts_by_path[
                                "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta"
                            ],
                            "content",
                        ),
                        source,
                    )
                )
                if (
                    source.get("calculation_id")
                    == aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                    and source
                    != receipts.get(
                        aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                    )
                ):
                    raise ValueError("upstream conditional source drifted")
                if (
                    source.get("calculation_id")
                    != aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                    and source.get("output_digest")
                    != getattr(
                        drafts_by_path["aox_hmm/target.fasta"],
                        "content_digest",
                    )
                ):
                    raise ValueError("sequence-join zero receipt drifted")
            else:
                expected_result = (
                    aox_finalization.materialize_empty_membership(source)
                )
                if source != candidate:
                    raise ValueError("candidate zero source drifted")
            expected_receipt = expected_result.calculation_receipt()
            if (
                receipt != expected_receipt
                or receipt.get("output_digest")
                != getattr(drafts_by_path[output_path], "content_digest")
            ):
                raise ValueError("conditional output drifted")
        except Exception as exc:
            raise AoxBundleFinalizationError(
                "aox_finalization_conditional_empty_receipt_invalid",
                "conditional-empty receipt does not bind its exact installed calculation",
                details={"calculation_id": calculation_id},
            ) from exc


def _bounded_response(payload: Mapping[str, object]) -> dict[str, object]:
    validation = dict(payload["validation"])
    return {
        "schema_id": aox_finalization.FINALIZATION_RECEIPT_SCHEMA_ID,
        "status": "passed",
        "receipt_id": payload["receipt_id"],
        "receipt_digest": payload["receipt_digest"],
        "bundle_digest": payload["bundle_digest"],
        "artifact_refs": [
            {
                "artifact_id": item["artifact_id"],
                "content_digest": item["content_digest"],
                "relative_path": item["relative_path"],
            }
            for item in payload["artifacts"]
        ],
        "validation": {
            "passed": True,
            "error_count": len(validation.get("errors") or []),
            "errors_digest": validation["errors_digest"],
            "earliest_error_code": validation["earliest_error_code"],
        },
    }


def validate_persisted_aox_finalization_receipt(
    repositories: Any,
    *,
    session_id: str,
    execution_task_id: str,
    receipt_id: str | None = None,
    attempt_id: str | None = None,
    selection_id: str | None = None,
) -> dict[str, object]:
    documents = [
        document
        for document in repositories.engine_documents.list_by_session(session_id)
        if document.document_kind == AOX_FINALIZATION_DOCUMENT_KIND
        and dict(document.payload or {}).get("execution_task_id")
        == execution_task_id
        and (
            receipt_id is None
            or document.document_id == receipt_id
        )
        and (
            attempt_id is None
            or dict(document.payload or {}).get("attempt_id") == attempt_id
        )
        and (
            selection_id is None
            or dict(document.payload or {}).get("selection_id") == selection_id
        )
    ]
    if len(documents) != 1:
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_cardinality_invalid",
            "AOX terminal progression requires one exact validation receipt",
            details={"receipt_count": len(documents)},
        )
    document = documents[0]
    payload = dict(document.payload or {})
    expected_keys = {
        "schema_id",
        "status",
        "receipt_id",
        "receipt_digest",
        "bundle_digest",
        "session_id",
        "execution_task_id",
        "agent_id",
        "attempt_id",
        "selection_id",
        "sandbox_workspace_id",
        "sandbox_run_id",
        "source_snapshot_artifact_id",
        "source_tree_digest",
        "artifacts",
        "calculation_receipts",
        "validation_metadata",
        "validation",
    }
    payload_without_digest = dict(payload)
    observed_receipt_digest = payload_without_digest.pop(
        "receipt_digest", None
    )
    artifacts = payload.get("artifacts")
    validation = payload.get("validation")
    if (
        set(payload) != expected_keys
        or document.document_id != payload.get("receipt_id")
        or payload.get("schema_id")
        != aox_finalization.FINALIZATION_RECEIPT_SCHEMA_ID
        or payload.get("status") != "passed"
        or payload.get("session_id") != session_id
        or payload.get("execution_task_id") != execution_task_id
        or not isinstance(payload.get("agent_id"), str)
        or not payload.get("agent_id")
        or (receipt_id is not None and document.document_id != receipt_id)
        or (attempt_id is not None and payload.get("attempt_id") != attempt_id)
        or (
            selection_id is not None
            and payload.get("selection_id") != selection_id
        )
        or observed_receipt_digest != _digest(payload_without_digest)
        or not isinstance(validation, dict)
        or validation.get("passed") is not True
        or not isinstance(artifacts, list)
        or len(artifacts) != len(S15_AOX_HMM_FIXED_DELIVERABLES)
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_invalid",
            "persisted AOX validation receipt failed its closed identity check",
        )
    paths: set[str] = set()
    artifacts_by_path: dict[str, object] = {}
    for raw_ref in artifacts:
        if not isinstance(raw_ref, dict) or set(raw_ref) != {
            "artifact_id",
            "relative_path",
            "content_digest",
        }:
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_artifact_invalid",
                "AOX validation receipt contains an invalid artifact ref",
            )
        path = str(raw_ref["relative_path"])
        artifact = repositories.artifacts.get(str(raw_ref["artifact_id"]))
        metadata = {} if artifact is None else dict(artifact.metadata or {})
        if (
            path in paths
            or path not in S15_AOX_HMM_FIXED_DELIVERABLES
            or artifact is None
            or artifact.session_id != session_id
            or artifact.relative_path != path
            or metadata.get("content_digest") != raw_ref["content_digest"]
            or metadata.get("aox_finalization_receipt_id")
            != document.document_id
            or metadata.get("aox_finalization_bundle_digest")
            != payload.get("bundle_digest")
            or metadata.get("aox_finalization_attempt_id")
            != payload.get("attempt_id")
            or metadata.get("aox_finalization_selection_id")
            != payload.get("selection_id")
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_artifact_drift",
                "persisted AOX receipt no longer closes over its artifact set",
                details={"relative_path": path},
            )
        paths.add(path)
        artifacts_by_path[path] = artifact
    if paths != S15_AOX_HMM_FIXED_DELIVERABLES:
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_artifact_drift",
            "persisted AOX receipt artifact paths are incomplete",
        )
    run = repositories.sandbox_runs.get(str(payload["sandbox_run_id"]))
    source = repositories.artifacts.get(
        str(payload["source_snapshot_artifact_id"])
    )
    source_metadata = {} if source is None else dict(source.metadata or {})
    if (
        run is None
        or getattr(run, "session_id", None) != session_id
        or getattr(run, "sandbox_workspace_id", None)
        != payload.get("sandbox_workspace_id")
        or getattr(run, "source_snapshot_artifact_id", None)
        != payload.get("source_snapshot_artifact_id")
        or getattr(run, "source_tree_digest", None)
        != payload.get("source_tree_digest")
        or getattr(run, "task_id", None) != execution_task_id
        or getattr(run, "agent_id", None) != payload.get("agent_id")
        or source is None
        or source.session_id != session_id
        or _value(getattr(source, "kind", None)) != "code"
        or source_metadata.get("semantic_type")
        != "pipeline_source_snapshot"
        or source_metadata.get("format") != "source_tree"
        or source_metadata.get("sandbox_workspace_id")
        != payload.get("sandbox_workspace_id")
        or source_metadata.get("source_tree_digest")
        != payload.get("source_tree_digest")
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_source_drift",
            "persisted AOX receipt source binding drifted",
        )
    receipts = _calculation_receipts(payload.get("calculation_receipts"))
    if (
        receipts.get(aox_candidate.CALCULATION_ID, {}).get(
            "calculation_contract_digest"
        )
        != aox_candidate.CONTRACT_DIGEST
        or receipts.get(aox_candidate.CALCULATION_ID, {}).get(
            "calculation_implementation_digest"
        )
        != aox_candidate.IMPLEMENTATION_DIGEST
        or receipts.get(aox_finalization.FINALIZATION_CALCULATION_ID)
        != aox_finalization.finalization_calculation_receipt()
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_calculation_drift",
            "persisted AOX receipt calculation identity drifted",
        )
    conditional_ids = set(receipts).intersection(
        {
            aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID,
            aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
            aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID,
        }
    )
    try:
        for calculation_id in conditional_ids:
            aox_finalization.validate_conditional_receipt(
                receipts[calculation_id]
            )
    except Exception as exc:
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_calculation_drift",
            "persisted AOX conditional calculation identity drifted",
        ) from exc
    validation_metadata = payload.get("validation_metadata")
    if (
        not isinstance(validation_metadata, dict)
        or set(validation_metadata) != S15_AOX_HMM_FIXED_DELIVERABLES
        or not all(
            isinstance(value, dict) for value in validation_metadata.values()
        )
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_validation_metadata_invalid",
            "persisted AOX receipt lacks its exact validator metadata preimage",
        )
    artifact_ref_by_path = {
        str(item["relative_path"]): item
        for item in artifacts
        if isinstance(item, dict) and "relative_path" in item
    }
    for path, expected_metadata in validation_metadata.items():
        artifact_ref = artifact_ref_by_path.get(path)
        artifact = (
            None
            if artifact_ref is None
            else repositories.artifacts.get(str(artifact_ref["artifact_id"]))
        )
        artifact_metadata = (
            {} if artifact is None else dict(artifact.metadata or {})
        )
        if any(
            artifact_metadata.get(key) != value
            for key, value in expected_metadata.items()
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_validation_metadata_drift",
                "persisted AOX validator metadata no longer matches the catalog",
                details={"relative_path": path},
            )
    errors = validation.get("errors")
    if (
        errors != []
        or validation.get("earliest_error") is not None
        or validation.get("earliest_error_code") is not None
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_validation_drift",
            "persisted AOX passed receipt contains a causal validation error",
        )
    candidate = receipts.get(aox_candidate.CALCULATION_ID)
    try:
        if candidate is None:
            raise ValueError("candidate receipt missing")
        aox_candidate.validate_calculation_receipt(candidate)
    except Exception as exc:
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_calculation_drift",
            "persisted AOX candidate calculation identity drifted",
        ) from exc

    def content_digest(path: str) -> object:
        return artifact_ref_by_path[path]["content_digest"]

    if (
        candidate.get("target_input_digest")
        != content_digest("aox_hmm/target.fasta")
        or candidate.get("scoring_input_digest")
        != content_digest("aox_hmm/scored_ref_plus_hits.csv")
        or candidate.get("output_digest")
        != content_digest("aox_hmm/AOX_candidates.fasta")
        or candidate.get("candidate_count")
        != validation.get("candidate_count")
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_calculation_drift",
            "persisted AOX candidate receipt no longer binds its artifacts",
        )
    expected_conditional = required_aox_conditional_output_paths(validation)
    if conditional_ids != set(expected_conditional):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_calculation_drift",
            "persisted AOX conditional receipt set drifted from its branch",
        )
    for calculation_id, output_path in expected_conditional.items():
        conditional = receipts[calculation_id]
        source_calculation = conditional.get("source_calculation")
        if (
            conditional.get("output_digest") != content_digest(output_path)
            or not isinstance(source_calculation, dict)
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_calculation_drift",
                "persisted AOX conditional receipt output drifted",
                details={"calculation_id": calculation_id},
            )
        if (
            calculation_id
            == aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID
            and source_calculation != candidate
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_calculation_drift",
                "persisted AOX empty membership source drifted",
            )
        if (
            calculation_id
            == aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
            and source_calculation.get("output_digest")
            != content_digest(
                "aox_hmm/hmmer_score_filtered_accessions.csv"
            )
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_calculation_drift",
                "persisted AOX upstream-empty source drifted",
            )
        if (
            calculation_id
            == aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID
        ):
            source_calculation_id = source_calculation.get("calculation_id")
            if (
                source_calculation_id
                == aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                and source_calculation
                != receipts.get(
                    aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                )
            ) or (
                source_calculation_id
                != aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                and source_calculation.get("output_digest")
                != content_digest("aox_hmm/target.fasta")
            ):
                raise AoxBundleFinalizationError(
                    "aox_finalization_receipt_calculation_drift",
                    "persisted AOX reference-only source drifted",
                )

    attempt = repositories.scientific_attempts.get(str(payload["attempt_id"]))
    selection = repositories.scientific_selections.get(
        str(payload["selection_id"])
    )
    task = repositories.tasks.get(execution_task_id)
    if (
        task is None
        or getattr(task, "session_id", None) != session_id
        or getattr(task, "assigned_ref", None) != payload.get("agent_id")
        or attempt is None
        or attempt.session_id != session_id
        or attempt.task_id != execution_task_id
        or attempt.scope is not ScientificAttemptScope.FORMAL
        or attempt.status
        not in {
            ScientificAttemptStatus.ACTIVE,
            ScientificAttemptStatus.CLOSING,
            ScientificAttemptStatus.CLOSED,
        }
        or selection is None
        or selection.attempt_id != attempt.attempt_id
        or selection.state is not ScientificSelectionState.SEALED
        or selection.actor_ref != payload.get("agent_id")
        or selection.workflow_contract_digest
        != attempt.workflow_contract_digest
        or getattr(run, "lane_id", None) != attempt.lane_id
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_lifecycle_drift",
            "persisted AOX receipt no longer binds its formal lifecycle",
        )
    bundle_preimage = {
        "schema_id": aox_finalization.FINAL_BUNDLE_PROFILE_ID,
        "session_id": session_id,
        "execution_task_id": execution_task_id,
        "agent_id": payload["agent_id"],
        "attempt_id": payload["attempt_id"],
        "selection_id": payload["selection_id"],
        "sandbox_workspace_id": payload["sandbox_workspace_id"],
        "sandbox_run_id": payload["sandbox_run_id"],
        "source_snapshot_artifact_id": payload[
            "source_snapshot_artifact_id"
        ],
        "source_tree_digest": payload["source_tree_digest"],
        "items": [
            {
                "relative_path": path,
                "content_digest": content_digest(path),
                "kind": _value(getattr(artifacts_by_path[path], "kind", None)),
                "metadata_digest": _digest(validation_metadata[path]),
            }
            for path in sorted(artifacts_by_path)
        ],
        "calculation_receipts": [
            receipts[key] for key in sorted(receipts)
        ],
        "validation_digest": _digest(validation),
    }
    if payload.get("bundle_digest") != _digest(bundle_preimage):
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_bundle_drift",
            "persisted AOX receipt bundle digest drifted",
        )
    return payload


def finalize_aox_deliverable_bundle(
    *,
    repositories: Any,
    artifact_boundary_service: Any,
    session_id: str,
    sandbox_workspace_id: str,
    sandbox_run_id: str,
    agent_id: str,
    task_id: str | None,
    lane_id: str | None,
    source_snapshot_artifact_id: str,
    source_tree_digest: str,
    params: Mapping[str, object],
) -> dict[str, object]:
    if set(params) != _REQUEST_KEYS or params.get(
        "profile_id"
    ) != aox_finalization.FINAL_BUNDLE_PROFILE_ID:
        raise AoxBundleFinalizationError(
            "aox_finalization_request_invalid",
            "AOX finalization request does not match its closed profile",
        )
    attempt_id = str(params.get("attempt_id") or "")
    selection_id = str(params.get("selection_id") or "")
    execution_task_id = str(params.get("execution_task_id") or "")
    _require_bound_runtime(
        repositories=repositories,
        session_id=session_id,
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id=sandbox_run_id,
        agent_id=agent_id,
        task_id=task_id,
        lane_id=lane_id,
        source_snapshot_artifact_id=source_snapshot_artifact_id,
        source_tree_digest=source_tree_digest,
        attempt_id=attempt_id,
        selection_id=selection_id,
        execution_task_id=execution_task_id,
    )
    raw_items = params.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != len(
        aox_finalization.FIXED_DELIVERABLE_PATHS
    ):
        raise AoxBundleFinalizationError(
            "aox_finalization_deliverable_set_invalid",
            "AOX finalization requires exactly 17 draft items",
        )
    drafts_by_path: dict[str, object] = {}
    items_by_path: dict[str, dict[str, object]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or set(raw_item) != _ITEM_KEYS:
            raise AoxBundleFinalizationError(
                "aox_finalization_item_invalid",
                "AOX finalization item does not match its closed schema",
            )
        item = dict(raw_item)
        relative_path = str(item.get("relative_path") or "")
        if relative_path in items_by_path:
            raise AoxBundleFinalizationError(
                "aox_finalization_deliverable_set_invalid",
                "AOX finalization contains a duplicate deliverable path",
            )
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            raise AoxBundleFinalizationError(
                "aox_finalization_item_invalid",
                "AOX finalization item metadata must be an object",
            )
        try:
            draft = artifact_boundary_service.read_registration_draft(
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                path=str(item.get("path") or ""),
                kind=str(item.get("kind") or ""),
                format=str(item.get("format") or ""),
                validation_profile=(
                    None
                    if item.get("validation_profile") is None
                    else str(item["validation_profile"])
                ),
                metadata=dict(metadata),
                source_snapshot_artifact_id=source_snapshot_artifact_id,
            )
        except ArtifactBoundaryError as exc:
            raise AoxBundleFinalizationError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc
        if (
            draft.relative_path != relative_path
            or relative_path not in S15_AOX_HMM_FIXED_DELIVERABLES
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_path_invalid",
                "AOX finalization public and relative paths disagree",
                details={"relative_path": relative_path},
            )
        drafts_by_path[relative_path] = draft
        items_by_path[relative_path] = item
    if set(drafts_by_path) != S15_AOX_HMM_FIXED_DELIVERABLES:
        raise AoxBundleFinalizationError(
            "aox_finalization_deliverable_set_invalid",
            "AOX finalization draft set differs from the exact 17 deliverables",
        )
    try:
        artifact_text = {
            path: getattr(draft, "content").decode("utf-8")
            for path, draft in drafts_by_path.items()
        }
    except UnicodeDecodeError as exc:
        raise AoxBundleFinalizationError(
            "aox_finalization_artifact_encoding_invalid",
            "AOX normalized deliverables must be UTF-8 text",
            details={"start": exc.start},
        ) from exc
    metadata_by_path = {
        path: dict(getattr(draft, "metadata"))
        for path, draft in drafts_by_path.items()
    }
    validation = validate_aox_final_artifacts(
        set(drafts_by_path),
        artifact_text,
        metadata_by_path,
    )
    if validation.get("passed") is not True:
        errors = list(validation.get("errors") or [])
        raise AoxBundleFinalizationError(
            "aox_final_deliverable_validation_failed",
            "AOX final deliverable prevalidation failed",
            details={
                "error_count": len(errors),
                "errors_digest": validation.get("errors_digest"),
                "earliest_error": validation.get("earliest_error"),
                "earliest_error_code": validation.get(
                    "earliest_error_code"
                ),
            },
        )
    receipts = _calculation_receipts(params.get("calculation_receipts"))
    _verify_calculation_receipts(
        receipts=receipts,
        drafts_by_path=drafts_by_path,
        validation=validation,
    )
    bundle_preimage = {
        "schema_id": aox_finalization.FINAL_BUNDLE_PROFILE_ID,
        "session_id": session_id,
        "execution_task_id": execution_task_id,
        "agent_id": agent_id,
        "attempt_id": attempt_id,
        "selection_id": selection_id,
        "sandbox_workspace_id": sandbox_workspace_id,
        "sandbox_run_id": sandbox_run_id,
        "source_snapshot_artifact_id": source_snapshot_artifact_id,
        "source_tree_digest": source_tree_digest,
        "items": [
            {
                "relative_path": path,
                "content_digest": getattr(drafts_by_path[path], "content_digest"),
                "kind": _value(getattr(drafts_by_path[path], "kind")),
                "metadata_digest": _digest(metadata_by_path[path]),
            }
            for path in sorted(drafts_by_path)
        ],
        "calculation_receipts": [
            receipts[key] for key in sorted(receipts)
        ],
        "validation_digest": _digest(validation),
    }
    bundle_digest = _digest(bundle_preimage)
    receipt_id = f"aox_finalization_{bundle_digest[7:39]}"
    existing = repositories.engine_documents.get(receipt_id)
    if existing is not None:
        existing_payload = dict(existing.payload or {})
        if (
            existing.session_id != session_id
            or existing.document_kind != AOX_FINALIZATION_DOCUMENT_KIND
            or existing_payload.get("bundle_digest") != bundle_digest
            or existing_payload.get("receipt_id") != receipt_id
        ):
            raise AoxBundleFinalizationError(
                "aox_finalization_receipt_identity_conflict",
                "AOX finalization receipt identity already has different facts",
            )
        validated = validate_persisted_aox_finalization_receipt(
            repositories,
            session_id=session_id,
            execution_task_id=execution_task_id,
            receipt_id=receipt_id,
            attempt_id=attempt_id,
            selection_id=selection_id,
        )
        return _bounded_response(validated)

    artifacts: list[dict[str, object]] = []
    now = utc_now_iso()
    try:
        with repositories.atomic(prefix="aox_final_deliverable_bundle"):
            for path in sorted(drafts_by_path):
                item = items_by_path[path]
                metadata = {
                    **metadata_by_path[path],
                    "aox_finalization_profile_id": (
                        aox_finalization.FINAL_BUNDLE_PROFILE_ID
                    ),
                    "aox_finalization_receipt_id": receipt_id,
                    "aox_finalization_bundle_digest": bundle_digest,
                    "aox_finalization_attempt_id": attempt_id,
                    "aox_finalization_selection_id": selection_id,
                }
                registered = artifact_boundary_service.register(
                    session_id=session_id,
                    sandbox_workspace_id=sandbox_workspace_id,
                    path=str(item["path"]),
                    kind=str(item["kind"]),
                    format=str(item["format"]),
                    validation_profile=(
                        None
                        if item["validation_profile"] is None
                        else str(item["validation_profile"])
                    ),
                    _resolved_metadata=metadata,
                    source_snapshot_artifact_id=source_snapshot_artifact_id,
                    run_id=sandbox_run_id,
                )
                if (
                    registered.content_digest
                    != getattr(drafts_by_path[path], "content_digest")
                    or registered.tree_digest is not None
                ):
                    raise AoxBundleFinalizationError(
                        "aox_finalization_artifact_digest_drift",
                        "AOX draft changed between prevalidation and commit",
                        details={"relative_path": path},
                    )
                artifacts.append(
                    {
                        "artifact_id": registered.artifact.artifact_id,
                        "relative_path": path,
                        "content_digest": registered.content_digest,
                    }
                )
            payload_without_digest: dict[str, object] = {
                "schema_id": (
                    aox_finalization.FINALIZATION_RECEIPT_SCHEMA_ID
                ),
                "status": "passed",
                "receipt_id": receipt_id,
                "bundle_digest": bundle_digest,
                "session_id": session_id,
                "execution_task_id": execution_task_id,
                "agent_id": agent_id,
                "attempt_id": attempt_id,
                "selection_id": selection_id,
                "sandbox_workspace_id": sandbox_workspace_id,
                "sandbox_run_id": sandbox_run_id,
                "source_snapshot_artifact_id": (
                    source_snapshot_artifact_id
                ),
                "source_tree_digest": source_tree_digest,
                "artifacts": artifacts,
                "calculation_receipts": [
                    receipts[key] for key in sorted(receipts)
                ],
                "validation_metadata": {
                    path: metadata_by_path[path]
                    for path in sorted(metadata_by_path)
                },
                "validation": validation,
            }
            payload = {
                **payload_without_digest,
                "receipt_digest": _digest(payload_without_digest),
            }
            repositories.engine_documents.save(
                EngineDocumentRecord(
                    document_id=receipt_id,
                    session_id=session_id,
                    document_kind=AOX_FINALIZATION_DOCUMENT_KIND,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                    invocation_id=None,
                )
            )
    except AoxBundleFinalizationError:
        raise
    except ArtifactBoundaryError as exc:
        raise AoxBundleFinalizationError(
            exc.error_code,
            str(exc),
            details=exc.details,
        ) from exc
    except Exception as exc:
        raise AoxBundleFinalizationError(
            "aox_finalization_atomic_commit_failed",
            "AOX final deliverable transaction failed and was rolled back",
        ) from exc
    persisted = repositories.engine_documents.get(receipt_id)
    if persisted is None:
        raise AoxBundleFinalizationError(
            "aox_finalization_receipt_missing",
            "AOX finalization transaction returned without its receipt",
        )
    return _bounded_response(dict(persisted.payload or {}))


__all__ = [
    "AOX_FINALIZATION_DOCUMENT_KIND",
    "AoxBundleFinalizationError",
    "finalize_aox_deliverable_bundle",
    "required_aox_conditional_output_paths",
    "validate_persisted_aox_finalization_receipt",
]
