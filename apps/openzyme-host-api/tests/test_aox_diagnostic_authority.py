from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import stat

import pytest

from openzyme_host_api.aox_attempt_authority import (
    attempt_authority_consumption_path,
)
from openzyme_host_api.aox_attempt_authority import (
    build_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    consume_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    publish_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_consumption,
)
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_diagnostic_authority import (
    AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from openzyme_host_api.aox_diagnostic_authority import (
    AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID,
)
from openzyme_host_api.aox_diagnostic_authority import (
    build_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    consume_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    diagnostic_authority_consumption_path,
)
from openzyme_host_api.aox_diagnostic_authority import (
    load_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    publish_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    validate_aox_diagnostic_authority_consumption,
)
from openzyme_host_api.aox_diagnostic_authority import (
    validate_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass


def _declarations() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    return (
        {"git_commit": "a" * 40, "config_digest": "sha256:" + "b" * 64},
        {"provider_cache_mode": "bypass", "evidence_cache_reuse": False},
        {
            "schema_id": "aox_architecture_qualification_receipt@1",
            "report_payload_digest": "sha256:" + "c" * 64,
        },
    )


def _diagnostic_plan() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    identity, prerequisites, qualification = _declarations()
    plan = build_aox_diagnostic_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=10_000,
        max_cost_microunits=20_000,
        max_wall_time_seconds=3_600,
    )
    return plan, identity, prerequisites, qualification


def _formal_plan() -> dict[str, object]:
    identity, prerequisites, qualification = _declarations()
    return build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=10_000,
        max_cost_microunits_per_attempt=20_000,
        max_wall_time_seconds_per_attempt=3_600,
    )


