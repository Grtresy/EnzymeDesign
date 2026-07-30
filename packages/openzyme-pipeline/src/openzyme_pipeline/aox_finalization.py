from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import aox_candidate
from . import aox_hmmer
from . import aox_sequence_join
from .aox_motif import ScientificPrerequisiteError
from .client import PipelineSdkError, call


FINAL_BUNDLE_PROFILE_ID = "aox_final_deliverable_bundle@1"
FINALIZATION_RECEIPT_SCHEMA_ID = "aox_final_deliverable_validation_receipt@1"
FINALIZATION_CALCULATION_ID = "aox_final_deliverable_normalization@1"
FINALIZATION_CALCULATION_RESULT_SCHEMA_ID = (
    "aox_final_deliverable_normalization_result@1"
)
UPSTREAM_EMPTY_CALCULATION_ID = "aox_upstream_empty_materialization@1"
REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID = (
    "aox_reference_only_scoring_alignment@1"
)
EMPTY_MEMBERSHIP_CALCULATION_ID = "aox_empty_membership@1"
CONDITIONAL_EMPTY_RESULT_SCHEMA_ID = "aox_conditional_empty_result@1"
ZERO_SOURCE_RECEIPT_SCHEMA_ID = "aox_zero_calculation_source_receipt@1"

FIXED_DELIVERABLE_PATHS = (
    "aox_hmm/AOX_candidates.fasta",
    "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
    "aox_hmm/AOX_candidates_cdhit85.fasta",
    "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
    "aox_hmm/AOX_ref.hmm",
    "aox_hmm/AOX_ref21.fasta",
    "aox_hmm/AOX_scoring_input.fasta",
    "aox_hmm/AOX_scoring_alignment.fasta",
    "aox_hmm/edges_similarity.csv",
    "aox_hmm/execution_summary.json",
    "aox_hmm/hits_len650_700_200.csv",
    "aox_hmm/hits_raw.csv",
    "aox_hmm/hmmer_score_filtered_accessions.csv",
    "aox_hmm/nodes.csv",
    "aox_hmm/scored_ref_plus_hits.csv",
    "aox_hmm/similarity_graph_manifest.json",
    "aox_hmm/target.fasta",
)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_ZERO_SOURCE_RECEIPT_KEYS = frozenset(
    {
        "schema_id",
        "calculation_id",
        "calculation_contract_digest",
        "calculation_implementation_digest",
        "output_count",
        "output_digest",
        "empty_result_reason",
    }
)
_CONDITIONAL_RECEIPT_KEYS = frozenset(
    {
        "schema_id",
        "calculation_id",
        "calculation_contract_digest",
        "calculation_implementation_digest",
        "serializer_id",
        "source_calculation",
        "output_count",
        "output_format",
        "output_digest",
        "empty_result_reason",
    }
)
_ARTIFACT_KINDS = frozenset(
    {
        "code",
        "log",
        "sequence",
        "structure",
        "report",
        "research_dossier",
        "result",
        "cache",
        "other",
    }
)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _required_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ScientificPrerequisiteError(
            "conditional_empty_digest_invalid",
            "conditional-empty calculation requires canonical SHA-256 identity",
            details={"field": field},
        )
    return value


