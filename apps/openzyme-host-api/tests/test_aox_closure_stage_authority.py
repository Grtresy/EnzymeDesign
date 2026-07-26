from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import stat

import pytest

import openzyme_host_api.aox_closure_stage_authority as closure_authority
from openzyme_host_api.aox_attempt_authority import (
    build_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    publish_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    build_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    closure_stage_authority_consumption_path,
)
from openzyme_host_api.aox_closure_stage_authority import (
    consume_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    load_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    publish_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    validate_aox_closure_stage_authority_consumption,
)
from openzyme_host_api.aox_closure_stage_authority import (
    validate_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_cutover_evidence import create_blank_world_roots
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_diagnostic_authority import (
    build_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    publish_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    validate_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_ID,
)


def _digest(digit: str) -> str:
    return "sha256:" + digit * 64


def _fixture(
    tmp_path: Path,
) -> dict[str, object]:
    campaign_id = "aox_campaign_" + "1" * 24
    attempt_id = "positive-" + "2" * 32
    campaign_root = tmp_path / f"r59-{campaign_id}"
    attempt_root = campaign_root / attempt_id
    attempt_root.mkdir(parents=True)
    database_path = attempt_root / "control-plane.sqlite3"
    database_path.write_bytes(b"source-db")
    authority_root = tmp_path / "r59-authority"
    authority_root.mkdir()
    authority_path = authority_root / "attempt-authority.json"
    authority_path.write_bytes(b"source-authority")
    consumption_path = authority_root / "attempt-authority.json.consumed.json"
    consumption_path.write_bytes(b"source-consumption")
    ledger_path = tmp_path / "micu-ledger.sqlite3"
    ledger_path.write_bytes(b"ledger")
    source_inventory = {
        "schema_id": AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID,
        "campaign_root": str(campaign_root.resolve()),
        "attempt_root": str(attempt_root.resolve()),
        "database_path": str(database_path.resolve()),
        "authority_plan_path": str(authority_path.resolve()),
        "authority_consumption_path": str(consumption_path.resolve()),
        "campaign_id": campaign_id,
        "attempt_id": attempt_id,
        "session_id": f"sess_formal_{attempt_id.replace('-', '_')}",
        "execution_task_id": (
            f"aox_execution_cutover_{attempt_id.replace('-', '_')}"
        ),
        "executor_agent_id": "agent:executor:" + "3" * 12,
        "selection_id": "selection_" + "4" * 24,
        "operation_universe_digest": _digest("5"),
        "source_root_identity": _digest("6"),
        "database_sha256": _digest("7"),
        "inventory_digest": _digest("8"),
        "frozen_paths_digest": _digest("9"),
        "cut_cursor": 614,
        "first_post_cut_cursor": 615,
    }
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("b"),
    }
    prerequisites = {
        "provider_cache_mode": "bypass",
        "evidence_cache_reuse": False,
    }
    qualification = {
        "schema_id": "aox_architecture_qualification_receipt@1",
        "report_payload_digest": _digest("c"),
    }
    qualification_digest = canonical_digest(qualification)
    contract_bindings = {
        "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "workflow_contract_digest": _digest("d"),
        "sop_digest": _digest("e"),
        "closure_stage_sop_digest": canonical_digest(
            {"label": "closure-stage-sop"}
        ),
        "architecture_qualification_digest": qualification_digest,
        "ui_dist_digest": _digest("f"),
        "source_launch_receipt_digest": _digest("0"),
        "repair_commit": identity["git_commit"],
        "runtime_config_digest": identity["config_digest"],
    }
    runtime_parity = {
        "schema_id": (
            AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID
        ),
        "source_launch_receipt_digest": _digest("0"),
        "model_config_digest": _digest("1"),
        "driver_limits_digest": _digest("2"),
        "writer_policy_digest": _digest("3"),
        "tool_response_policy_digest": _digest("4"),
        "source_supervision_contract_digest": _digest("5"),
        "target_supervision_contract_digest": _digest("7"),
        "public_observation_contract_digest": _digest("6"),
    }
    micu = {
        "schema_id": AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID,
        "provider": "openai-compatible",
        "endpoint_identity": _digest("7"),
        "model": "gpt-5.5",
        "token_scenario": "aox_closure_stage_diagnostic",
        "ledger_path": str(ledger_path.resolve()),
        "ledger_identity": canonical_digest(
            {"ledger_path": str(ledger_path.resolve())}
        ),
        "effective_config_digest": identity["config_digest"],
    }
    target_parent = tmp_path / "closure-stage-targets"
    target_parent.mkdir()
    return {
        "source_inventory": source_inventory,
        "target_parent": target_parent,
        "identity": identity,
        "allowed_prerequisites": prerequisites,
        "architecture_qualification": qualification,
        "contract_bindings": contract_bindings,
        "runtime_parity": runtime_parity,
        "micu": micu,
        "browser_observation_receipt": None,
    }


