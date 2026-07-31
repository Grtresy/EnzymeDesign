from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import stat

import pytest

from openzyme_core import scientific_attempt_authorization_identity
from openzyme_host_api.aox_attempt_authority import (
    AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from openzyme_host_api.aox_attempt_authority import (
    AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
)
from openzyme_host_api.aox_attempt_authority import attempt_admission_arguments
from openzyme_host_api.aox_attempt_authority import (
    attempt_authority_consumption_path,
)
from openzyme_host_api.aox_attempt_authority import attempt_authority_slot_claim_path
from openzyme_host_api.aox_attempt_authority import (
    build_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    consume_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import claim_aox_attempt_authority_slot
from openzyme_host_api.aox_attempt_authority import (
    load_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    load_aox_attempt_authority_slot_claim,
)
from openzyme_host_api.aox_attempt_authority import (
    publish_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)


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


def _plan() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    identity, prerequisites, qualification = _declarations()
    plan = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=10_000,
        max_cost_microunits_per_attempt=20_000,
        max_wall_time_seconds_per_attempt=3_600,
    )
    return plan, identity, prerequisites, qualification


def _reseal_slot_and_plan(
    plan: dict[str, object],
    *,
    ordinal: int,
) -> None:
    slots = plan["slots"]
    assert isinstance(slots, list)
    slot = slots[ordinal - 1]
    assert isinstance(slot, dict)
    request = slot["authority_request"]
    assert isinstance(request, dict)
    envelope_id, request_digest, normalized_request = (
        scientific_attempt_authorization_identity(
            **{
                key: value
                for key, value in request.items()
                if key != "command"
            }
        )
    )
    slot["authority_request"] = normalized_request
    slot["envelope_id"] = envelope_id
    slot["request_digest"] = request_digest
    plan["plan_digest"] = canonical_digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )


def test_authority_plan_binds_three_one_use_attempt_slots() -> None:
    plan, identity, prerequisites, qualification = _plan()

    validated = validate_aox_attempt_authority_plan(
        plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )

    assert validated["schema_id"] == AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
    slots = validated["slots"]
    assert [slot["attempt_kind"] for slot in slots] == [
        "positive",
        "positive",
        "fault",
    ]
    assert [slot["ordinal"] for slot in slots] == [1, 2, 3]
    assert len({slot["attempt_id"] for slot in slots}) == 3
    assert len({slot["envelope_id"] for slot in slots}) == 3
    for slot in slots:
        request = slot["authority_request"]
        assert request["max_attempts"] == 1
        assert request["allowed_effect_classes"] == ["hpc", "provider"]
        assert request["root_ref"] == f"attempts/{slot['attempt_id']}"
        admission = attempt_admission_arguments(slot)
        assert admission["envelope_id"] == slot["envelope_id"]
        assert (
            admission["workflow_contract_digest"]
            == AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        )


def test_authority_plan_rejects_resealed_semantic_expansion() -> None:
    plan, identity, prerequisites, qualification = _plan()
    tampered = deepcopy(plan)
    slots = tampered["slots"]
    assert isinstance(slots, list)
    request = slots[0]["authority_request"]
    request["allowed_effect_classes"] = ["hpc", "provider", "shell"]
    _reseal_slot_and_plan(tampered, ordinal=1)

    with pytest.raises(CutoverEvidenceError) as error:
        validate_aox_attempt_authority_plan(
            tampered,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )

    assert error.value.code == "attempt_authority_slot_request_mismatch"


