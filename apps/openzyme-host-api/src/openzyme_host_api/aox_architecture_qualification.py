from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
import re

from openzyme_runtime import REPO_ROOT

from .architecture_qualification import ArchitectureQualificationReportError
from .architecture_qualification import PROFILE_ID
from .architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID
from .architecture_qualification import canonical_json_bytes
from .architecture_qualification_report import load_report
from .architecture_qualification_report import verify_report


ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1 = (
    "aox_architecture_qualification_receipt@1"
)
ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2 = (
    "aox_architecture_qualification_receipt@2"
)
ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID = (
    "aox_architecture_qualification_receipt@3"
)
ARCHITECTURE_QUALIFICATION_RUNNER_RELATIVE_PATH = Path(
    "scripts/v3_architecture_qualification.py"
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


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _receipt_preimage(
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
    return {
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
    preimage = _receipt_preimage(
        report_payload_digest=report_payload_digest,
        registry_digest=registry_digest,
        test_manifest_digest=test_manifest_digest,
        profile_id=profile_id,
        source_commit=source_commit,
        report_schema_id=report_schema_id,
        run_evidence_digest=run_evidence_digest,
        source_identity_digest=source_identity_digest,
        owner_constraint_registry_digest=owner_constraint_registry_digest,
        transformation_results_digest=transformation_results_digest,
    )
    return normalize_architecture_qualification_receipt(
        {
            **preimage,
            "receipt_digest": _sha256(canonical_json_bytes(preimage)),
        }
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
    if normalized["profile_id"] != PROFILE_ID:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_profile_unsupported",
            "architecture qualification receipt profile is unsupported",
        )
    digest_keys = (
        "receipt_digest",
        "registry_digest",
        "report_payload_digest",
        "test_manifest_digest",
    )
    if schema_id in {
        ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID,
        ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2,
    }:
        digest_keys += ("run_evidence_digest", "source_identity_digest")
    if schema_id == ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID:
        digest_keys += (
            "owner_constraint_registry_digest",
            "transformation_results_digest",
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
        and normalized["report_schema_id"] != QUALIFICATION_REPORT_SCHEMA_ID
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
    if normalized["receipt_digest"] != _sha256(canonical_json_bytes(preimage)):
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_invalid",
            "architecture qualification receipt digest does not close its fields",
        )
    return normalized


def verify_aox_architecture_qualification_report(
    report_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    runner_path: Path | None = None,
) -> dict[str, str]:
    """Verify one current admission report and derive its immutable AOX receipt."""

    resolved_root = repo_root.resolve()
    resolved_runner = (
        resolved_root / ARCHITECTURE_QUALIFICATION_RUNNER_RELATIVE_PATH
        if runner_path is None
        else runner_path
    )
    try:
        loaded = load_report(report_path)
        if loaded.envelope.get("schema_id") != QUALIFICATION_REPORT_SCHEMA_ID:
            raise AoxArchitectureQualificationError(
                "aox_architecture_qualification_report_version_unsupported",
                "historical architecture qualification reports cannot enter current AOX admission",
            )
        verification = verify_report(
            loaded,
            repo_root=resolved_root,
            runner_path=resolved_runner,
        )
    except AoxArchitectureQualificationError:
        raise
    except ArchitectureQualificationReportError as exc:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_report_invalid",
            "architecture qualification report is invalid for this checkout",
            details={"failure_type": type(exc).__name__},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - fail closed and redact internals
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_report_invalid",
            "architecture qualification report could not be verified",
            details={"failure_type": type(exc).__name__},
        ) from exc
    if not verification.admission_eligible:
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_not_admissible",
            "architecture qualification report does not authorize AOX preparation",
            details={"rejection_reasons": list(verification.rejection_reasons)},
        )
    payload = loaded.payload
    profile = payload.get("profile")
    if not isinstance(profile, Mapping):
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_report_invalid",
            "architecture qualification report profile is missing",
        )
    receipt = build_architecture_qualification_receipt(
        report_payload_digest=verification.payload_digest,
        registry_digest=str(payload.get("registry_digest") or ""),
        test_manifest_digest=str(payload.get("test_manifest_digest") or ""),
        profile_id=str(profile.get("profile_id") or ""),
        source_commit=verification.source_commit,
        report_schema_id=str(loaded.envelope["schema_id"]),
        run_evidence_digest=str(payload.get("run_evidence_digest") or ""),
        source_identity_digest=_sha256(
            canonical_json_bytes(payload.get("source_identity"))
        ),
        owner_constraint_registry_digest=str(
            payload.get("owner_constraint_registry_digest") or ""
        ),
        transformation_results_digest=str(
            payload.get("transformation_results_digest") or ""
        ),
    )
    return normalize_architecture_qualification_receipt(
        receipt,
        expected_source_commit=verification.source_commit,
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
    "ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_FIELDS_V1",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1",
    "ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2",
    "ARCHITECTURE_QUALIFICATION_RUNNER_RELATIVE_PATH",
    "AoxArchitectureQualificationError",
    "build_architecture_qualification_receipt",
    "normalize_architecture_qualification_receipt",
    "require_matching_architecture_qualification_receipt",
    "verify_aox_architecture_qualification_report",
]