def _validate_source_receipt(
    receipt: Mapping[str, object],
    *,
    allowed_calculation_ids: frozenset[str],
) -> dict[str, object]:
    normalized = dict(receipt)
    calculation_id = receipt.get("calculation_id")
    if (
        not isinstance(calculation_id, str)
        or calculation_id not in allowed_calculation_ids
    ):
        raise ScientificPrerequisiteError(
            "conditional_empty_source_receipt_invalid",
            "conditional-empty calculation requires one exact installed source calculation",
            details={
                "calculation_id": calculation_id,
                "allowed_calculation_ids": sorted(allowed_calculation_ids),
            },
        )
    contract_digest = _required_digest(
        receipt.get("calculation_contract_digest"),
        field="calculation_contract_digest",
    )
    implementation_digest = _required_digest(
        receipt.get("calculation_implementation_digest"),
        field="calculation_implementation_digest",
    )
    _required_digest(
        receipt.get("output_digest"),
        field="output_digest",
    )
    count = receipt.get("candidate_count", receipt.get("output_count"))
    if isinstance(count, bool) or not isinstance(count, int) or count != 0:
        raise ScientificPrerequisiteError(
            "conditional_empty_source_not_zero",
            "conditional-empty calculation requires an exact typed zero result",
        )
    reason = receipt.get("empty_result_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ScientificPrerequisiteError(
            "conditional_empty_reason_missing",
            "typed zero source requires a stable empty-result reason",
        )
    expected_identity = _source_calculation_identity(calculation_id)
    if (
        contract_digest != expected_identity["calculation_contract_digest"]
        or implementation_digest
        != expected_identity["calculation_implementation_digest"]
    ):
        raise ScientificPrerequisiteError(
            "conditional_empty_source_identity_mismatch",
            "typed zero source does not match the installed calculation identity",
            details={"calculation_id": calculation_id},
        )
    if calculation_id == aox_candidate.CALCULATION_ID:
        aox_candidate.validate_calculation_receipt(normalized)
    elif calculation_id in {
        aox_hmmer.CONTRACT_ID,
        aox_sequence_join.CONTRACT_ID,
    }:
        if (
            set(normalized) != _ZERO_SOURCE_RECEIPT_KEYS
            or normalized.get("schema_id") != ZERO_SOURCE_RECEIPT_SCHEMA_ID
        ):
            raise ScientificPrerequisiteError(
                "conditional_empty_source_receipt_invalid",
                "typed zero source does not match its closed receipt schema",
                details={"calculation_id": calculation_id},
            )
    else:
        validate_conditional_receipt(normalized)
    return normalized


def _source_calculation_identity(calculation_id: str) -> dict[str, str]:
    if calculation_id == aox_candidate.CALCULATION_ID:
        return {
            "calculation_contract_digest": aox_candidate.CONTRACT_DIGEST,
            "calculation_implementation_digest": (
                aox_candidate.IMPLEMENTATION_DIGEST
            ),
        }
    if calculation_id == aox_hmmer.CONTRACT_ID:
        return {
            "calculation_contract_digest": aox_hmmer.CONTRACT_DIGEST,
            "calculation_implementation_digest": (
                aox_hmmer.IMPLEMENTATION_DIGEST
            ),
        }
    if calculation_id == aox_sequence_join.CONTRACT_ID:
        return {
            "calculation_contract_digest": aox_sequence_join.CONTRACT_DIGEST,
            "calculation_implementation_digest": (
                aox_sequence_join.IMPLEMENTATION_DIGEST
            ),
        }
    if calculation_id in CALCULATION_CONTRACT_DIGESTS:
        return {
            "calculation_contract_digest": CALCULATION_CONTRACT_DIGESTS[
                calculation_id
            ],
            "calculation_implementation_digest": IMPLEMENTATION_DIGEST,
        }
    raise ScientificPrerequisiteError(
        "conditional_empty_source_receipt_invalid",
        "conditional-empty source calculation is not installed",
        details={"calculation_id": calculation_id},
    )


def _zero_source_receipt(
    *,
    calculation_id: str,
    calculation_contract_digest: str,
    calculation_implementation_digest: str,
    output_digest: str,
    empty_result_reason: str,
) -> dict[str, object]:
    receipt = {
        "schema_id": ZERO_SOURCE_RECEIPT_SCHEMA_ID,
        "calculation_id": calculation_id,
        "calculation_contract_digest": calculation_contract_digest,
        "calculation_implementation_digest": calculation_implementation_digest,
        "output_count": 0,
        "output_digest": output_digest,
        "empty_result_reason": empty_result_reason,
    }
    _validate_source_receipt(
        receipt,
        allowed_calculation_ids=frozenset({calculation_id}),
    )
    return receipt


def hmmer_zero_source_receipt(
    result: aox_hmmer.ScoreFilteredAccessionsResult,
) -> dict[str, object]:
    if not isinstance(result, aox_hmmer.ScoreFilteredAccessionsResult):
        raise ScientificPrerequisiteError(
            "conditional_empty_source_result_invalid",
            "HMMER zero-source receipt requires the installed typed result",
        )
    if result.accessions:
        raise ScientificPrerequisiteError(
            "conditional_empty_source_not_zero",
            "HMMER zero-source receipt requires zero filtered accessions",
        )
    return _zero_source_receipt(
        calculation_id=aox_hmmer.CONTRACT_ID,
        calculation_contract_digest=aox_hmmer.CONTRACT_DIGEST,
        calculation_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
        output_digest=result.output_digest,
        empty_result_reason="no_accessions_after_hmmer_score_filter",
    )


