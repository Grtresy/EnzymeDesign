from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import stat

import pytest
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
from openzyme_host_api.aox_attempt_authority import authority_grant_identity
from openzyme_host_api.aox_attempt_authority import authority_grant_payload
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
from openzyme_host_api.aox_launch_profile import build_aox_cutover_launch_profile
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime.reliability import ControlledOperationOwnerPolicy


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


def _launch_profile() -> dict[str, object]:
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        reliability=replace(
            settings.reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
        ),
    )
    return build_aox_cutover_launch_profile(
        settings=settings,
        ledger_path=Path("/tmp/aox-authority-ledger.json"),
        source_commit="a" * 40,
        config_digest="sha256:" + "b" * 64,
        created_at="2026-07-23T00:00:00+00:00",
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
        launch_profile=_launch_profile(),
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
    policy = slot["authority_policy"]
    assert isinstance(policy, dict)
    slot["authority_policy_digest"] = canonical_digest(policy)
    plan["plan_digest"] = canonical_digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )


def test_authority_plan_binds_three_one_use_launch_slots() -> None:
    plan, identity, prerequisites, qualification = _plan()

    validated = validate_aox_attempt_authority_plan(
        plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        launch_profile=_launch_profile(),
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
    assert len({slot["root_ref"] for slot in slots}) == 3
    for slot in slots:
        assert "attempt_id" not in slot
        assert "lane_id" not in slot
        assert "task_id" not in slot
        assert "envelope_id" not in slot
        assert "request_digest" not in slot
        policy = slot["authority_policy"]
        assert policy["max_attempts"] == 1
        assert policy["allowed_effect_classes"] == ["hpc", "provider"]
        assert slot["authority_policy_digest"] == canonical_digest(policy)
        assert str(slot["root_ref"]).startswith(
            f"formal-slots/{plan['campaign_id']}/{slot['ordinal']}/"
        )


def test_authority_plan_rejects_resealed_semantic_expansion() -> None:
    plan, identity, prerequisites, qualification = _plan()
    tampered = deepcopy(plan)
    slots = tampered["slots"]
    assert isinstance(slots, list)
    policy = slots[0]["authority_policy"]
    policy["allowed_effect_classes"] = ["hpc", "provider", "shell"]
    _reseal_slot_and_plan(tampered, ordinal=1)

    with pytest.raises(CutoverEvidenceError) as error:
        validate_aox_attempt_authority_plan(
            tampered,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
            launch_profile=_launch_profile(),
        )

    assert error.value.code == "attempt_authority_slot_policy_mismatch"


def test_authority_grant_late_binds_only_the_canonical_execution_task() -> None:
    plan, *_ = _plan()
    slot = plan["slots"][0]
    first = authority_grant_identity(
        slot,
        campaign_id=str(plan["campaign_id"]),
        task_id="task_agent_selected_execution",
    )
    second = authority_grant_identity(
        slot,
        campaign_id=str(plan["campaign_id"]),
        task_id="task_other_execution",
    )

    assert first[0] != second[0]
    assert first[1] != second[1]
    assert first[2]["task_id"] == "task_agent_selected_execution"
    assert authority_grant_payload(
        slot,
        campaign_id=str(plan["campaign_id"]),
        task_id="task_agent_selected_execution",
    )["task_id"] == "task_agent_selected_execution"


def test_authority_plan_rejects_declaration_drift_and_invalid_resources() -> None:
    plan, identity, prerequisites, qualification = _plan()

    with pytest.raises(CutoverEvidenceError) as drift:
        validate_aox_attempt_authority_plan(
            plan,
            identity={**identity, "git_commit": "d" * 40},
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
            launch_profile=_launch_profile(),
        )
    assert drift.value.code == "attempt_authority_plan_digest_mismatch"

    with pytest.raises(CutoverEvidenceError) as resource:
        build_aox_attempt_authority_plan(
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
            launch_profile=_launch_profile(),
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
            launch_profile=_launch_profile(),
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
        launch_profile=_launch_profile(),
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
        launch_profile=_launch_profile(),
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
    assert "task_id" not in first
    assert "envelope_id" not in first
    assert "request_digest" not in first


@pytest.mark.parametrize(
    "schema_id",
    (
        "aox_live_attempt_authority_plan@1",
        "aox_live_attempt_authority_plan@2",
        "aox_live_attempt_authority_plan@3",
    ),
)
def test_prebound_launch_schemas_are_not_reusable(schema_id: str) -> None:
    plan, identity, prerequisites, qualification = _plan()
    plan["schema_id"] = schema_id
    plan["plan_digest"] = canonical_digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )

    with pytest.raises(CutoverEvidenceError) as error:
        validate_aox_attempt_authority_plan(
            plan,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
            launch_profile=_launch_profile(),
        )

    assert error.value.code == "attempt_authority_plan_schema_invalid"
