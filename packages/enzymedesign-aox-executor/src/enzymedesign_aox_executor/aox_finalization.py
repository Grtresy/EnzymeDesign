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
from openzyme_execution_sdk import ExecutionSdkError as PipelineSdkError
from openzyme_execution_sdk import call


FINAL_BUNDLE_PROFILE_ID = "aox_final_deliverable_bundle@1"
FINALIZATION_RECEIPT_SCHEMA_ID = "aox_final_deliverable_validation_receipt@1"
FINALIZATION_CALCULATION_ID = "aox_final_deliverable_normalization@1"
FINALIZATION_CALCULATION_RESULT_SCHEMA_ID = (
    "aox_final_deliverable_normalization_result@1"
)
UPSTREAM_EMPTY_CALCULATION_ID = "aox_upstream_empty_encoding@1"
REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID = (
    "aox_reference_only_scoring_alignment@1"
)
EMPTY_MEMBERSHIP_CALCULATION_ID = "aox_empty_membership@1"
CONDITIONAL_EMPTY_RESULT_SCHEMA_ID = "aox_conditional_empty_result@1"
CONDITIONAL_EMPTY_FILE_SCHEMA_ID = "aox_conditional_empty_file@1"
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
FIXED_DELIVERABLE_ROLES = (
    "candidates_fasta",
    "cdhit_clusters",
    "cdhit_candidates_fasta",
    "coordinate_reference_fasta",
    "reference_hmm",
    "reference_panel_fasta",
    "scoring_input_fasta",
    "scoring_alignment_fasta",
    "similarity_edges",
    "execution_summary",
    "length_filtered_hits",
    "raw_hits",
    "score_filtered_accessions",
    "similarity_nodes",
    "scored_reference_hits",
    "similarity_graph_manifest",
    "target_fasta",
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


def encode_upstream_empty(
    source_receipt: Mapping[str, object],
) -> ConditionalEmptyResult:
    source = _validate_source_receipt(
        source_receipt,
        allowed_calculation_ids=frozenset({aox_hmmer.CONTRACT_ID}),
    )
    reason = str(source["empty_result_reason"])
    empty_file = {
        "schema_id": CONDITIONAL_EMPTY_FILE_SCHEMA_ID,
        "calculation_id": UPSTREAM_EMPTY_CALCULATION_ID,
        "empty_result_reason": reason,
        "source_output_digest": source["output_digest"],
        "source_receipt_digest": _sha256(_canonical_json_bytes(source)),
    }
    return ConditionalEmptyResult(
        calculation_id=UPSTREAM_EMPTY_CALCULATION_ID,
        source_receipt=source_receipt,
        output_bytes=_canonical_json_bytes(empty_file) + b"\n",
        output_format="typed_empty_json",
        empty_result_reason=reason,
    )


def encode_reference_only_alignment(
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


def encode_empty_membership(
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


def finalize_deliverable_bundle(
    *,
    publication_id: str,
    attempt_id: str,
    selection_id: str,
    execution_fencing_token: int,
    producer_adoption_ids_by_role: Mapping[str, str],
    calculation_receipts: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (publication_id, attempt_id, selection_id)
    ):
        raise PipelineSdkError(
            "AOX file finalization requires publication, attempt and selection ids",
            error_code="aox_finalization_identity_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    if (
        isinstance(execution_fencing_token, bool)
        or not isinstance(execution_fencing_token, int)
        or execution_fencing_token < 1
    ):
        raise PipelineSdkError(
            "AOX file finalization requires a positive execution fencing token",
            error_code="aox_finalization_fence_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    adoptions = dict(producer_adoption_ids_by_role)
    if set(adoptions) != set(FIXED_DELIVERABLE_ROLES) or not all(
        isinstance(value, str) and value.strip() for value in adoptions.values()
    ):
        raise PipelineSdkError(
            "AOX file finalization requires one producer adoption for each exact role",
            error_code="aox_finalization_adoption_set_invalid",
            stage="aox_finalization.request_validation",
            retryable=False,
            details={
                "expected_roles": list(FIXED_DELIVERABLE_ROLES),
                "observed_roles": sorted(adoptions),
            },
        )
    receipts = [dict(receipt) for receipt in calculation_receipts]
    receipt_by_calculation = {
        str(receipt.get("calculation_id") or ""): receipt
        for receipt in receipts
    }
    if len(receipt_by_calculation) != len(receipts):
        raise PipelineSdkError(
            "AOX finalization calculation receipts must have unique identities",
            error_code="aox_finalization_calculation_receipt_conflict",
            stage="aox_finalization.request_validation",
            retryable=False,
        )
    required_calculations = {
        aox_candidate.CALCULATION_ID,
        FINALIZATION_CALCULATION_ID,
    }
    observed_calculations = set(receipt_by_calculation)
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
    for receipt in receipts:
        validate_installed_calculation_receipt(receipt)
    return dict(
        call(
            "scientific.deliverables.finalize",
            {
                "schema_version": "aox_scientific_file_finalize_request@1",
                "publication_id": publication_id,
                "attempt_id": attempt_id,
                "selection_id": selection_id,
                "execution_fencing_token": execution_fencing_token,
                "producer_adoption_ids_by_role": adoptions,
                "calculation_receipts": receipts,
            },
        )
    )


def adopt_producer_result(
    *,
    selection_id: str,
    operation_id: str,
    execution_id: str,
    result_id: str,
    workflow_role: str,
    execution_fencing_token: int,
    idempotency_key: str,
) -> dict[str, Any]:
    identities = {
        "selection_id": selection_id,
        "operation_id": operation_id,
        "execution_id": execution_id,
        "result_id": result_id,
        "idempotency_key": idempotency_key,
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in identities.values()
    ):
        raise PipelineSdkError(
            "AOX producer adoption requires exact non-empty identities",
            error_code="aox_producer_adoption_identity_invalid",
            stage="aox_finalization.adoption_request_validation",
            retryable=False,
        )
    if workflow_role not in FIXED_DELIVERABLE_ROLES:
        raise PipelineSdkError(
            "AOX producer adoption requires one installed scientific role",
            error_code="aox_producer_adoption_role_invalid",
            stage="aox_finalization.adoption_request_validation",
            retryable=False,
            details={"workflow_role": workflow_role},
        )
    if (
        isinstance(execution_fencing_token, bool)
        or not isinstance(execution_fencing_token, int)
        or execution_fencing_token < 1
    ):
        raise PipelineSdkError(
            "AOX producer adoption requires a positive execution fencing token",
            error_code="aox_producer_adoption_fence_invalid",
            stage="aox_finalization.adoption_request_validation",
            retryable=False,
        )
    return dict(
        call(
            "scientific.deliverables.adopt",
            {
                "schema_version": "scientific_file_effect_adoption_request@1",
                **identities,
                "workflow_role": workflow_role,
                "execution_fencing_token": execution_fencing_token,
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
            "prevalidation": "exact_published_git_lfs_bytes",
            "commit": "atomic_scientific_refs_and_validation_receipt",
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
        UPSTREAM_EMPTY_CALCULATION_ID: "typed_empty_json",
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


def validate_installed_calculation_receipt(
    receipt: Mapping[str, object],
) -> dict[str, object]:
    """Validate one exact receipt from the closed AOX calculation surface."""
    normalized = dict(receipt)
    calculation_id = normalized.get("calculation_id")
    if calculation_id == aox_candidate.CALCULATION_ID:
        return aox_candidate.validate_calculation_receipt(normalized)
    if calculation_id == FINALIZATION_CALCULATION_ID:
        if normalized != finalization_calculation_receipt():
            raise ScientificPrerequisiteError(
                "aox_finalization_calculation_receipt_invalid",
                "AOX finalization receipt does not match the installed calculation",
            )
        return normalized
    if calculation_id in {
        aox_hmmer.CONTRACT_ID,
        aox_sequence_join.CONTRACT_ID,
    }:
        return _validate_source_receipt(
            normalized,
            allowed_calculation_ids=frozenset({calculation_id}),
        )
    if calculation_id in {
        UPSTREAM_EMPTY_CALCULATION_ID,
        REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
        EMPTY_MEMBERSHIP_CALCULATION_ID,
    }:
        return validate_conditional_receipt(normalized)
    raise ScientificPrerequisiteError(
        "aox_finalization_calculation_receipt_unknown",
        "AOX finalization receipt names an uninstalled calculation",
        details={"calculation_id": calculation_id},
    )


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
        "aox_finalization.adopt_producer_result",
        "aox_finalization.finalization_calculation_receipt",
        "aox_finalization.finalize_deliverable_bundle",
        "aox_finalization.hmmer_zero_source_receipt",
        "aox_finalization.encode_empty_membership",
        "aox_finalization.encode_reference_only_alignment",
        "aox_finalization.encode_upstream_empty",
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
    "CONDITIONAL_EMPTY_FILE_SCHEMA_ID",
    "CONDITIONAL_EMPTY_RESULT_SCHEMA_ID",
    "ConditionalEmptyResult",
    "EMPTY_MEMBERSHIP_CALCULATION_ID",
    "FINALIZATION_CALCULATION_ID",
    "FINALIZATION_CALCULATION_RESULT_SCHEMA_ID",
    "FINALIZATION_RECEIPT_SCHEMA_ID",
    "FINAL_BUNDLE_PROFILE_ID",
    "FIXED_DELIVERABLE_PATHS",
    "FIXED_DELIVERABLE_ROLES",
    "IMPLEMENTATION_DIGEST",
    "REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID",
    "UPSTREAM_EMPTY_CALCULATION_ID",
    "ZERO_SOURCE_RECEIPT_SCHEMA_ID",
    "adopt_producer_result",
    "finalization_calculation_receipt",
    "finalize_deliverable_bundle",
    "hmmer_zero_source_receipt",
    "installed_calculation_manifest",
    "encode_empty_membership",
    "encode_reference_only_alignment",
    "encode_upstream_empty",
    "sequence_join_zero_source_receipt",
    "validate_conditional_receipt",
    "validate_installed_calculation_receipt",
]
