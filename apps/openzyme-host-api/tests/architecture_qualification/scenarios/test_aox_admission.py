from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_host_api import aox_architecture_qualification as qualification
from openzyme_host_api import aox_cutover_cli as cli
from openzyme_host_api.aox_architecture_qualification import (
    AoxArchitectureQualificationError,
)
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    normalize_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    require_matching_architecture_qualification_receipt,
)
from openzyme_host_api.architecture_qualification import canonical_json_bytes

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger


def _digest(digit: str) -> str:
    return "sha256:" + digit * 64


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.aox-admission-receipt-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_aox_admission_precedes_roots_and_receipt_closes_exact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = SimpleNamespace(payload={})
    monkeypatch.setattr(qualification, "load_report", lambda path: loaded)
    monkeypatch.setattr(
        qualification,
        "verify_report",
        lambda report, *, repo_root, runner_path: SimpleNamespace(
            admission_eligible=False,
            payload_digest=_digest("1"),
            rejection_reasons=("mode_not_admission",),
            source_commit="a" * 40,
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        qualification.verify_aox_architecture_qualification_report,
    )
    root_calls: list[object] = []

    def reject_root_creation(*args: object, **kwargs: object) -> None:
        root_calls.append((args, kwargs))
        raise AssertionError("AOX root creation crossed a rejected admission gate")

    monkeypatch.setattr(cli, "create_blank_world_roots", reject_root_creation)
    campaign_root = tmp_path / "campaign"
    args = cli.build_parser().parse_args(
        [
            "preflight",
            "--campaign-root",
            str(campaign_root),
            "--attempt-kind",
            "positive",
            "--allowed-prerequisites",
            str(tmp_path / "allowed-prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "qualification-report.json"),
        ]
    )

    with pytest.raises(AoxArchitectureQualificationError) as gate_error:
        cli._preflight(args)

    assert gate_error.value.code == "aox_architecture_qualification_not_admissible"
    assert root_calls == []
    assert not campaign_root.exists()

    receipt = build_architecture_qualification_receipt(
        report_payload_digest=_digest("1"),
        registry_digest=_digest("2"),
        test_manifest_digest=_digest("3"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
    )
    assert normalize_architecture_qualification_receipt(
        receipt,
        expected_source_commit="a" * 40,
    ) == receipt

    tampered = deepcopy(receipt)
    tampered["report_payload_digest"] = _digest("4")
    with pytest.raises(AoxArchitectureQualificationError) as digest_error:
        normalize_architecture_qualification_receipt(tampered)
    assert digest_error.value.code == "aox_architecture_qualification_receipt_invalid"

    different_report = build_architecture_qualification_receipt(
        report_payload_digest=_digest("4"),
        registry_digest=_digest("2"),
        test_manifest_digest=_digest("3"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
    )
    with pytest.raises(AoxArchitectureQualificationError) as mismatch_error:
        require_matching_architecture_qualification_receipt(receipt, different_report)
    assert mismatch_error.value.code == (
        "aox_architecture_qualification_receipt_mismatch"
    )

    observation = {
        "admission_error_code": gate_error.value.code,
        "campaign_root_created": campaign_root.exists(),
        "digest_tamper_error_code": digest_error.value.code,
        "receipt": receipt,
        "receipt_mismatch_error_code": mismatch_error.value.code,
        "root_call_count": len(root_calls),
        "schema_id": "aox_architecture_qualification_observation@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
