from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from openzyme_host_api.aox_architecture_qualification import (
    AoxArchitectureQualificationError,
)
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_attempt_authority import (
    attempt_authority_consumption_path,
    build_aox_attempt_authority_plan,
    claim_aox_attempt_authority_slot,
    consume_aox_attempt_authority_plan,
    publish_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_cutover_evidence import (
    AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
    CutoverEvidenceError,
    KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS,
    KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS,
    canonical_json_bytes,
)
from openzyme_host_api.aox_launch_profile import build_aox_cutover_launch_profile
from openzyme_host_api.aox_preflight_failure import (
    FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID,
    FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID,
    evaluate_formal_preflight_failure,
    formal_preflight_failure_path,
    seal_formal_preflight_failure,
    seal_formal_preflight_failure_decision,
    verify_formal_preflight_failure,
)
from openzyme_pipeline import aox_reference
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime.reliability import ControlledOperationOwnerPolicy


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _sources(
    tmp_path: Path,
    *,
    historical_qualification: bool = False,
) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": "workflow:aox-hmm-live@1.0.0#" + _digest("workflow"),
        "scoring_contract_digest": _digest("scoring-contract"),
        "scoring_implementation_digest": _digest("scoring-implementation"),
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }
    hmmer_digest = _digest("hmmer")
    prerequisites = {
        "git_commit": identity["git_commit"],
        "config_digest": identity["config_digest"],
        "workflow_ref": identity["workflow_ref"],
        "image_digest": identity["image_digest"],
        "sdk_digest": identity["sdk_digest"],
        "toolchain_image_digests": {
            contract["toolchain_id"]: (
                hmmer_digest
                if name in {"hmmbuild", "hmmalign"}
                else _digest(f"{name}-image")
            )
            for name, contract in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.items()
        },
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi"),
        "prompt_accessions": {
            "formal_ncbi": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
            "probe_ncbi": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "probe_uniprot": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
        },
    }
    qualification = build_architecture_qualification_receipt(
        report_payload_digest=_digest("qualification-report"),
        registry_digest=_digest("qualification-registry"),
        test_manifest_digest=_digest("qualification-manifest"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit=str(identity["git_commit"]),
        report_schema_id="openzyme_v3_architecture_qualification_report@3",
        run_evidence_digest=_digest("qualification-run"),
        source_identity_digest=_digest("qualification-source"),
        owner_constraint_registry_digest=_digest("owner-registry"),
        transformation_results_digest=_digest("transformations"),
    )
    if historical_qualification:
        qualification.pop("owner_constraint_registry_digest")
        qualification.pop("transformation_results_digest")
        qualification["schema_id"] = "aox_architecture_qualification_receipt@2"
        qualification["report_schema_id"] = (
            "openzyme_v3_architecture_qualification_report@2"
        )
        preimage = {
            key: value
            for key, value in qualification.items()
            if key != "receipt_digest"
        }
        qualification["receipt_digest"] = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()
        )
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
    profile = build_aox_cutover_launch_profile(
        settings=settings,
        ledger_path=tmp_path / "micu-ledger.json",
        source_commit=str(identity["git_commit"]),
        config_digest=str(identity["config_digest"]),
        created_at="2026-08-08T00:00:00+00:00",
    )
    plan = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        launch_profile=profile,
        issued_at="2026-08-08T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=100,
        max_cost_microunits_per_attempt=100,
        max_wall_time_seconds_per_attempt=600,
    )
    plan_path = tmp_path / "attempt-authority.json"
    publish_aox_attempt_authority_plan(plan, plan_path)
    consumption = consume_aox_attempt_authority_plan(
        plan,
        plan_path=plan_path,
        path=attempt_authority_consumption_path(plan_path),
    )
    return {
        "identity": identity,
        "prerequisites": prerequisites,
        "qualification": qualification,
        "profile": profile,
        "plan": plan,
        "plan_path": plan_path,
        "consumption": consumption,
    }


def _failure() -> dict[str, object]:
    return {
        "schema_id": "aox_cutover_launch_failure@3",
        "status": "failed",
        "failure_code": "aox_launch_effective_config_schema_invalid",
        "failure_details": {
            "kind": "schema_field",
            "identity": (
                "effective_config.reliability.controlled_operation_owner_policy"
            ),
        },
    }


