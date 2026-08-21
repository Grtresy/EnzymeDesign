from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from enzymedesign_aox import AoxArchitectureQualificationError
from enzymedesign_aox import AoxArchitectureQualificationEvidence
from enzymedesign_aox import build_architecture_qualification_receipt
from enzymedesign_aox import derive_architecture_qualification_receipt
from enzymedesign_aox import normalize_architecture_qualification_receipt
from enzymedesign_aox import require_matching_architecture_qualification_receipt


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _receipt(*, payload_digit: str = "1") -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest="sha256:" + payload_digit * 64,
        registry_digest="sha256:" + "2" * 64,
        test_manifest_digest="sha256:" + "3" * 64,
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
        report_schema_id="openzyme_v3_architecture_qualification_report@3",
        run_evidence_digest="sha256:" + "4" * 64,
        source_identity_digest="sha256:" + "5" * 64,
        owner_constraint_registry_digest="sha256:" + "6" * 64,
        transformation_results_digest="sha256:" + "7" * 64,
    )


def _evidence(
    *, admission_eligible: bool = True
) -> AoxArchitectureQualificationEvidence:
    return AoxArchitectureQualificationEvidence(
        admission_eligible=admission_eligible,
        rejection_reasons=() if admission_eligible else ("open_p0",),
        report_schema_id="openzyme_v3_architecture_qualification_report@3",
        report_payload_digest="sha256:" + "1" * 64,
        registry_digest="sha256:" + "2" * 64,
        test_manifest_digest="sha256:" + "3" * 64,
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
        run_evidence_digest="sha256:" + "4" * 64,
        source_identity_digest="sha256:" + "5" * 64,
        owner_constraint_registry_digest="sha256:" + "6" * 64,
        transformation_results_digest="sha256:" + "7" * 64,
    )


def test_receipt_is_closed_self_digesting_and_commit_bound() -> None:
    receipt = _receipt()
    assert (
        normalize_architecture_qualification_receipt(
            receipt,
            expected_source_commit="a" * 40,
        )
        == receipt
    )

    for mutation in ("unknown_field", "digest_tamper", "old_version", "wrong_commit"):
        tampered = deepcopy(receipt)
        if mutation == "unknown_field":
            tampered["force"] = "true"
        elif mutation == "digest_tamper":
            tampered["report_payload_digest"] = "sha256:" + "f" * 64
        elif mutation == "old_version":
            tampered["schema_id"] = "aox_architecture_qualification_receipt@0"
        else:
            tampered["source_commit"] = "b" * 40
        with pytest.raises(AoxArchitectureQualificationError):
            normalize_architecture_qualification_receipt(
                tampered,
                expected_source_commit="a" * 40,
            )


def test_pinned_receipt_requires_exact_verified_identity() -> None:
    verified = _receipt()
    assert (
        require_matching_architecture_qualification_receipt(
            verified,
            verified,
        )
        == verified
    )
    with pytest.raises(AoxArchitectureQualificationError) as error:
        require_matching_architecture_qualification_receipt(
            _receipt(payload_digit="4"),
            verified,
        )
    assert error.value.code == "aox_architecture_qualification_receipt_mismatch"


def test_historical_receipts_are_read_only() -> None:
    preimage = {
        "profile_id": "local_single_process_file_sqlite@1",
        "registry_digest": "sha256:" + "2" * 64,
        "report_payload_digest": "sha256:" + "1" * 64,
        "schema_id": "aox_architecture_qualification_receipt@1",
        "source_commit": "a" * 40,
        "test_manifest_digest": "sha256:" + "3" * 64,
    }
    historical = {
        **preimage,
        "receipt_digest": "sha256:"
        + hashlib.sha256(_canonical_json_bytes(preimage)).hexdigest(),
    }
    with pytest.raises(AoxArchitectureQualificationError):
        normalize_architecture_qualification_receipt(historical)
    assert (
        normalize_architecture_qualification_receipt(
            historical,
            allow_historical=True,
        )
        == historical
    )

    historical_v2 = deepcopy(_receipt())
    historical_v2.pop("owner_constraint_registry_digest")
    historical_v2.pop("transformation_results_digest")
    historical_v2["schema_id"] = "aox_architecture_qualification_receipt@2"
    historical_v2["report_schema_id"] = (
        "openzyme_v3_architecture_qualification_report@2"
    )
    v2_preimage = {
        key: value for key, value in historical_v2.items() if key != "receipt_digest"
    }
    historical_v2["receipt_digest"] = (
        "sha256:" + hashlib.sha256(_canonical_json_bytes(v2_preimage)).hexdigest()
    )
    with pytest.raises(AoxArchitectureQualificationError):
        normalize_architecture_qualification_receipt(historical_v2)
    assert (
        normalize_architecture_qualification_receipt(
            historical_v2,
            allow_historical=True,
        )
        == historical_v2
    )


def test_qualification_derivation_requires_current_admissible_evidence() -> None:
    assert derive_architecture_qualification_receipt(_evidence()) == _receipt()

    with pytest.raises(AoxArchitectureQualificationError) as error:
        derive_architecture_qualification_receipt(_evidence(admission_eligible=False))
    assert error.value.code == "aox_architecture_qualification_not_admissible"
    assert error.value.details == {"rejection_reasons": ["open_p0"]}

    stale = replace(
        _evidence(),
        report_schema_id="openzyme_v3_architecture_qualification_report@2",
    )
    with pytest.raises(AoxArchitectureQualificationError) as stale_error:
        derive_architecture_qualification_receipt(stale)
    assert stale_error.value.code == (
        "aox_architecture_qualification_report_version_unsupported"
    )