def test_authority_plan_rejects_declaration_drift_and_invalid_resources() -> None:
    plan, identity, prerequisites, qualification = _plan()

    with pytest.raises(CutoverEvidenceError) as drift:
        validate_aox_attempt_authority_plan(
            plan,
            identity={**identity, "git_commit": "d" * 40},
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    assert drift.value.code == "attempt_authority_plan_digest_mismatch"

    with pytest.raises(CutoverEvidenceError) as resource:
        build_aox_attempt_authority_plan(
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
            expires_at="2099-01-01T00:00:00+00:00",
            max_micu_per_attempt=True,
            max_cost_microunits_per_attempt=20_000,
            max_wall_time_seconds_per_attempt=3_600,
        )
    assert resource.value.code == "attempt_authority_resource_invalid"


def test_authority_plan_rejects_invalid_time_order() -> None:
    identity, prerequisites, qualification = _declarations()

    with pytest.raises(CutoverEvidenceError) as error:
        build_aox_attempt_authority_plan(
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
            issued_at="2099-01-02T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
            max_micu_per_attempt=10_000,
            max_cost_microunits_per_attempt=20_000,
            max_wall_time_seconds_per_attempt=3_600,
        )

    assert error.value.code == "attempt_authority_time_order_invalid"


def test_private_authority_file_has_one_deterministic_consumption_target(
    tmp_path: Path,
) -> None:
    plan, identity, prerequisites, qualification = _plan()
    plan_path = tmp_path / "authority.json"
    publish_aox_attempt_authority_plan(plan, plan_path)

    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o400
    loaded = load_aox_attempt_authority_plan(
        plan_path,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )
    consumption_path = attempt_authority_consumption_path(plan_path)
    assert consumption_path.name == "authority.json.consumed.json"

    with pytest.raises(CutoverEvidenceError) as wrong_target:
        consume_aox_attempt_authority_plan(
            loaded,
            plan_path=plan_path,
            path=tmp_path / "another-receipt.json",
        )
    assert (
        wrong_target.value.code
        == "attempt_authority_consumption_target_mismatch"
    )

    receipt = consume_aox_attempt_authority_plan(
        loaded,
        plan_path=plan_path,
        path=consumption_path,
    )
    assert receipt == {
        "schema_id": AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "plan_schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": plan["plan_digest"],
        "campaign_id": plan["campaign_id"],
        "consumption_file": consumption_path.name,
        "consumed_at": receipt["consumed_at"],
    }
    assert stat.S_IMODE(consumption_path.stat().st_mode) == 0o400

    with pytest.raises(CutoverEvidenceError) as reused:
        consume_aox_attempt_authority_plan(
            loaded,
            plan_path=plan_path,
            path=consumption_path,
        )
    assert reused.value.code == "attempt_authority_publish_target_invalid"


def test_authority_slots_are_atomically_claimed_once_across_campaign_roots(
    tmp_path: Path,
) -> None:
    plan, identity, prerequisites, qualification = _plan()
    plan_path = tmp_path / "authority.json"
    publish_aox_attempt_authority_plan(plan, plan_path)
    loaded = load_aox_attempt_authority_plan(
        plan_path,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )
    consumption = consume_aox_attempt_authority_plan(
        loaded,
        plan_path=plan_path,
        path=attempt_authority_consumption_path(plan_path),
    )

    first = claim_aox_attempt_authority_slot(
        plan=loaded,
        consumption=consumption,
        plan_path=plan_path,
        ordinal=1,
        campaign_root=tmp_path / "campaign-a",
    )
    first_path = attempt_authority_slot_claim_path(plan_path, 1)
    assert stat.S_IMODE(first_path.stat().st_mode) == 0o400
    assert (
        load_aox_attempt_authority_slot_claim(
            first_path,
            plan=loaded,
            consumption=consumption,
            plan_path=plan_path,
            ordinal=1,
            campaign_root=tmp_path / "campaign-a",
        )
        == first
    )

    with pytest.raises(CutoverEvidenceError) as reused:
        claim_aox_attempt_authority_slot(
            plan=loaded,
            consumption=consumption,
            plan_path=plan_path,
            ordinal=1,
            campaign_root=tmp_path / "campaign-b",
        )
    assert reused.value.code == "attempt_authority_publish_target_invalid"

    second = claim_aox_attempt_authority_slot(
        plan=loaded,
        consumption=consumption,
        plan_path=plan_path,
        ordinal=2,
        campaign_root=tmp_path / "campaign-b",
    )
    assert second["ordinal"] == 2
    assert second["attempt_id"] != first["attempt_id"]