def sequence_join_zero_source_receipt(
    result: aox_sequence_join.SequenceLengthJoinResult,
) -> dict[str, object]:
    if not isinstance(result, aox_sequence_join.SequenceLengthJoinResult):
        raise ScientificPrerequisiteError(
            "conditional_empty_source_result_invalid",
            "sequence-join zero-source receipt requires the installed typed result",
        )
    if result.hits:
        raise ScientificPrerequisiteError(
            "conditional_empty_source_not_zero",
            "sequence-join zero-source receipt requires zero post-UniProt targets",
        )
    return _zero_source_receipt(
        calculation_id=aox_sequence_join.CONTRACT_ID,
        calculation_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
        calculation_implementation_digest=aox_sequence_join.IMPLEMENTATION_DIGEST,
        output_digest=_sha256(result.target_fasta().encode("utf-8")),
        empty_result_reason="no_candidates_after_length_filter",
    )


@dataclass(frozen=True, slots=True)
class ConditionalEmptyResult:
    calculation_id: str
    source_receipt: Mapping[str, object]
    output_bytes: bytes
    output_format: str
    empty_result_reason: str

    def calculation_receipt(self) -> dict[str, object]:
        source = _validate_conditional_source(
            self.calculation_id,
            self.source_receipt,
        )
        contract = CALCULATION_CONTRACT_DIGESTS[self.calculation_id]
        return {
            "schema_id": CONDITIONAL_EMPTY_RESULT_SCHEMA_ID,
            "calculation_id": self.calculation_id,
            "calculation_contract_digest": contract,
            "calculation_implementation_digest": IMPLEMENTATION_DIGEST,
            "serializer_id": f"{self.calculation_id}_serializer",
            "source_calculation": source,
            "output_count": 0,
            "output_format": self.output_format,
            "output_digest": _sha256(self.output_bytes),
            "empty_result_reason": self.empty_result_reason,
        }


def materialize_upstream_empty(
    source_receipt: Mapping[str, object],
) -> ConditionalEmptyResult:
    source = _validate_source_receipt(
        source_receipt,
        allowed_calculation_ids=frozenset({aox_hmmer.CONTRACT_ID}),
    )
    return ConditionalEmptyResult(
        calculation_id=UPSTREAM_EMPTY_CALCULATION_ID,
        source_receipt=source_receipt,
        output_bytes=b"",
        output_format="fasta",
        empty_result_reason=str(source["empty_result_reason"]),
    )


def materialize_reference_only_alignment(
    reference_fasta: str | bytes,
    source_receipt: Mapping[str, object],
) -> ConditionalEmptyResult:
    source = _validate_source_receipt(
        source_receipt,
        allowed_calculation_ids=frozenset(
            {
                UPSTREAM_EMPTY_CALCULATION_ID,
                aox_sequence_join.CONTRACT_ID,
            }
        ),
    )
    raw = (
        reference_fasta.encode("ascii")
        if isinstance(reference_fasta, str)
        else bytes(reference_fasta)
    )
    if not raw.startswith(b">AAB57849.1") or raw.count(b">") != 1:
        raise ScientificPrerequisiteError(
            "reference_only_alignment_reference_invalid",
            "reference-only alignment requires the exact single coordinate reference",
        )
    return ConditionalEmptyResult(
        calculation_id=REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
        source_receipt=source_receipt,
        output_bytes=raw,
        output_format="aligned_fasta",
        empty_result_reason=str(source["empty_result_reason"]),
    )


def materialize_empty_membership(
    source_receipt: Mapping[str, object],
) -> ConditionalEmptyResult:
    source = _validate_source_receipt(
        source_receipt,
        allowed_calculation_ids=frozenset({aox_candidate.CALCULATION_ID}),
    )
    return ConditionalEmptyResult(
        calculation_id=EMPTY_MEMBERSHIP_CALCULATION_ID,
        source_receipt=source_receipt,
        output_bytes=(
            b"cluster_id,member_id,representative_id,is_representative,"
            b"identity_to_representative,member_length\n"
        ),
        output_format="csv",
        empty_result_reason=str(source["empty_result_reason"]),
    )


