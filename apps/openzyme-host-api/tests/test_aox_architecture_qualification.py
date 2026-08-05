from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from openzyme_host_api import aox_architecture_qualification as qualification
from openzyme_host_api.aox_architecture_qualification import (
    AoxArchitectureQualificationError,
)
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    normalize_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    require_matching_architecture_qualification_receipt,
)


def _receipt(*, payload_digit: str = "1") -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest="sha256:" + payload_digit * 64,
        registry_digest="sha256:" + "2" * 64,
        test_manifest_digest="sha256:" + "3" * 64,
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
        report_schema_id="openzyme_v3_architecture_qualification_report@2",
        run_evidence_digest="sha256:" + "4" * 64,
        source_identity_digest="sha256:" + "5" * 64,
    )


def test_receipt_is_closed_self_digesting_and_commit_bound() -> None:
    receipt = _receipt()

    assert normalize_architecture_qualification_receipt(
        receipt,
        expected_source_commit="a" * 40,
    ) == receipt

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


def test_pinned_receipt_requires_exact_verified_report_identity() -> None:
    verified = _receipt()
    assert require_matching_architecture_qualification_receipt(
        verified,
        verified,
    ) == verified

    with pytest.raises(AoxArchitectureQualificationError) as error:
        require_matching_architecture_qualification_receipt(
            _receipt(payload_digit="4"),
            verified,
        )

    assert error.value.code == "aox_architecture_qualification_receipt_mismatch"


def test_historical_receipt_is_read_only_compatible() -> None:
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
        "receipt_digest": (
            f"sha256:{hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()}"
        ),
    }

    with pytest.raises(AoxArchitectureQualificationError) as current_error:
        normalize_architecture_qualification_receipt(historical)
    assert current_error.value.code == (
        "aox_architecture_qualification_receipt_version_unsupported"
    )
    assert normalize_architecture_qualification_receipt(
        historical,
        allow_historical=True,
    ) == historical


def test_report_adapter_derives_receipt_only_from_verified_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("not consulted by loader double", encoding="utf-8")
    loaded = SimpleNamespace(
        envelope={"schema_id": "openzyme_v3_architecture_qualification_report@2"},
        payload={
            "profile": {"profile_id": "local_single_process_file_sqlite@1"},
            "registry_digest": "sha256:" + "2" * 64,
            "test_manifest_digest": "sha256:" + "3" * 64,
            "run_evidence_digest": "sha256:" + "4" * 64,
            "source_identity": {"test": "source"},
        }
    )
    monkeypatch.setattr(qualification, "load_report", lambda path: loaded)
    monkeypatch.setattr(
        qualification,
        "verify_report",
        lambda report, *, repo_root, runner_path: SimpleNamespace(
            admission_eligible=True,
            payload_digest="sha256:" + "1" * 64,
            rejection_reasons=(),
            source_commit="a" * 40,
        ),
    )

    receipt = qualification.verify_aox_architecture_qualification_report(
        report_path,
        repo_root=tmp_path,
    )

    assert receipt["report_payload_digest"] == _receipt()["report_payload_digest"]
    assert receipt["run_evidence_digest"] == "sha256:" + "4" * 64


def test_report_adapter_rejects_diagnostic_or_open_p0_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = SimpleNamespace(
        envelope={"schema_id": "openzyme_v3_architecture_qualification_report@2"},
        payload={},
    )
    monkeypatch.setattr(qualification, "load_report", lambda path: loaded)
    monkeypatch.setattr(
        qualification,
        "verify_report",
        lambda report, *, repo_root, runner_path: SimpleNamespace(
            admission_eligible=False,
            payload_digest="sha256:" + "1" * 64,
            rejection_reasons=("mode_not_admission", "open_p0"),
            source_commit="a" * 40,
        ),
    )

    with pytest.raises(AoxArchitectureQualificationError) as error:
        qualification.verify_aox_architecture_qualification_report(
            tmp_path / "diagnostic.json",
            repo_root=tmp_path,
        )

    assert error.value.code == "aox_architecture_qualification_not_admissible"
    assert error.value.details == {
        "rejection_reasons": ["mode_not_admission", "open_p0"]
    }
