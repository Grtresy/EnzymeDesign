from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re


ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1 = (
    "aox_architecture_qualification_receipt@1"
)
ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2 = (
    "aox_architecture_qualification_receipt@2"
)
ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID = (
    "aox_architecture_qualification_receipt@3"
)
ARCHITECTURE_QUALIFICATION_PROFILE_ID = "local_single_process_file_sqlite@1"
ARCHITECTURE_QUALIFICATION_REPORT_SCHEMA_ID = (
    "openzyme_v3_architecture_qualification_report@3"
)
ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V1 = frozenset(
    {
        "profile_id",
        "receipt_digest",
        "registry_digest",
        "report_payload_digest",
        "schema_id",
        "source_commit",
        "test_manifest_digest",
    }
)
ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V2 = frozenset(
    set(ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V1)
    | {
        "report_schema_id",
        "run_evidence_digest",
        "source_identity_digest",
    }
)
ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS = frozenset(
    set(ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V2)
    | {
        "owner_constraint_registry_digest",
        "transformation_results_digest",
    }
)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class AoxArchitectureQualificationError(RuntimeError):
    """Stable, public-safe AOX admission error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else dict(details)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def build_architecture_qualification_receipt(
    *,
    report_payload_digest: str,
    registry_digest: str,
    test_manifest_digest: str,
    profile_id: str,
    source_commit: str,
    report_schema_id: str,
    run_evidence_digest: str,
    source_identity_digest: str,
    owner_constraint_registry_digest: str,
    transformation_results_digest: str,
) -> dict[str, str]:
    preimage = {
        "owner_constraint_registry_digest": owner_constraint_registry_digest,
        "profile_id": profile_id,
        "registry_digest": registry_digest,
        "report_payload_digest": report_payload_digest,
        "report_schema_id": report_schema_id,
        "run_evidence_digest": run_evidence_digest,
        "schema_id": ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID,
        "source_commit": source_commit,
        "source_identity_digest": source_identity_digest,
        "test_manifest_digest": test_manifest_digest,
        "transformation_results_digest": transformation_results_digest,
    }
    return normalize_architecture_qualification_receipt(
        {**preimage, "receipt_digest": _sha256(_canonical_json_bytes(preimage))}
    )


def normalize_architecture_qualification_receipt(
    receipt: Mapping[str, object],
    *,
    expected_source_commit: str | None = None,
    allow_historical: bool = False,
) -> dict[str, str]:
    schema_id = receipt.get("schema_id")
    if schema_id == ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID:
        expected_fields = ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS
    elif schema_id == ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2:
        if not allow_historical:
            raise AoxArchitectureQualificationError(
                "aox_architecture_qualification_receipt_version_unsupported",
                "historical architecture qualification receipts are read-only",
            )
        expected_fields = ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V2
    elif schema_id == ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1:
        if not allow_historical:
            raise AoxArchitectureQualificationError(
                "aox_architecture_qualification_receipt_version_unsupported",
                "historical architecture qualification receipts are read-only",
            )
        expected_fields = ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V1
    else:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_version_unsupported",
            "architecture qualification receipt schema is unsupported",
        )
    fields = set(receipt)
    if fields != expected_fields:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_invalid",
            "architecture qualification receipt must use its exact closed schema",
            details={
                "missing": sorted(expected_fields - fields),
                "unexpected": sorted(fields - expected_fields),
            },
        )
    normalized: dict[str, str] = {}
    for key in sorted(expected_fields):
        value = receipt[key]
        if not isinstance(value, str) or not value or value != value.strip():
            raise AoxArchitectureQualificationError(
                "aox_architecture_qualification_receipt_invalid",
                "architecture qualification receipt values must be canonical text",
                details={"identity": f"architecture_qualification.{key}"},
            )
        normalized[key] = value
    if normalized["profile_id"] != ARCHITECTURE_QUALIFICATION_PROFILE_ID:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_profile_unsupported",
            "architecture qualification receipt profile is unsupported",
        )
    digest_keys = [
        "receipt_digest",
        "registry_digest",
        "report_payload_digest",
        "test_manifest_digest",
    ]
    if schema_id in {
        ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID,
        ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2,
    }:
        digest_keys.extend(("run_evidence_digest", "source_identity_digest"))
    if schema_id == ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID:
        digest_keys.extend(
            (
                "owner_constraint_registry_digest",
                "transformation_results_digest",
            )
        )
    for key in digest_keys:
        if _DIGEST_PATTERN.fullmatch(normalized[key]) is None:
            raise AoxArchitectureQualificationError(
                "aox_architecture_qualification_receipt_invalid",
                "architecture qualification receipt contains a malformed digest",
                details={"identity": f"architecture_qualification.{key}"},
            )
    if _COMMIT_PATTERN.fullmatch(normalized["source_commit"]) is None:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_invalid",
            "architecture qualification receipt requires a full lowercase commit",
        )
    if (
        schema_id == ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID
        and normalized["report_schema_id"]
        != ARCHITECTURE_QUALIFICATION_REPORT_SCHEMA_ID
    ):
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_report_version_unsupported",
            "architecture qualification receipt does not bind the current report schema",
        )
    if (
        expected_source_commit is not None
        and normalized["source_commit"] != expected_source_commit
    ):
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_source_mismatch",
            "architecture qualification receipt does not bind the launch commit",
        )
    preimage = {
        key: value for key, value in normalized.items() if key != "receipt_digest"
    }
    if normalized["receipt_digest"] != _sha256(_canonical_json_bytes(preimage)):
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_invalid",
            "architecture qualification receipt digest does not close its fields",
        )
    return normalized


@dataclass(frozen=True, slots=True)
class AoxArchitectureQualificationEvidence:
    admission_eligible: bool
    rejection_reasons: tuple[str, ...]
    report_schema_id: str
    report_payload_digest: str
    registry_digest: str
    test_manifest_digest: str
    profile_id: str
    source_commit: str
    run_evidence_digest: str
    source_identity_digest: str
    owner_constraint_registry_digest: str
    transformation_results_digest: str


def derive_architecture_qualification_receipt(
    evidence: AoxArchitectureQualificationEvidence,
) -> dict[str, str]:
    if evidence.report_schema_id != ARCHITECTURE_QUALIFICATION_REPORT_SCHEMA_ID:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_report_version_unsupported",
            "historical architecture qualification reports cannot enter current AOX admission",
        )
    if not evidence.admission_eligible:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_not_admissible",
            "architecture qualification report does not authorize AOX preparation",
            details={"rejection_reasons": list(evidence.rejection_reasons)},
        )
    receipt = build_architecture_qualification_receipt(
        report_payload_digest=evidence.report_payload_digest,
        registry_digest=evidence.registry_digest,
        test_manifest_digest=evidence.test_manifest_digest,
        profile_id=evidence.profile_id,
        source_commit=evidence.source_commit,
        report_schema_id=evidence.report_schema_id,
        run_evidence_digest=evidence.run_evidence_digest,
        source_identity_digest=evidence.source_identity_digest,
        owner_constraint_registry_digest=(evidence.owner_constraint_registry_digest),
        transformation_results_digest=evidence.transformation_results_digest,
    )
    return normalize_architecture_qualification_receipt(
        receipt,
        expected_source_commit=evidence.source_commit,
    )


def require_matching_architecture_qualification_receipt(
    declared: Mapping[str, object],
    verified: Mapping[str, object],
) -> dict[str, str]:
    normalized_declared = normalize_architecture_qualification_receipt(declared)
    normalized_verified = normalize_architecture_qualification_receipt(verified)
    if normalized_declared != normalized_verified:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_mismatch",
            "pinned architecture qualification does not match the verified report",
        )
    return normalized_verified


__all__ = [
    "ARCHITECTURE_QUALIFICATION_PROFILE_ID",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V1",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2",
    "ARCHITECTURE_QUALIFICATION_REPORT_SCHEMA_ID",
    "AoxArchitectureQualificationError",
    "AoxArchitectureQualificationEvidence",
    "build_architecture_qualification_receipt",
    "derive_architecture_qualification_receipt",
    "normalize_architecture_qualification_receipt",
    "require_matching_architecture_qualification_receipt",
]