def test_diagnostic_authority_is_one_slot_and_schema_disjoint() -> None:
    plan, identity, prerequisites, qualification = _diagnostic_plan()

    validated = validate_aox_diagnostic_authority_plan(
        plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )

    assert validated["schema_id"] == AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
    assert validated["run_class"] == AoxLiveRunClass.DIAGNOSTIC.value
    assert "slots" not in validated
    slot = validated["slot"]
    assert slot["run_class"] == AoxLiveRunClass.DIAGNOSTIC.value
    assert slot["ordinal"] == 1
    assert slot["attempt_kind"] == "positive"
    assert slot["attempt_id"].startswith("diagnostic-positive-")
    assert slot["session_id"].startswith("sess_diagnostic_")
    assert slot["task_id"].startswith("aox_execution_diagnostic_")
    assert slot["lane_id"].startswith("lane_aox_diagnostic_")
    assert slot["authority_request"]["root_ref"].startswith(
        "diagnostic-attempts/"
    )

    with pytest.raises(CutoverEvidenceError) as formal_rejects_diagnostic:
        validate_aox_attempt_authority_plan(
            plan,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    assert (
        formal_rejects_diagnostic.value.code
        == "attempt_authority_plan_schema_invalid"
    )

    with pytest.raises(CutoverEvidenceError) as diagnostic_rejects_formal:
        validate_aox_diagnostic_authority_plan(
            _formal_plan(),
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    assert (
        diagnostic_rejects_formal.value.code
        == "diagnostic_authority_plan_schema_invalid"
    )


def test_diagnostic_consumption_is_private_deterministic_and_one_use(
    tmp_path: Path,
) -> None:
    plan, identity, prerequisites, qualification = _diagnostic_plan()
    plan_path = tmp_path / "diagnostic-authority.json"
    publish_aox_diagnostic_authority_plan(plan, plan_path)

    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o400
    loaded = load_aox_diagnostic_authority_plan(
        plan_path,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )
    consumption_path = diagnostic_authority_consumption_path(plan_path)
    assert consumption_path.name == (
        "diagnostic-authority.json.diagnostic-consumed.json"
    )
    assert consumption_path != attempt_authority_consumption_path(plan_path)

    with pytest.raises(CutoverEvidenceError) as wrong_target:
        consume_aox_diagnostic_authority_plan(
            loaded,
            plan_path=plan_path,
            path=tmp_path / "wrong.json",
        )
    assert (
        wrong_target.value.code
        == "diagnostic_authority_consumption_target_mismatch"
    )

    receipt = consume_aox_diagnostic_authority_plan(
        loaded,
        plan_path=plan_path,
        path=consumption_path,
    )
    assert (
        receipt["schema_id"]
        == AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID
    )
    assert receipt["run_class"] == AoxLiveRunClass.DIAGNOSTIC.value
    assert receipt["plan_schema_id"] == AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
    assert receipt["root_namespace"] == plan["root_namespace"]
    assert receipt["consumption_file"] == consumption_path.name
    assert stat.S_IMODE(consumption_path.stat().st_mode) == 0o400
    assert (
        validate_aox_diagnostic_authority_consumption(
            receipt,
            plan=loaded,
            plan_path=plan_path,
        )
        == receipt
    )

    with pytest.raises(CutoverEvidenceError) as reused:
        consume_aox_diagnostic_authority_plan(
            loaded,
            plan_path=plan_path,
            path=consumption_path,
        )
    assert reused.value.code == "attempt_authority_publish_target_invalid"


def test_cross_mode_consumers_and_receipts_reject_equal_digest_reuse(
    tmp_path: Path,
) -> None:
    diagnostic, _, _, _ = _diagnostic_plan()
    formal = _formal_plan()
    formal_path = tmp_path / "formal.json"
    diagnostic_path = tmp_path / "diagnostic.json"

    with pytest.raises(CutoverEvidenceError) as formal_publisher:
        publish_aox_attempt_authority_plan(
            diagnostic,
            tmp_path / "published-as-formal.json",
        )
    assert (
        formal_publisher.value.code
        == "attempt_authority_plan_class_mismatch"
    )

    with pytest.raises(CutoverEvidenceError) as diagnostic_publisher:
        publish_aox_diagnostic_authority_plan(
            formal,
            tmp_path / "published-as-diagnostic.json",
        )
    assert (
        diagnostic_publisher.value.code
        == "diagnostic_authority_plan_class_mismatch"
    )

    with pytest.raises(CutoverEvidenceError) as formal_consumer:
        consume_aox_attempt_authority_plan(
            diagnostic,
            plan_path=diagnostic_path,
            path=attempt_authority_consumption_path(diagnostic_path),
        )
    assert (
        formal_consumer.value.code
        == "attempt_authority_plan_class_mismatch"
    )

    with pytest.raises(CutoverEvidenceError) as diagnostic_consumer:
        consume_aox_diagnostic_authority_plan(
            formal,
            plan_path=formal_path,
            path=diagnostic_authority_consumption_path(formal_path),
        )
    assert (
        diagnostic_consumer.value.code
        == "diagnostic_authority_plan_class_mismatch"
    )

    forged_diagnostic_receipt = {
        "schema_id": AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.DIAGNOSTIC.value,
        "plan_schema_id": AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": formal["plan_digest"],
        "diagnostic_id": diagnostic["diagnostic_id"],
        "root_namespace": diagnostic["root_namespace"],
        "consumption_file": attempt_authority_consumption_path(
            formal_path
        ).name,
        "consumed_at": "2026-07-25T00:00:00+00:00",
    }
    with pytest.raises(CutoverEvidenceError) as formal_receipt:
        validate_aox_attempt_authority_consumption(
            forged_diagnostic_receipt,
            plan=formal,
            plan_path=formal_path,
        )
    assert (
        formal_receipt.value.code
        == "attempt_authority_consumption_invalid"
    )

    forged_formal_receipt = deepcopy(forged_diagnostic_receipt)
    forged_formal_receipt["schema_id"] = (
        "aox_live_attempt_authority_consumption@2"
    )
    forged_formal_receipt["run_class"] = (
        AoxLiveRunClass.FORMAL_ACCEPTANCE.value
    )
    forged_formal_receipt["plan_schema_id"] = (
        "aox_live_attempt_authority_plan@1"
    )
    with pytest.raises(CutoverEvidenceError) as diagnostic_receipt:
        validate_aox_diagnostic_authority_consumption(
            forged_formal_receipt,
            plan=diagnostic,
            plan_path=diagnostic_path,
        )
    assert (
        diagnostic_receipt.value.code
        == "diagnostic_authority_consumption_invalid"
    )