def _seal(
    tmp_path: Path,
    *,
    failure: dict[str, object] | None = None,
) -> tuple[Path, str, dict[str, object]]:
    sources = _sources(tmp_path)
    campaign_root = tmp_path / "campaign"
    campaign_root.mkdir(mode=0o700)
    path, digest = seal_formal_preflight_failure(
        plan_path=sources["plan_path"],
        campaign_root=campaign_root,
        slot_ordinal=1,
        identity=sources["identity"],
        allowed_prerequisites=sources["prerequisites"],
        architecture_qualification=sources["qualification"],
        launch_profile=sources["profile"],
        authority_plan=sources["plan"],
        authority_consumption=sources["consumption"],
        failure=_failure() if failure is None else failure,
        sealed_at="2026-08-08T00:01:00+00:00",
    )
    return path, digest, sources


def test_preflight_failure_preserves_closed_sandbox_runtime_cause(
    tmp_path: Path,
) -> None:
    failure = {
        "schema_id": "aox_cutover_launch_failure@3",
        "status": "failed",
        "failure_code": "aox_launch_sandbox_preflight_failed",
        "failure_details": {
            "kind": "sandbox_runtime",
            "failure_code": "podman_rootless_preflight_failed",
        },
    }
    path, _, _ = _seal(tmp_path, failure=failure)

    verification = verify_formal_preflight_failure(path)
    decision = evaluate_formal_preflight_failure(path)

    assert verification.passed is True
    assert decision["blocker"] == {
        "code": "aox_launch_sandbox_preflight_failed",
        "identity": "sandbox_runtime.podman_rootless_preflight_failed",
        "message": (
            "the consumed authority failed before slot claim, campaign attempt "
            "root creation, Host startup, or scientific attempt creation"
        ),
    }

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["failure"]["failure_details"]["failure_code"] = (
        "private_runtime_/home/operator"
    )
    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(tampered) + b"\n")
    invalid = verify_formal_preflight_failure(path)
    assert invalid.passed is False
    assert invalid.issue is not None
    assert invalid.issue.code == "formal_preflight_failure_cause_invalid"


def test_preflight_failure_closes_consumed_authority_without_launch(
    tmp_path: Path,
) -> None:
    path, digest, sources = _seal(tmp_path)

    assert path == formal_preflight_failure_path(sources["plan_path"], 1)
    verification = verify_formal_preflight_failure(path)
    assert verification.passed is True
    assert verification.failure_digest == digest
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["schema_id"] == FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID
    assert "launch_id" not in receipt
    assert receipt["effect_closure"] == {
        "effect_certainty": "no_effect",
        "slot_claim_created": False,
        "campaign_attempt_root_created": False,
        "host_started": False,
        "session_created": False,
        "scientific_attempt_count": 0,
        "micu_delta": 0,
        "provider_dispatch_started": False,
        "runner_dispatch_started": False,
        "hpc_dispatch_started": False,
        "browser_action_started": False,
    }

    decision = evaluate_formal_preflight_failure(
        path,
        decided_at="2026-08-08T00:02:00+00:00",
    )
    assert decision["schema_id"] == FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID
    assert decision["decision"] == "NO-GO"
    assert decision["attempt_ids"] == []
    assert decision["attempt_digests"] == []
    assert "launch_id" not in decision
    decision_path = tmp_path / "campaign-decision.json"
    assert (
        seal_formal_preflight_failure_decision(decision, decision_path)
        == decision["decision_digest"]
    )


