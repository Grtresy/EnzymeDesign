from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import pickle
import stat
from types import SimpleNamespace

import pytest

from openzyme_core import MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_host_api import aox_closure_stage_live as closure_stage_live
from openzyme_host_api.aox_attempt_supervision import SUPERVISION_SCHEMA_ID
from openzyme_host_api.aox_attempt_supervision import SUPERVISION_SCHEMA_ID_V2
from openzyme_host_api.aox_attempt_supervision import (
    SUPERVISION_RECEIPT_SCHEMA_ID,
)
from openzyme_host_api.aox_attempt_supervision import (
    supervision_contract_digest,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_live import (
    AOX_CLOSURE_STAGE_CHILD_EVIDENCE_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_live import (
    AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_live import (
    AOX_CLOSURE_STAGE_LIVE_RESULT_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_live import (
    AOX_CLOSURE_STAGE_PARITY_RECEIPT_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_live import (
    ClosureStageLiveRunner,
)
from openzyme_host_api.aox_closure_stage_live import (
    _closure_stage_browser_anchor,
)
from openzyme_host_api.aox_closure_stage_live import (
    _closure_stage_runtime_summary,
)
from openzyme_host_api.aox_closure_stage_live import _effect_delta
from openzyme_host_api.aox_closure_stage_live import _sha256_file
from openzyme_host_api.aox_closure_stage_live import (
    build_aox_closure_stage_diagnostic_decision,
)
from openzyme_host_api.aox_closure_stage_live import (
    build_aox_closure_stage_live_result,
)
from openzyme_host_api.aox_closure_stage_reconstruction import (
    ClosureStageReconstruction,
)
from openzyme_host_api.aox_cutover_live import SessionDriveResult
from openzyme_host_api.aox_closure_stage_live import (
    seal_aox_closure_stage_runtime_parity,
)
from openzyme_host_api.aox_closure_stage_live import (
    validate_aox_closure_stage_diagnostic_decision,
)
from openzyme_host_api.aox_closure_stage_live import (
    validate_aox_closure_stage_live_result,
)
from openzyme_host_api.aox_closure_stage_live import (
    validate_aox_closure_stage_runtime_parity,
)
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass
from openzyme_host_api.aox_live_run_class import (
    CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY,
)
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import REPO_ROOT


def _digest(label: str) -> str:
    return canonical_digest({"label": label})


def _parity_receipt() -> dict[str, object]:
    file_digests = {
        "authority": _digest("authority"),
        "consumption": _digest("consumption"),
        "fatal": _digest("fatal"),
        "campaign_decision": _digest("campaign-decision"),
        "supervision_result": _digest("supervision-result"),
    }
    source_payload = {
        "source_attempt_id": "positive-" + "a" * 32,
        "source_authority_envelope_id": "attempt_authority_" + "b" * 24,
        "source_authority_request_digest": _digest("request"),
        "effective_config_digest": _digest("config"),
        "model": "gpt-5.5",
        "max_signals_per_drain": 1,
        "max_steps_per_agent": 16,
        "auto_enqueue_ready_tasks": False,
        "supervision_timeout_seconds": 15_060,
        "supervision_protocol_schema_id": SUPERVISION_SCHEMA_ID_V2,
        "supervision_contract_digest": supervision_contract_digest(
            timeout_seconds=15_060.0,
            term_grace_seconds=15.0,
            kill_grace_seconds=10.0,
            protocol_schema_id=SUPERVISION_SCHEMA_ID_V2,
        ),
        "max_micu": 20_000_000,
        "max_cost_microunits": 0,
        "max_wall_time_seconds": 10_800,
        "file_digests": file_digests,
    }
    source = {
        **source_payload,
        "source_launch_receipt_digest": canonical_digest(source_payload),
    }
    declaration = {
        "schema_id": (
            AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID
        ),
        "source_launch_receipt_digest": source[
            "source_launch_receipt_digest"
        ],
        "model_config_digest": _digest("model"),
        "driver_limits_digest": _digest("driver"),
        "writer_policy_digest": _digest("writer"),
        "tool_response_policy_digest": _digest("tool-response"),
        "source_supervision_contract_digest": source[
            "supervision_contract_digest"
        ],
        "target_supervision_contract_digest": supervision_contract_digest(
            timeout_seconds=15_060.0,
            term_grace_seconds=15.0,
            kill_grace_seconds=10.0,
        ),
        "public_observation_contract_digest": _digest("public"),
    }
    target = {
        "git_commit": "c" * 40,
        "config_digest": source["effective_config_digest"],
        "workflow_ref": "workflow:aox-hmm-live@2.0.0#" + _digest(
            "workflow"
        ),
        "model": "gpt-5.5",
        "model_config_digest": declaration["model_config_digest"],
        "driver_limits_digest": declaration["driver_limits_digest"],
        "writer_policy_digest": declaration["writer_policy_digest"],
        "tool_response_policy_digest": declaration[
            "tool_response_policy_digest"
        ],
        "supervision_timeout_seconds": 15_060.0,
        "supervision_protocol_schema_id": SUPERVISION_SCHEMA_ID,
        "supervision_contract_digest": declaration[
            "target_supervision_contract_digest"
        ],
        "public_observation_contract_digest": declaration[
            "public_observation_contract_digest"
        ],
    }
    payload = {
        "schema_id": AOX_CLOSURE_STAGE_PARITY_RECEIPT_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "source": source,
        "target": target,
        "allowed_differences": [
            "implementation_commit_and_derived_contract_digests",
            "closure_stage_run_authority_root_process_and_evidence_identities",
            "cursor_614_reconstructed_start_projection",
            "diagnostic_micu_scenario_and_non_acceptance_result_schema",
            "supervision_protocol_v2_to_v3_local_settlement_repair",
        ],
        "declaration": declaration,
    }
    return {**payload, "receipt_digest": canonical_digest(payload)}


def _ledger_snapshot(
    *,
    attempts: int,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, object]:
    charged_tokens = input_tokens + output_tokens
    counters = {
        "attempt_count": attempts,
        "charged_tokens": charged_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_attempt_count": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
    }
    return {
        "hard_limit_tokens": 500_000_000,
        "charged_tokens": charged_tokens,
        "remaining_tokens": 500_000_000 - charged_tokens,
        "hard_limit_overage_tokens": 0,
        "attempt_count": attempts,
        "estimated_attempt_count": 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
        "by_scenario": (
            []
            if attempts == 0
            else [
                {
                    "scenario": "aox_closure_stage_diagnostic",
                    **counters,
                }
            ]
        ),
        "by_model": (
            []
            if attempts == 0
            else [{"model": "gpt-5.5", **counters}]
        ),
        "ledger_identity_digest": _digest("ledger"),
    }


def _live_result() -> dict[str, object]:
    run_attempt_id = "closure-stage-" + "a" * 32
    scientific_attempt_id = "attempt_" + "f" * 24
    session_id = CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.identities(
        run_attempt_id
    )[0]
    authority_id = "attempt_authority_" + "b" * 24
    request_digest = _digest("authority-request")
    primary_pubmed_artifact_ref = "artifact:art_primary_pubmed"
    report_ref = "report:report_closure_stage"
    task_receipts = [
        {
            "task_id": f"task_{role}",
            "role": role,
            "kind": kind,
            "status": "completed",
            "business_exit": "agent_explicit",
            "assigned_ref": f"agent:{role}:test",
            "lane_id": f"lane_{role}",
            "finish_ref": f"finish_{role}",
            "finish_payload_digest": _digest(f"finish-{role}"),
            "finished_by": f"agent:{role}:test",
            "evidence_refs": (
                [primary_pubmed_artifact_ref]
                if role == "researcher"
                else ["artifact:art_execution_result"]
                if role == "executor"
                else [report_ref, primary_pubmed_artifact_ref]
            ),
        }
        for role, kind in (
            ("researcher", "research"),
            ("executor", "execution"),
            ("reporter", "reporting"),
        )
    ]
    browser_approval_digest = _digest("browser-approval")
    browser_observation_digest = _digest("browser-observation")
    scientific_control_digest = _digest("scientific-control")
    operation_universe_digest = _digest("operation-universe")
    terminal_projection_digest = _digest("terminal")
    terminal_operations = [
        {
            "operation_id": f"operation_{index}",
            "operation_digest": _digest(f"operation-{index}"),
            "status": "completed",
            "effect_certainty": "terminal_known",
        }
        for index in range(6)
    ]
    scope_rollover_payload = {
        "phase": "post_closure_scope_open",
        "attempt_id": scientific_attempt_id,
        "attempt_scope_id": f"mutation_scope_{scientific_attempt_id}",
        "attempt_scope_state": "sealed",
        "post_scope_id": (
            f"mutation_scope_post_{scientific_attempt_id}"
        ),
        "open_scope_count": 1,
    }
    scope_rollover = {
        **scope_rollover_payload,
        "projection_digest": canonical_digest(scope_rollover_payload),
    }
    report_source_link_payload = {
        "report_ref": report_ref,
        "primary_pubmed_artifact_ref": primary_pubmed_artifact_ref,
        "primary_pubmed_artifact_digest": _digest(
            "primary-pubmed-artifact"
        ),
        "source_ref_ids": ["source_ref_pubmed_001"],
    }
    runtime_summary = {
        "session_id": session_id,
        "purpose": "formal",
        "state": "completed",
        "blocker_code": None,
        "drain_count": 3,
        "approval_count": 0,
        "browser_anchor_observed": True,
        "browser_anchor_receipt_digest": browser_approval_digest,
        "browser_observation_observed": True,
        "browser_observation_receipt_digest": (
            browser_observation_digest
        ),
        "task_count": 3,
        "projected_operation_count": 6,
        "workspace_digest": _digest("workspace"),
        "event_receipt": {"stream_digest": _digest("events")},
        "mutation_scope": {},
        "scientific_attempt_control_digest": scientific_control_digest,
        "failure_task_projection": {
            "task_fact_count": 0,
            "task_facts_digest": canonical_digest([]),
            "task_facts_truncated": False,
        },
    }
    supervision = {
        "schema_id": SUPERVISION_RECEIPT_SCHEMA_ID,
        "mode": "process_isolated_spawn",
        "attempt_id": run_attempt_id,
        "attempt_kind": "positive",
        "campaign_id": _digest("campaign"),
        "process_epoch": "c" * 32,
        "protocol_final_sequence": 4,
        "protocol_final_digest": _digest("protocol"),
        "child_exit_code": 0,
        "local_state_settled": True,
        "descendant_retirement_proven": True,
        "parent_snapshot_revalidated": True,
        "mutation_authority_schema_id": (
            MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
        ),
        "mutation_authority_snapshot_digest": _digest(
            "mutation-authority"
        ),
        "mutation_authority_observed_row_count": 2,
        "nonterminal_mutation_scope_count": 1,
        "active_mutation_writer_count": 0,
        "sqlite_checkpoint": "passed",
        "sqlite_integrity": "passed",
        "declared_root_sync": True,
        "result_digest": _digest("child-result"),
        "supervisor_contract_digest": supervision_contract_digest(
            timeout_seconds=15_060.0,
            term_grace_seconds=15.0,
            kill_grace_seconds=10.0,
        ),
        "timeout_seconds": 15_060.0,
        "term_grace_seconds": 15.0,
        "kill_grace_seconds": 10.0,
        "attempt_authority_id": authority_id,
        "attempt_authority_request_digest": request_digest,
    }
    payload = {
        "schema_id": AOX_CLOSURE_STAGE_LIVE_RESULT_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": "aox_closure_stage_" + "d" * 24,
        "run_attempt_id": run_attempt_id,
        "scientific_attempt_id": scientific_attempt_id,
        "session_id": session_id,
        "status": "completed",
        "completed_at": "2026-07-26T00:00:00+00:00",
        "authority": {
            "plan_schema_id": AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
            "consumption_schema_id": (
                AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
            ),
            "plan_digest": _digest("plan"),
            "consumption_digest": _digest("consumption"),
            "envelope_id": authority_id,
            "request_digest": request_digest,
        },
        "source": {
            "manifest_digest": _digest("source-manifest"),
            "database_sha256_before": _digest("source-database"),
            "database_sha256_after": _digest("source-database"),
            "inventory_digest_before": _digest("source-inventory"),
            "inventory_digest_after": _digest("source-inventory"),
            "immutable": True,
        },
        "reconstruction": {
            "receipt_digest": _digest("reconstruction"),
            "target_root_identity": _digest("target-root"),
            "canonical_state_digest": _digest("canonical-state"),
            "scientific_attempt_id": scientific_attempt_id,
            "operation_count": 6,
            "operation_universe_digest": operation_universe_digest,
        },
        "parity": {
            "receipt_digest": _digest("parity"),
            "declaration_digest": _digest("parity-declaration"),
            "target_supervision_contract_digest": supervision[
                "supervisor_contract_digest"
            ],
        },
        "runtime": {
            "summary": runtime_summary,
            "child_result_digest": supervision["result_digest"],
            "terminal_projection_digest": terminal_projection_digest,
            "operation_binding": {
                "scientific_attempt_id": scientific_attempt_id,
                "projected_operation_count": 6,
                "terminal_operation_count": 6,
                "terminal_operations": terminal_operations,
                "terminal_operations_digest": canonical_digest(
                    terminal_operations
                ),
                "terminal_operation_universe_digest": (
                    operation_universe_digest
                ),
                "reconstruction_operation_count": 6,
                "reconstruction_operation_universe_digest": (
                    operation_universe_digest
                ),
                "terminal_projection_digest": terminal_projection_digest,
            },
            "closure": {
                "task_receipts": task_receipts,
                "report_id": "report_closure_stage",
                "report_content_ref": "doc_report_content",
                "report_source_link": {
                    **report_source_link_payload,
                    "link_digest": canonical_digest(
                        report_source_link_payload
                    ),
                },
                "closure_request_id": "closure_request_test",
                "closure_response_id": "closure_response_test",
                "closure_id": "closure_test",
                "scope_rollover": scope_rollover,
                "scientific_attempt_control_digest": (
                    scientific_control_digest
                ),
            },
        },
        "effects": {
            "count_deltas": {
                "approval": 0,
                "controlled_operation": 0,
                "controlled_execution": 0,
                "controlled_dispatch": 0,
                "sandbox_run": 0,
                "artifact_materialization": 0,
                "scientific_materialization": 0,
            },
            "operation_identity_unchanged": True,
            "new_artifacts": [],
            "no_new_session_artifact": True,
            "new_report_content_documents": [
                {
                    "document_id": "doc_report_content",
                    "document_kind": "report_draft_content",
                    "payload_digest": _digest("report-content"),
                }
            ],
            "report_content_document_only": True,
            "no_new_scientific_effect": True,
        },
        "micu": {
            "attempts": [
                {
                    "id": 1,
                    "scenario": "aox_closure_stage_diagnostic",
                    "purpose": "agent_turn",
                    "kind": "responses",
                    "model": "gpt-5.5",
                    "attempt": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "charged_tokens": 15,
                    "estimated": 0,
                    "status": "succeeded",
                    "reservation_overage_tokens": 0,
                    "hard_limit_breached": 0,
                    "cumulative_tokens": 15,
                }
            ],
            "attempt_count": 1,
            "all_bound_to_diagnostic_scenario": True,
            "authority_max_micu": 20_000_000,
            "charged_tokens": 15,
            "within_authority": True,
        },
        "public_observation": {
            "api_receipt_count": 4,
            "api_receipts_digest": _digest("api-receipts"),
            "browser_required": True,
            "browser_observed": True,
            "browser_receipt_digest": browser_observation_digest,
        },
        "supervision": supervision,
        "ledger": {
            "before": _ledger_snapshot(
                attempts=0,
                input_tokens=0,
                output_tokens=0,
            ),
            "after": _ledger_snapshot(
                attempts=1,
                input_tokens=10,
                output_tokens=5,
            ),
        },
    }
    operation_binding = payload["runtime"]["operation_binding"]
    operation_binding["binding_digest"] = canonical_digest(
        operation_binding
    )
    return {**payload, "result_digest": canonical_digest(payload)}


def _supervised_child_evidence(
    result: dict[str, object],
    *,
    selection_id: str,
) -> dict[str, object]:
    scientific_attempt_id = str(result["scientific_attempt_id"])
    operation_universe_digest = str(
        result["reconstruction"]["operation_universe_digest"]
    )
    operations = [
        {
            "operation_id": f"operation_{index}",
            "operation_digest": _digest(f"operation-{index}"),
            "status": "completed",
            "effect_certainty": "terminal_known",
        }
        for index in range(6)
    ]
    drive = SessionDriveResult(
        session_id=str(result["session_id"]),
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "task_board": {"items": [{}, {}, {}]},
            "scientific_evidence": {"operations": operations},
            "runtime_state": {"controlled_operations": []},
        },
        workspace_response_binding={},
        event_receipt={"stream_digest": _digest("events")},
        drain_count=3,
        approval_ids=(),
        browser_approval_receipt={"label": "browser-approval"},
        browser_observation_receipt={"label": "browser-observation"},
        mutation_scope={},
        scientific_attempt_control={"label": "scientific-control"},
    )
    terminal_payload = {
        "attempt": {
            "attempt_id": scientific_attempt_id,
            "status": "active",
            "mutation_scope_id": (
                f"mutation_scope_{scientific_attempt_id}"
            ),
        },
        "operations": operations,
        "counts": {"controlled_operation": 6},
        "closures": [
            {
                "attempt_id": scientific_attempt_id,
                "selection_id": selection_id,
                "operation_universe_digest": (
                    operation_universe_digest
                ),
            }
        ],
    }
    terminal = {
        **terminal_payload,
        "projection_digest": canonical_digest(terminal_payload),
    }
    return {
        "schema_id": AOX_CLOSURE_STAGE_CHILD_EVIDENCE_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": result["diagnostic_id"],
        "run_attempt_id": result["run_attempt_id"],
        "scientific_attempt_id": scientific_attempt_id,
        "session_id": result["session_id"],
        "reconstruction_receipt_digest": result["reconstruction"][
            "receipt_digest"
        ],
        "health": {},
        "baseline": {},
        "terminal": terminal,
        "effects": deepcopy(result["effects"]),
        "closure": deepcopy(result["runtime"]["closure"]),
        "micu_attempts": deepcopy(result["micu"]["attempts"]),
        "api_receipts": [
            {"sequence": sequence} for sequence in range(1, 5)
        ],
        "runtime": _closure_stage_runtime_summary(drive),
        "product_path": {
            "completed": True,
            "attempt_supervision": deepcopy(result["supervision"]),
        },
    }


def test_runtime_parity_is_closed_reproducible_and_private(
    tmp_path: Path,
) -> None:
    receipt = _parity_receipt()

    assert validate_aox_closure_stage_runtime_parity(receipt) == receipt
    output = tmp_path / "runtime-parity.json"
    seal_aox_closure_stage_runtime_parity(receipt, output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o400

    drifted = deepcopy(receipt)
    drifted["source"]["max_steps_per_agent"] = 17
    drifted["receipt_digest"] = canonical_digest(
        {
            key: value
            for key, value in drifted.items()
            if key != "receipt_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as error:
        validate_aox_closure_stage_runtime_parity(drifted)
    assert error.value.code == (
        "closure_stage_runtime_parity_receipt_invalid"
    )

    config_drift = deepcopy(receipt)
    config_drift["target"]["config_digest"] = _digest(
        "different-effective-config"
    )
    config_drift["receipt_digest"] = canonical_digest(
        {
            key: value
            for key, value in config_drift.items()
            if key != "receipt_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as config_error:
        validate_aox_closure_stage_runtime_parity(config_drift)
    assert config_error.value.code == (
        "closure_stage_runtime_parity_receipt_invalid"
    )


def test_session_drive_summary_uses_canonical_scientific_evidence() -> None:
    result = _live_result()
    child = _supervised_child_evidence(
        result,
        selection_id="selection_" + "1" * 24,
    )

    assert child["runtime"]["projected_operation_count"] == 6
    assert child["runtime"]["task_count"] == 3


def test_real_shape_builder_validator_and_decision_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_result = _live_result()
    selection_id = "selection_" + "1" * 24
    source_database_digest = _digest("source-database")
    source_inventory_entries: list[dict[str, object]] = []
    source_manifest = {
        "manifest_digest": _digest("source-manifest"),
        "source_inventory": {
            "database_path": "/tmp/read-only-source.sqlite3",
            "database_sha256": source_database_digest,
            "inventory_digest": canonical_digest(
                source_inventory_entries
            ),
        },
        "inventory_entries": source_inventory_entries,
    }
    reconstruction = ClosureStageReconstruction(
        roots=SimpleNamespace(
            proof={"root_identity": _digest("target-root")}
        ),
        receipt={
            "receipt_digest": _digest("reconstruction"),
            "canonical_state": {
                "canonical_state_digest": _digest(
                    "canonical-state"
                )
            },
            "target_graph": {
                "attempt_id": fixture_result[
                    "scientific_attempt_id"
                ],
                "selection_id": selection_id,
                "operation_universe_digest": fixture_result[
                    "reconstruction"
                ]["operation_universe_digest"],
                "operation_count": 6,
                "closure_request_ready": True,
                "source_to_target_universe_transform": (
                    "outer_identity_rewrite_and_service_reseal"
                ),
            },
        },
        scientific_attempt_id=str(
            fixture_result["scientific_attempt_id"]
        ),
        selection_id=selection_id,
        executor_agent_id="agent:executor:test",
        research_task_id="task_research",
        report_task_id="task_report",
    )
    plan = {
        "diagnostic_id": fixture_result["diagnostic_id"],
        "plan_digest": _digest("plan"),
        "browser_observation_receipt": "/tmp/browser.json",
        "resources": {"max_micu": 20_000_000},
        "slot": {
            "attempt_id": fixture_result["run_attempt_id"],
            "session_id": fixture_result["session_id"],
            "envelope_id": fixture_result["authority"][
                "envelope_id"
            ],
            "request_digest": fixture_result["authority"][
                "request_digest"
            ],
        },
    }
    child = _supervised_child_evidence(
        fixture_result,
        selection_id=selection_id,
    )
    monkeypatch.setattr(
        closure_stage_live,
        "independently_verify_aox_closure_stage_source_manifest",
        lambda _manifest: None,
    )
    monkeypatch.setattr(
        closure_stage_live,
        "independently_verify_aox_closure_stage_reconstruction",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        closure_stage_live,
        "_sha256_file",
        lambda _path: source_database_digest,
    )

    live_result = build_aox_closure_stage_live_result(
        plan=plan,
        consumption={"consumed": True},
        source_manifest=source_manifest,
        reconstruction=reconstruction,
        parity=_parity_receipt(),
        evidence=child,
        ledger_before=fixture_result["ledger"]["before"],
        ledger_after=fixture_result["ledger"]["after"],
    )
    decision = build_aox_closure_stage_diagnostic_decision(
        plan=plan,
        source_manifest=source_manifest,
        source_post_verified=True,
        live_result=live_result,
        failure=None,
    )

    assert live_result["run_attempt_id"] != (
        live_result["scientific_attempt_id"]
    )
    assert live_result["runtime"]["operation_binding"][
        "terminal_operation_count"
    ] == 6
    assert live_result["parity"][
        "target_supervision_contract_digest"
    ] == live_result["supervision"]["supervisor_contract_digest"]
    assert decision["status"] == "completed"
    assert decision["live_result_digest"] == live_result["result_digest"]


def test_closure_stage_sop_digest_is_separate_from_stable_workflow() -> None:
    execution_sop_digest = _sha256_file(
        REPO_ROOT
        / "docs/v3/execution-pipeline-docs/aox-hmm-live.md"
    )
    closure_stage_sop_digest = _sha256_file(
        REPO_ROOT / "docs/v3/aox-closure-stage-live-diagnostic.md"
    )
    workflow_ref = next(
        manifest.selection_ref
        for manifest in default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
        and manifest.version == "2.0.0"
    )

    assert execution_sop_digest.startswith("sha256:")
    assert closure_stage_sop_digest.startswith("sha256:")
    assert closure_stage_sop_digest != execution_sop_digest
    assert workflow_ref == (
        "workflow:aox-hmm-live@2.0.0#"
        "sha256:8865f1364cbd5261f953dd7e901f02b381"
        "2f96cae34376f177c8ad78c8c08218"
    )


def test_live_result_closes_nested_evidence_and_browser_ledger_bindings() -> None:
    result = _live_result()

    assert validate_aox_closure_stage_live_result(result) == result

    nested_extra = deepcopy(result)
    nested_extra["source"]["unexpected"] = True
    nested_extra["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in nested_extra.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as extra:
        validate_aox_closure_stage_live_result(nested_extra)
    assert extra.value.code == "closure_stage_live_result_schema_invalid"

    missing_source_link = deepcopy(result)
    reporter_receipt = next(
        receipt
        for receipt in missing_source_link["runtime"]["closure"][
            "task_receipts"
        ]
        if receipt["role"] == "reporter"
    )
    reporter_receipt["evidence_refs"].remove(
        "artifact:art_primary_pubmed"
    )
    missing_source_link["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in missing_source_link.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as source_link:
        validate_aox_closure_stage_live_result(missing_source_link)
    assert source_link.value.code == (
        "closure_stage_live_report_source_link_invalid"
    )

    browser_drift = deepcopy(result)
    browser_drift["public_observation"]["browser_required"] = False
    browser_drift["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in browser_drift.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as browser:
        validate_aox_closure_stage_live_result(browser_drift)
    assert browser.value.code == (
        "closure_stage_live_browser_observation_invalid"
    )

    ledger_drift = deepcopy(result)
    ledger_drift["micu"]["attempts"][0]["input_tokens"] = 11
    ledger_drift["micu"]["attempts"][0]["charged_tokens"] = 16
    ledger_drift["micu"]["charged_tokens"] = 16
    ledger_drift["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in ledger_drift.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as ledger:
        validate_aox_closure_stage_live_result(ledger_drift)
    assert ledger.value.code == (
        "closure_stage_live_ledger_transition_invalid"
    )

    over_authority = deepcopy(result)
    over_authority["micu"]["attempts"][0]["input_tokens"] = 20_000_001
    over_authority["micu"]["attempts"][0]["output_tokens"] = 0
    over_authority["micu"]["attempts"][0]["charged_tokens"] = 20_000_001
    over_authority["micu"]["charged_tokens"] = 20_000_001
    over_authority["ledger"]["after"] = _ledger_snapshot(
        attempts=1,
        input_tokens=20_000_001,
        output_tokens=0,
    )
    over_authority["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in over_authority.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as authority:
        validate_aox_closure_stage_live_result(over_authority)
    assert authority.value.code == "closure_stage_live_micu_invalid"

    duplicate_terminal = deepcopy(result)
    duplicate_terminal["runtime"]["closure"]["task_receipts"].append(
        deepcopy(
            duplicate_terminal["runtime"]["closure"][
                "task_receipts"
            ][0]
        )
    )
    duplicate_terminal["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in duplicate_terminal.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as duplicate:
        validate_aox_closure_stage_live_result(duplicate_terminal)
    assert duplicate.value.code == "closure_stage_live_closure_invalid"

    accepted_negative_executor = deepcopy(result)
    executor_receipt = next(
        receipt
        for receipt in accepted_negative_executor["runtime"]["closure"][
            "task_receipts"
        ]
        if receipt["role"] == "executor"
    )
    executor_receipt["status"] = "blocked"
    accepted_negative_executor["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in accepted_negative_executor.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as accepted_negative:
        validate_aox_closure_stage_live_result(
            accepted_negative_executor
        )
    assert accepted_negative.value.code == (
        "closure_stage_live_closure_invalid"
    )

    active_writer = deepcopy(result)
    active_writer["supervision"]["active_mutation_writer_count"] = 1
    active_writer["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in active_writer.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as unretired:
        validate_aox_closure_stage_live_result(active_writer)
    assert unretired.value.code == "attempt_supervision_receipt_invalid"

    malformed_rollover = deepcopy(result)
    rollover = malformed_rollover["runtime"]["closure"]["scope_rollover"]
    rollover["post_scope_id"] = "mutation_scope_post_forged"
    rollover["projection_digest"] = canonical_digest(
        {
            key: value
            for key, value in rollover.items()
            if key != "projection_digest"
        }
    )
    malformed_rollover["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in malformed_rollover.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as rollover_error:
        validate_aox_closure_stage_live_result(malformed_rollover)
    assert rollover_error.value.code == (
        "closure_stage_live_scope_rollover_invalid"
    )

    conflated_attempts = deepcopy(result)
    rollover = conflated_attempts["runtime"]["closure"][
        "scope_rollover"
    ]
    rollover["attempt_id"] = conflated_attempts["run_attempt_id"]
    rollover["attempt_scope_id"] = (
        f"mutation_scope_{conflated_attempts['run_attempt_id']}"
    )
    rollover["post_scope_id"] = (
        f"mutation_scope_post_{conflated_attempts['run_attempt_id']}"
    )
    rollover["projection_digest"] = canonical_digest(
        {
            key: value
            for key, value in rollover.items()
            if key != "projection_digest"
        }
    )
    conflated_attempts["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in conflated_attempts.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as conflated:
        validate_aox_closure_stage_live_result(conflated_attempts)
    assert conflated.value.code == (
        "closure_stage_live_scope_rollover_invalid"
    )

    stale_public_operation_count = deepcopy(result)
    stale_public_operation_count["runtime"]["summary"][
        "projected_operation_count"
    ] = 0
    stale_public_operation_count["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in stale_public_operation_count.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as operation_count:
        validate_aox_closure_stage_live_result(
            stale_public_operation_count
        )
    assert operation_count.value.code == (
        "closure_stage_live_operation_binding_invalid"
    )

    terminal_operation_drift = deepcopy(result)
    operation_binding = terminal_operation_drift["runtime"][
        "operation_binding"
    ]
    operation_binding["terminal_operations"][0][
        "operation_digest"
    ] = _digest("different-terminal-operation")
    operation_binding["binding_digest"] = canonical_digest(
        {
            key: value
            for key, value in operation_binding.items()
            if key != "binding_digest"
        }
    )
    terminal_operation_drift["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in terminal_operation_drift.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as operation_drift:
        validate_aox_closure_stage_live_result(
            terminal_operation_drift
        )
    assert operation_drift.value.code == (
        "closure_stage_live_operation_binding_invalid"
    )

    child_binding_drift = deepcopy(result)
    child_binding_drift["runtime"]["child_result_digest"] = _digest(
        "different-child-result"
    )
    child_binding_drift["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in child_binding_drift.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as child_binding:
        validate_aox_closure_stage_live_result(child_binding_drift)
    assert child_binding.value.code == (
        "closure_stage_live_child_binding_invalid"
    )

    supervision_parity_drift = deepcopy(result)
    supervision_parity_drift["parity"][
        "target_supervision_contract_digest"
    ] = _digest("different-supervision-contract")
    supervision_parity_drift["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in supervision_parity_drift.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as supervision_parity:
        validate_aox_closure_stage_live_result(
            supervision_parity_drift
        )
    assert supervision_parity.value.code == (
        "closure_stage_live_supervision_parity_invalid"
    )

    source_post_hash_drift = deepcopy(result)
    source_post_hash_drift["source"][
        "database_sha256_after"
    ] = _digest("changed-source-database")
    source_post_hash_drift["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in source_post_hash_drift.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as source_drift:
        validate_aox_closure_stage_live_result(source_post_hash_drift)
    assert source_drift.value.code == (
        "closure_stage_live_result_schema_invalid"
    )

    hidden_effect = deepcopy(result)
    hidden_effect["effects"]["count_deltas"][
        "controlled_dispatch"
    ] = 1
    hidden_effect["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in hidden_effect.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as effect:
        validate_aox_closure_stage_live_result(hidden_effect)
    assert effect.value.code == (
        "closure_stage_live_effect_delta_invalid"
    )

    unsafe_public_field = deepcopy(result)
    unsafe_public_field["public_observation"][
        "target_root"
    ] = "/tmp/private-root"
    unsafe_public_field["result_digest"] = canonical_digest(
        {
            key: value
            for key, value in unsafe_public_field.items()
            if key != "result_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as unsafe_public:
        validate_aox_closure_stage_live_result(unsafe_public_field)
    assert unsafe_public.value.code == (
        "closure_stage_live_result_schema_invalid"
    )


def test_effect_delta_allows_only_one_fresh_report_content_document() -> None:
    unchanged_counts = {
        "approval": 1,
        "controlled_operation": 6,
        "controlled_execution": 6,
        "controlled_dispatch": 6,
        "sandbox_run": 7,
        "artifact_materialization": 5,
        "scientific_materialization": 5,
    }
    baseline = {
        "counts": unchanged_counts,
        "operations": [{"operation_id": "operation_source"}],
        "artifacts": [
            {
                "artifact_id": "artifact_source",
                "diagnostic_source_copy": True,
            }
        ],
        "report_content_documents": [],
        "report_drafts": [],
    }
    terminal = {
        "counts": dict(unchanged_counts),
        "operations": [{"operation_id": "operation_source"}],
        "artifacts": list(baseline["artifacts"]),
        "report_content_documents": [
            {
                "document_id": "doc_report_content",
                "document_kind": "report_draft_content",
                "payload_digest": _digest("report-content"),
            }
        ],
        "report_drafts": [
            {
                "status": "published",
                "content_ref": "doc_report_content",
            }
        ],
    }

    delta = _effect_delta(baseline, terminal)

    assert delta["count_deltas"] == {
        key: 0 for key in unchanged_counts
    }
    assert delta["operation_identity_unchanged"] is True
    assert delta["no_new_session_artifact"] is True
    assert delta["report_content_document_only"] is True
    assert delta["no_new_scientific_effect"] is True

    hidden_effect = deepcopy(terminal)
    hidden_effect["counts"]["controlled_dispatch"] += 1
    assert _effect_delta(baseline, hidden_effect)[
        "no_new_scientific_effect"
    ] is False
    hidden_artifact = deepcopy(terminal)
    hidden_artifact["artifacts"].append(
        {
            "artifact_id": "artifact_hidden",
            "diagnostic_source_copy": False,
        }
    )
    assert _effect_delta(baseline, hidden_artifact)[
        "no_new_scientific_effect"
    ] is False


def test_browser_anchor_uses_one_real_restored_sealed_operation() -> None:
    operations = [
        {
            "operation_id": f"operation_{index}",
            "operation_digest": _digest(f"operation-{index}"),
            "status": "completed",
            "effect_certainty": "terminal_known",
        }
        for index in range(6)
    ]
    challenge = _digest("challenge")

    anchor = _closure_stage_browser_anchor(
        {"operations": operations},
        ui_dist_digest=_digest("ui"),
        host_process_id=1234,
        observation_challenge=challenge,
    )

    assert anchor["approval_id"] == "closure-stage-no-operation-approval"
    assert anchor["operation_id"] == operations[-1]["operation_id"]
    assert anchor["operation_digest"] == operations[-1]["operation_digest"]
    assert anchor["observation_challenge"] == challenge


def test_failed_decision_is_finite_and_permanently_non_adoptable() -> None:
    plan = {
        "diagnostic_id": "aox_closure_stage_" + "a" * 24,
        "slot": {"attempt_id": "closure-stage-" + "b" * 32},
    }
    failure = CutoverEvidenceError(
        "closure_stage_runtime_parity_mismatch",
        "parity failed",
    )
    source_manifest = {
        "manifest_digest": _digest("source-manifest"),
        "source_inventory": {
            "database_sha256": _digest("source-database"),
            "inventory_digest": _digest("source-inventory"),
        },
    }

    decision = build_aox_closure_stage_diagnostic_decision(
        plan=plan,
        source_manifest=source_manifest,
        source_post_verified=True,
        live_result=None,
        failure=failure,
    )

    assert (
        decision["schema_id"]
        == AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_SCHEMA_ID
    )
    assert decision["status"] == "failed"
    assert decision["acceptance_eligible"] is False
    assert decision["blocker"] == {
        "code": "closure_stage_runtime_parity_mismatch",
        "identity": "closure_stage.runner",
    }
    assert decision["source_integrity"] == {
        "manifest_digest": source_manifest["manifest_digest"],
        "database_sha256_before": source_manifest["source_inventory"][
            "database_sha256"
        ],
        "database_sha256_after": source_manifest["source_inventory"][
            "database_sha256"
        ],
        "inventory_digest_before": source_manifest["source_inventory"][
            "inventory_digest"
        ],
        "inventory_digest_after": source_manifest["source_inventory"][
            "inventory_digest"
        ],
        "post_verified": True,
        "immutable": True,
    }
    assert decision["formal_adoption"] == {
        "eligible": False,
        "formal_bundle_created": False,
        "campaign_reducer_invoked": False,
        "decision": None,
    }
    assert (
        validate_aox_closure_stage_diagnostic_decision(decision)
        == decision
    )


def test_closure_stage_runner_is_spawn_pickleable(tmp_path: Path) -> None:
    ledger_path = tmp_path / "micu-ledger.sqlite3"
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        test=replace(
            settings.test,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )
    runner = ClosureStageLiveRunner(
        settings=settings,
        ledger_path=ledger_path,
        run_class=AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC,
        diagnostic_id="aox_closure_stage_" + "a" * 24,
        scientific_attempt_id="attempt_" + "b" * 24,
        selection_id="selection_" + "c" * 24,
        research_task_id="research_" + "d" * 24,
        report_task_id="report_" + "e" * 24,
        reconstruction_receipt_digest=_digest("reconstruction"),
    )

    restored = pickle.loads(
        pickle.dumps(runner, protocol=pickle.HIGHEST_PROTOCOL)
    )

    assert isinstance(restored, ClosureStageLiveRunner)
    assert restored.run_class is (
        AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC
    )
    assert restored.diagnostic_id == runner.diagnostic_id
    assert restored.reconstruction_receipt_digest == (
        runner.reconstruction_receipt_digest
    )
