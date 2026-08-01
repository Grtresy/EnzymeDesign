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
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_consumption,
)
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_slot_claim,
)
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass
from openzyme_host_api.aox_live_run_class import FORMAL_ACCEPTANCE_RUN_POLICY
from openzyme_host_api.aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError


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


def _legacy_plan() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    identity, prerequisites, qualification = _declarations()
    identity_digest = canonical_digest(identity)
    campaign_id = "aox_campaign_" + "1" * 24
    slots: list[dict[str, object]] = []
    for ordinal, attempt_kind in enumerate(
        ("positive", "positive", "fault"),
        start=1,
    ):
        attempt_id = f"{attempt_kind}-{ordinal:032x}"
        session_id, task_id, lane_id, root_ref = (
            FORMAL_ACCEPTANCE_RUN_POLICY.identities(attempt_id)
        )
        scope = "fault" if attempt_kind == "fault" else "formal"
        envelope_id, request_digest, request = (
            scientific_attempt_authorization_identity(
                session_id=session_id,
                task_id=task_id,
                campaign_id=campaign_id,
                workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
                root_ref=root_ref,
                grantor_kind="operator",
                grantor_ref="user:local-dev",
                allowed_scopes=(scope,),
                allowed_effect_classes=("hpc", "provider"),
                allowed_providers=(f"aox-provider-routes@{identity_digest}",),
                allowed_hpc_targets=(f"aox-hpc-routes@{identity_digest}",),
                max_attempts=1,
                max_micu=10_000,
                max_cost_microunits=20_000,
                max_wall_time_seconds=3_600,
                expires_at="2099-01-01T00:00:00+00:00",
                idempotency_key=f"{campaign_id}:authority:{ordinal}",
            )
        )
        slots.append(
            {
                "ordinal": ordinal,
                "attempt_kind": attempt_kind,
                "attempt_id": attempt_id,
                "session_id": session_id,
                "task_id": task_id,
                "lane_id": lane_id,
                "scope": scope,
                "authority_request": request,
                "envelope_id": envelope_id,
                "request_digest": request_digest,
            }
        )
    payload: dict[str, object] = {
        "schema_id": "aox_live_attempt_authority_plan@1",
        "campaign_id": campaign_id,
        "identity_digest": identity_digest,
        "allowed_prerequisite_digest": canonical_digest(prerequisites),
        "architecture_qualification_digest": canonical_digest(qualification),
        "issued_at": "2026-07-23T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "slots": slots,
    }
    return (
        {**payload, "plan_digest": canonical_digest(payload)},
        identity,
        prerequisites,
        qualification,
    )


def test_authority_plan_binds_three_one_use_launch_slots() -> None:
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
    assert len({slot["session_id"] for slot in slots}) == 3
    assert len({slot["task_id"] for slot in slots}) == 3
    assert len({slot["root_ref"] for slot in slots}) == 3
    assert len({slot["envelope_id"] for slot in slots}) == 3
    for slot in slots:
        assert "attempt_id" not in slot
        assert "lane_id" not in slot
        request = slot["authority_request"]
        assert request["max_attempts"] == 1
        assert request["allowed_effect_classes"] == ["hpc", "provider"]
        assert request["root_ref"] == slot["root_ref"]
        assert str(slot["root_ref"]).startswith(
            f"formal-slots/{plan['campaign_id']}/{slot['ordinal']}/"
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
    assert second["launch_id"] != first["launch_id"]
    assert second["root_ref"] != first["root_ref"]
    assert "attempt_id" not in first
    assert "lane_id" not in first


def test_legacy_launch_schemas_are_readable_but_cannot_be_reemitted(
    tmp_path: Path,
) -> None:
    plan, identity, prerequisites, qualification = _legacy_plan()
    plan_path = tmp_path / "legacy-authority.json"
    validated = validate_aox_attempt_authority_plan(
        plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )
    consumption = {
        "schema_id": "aox_live_attempt_authority_consumption@2",
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "plan_schema_id": "aox_live_attempt_authority_plan@1",
        "plan_digest": plan["plan_digest"],
        "campaign_id": plan["campaign_id"],
        "consumption_file": attempt_authority_consumption_path(plan_path).name,
        "consumed_at": "2026-07-23T00:00:01+00:00",
    }
    validated_consumption = validate_aox_attempt_authority_consumption(
        consumption,
        plan=validated,
        plan_path=plan_path,
    )
    slot = validated["slots"][0]
    campaign_root = tmp_path / "legacy-campaign"
    claim_payload = {
        "schema_id": "aox_attempt_authority_slot_claim@1",
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "campaign_id": plan["campaign_id"],
        "plan_digest": plan["plan_digest"],
        "consumption_digest": canonical_digest(consumption),
        "ordinal": 1,
        "attempt_kind": slot["attempt_kind"],
        "attempt_id": slot["attempt_id"],
        "session_id": slot["session_id"],
        "task_id": slot["task_id"],
        "lane_id": slot["lane_id"],
        "envelope_id": slot["envelope_id"],
        "request_digest": slot["request_digest"],
        "campaign_root_identity": canonical_digest(
            {"campaign_root": str(campaign_root.absolute())}
        ),
        "claim_file": attempt_authority_slot_claim_path(plan_path, 1).name,
        "claimed_at": "2026-07-23T00:00:02+00:00",
    }
    claim = {**claim_payload, "claim_digest": canonical_digest(claim_payload)}

    assert validated_consumption == consumption
    assert (
        validate_aox_attempt_authority_slot_claim(
            claim,
            plan=validated,
            consumption=consumption,
            plan_path=plan_path,
            ordinal=1,
            campaign_root=campaign_root,
        )
        == claim
    )
    with pytest.raises(CutoverEvidenceError) as consume_legacy:
        consume_aox_attempt_authority_plan(
            validated,
            plan_path=plan_path,
            path=attempt_authority_consumption_path(plan_path),
        )
    assert consume_legacy.value.code == "attempt_authority_plan_class_mismatch"
    with pytest.raises(CutoverEvidenceError) as claim_legacy:
        claim_aox_attempt_authority_slot(
            plan=validated,
            consumption=consumption,
            plan_path=plan_path,
            ordinal=1,
            campaign_root=campaign_root,
        )
    assert claim_legacy.value.code == "attempt_authority_slot_claim_invalid"