def _resolved_output_path(path: object) -> tuple[str, str]:
    if not isinstance(path, str) or not path:
        raise PipelineSdkError(
            "AOX finalization item path must be non-empty",
            error_code="aox_finalization_item_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    raw = Path(path)
    resolved = (
        raw if raw.is_absolute() else Path("/workspace/output") / raw
    ).resolve()
    root = Path("/workspace/output").resolve()
    if root not in (resolved, *resolved.parents):
        raise PipelineSdkError(
            "AOX finalization accepts only /workspace/output drafts",
            error_code="aox_finalization_path_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    relative = resolved.relative_to(root).as_posix()
    if relative not in FIXED_DELIVERABLE_PATHS:
        raise PipelineSdkError(
            "AOX finalization item is outside the exact deliverable set",
            error_code="aox_finalization_path_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
            details={"relative_path": relative},
        )
    return str(resolved), relative


def _closed_item(item: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "path",
        "kind",
        "format",
        "validation_profile",
        "metadata",
    }
    if set(item) != allowed:
        raise PipelineSdkError(
            "AOX finalization item does not match its closed schema",
            error_code="aox_finalization_item_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    resolved, relative = _resolved_output_path(item.get("path"))
    kind = item.get("kind")
    format_value = item.get("format")
    validation_profile = item.get("validation_profile")
    metadata = item.get("metadata")
    if (
        kind not in _ARTIFACT_KINDS
        or not isinstance(format_value, str)
        or not format_value
        or (
            validation_profile is not None
            and (
                not isinstance(validation_profile, str)
                or not validation_profile
            )
        )
        or not isinstance(metadata, dict)
    ):
        raise PipelineSdkError(
            "AOX finalization item fields are invalid",
            error_code="aox_finalization_item_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    return {
        "path": resolved,
        "relative_path": relative,
        "kind": kind,
        "format": format_value,
        "validation_profile": validation_profile,
        "metadata": dict(metadata),
    }


def finalize_deliverable_bundle(
    *,
    attempt_id: str,
    selection_id: str,
    execution_task_id: str,
    items: Sequence[Mapping[str, Any]],
    calculation_receipts: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (attempt_id, selection_id, execution_task_id)
    ):
        raise PipelineSdkError(
            "AOX finalization requires attempt, selection and execution task ids",
            error_code="aox_finalization_identity_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    closed_items = [_closed_item(item) for item in items]
    paths = [str(item["relative_path"]) for item in closed_items]
    if len(paths) != len(FIXED_DELIVERABLE_PATHS) or set(paths) != set(
        FIXED_DELIVERABLE_PATHS
    ) or len(paths) != len(set(paths)):
        raise PipelineSdkError(
            "AOX finalization requires each exact deliverable path once",
            error_code="aox_finalization_deliverable_set_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
            details={
                "expected_count": len(FIXED_DELIVERABLE_PATHS),
                "observed_count": len(paths),
            },
        )
    receipts = [dict(receipt) for receipt in calculation_receipts]
    required_calculations = {
        aox_candidate.CALCULATION_ID,
        FINALIZATION_CALCULATION_ID,
    }
    observed_calculations = {
        str(receipt.get("calculation_id") or "") for receipt in receipts
    }
    if not required_calculations <= observed_calculations:
        raise PipelineSdkError(
            "AOX finalization lacks required exact calculation receipts",
            error_code="aox_finalization_calculation_receipt_missing",
            stage="aox_finalization.request_validation",
            retryable=False,
            details={
                "missing_calculation_ids": sorted(
                    required_calculations - observed_calculations
                )
            },
        )
    return dict(
        call(
            "artifacts.finalize_bundle",
            {
                "profile_id": FINAL_BUNDLE_PROFILE_ID,
                "attempt_id": attempt_id,
                "selection_id": selection_id,
                "execution_task_id": execution_task_id,
                "items": closed_items,
                "calculation_receipts": receipts,
            },
        )
    )


def implementation_digest() -> str:
    return _sha256(Path(__file__).read_bytes())


def _calculation_contract_payload(
    calculation_id: str,
    *,
    implementation_digest_value: str,
) -> dict[str, object]:
    if calculation_id == FINALIZATION_CALCULATION_ID:
        return {
            "calculation_id": calculation_id,
            "implementation_digest": implementation_digest_value,
            "input_profile_id": FINAL_BUNDLE_PROFILE_ID,
            "deliverable_count": len(FIXED_DELIVERABLE_PATHS),
            "deliverable_path_digest": _sha256(
                _canonical_json_bytes(list(FIXED_DELIVERABLE_PATHS))
            ),
            "prevalidation": "complete_before_catalog_mutation",
            "commit": "atomic_catalog_and_validation_receipt",
            "result_schema_id": FINALIZATION_CALCULATION_RESULT_SCHEMA_ID,
            "serializer_id": f"{calculation_id}_serializer",
        }
    return {
        "calculation_id": calculation_id,
        "implementation_digest": implementation_digest_value,
        "source_requirement": "exact_typed_zero_calculation_receipt",
        "output_count": 0,
        "serializer_id": f"{calculation_id}_serializer",
    }


IMPLEMENTATION_DIGEST = implementation_digest()
CALCULATION_CONTRACT_DIGESTS = {
    calculation_id: _sha256(
        _canonical_json_bytes(
            _calculation_contract_payload(
                calculation_id,
                implementation_digest_value=IMPLEMENTATION_DIGEST,
            )
        )
    )
    for calculation_id in (
        UPSTREAM_EMPTY_CALCULATION_ID,
        REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
        EMPTY_MEMBERSHIP_CALCULATION_ID,
        FINALIZATION_CALCULATION_ID,
    )
}


def _validate_conditional_source(
    calculation_id: str,
    source_receipt: Mapping[str, object],
) -> dict[str, object]:
    allowed_by_calculation = {
        UPSTREAM_EMPTY_CALCULATION_ID: frozenset({aox_hmmer.CONTRACT_ID}),
        REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID: frozenset(
            {
                UPSTREAM_EMPTY_CALCULATION_ID,
                aox_sequence_join.CONTRACT_ID,
            }
        ),
        EMPTY_MEMBERSHIP_CALCULATION_ID: frozenset(
            {aox_candidate.CALCULATION_ID}
        ),
    }
    allowed = allowed_by_calculation.get(calculation_id)
    if allowed is None:
        raise ScientificPrerequisiteError(
            "conditional_empty_calculation_invalid",
            "conditional-empty calculation id is not installed",
            details={"calculation_id": calculation_id},
        )
    return _validate_source_receipt(
        source_receipt,
        allowed_calculation_ids=allowed,
    )


def validate_conditional_receipt(
    receipt: Mapping[str, object],
) -> dict[str, object]:
    normalized = dict(receipt)
    calculation_id = normalized.get("calculation_id")
    expected_formats = {
        UPSTREAM_EMPTY_CALCULATION_ID: "fasta",
        REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID: "aligned_fasta",
        EMPTY_MEMBERSHIP_CALCULATION_ID: "csv",
    }
    if (
        set(normalized) != _CONDITIONAL_RECEIPT_KEYS
        or not isinstance(calculation_id, str)
        or calculation_id
        not in {
            UPSTREAM_EMPTY_CALCULATION_ID,
            REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
            EMPTY_MEMBERSHIP_CALCULATION_ID,
        }
        or normalized.get("schema_id")
        != CONDITIONAL_EMPTY_RESULT_SCHEMA_ID
        or normalized.get("calculation_contract_digest")
        != CALCULATION_CONTRACT_DIGESTS[calculation_id]
        or normalized.get("calculation_implementation_digest")
        != IMPLEMENTATION_DIGEST
        or normalized.get("serializer_id")
        != f"{calculation_id}_serializer"
        or normalized.get("output_count") != 0
        or not isinstance(normalized.get("source_calculation"), dict)
        or normalized.get("output_format")
        != expected_formats.get(str(calculation_id))
    ):
        raise ScientificPrerequisiteError(
            "conditional_empty_receipt_invalid",
            "conditional-empty receipt does not match its installed calculation",
        )
    _required_digest(normalized.get("output_digest"), field="output_digest")
    source = _validate_conditional_source(
        calculation_id,
        normalized["source_calculation"],
    )
    if normalized.get("empty_result_reason") != source.get(
        "empty_result_reason"
    ):
        raise ScientificPrerequisiteError(
            "conditional_empty_receipt_invalid",
            "conditional-empty reason does not match its exact typed source",
        )
    return normalized


def finalization_calculation_receipt() -> dict[str, object]:
    return {
        "schema_id": FINALIZATION_CALCULATION_RESULT_SCHEMA_ID,
        "calculation_id": FINALIZATION_CALCULATION_ID,
        "calculation_contract_digest": CALCULATION_CONTRACT_DIGESTS[
            FINALIZATION_CALCULATION_ID
        ],
        "calculation_implementation_digest": IMPLEMENTATION_DIGEST,
        "serializer_id": f"{FINALIZATION_CALCULATION_ID}_serializer",
        "deliverable_paths": list(FIXED_DELIVERABLE_PATHS),
        "deliverable_path_digest": _sha256(
            _canonical_json_bytes(list(FIXED_DELIVERABLE_PATHS))
        ),
    }


def installed_calculation_manifest() -> dict[str, object]:
    calculations: dict[str, dict[str, object]] = {
        aox_candidate.CALCULATION_ID: {
            "contract_digest": aox_candidate.CONTRACT_DIGEST,
            "implementation_digest": aox_candidate.IMPLEMENTATION_DIGEST,
            "result_schema_id": aox_candidate.RESULT_SCHEMA_ID,
            "serializer_id": aox_candidate.SERIALIZER_ID,
        },
        **{
            calculation_id: {
                "contract_digest": CALCULATION_CONTRACT_DIGESTS[
                    calculation_id
                ],
                "implementation_digest": IMPLEMENTATION_DIGEST,
                "result_schema_id": CONDITIONAL_EMPTY_RESULT_SCHEMA_ID,
                "serializer_id": f"{calculation_id}_serializer",
            }
            for calculation_id in (
                UPSTREAM_EMPTY_CALCULATION_ID,
                REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
                EMPTY_MEMBERSHIP_CALCULATION_ID,
            )
        },
        FINALIZATION_CALCULATION_ID: {
            "contract_digest": CALCULATION_CONTRACT_DIGESTS[
                FINALIZATION_CALCULATION_ID
            ],
            "implementation_digest": IMPLEMENTATION_DIGEST,
            "result_schema_id": FINALIZATION_CALCULATION_RESULT_SCHEMA_ID,
            "serializer_id": f"{FINALIZATION_CALCULATION_ID}_serializer",
        },
    }
    callable_names = (
        "aox_candidate.filter_motif_candidates",
        "aox_finalization.finalization_calculation_receipt",
        "aox_finalization.finalize_deliverable_bundle",
        "aox_finalization.hmmer_zero_source_receipt",
        "aox_finalization.materialize_empty_membership",
        "aox_finalization.materialize_reference_only_alignment",
        "aox_finalization.materialize_upstream_empty",
        "aox_finalization.sequence_join_zero_source_receipt",
        "aox_finalization.validate_conditional_receipt",
    )
    return {
        "schema_id": "aox_exact_calculation_manifest@1",
        "calculations": {
            key: calculations[key] for key in sorted(calculations)
        },
        "callable_names": list(callable_names),
        "fixed_deliverable_paths": list(FIXED_DELIVERABLE_PATHS),
        "fixed_deliverable_path_digest": _sha256(
            _canonical_json_bytes(list(FIXED_DELIVERABLE_PATHS))
        ),
    }


__all__ = [
    "CALCULATION_CONTRACT_DIGESTS",
    "CONDITIONAL_EMPTY_RESULT_SCHEMA_ID",
    "ConditionalEmptyResult",
    "EMPTY_MEMBERSHIP_CALCULATION_ID",
    "FINALIZATION_CALCULATION_ID",
    "FINALIZATION_CALCULATION_RESULT_SCHEMA_ID",
    "FINALIZATION_RECEIPT_SCHEMA_ID",
    "FINAL_BUNDLE_PROFILE_ID",
    "FIXED_DELIVERABLE_PATHS",
    "IMPLEMENTATION_DIGEST",
    "REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID",
    "UPSTREAM_EMPTY_CALCULATION_ID",
    "ZERO_SOURCE_RECEIPT_SCHEMA_ID",
    "finalization_calculation_receipt",
    "finalize_deliverable_bundle",
    "hmmer_zero_source_receipt",
    "installed_calculation_manifest",
    "materialize_empty_membership",
    "materialize_reference_only_alignment",
    "materialize_upstream_empty",
    "sequence_join_zero_source_receipt",
    "validate_conditional_receipt",
]