def _build(values: dict[str, object]) -> dict[str, object]:
    return build_aox_closure_stage_authority_plan(
        **values,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=10_000,
        max_cost_microunits=20_000,
        max_wall_time_seconds=3_600,
    )


def _validate(
    plan: dict[str, object],
    values: dict[str, object],
    *,
    process_epoch: str | None = None,
) -> dict[str, object]:
    return validate_aox_closure_stage_authority_plan(
        plan,
        **values,
        process_epoch=process_epoch or str(plan["process_epoch"]),
    )


def test_closure_stage_plan_is_fresh_non_numbered_and_schema_disjoint(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    plan = _build(values)

    assert _validate(plan, values) == plan
    assert plan["schema_id"] == AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
    assert (
        plan["run_class"]
        == AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
    )
    assert plan["acceptance_eligible"] is False
    assert plan["browser_observation_receipt"] is None
    assert str(plan["diagnostic_id"]).startswith("aox_closure_stage_")
    assert str(plan["root_namespace"]).startswith("aox-closure-stage-")
    assert not Path(str(plan["target_root"])).exists()
    assert "r59" not in Path(str(plan["target_root"])).name
    slot = plan["slot"]
    assert isinstance(slot, dict)
    assert str(slot["attempt_id"]).startswith("closure-stage-")
    assert str(slot["session_id"]).startswith("sess_closure_stage_")
    assert str(slot["task_id"]).startswith(
        "aox_execution_closure_stage_"
    )
    assert str(slot["lane_id"]).startswith("lane_aox_closure_stage_")
    assert str(slot["authority_request"]["root_ref"]).startswith(
        "closure-stage-attempts/"
    )

    with pytest.raises(CutoverEvidenceError) as formal_rejection:
        validate_aox_attempt_authority_plan(
            plan,
            identity=values["identity"],
            allowed_prerequisites=values["allowed_prerequisites"],
            architecture_qualification=values["architecture_qualification"],
        )
    assert (
        formal_rejection.value.code
        == "attempt_authority_plan_schema_invalid"
    )
    with pytest.raises(CutoverEvidenceError) as diagnostic_rejection:
        validate_aox_diagnostic_authority_plan(
            plan,
            identity=values["identity"],
            allowed_prerequisites=values["allowed_prerequisites"],
            architecture_qualification=values["architecture_qualification"],
        )
    assert (
        diagnostic_rejection.value.code
        == "diagnostic_authority_plan_schema_invalid"
    )
    with pytest.raises(CutoverEvidenceError) as blank_world_rejection:
        create_blank_world_roots(
            Path(str(plan["target_root"])),
            attempt_kind="positive",
            allowed_prerequisites={},
            architecture_qualification={},
            attempt_id=str(slot["attempt_id"]),
            run_class=AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC,
        )
    assert (
        blank_world_rejection.value.code
        == "closure_stage_blank_world_forbidden"
    )
    assert not Path(str(plan["target_root"])).exists()


def test_closure_stage_authority_binds_one_fresh_external_browser_target(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    browser_parent = tmp_path / "browser-observations"
    browser_parent.mkdir()
    browser_target = browser_parent / "closure-stage-observation.json"
    browser_values = {
        **values,
        "browser_observation_receipt": browser_target,
    }

    plan = _build(browser_values)

    assert plan["browser_observation_receipt"] == str(
        browser_target.resolve()
    )
    assert _validate(plan, browser_values) == plan
    assert not browser_target.exists()

    other_parent = tmp_path / "other-browser-observations"
    other_parent.mkdir()
    substituted = {
        **browser_values,
        "browser_observation_receipt": other_parent / "receipt.json",
    }
    with pytest.raises(CutoverEvidenceError) as mismatch:
        _validate(plan, substituted)
    assert mismatch.value.code == (
        "closure_stage_authority_plan_binding_mismatch"
    )

    source = values["source_inventory"]
    assert isinstance(source, dict)
    with pytest.raises(CutoverEvidenceError) as source_overlap:
        _build(
            {
                **values,
                "browser_observation_receipt": (
                    Path(str(source["campaign_root"]))
                    / "browser-observation.json"
                ),
            }
        )
    assert source_overlap.value.code == (
        "closure_stage_browser_target_source_overlap"
    )


def test_closure_stage_authority_publish_load_consume_once_without_root(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    plan = _build(values)
    plan_path = tmp_path / "closure-stage-authority.json"

    publish_aox_closure_stage_authority_plan(plan, plan_path)

    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o400
    assert not Path(str(plan["target_root"])).exists()
    loaded = load_aox_closure_stage_authority_plan(
        plan_path,
        **values,
        process_epoch=str(plan["process_epoch"]),
    )
    consumption_path = closure_stage_authority_consumption_path(plan_path)
    assert consumption_path.name.endswith(
        ".closure-stage-consumed.json"
    )
    with pytest.raises(CutoverEvidenceError) as wrong_target:
        consume_aox_closure_stage_authority_plan(
            loaded,
            plan_path=plan_path,
            path=tmp_path / "wrong-consumption.json",
        )
    assert (
        wrong_target.value.code
        == "closure_stage_authority_consumption_target_mismatch"
    )

    receipt = consume_aox_closure_stage_authority_plan(
        loaded,
        plan_path=plan_path,
        path=consumption_path,
    )

    assert (
        receipt["schema_id"]
        == AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
    )
    assert receipt["acceptance_eligible"] is False
    assert receipt["target_root"] == plan["target_root"]
    assert receipt["process_epoch"] == plan["process_epoch"]
    assert stat.S_IMODE(consumption_path.stat().st_mode) == 0o400
    assert (
        validate_aox_closure_stage_authority_consumption(
            receipt,
            plan=loaded,
            plan_path=plan_path,
        )
        == receipt
    )
    assert not Path(str(plan["target_root"])).exists()

    with pytest.raises(CutoverEvidenceError) as replay:
        consume_aox_closure_stage_authority_plan(
            loaded,
            plan_path=plan_path,
            path=consumption_path,
        )
    assert replay.value.code == "attempt_authority_publish_target_invalid"


def test_closure_stage_authority_rejects_expiry_and_substitution(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    with pytest.raises(CutoverEvidenceError) as expired:
        build_aox_closure_stage_authority_plan(
            **values,
            issued_at="2020-01-01T00:00:00+00:00",
            expires_at="2020-01-02T00:00:00+00:00",
            max_micu=1,
            max_cost_microunits=1,
            max_wall_time_seconds=1,
        )
    assert expired.value.code == "closure_stage_authority_expired"

    plan = _build(values)
    other_target_parent = tmp_path / "other-targets"
    other_target_parent.mkdir()
    with pytest.raises(CutoverEvidenceError) as target_mismatch:
        validate_aox_closure_stage_authority_plan(
            plan,
            **{
                **values,
                "target_parent": other_target_parent,
            },
            process_epoch=str(plan["process_epoch"]),
        )
    assert (
        target_mismatch.value.code
        == "closure_stage_authority_identity_invalid"
    )
    with pytest.raises(CutoverEvidenceError) as process_mismatch:
        _validate(
            plan,
            values,
            process_epoch="closure-stage-process-" + "f" * 32,
        )
    assert (
        process_mismatch.value.code
        == "closure_stage_authority_identity_invalid"
    )
    stale_identity = deepcopy(values)
    stale_identity["identity"] = {
        **values["identity"],
        "git_commit": "f" * 40,
    }
    with pytest.raises(CutoverEvidenceError) as stale:
        _validate(plan, stale_identity)
    assert stale.value.code == "closure_stage_contract_binding_mismatch"

    forged = deepcopy(plan)
    forged["acceptance_eligible"] = True
    with pytest.raises(CutoverEvidenceError) as adoptable:
        _validate(forged, values)
    assert (
        adoptable.value.code
        == "closure_stage_authority_plan_schema_invalid"
    )


def test_closure_stage_authority_rejects_cross_class_and_source_authority_reuse(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    closure = _build(values)
    formal = build_aox_attempt_authority_plan(
        identity=values["identity"],
        allowed_prerequisites=values["allowed_prerequisites"],
        architecture_qualification=values["architecture_qualification"],
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=1,
        max_cost_microunits_per_attempt=1,
        max_wall_time_seconds_per_attempt=1,
    )
    diagnostic = build_aox_diagnostic_authority_plan(
        identity=values["identity"],
        allowed_prerequisites=values["allowed_prerequisites"],
        architecture_qualification=values["architecture_qualification"],
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=1,
        max_cost_microunits=1,
        max_wall_time_seconds=1,
    )
    with pytest.raises(CutoverEvidenceError) as closure_rejects_formal:
        publish_aox_closure_stage_authority_plan(
            formal,
            tmp_path / "formal-as-closure.json",
        )
    assert (
        closure_rejects_formal.value.code
        == "closure_stage_authority_plan_class_mismatch"
    )
    with pytest.raises(CutoverEvidenceError) as formal_rejects_closure:
        publish_aox_attempt_authority_plan(
            closure,
            tmp_path / "closure-as-formal.json",
        )
    assert (
        formal_rejects_closure.value.code
        == "attempt_authority_plan_class_mismatch"
    )
    with pytest.raises(CutoverEvidenceError) as diagnostic_rejects_closure:
        publish_aox_diagnostic_authority_plan(
            closure,
            tmp_path / "closure-as-diagnostic.json",
        )
    assert (
        diagnostic_rejects_closure.value.code
        == "diagnostic_authority_plan_class_mismatch"
    )
    with pytest.raises(CutoverEvidenceError) as closure_rejects_diagnostic:
        publish_aox_closure_stage_authority_plan(
            diagnostic,
            tmp_path / "diagnostic-as-closure.json",
        )
    assert (
        closure_rejects_diagnostic.value.code
        == "closure_stage_authority_plan_class_mismatch"
    )

    source = values["source_inventory"]
    assert isinstance(source, dict)
    source_authority = Path(str(source["authority_plan_path"]))
    with pytest.raises(CutoverEvidenceError) as source_publish:
        publish_aox_closure_stage_authority_plan(
            closure,
            source_authority,
        )
    assert (
        source_publish.value.code
        == "closure_stage_source_authority_reuse_forbidden"
    )
    with pytest.raises(CutoverEvidenceError) as source_consume:
        consume_aox_closure_stage_authority_plan(
            closure,
            plan_path=source_authority,
            path=closure_stage_authority_consumption_path(source_authority),
        )
    assert (
        source_consume.value.code
        == "closure_stage_source_authority_reuse_forbidden"
    )


def test_closure_stage_authority_rejects_mutable_source_paths(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    source = dict(values["source_inventory"])
    source_campaign = Path(str(source["campaign_root"]))
    source_ledger = Path(str(source["database_path"]))
    micu = dict(values["micu"])
    micu["ledger_path"] = str(source_ledger.resolve())
    micu["ledger_identity"] = canonical_digest(
        {"ledger_path": str(source_ledger.resolve())}
    )

    with pytest.raises(CutoverEvidenceError) as ledger_overlap:
        _build({**values, "micu": micu})

    assert ledger_overlap.value.code == (
        "closure_stage_micu_ledger_source_overlap"
    )

    plan = _build(values)
    forbidden_output = source_campaign / "new-closure-authority.json"
    with pytest.raises(CutoverEvidenceError) as output_overlap:
        publish_aox_closure_stage_authority_plan(
            plan,
            forbidden_output,
        )

    assert output_overlap.value.code == (
        "closure_stage_authority_output_source_overlap"
    )
    assert not forbidden_output.exists()


def test_closure_stage_outputs_stay_outside_checkout_but_pinned_ledger_may_live_inside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(closure_authority, "REPO_ROOT", checkout)
    values = _fixture(tmp_path)

    browser_parent = checkout / "browser"
    browser_parent.mkdir()
    with pytest.raises(CutoverEvidenceError) as browser:
        _build(
            {
                **values,
                "browser_observation_receipt": (
                    browser_parent / "observation.json"
                ),
            }
        )
    assert browser.value.code == (
        "closure_stage_browser_target_inside_checkout"
    )

    ledger = checkout / "micu-ledger.sqlite3"
    ledger.write_bytes(b"ledger")
    micu = {
        **values["micu"],
        "ledger_path": str(ledger.resolve()),
        "ledger_identity": canonical_digest(
            {"ledger_path": str(ledger.resolve())}
        ),
    }
    pinned_ledger_plan = _build({**values, "micu": micu})
    assert pinned_ledger_plan["micu"]["ledger_path"] == str(
        ledger.resolve()
    )

    target_parent = checkout / "targets"
    target_parent.mkdir()
    with pytest.raises(CutoverEvidenceError) as target:
        _build({**values, "target_parent": target_parent})
    assert target.value.code == "closure_stage_target_inside_checkout"

    plan = _build(values)
    with pytest.raises(CutoverEvidenceError) as authority_output:
        publish_aox_closure_stage_authority_plan(
            plan,
            checkout / "closure-stage-authority.json",
        )
    assert authority_output.value.code == (
        "closure_stage_authority_output_inside_checkout"
    )


def test_closure_stage_micu_binding_reproduces_path_and_config_identity(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    micu = dict(values["micu"])
    micu["ledger_identity"] = _digest("0")

    with pytest.raises(CutoverEvidenceError) as ledger_identity:
        _build({**values, "micu": micu})

    assert ledger_identity.value.code == (
        "closure_stage_micu_binding_identity_invalid"
    )

    micu = dict(values["micu"])
    micu["effective_config_digest"] = _digest("0")
    with pytest.raises(CutoverEvidenceError) as config_identity:
        _build({**values, "micu": micu})

    assert config_identity.value.code == (
        "closure_stage_micu_binding_identity_invalid"
    )