def test_preflight_failure_rejects_claimed_or_nonpristine_slot(
    tmp_path: Path,
) -> None:
    claimed_sources = _sources(tmp_path / "claimed")
    claim_aox_attempt_authority_slot(
        plan=claimed_sources["plan"],
        consumption=claimed_sources["consumption"],
        plan_path=claimed_sources["plan_path"],
        ordinal=1,
        campaign_root=tmp_path / "claimed-campaign",
    )
    with pytest.raises(CutoverEvidenceError) as claimed:
        seal_formal_preflight_failure(
            plan_path=claimed_sources["plan_path"],
            campaign_root=tmp_path / "claimed-campaign",
            slot_ordinal=1,
            identity=claimed_sources["identity"],
            allowed_prerequisites=claimed_sources["prerequisites"],
            architecture_qualification=claimed_sources["qualification"],
            launch_profile=claimed_sources["profile"],
            authority_plan=claimed_sources["plan"],
            authority_consumption=claimed_sources["consumption"],
            failure=_failure(),
        )
    assert claimed.value.code == "formal_preflight_failure_claim_exists"

    dirty_sources = _sources(tmp_path / "dirty")
    dirty_root = tmp_path / "dirty-campaign"
    dirty_root.mkdir(mode=0o700)
    (dirty_root / "unexpected").write_text("state", encoding="utf-8")
    with pytest.raises(CutoverEvidenceError) as dirty:
        seal_formal_preflight_failure(
            plan_path=dirty_sources["plan_path"],
            campaign_root=dirty_root,
            slot_ordinal=1,
            identity=dirty_sources["identity"],
            allowed_prerequisites=dirty_sources["prerequisites"],
            architecture_qualification=dirty_sources["qualification"],
            launch_profile=dirty_sources["profile"],
            authority_plan=dirty_sources["plan"],
            authority_consumption=dirty_sources["consumption"],
            failure=_failure(),
        )
    assert dirty.value.code == "formal_preflight_failure_root_not_pristine"


def test_preflight_failure_verifier_detects_authority_source_drift(
    tmp_path: Path,
) -> None:
    path, _, sources = _seal(tmp_path)
    plan_path = sources["plan_path"]
    plan_path.chmod(0o600)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["campaign_id"] = "aox_campaign_tampered"
    plan_path.write_bytes(canonical_json_bytes(plan) + b"\n")
    plan_path.chmod(0o400)

    verification = verify_formal_preflight_failure(path)
    assert verification.passed is False
    assert verification.issue is not None
    assert verification.issue.code == (
        "formal_preflight_failure_source_digest_mismatch"
    )


def test_preflight_failure_rejects_historical_qualification_source(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path, historical_qualification=True)

    with pytest.raises(AoxArchitectureQualificationError) as historical:
        seal_formal_preflight_failure(
            plan_path=sources["plan_path"],
            campaign_root=tmp_path / "campaign",
            slot_ordinal=1,
            identity=sources["identity"],
            allowed_prerequisites=sources["prerequisites"],
            architecture_qualification=sources["qualification"],
            launch_profile=sources["profile"],
            authority_plan=sources["plan"],
            authority_consumption=sources["consumption"],
            failure=_failure(),
        )

    assert historical.value.code == (
        "aox_architecture_qualification_receipt_version_unsupported"
    )


def test_preflight_failure_cannot_backfill_historical_authority_schemas(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path)
    plan_path = sources["plan_path"]
    consumption_path = attempt_authority_consumption_path(plan_path)
    plan = deepcopy(sources["plan"])
    plan.pop("launch_profile_digest")
    plan["schema_id"] = "aox_live_attempt_authority_plan@3"
    plan_preimage = {
        key: value for key, value in plan.items() if key != "plan_digest"
    }
    plan["plan_digest"] = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(plan_preimage)).hexdigest()
    )
    consumption = deepcopy(sources["consumption"])
    consumption["schema_id"] = "aox_live_attempt_authority_consumption@4"
    consumption["plan_schema_id"] = "aox_live_attempt_authority_plan@3"
    consumption["plan_digest"] = plan["plan_digest"]
    for path, value in ((plan_path, plan), (consumption_path, consumption)):
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value) + b"\n")
        path.chmod(0o400)

    with pytest.raises(CutoverEvidenceError) as historical:
        seal_formal_preflight_failure(
            plan_path=plan_path,
            campaign_root=tmp_path / "campaign",
            slot_ordinal=1,
            identity=sources["identity"],
            allowed_prerequisites=sources["prerequisites"],
            architecture_qualification=sources["qualification"],
            launch_profile=sources["profile"],
            authority_plan=plan,
            authority_consumption=consumption,
            failure=_failure(),
        )

    assert historical.value.code == "formal_preflight_failure_semantics_invalid"
