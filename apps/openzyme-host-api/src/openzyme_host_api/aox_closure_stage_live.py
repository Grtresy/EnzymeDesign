from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit

from openzyme_core import is_published_report_link
from openzyme_core import is_published_report_status
from openzyme_core import MutationWriterTurnFactory
from openzyme_core import ScientificAttemptScopeRolloverEnvelope
from openzyme_core import ScientificAttemptScopeRolloverIntegrityError
from openzyme_core import ScientificAttemptScopeRolloverPhase
from openzyme_core import ScientificAttemptScopeRolloverProjector
from openzyme_core import SQLiteRepositoryProvider
from openzyme_domain import MutationWriterKind
from openzyme_runtime import REPO_ROOT

from .aox_attempt_supervision import DEFAULT_KILL_GRACE_SECONDS
from .aox_attempt_supervision import DEFAULT_TERM_GRACE_SECONDS
from .aox_attempt_supervision import ProcessIsolatedAttemptRunner
from .aox_attempt_supervision import SUPERVISION_SCHEMA_ID
from .aox_attempt_supervision import SUPERVISION_SCHEMA_ID_V2
from .aox_attempt_supervision import supervision_contract_digest
from .aox_attempt_supervision import validate_attempt_supervision_receipt
from .aox_authority_storage import publish_private_canonical_authority
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
)
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID,
)
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID,
)
from .aox_closure_stage_reconstruction import ClosureStageReconstruction
from .aox_closure_stage_reconstruction import (
    independently_verify_aox_closure_stage_reconstruction,
)
from .aox_closure_stage_source import (
    independently_verify_aox_closure_stage_source_manifest,
)
from .aox_cutover_evidence import AttemptRunContext
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import safe_micu_ledger_snapshot
from .aox_cutover_live import BROWSER_OBSERVATION_MODE
from .aox_cutover_live import BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
from .aox_cutover_live import BROWSER_SEALED_PAGE_URL
from .aox_cutover_live import LiveAoxAttemptRunner
from .aox_cutover_live import LiveProductPathError
from .aox_cutover_live import MANUAL_APPROVAL_HANDOFF_SCHEMA_ID
from .aox_cutover_live import SessionDriveResult
from .aox_cutover_live import _emit_operator_record
from .aox_cutover_live import _micu_record_ids
from .aox_cutover_live import _safe_health
from .aox_cutover_live import _task_receipts
from .aox_cutover_live import _terminal_browser_page_state
from .aox_cutover_tool_policy import AoxCutoverFormalToolPrecondition
from .aox_cutover_tool_policy import evaluate_aox_source_linked_report
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY
from .aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID
from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation


AOX_CLOSURE_STAGE_PARITY_RECEIPT_SCHEMA_ID = (
    "aox_closure_stage_runtime_parity_receipt@2"
)
AOX_CLOSURE_STAGE_LIVE_RESULT_SCHEMA_ID = (
    "aox_closure_stage_live_result@3"
)
AOX_CLOSURE_STAGE_CHILD_EVIDENCE_SCHEMA_ID = (
    "aox_closure_stage_child_evidence@3"
)
AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_SCHEMA_ID = (
    "aox_closure_stage_diagnostic_decision@1"
)
AOX_CLOSURE_STAGE_LIVE_RESULT_FILENAME = "closure-stage-live-result.json"
AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_FILENAME = (
    "closure-stage-diagnostic-decision.json"
)
AOX_CLOSURE_STAGE_PARITY_RECEIPT_FILENAME = (
    "runtime-parity-receipt.json"
)
_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SCIENTIFIC_ATTEMPT_ID_PATTERN = re.compile(r"^attempt_[a-f0-9]{24}$")
_TERMINAL_MICU_STATUSES = frozenset(
    {
        "succeeded",
        "succeeded_overage",
        "succeeded_limit_breached",
        "succeeded_estimated",
        "failed_estimated",
    }
)
_PARITY_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "source",
        "target",
        "allowed_differences",
        "declaration",
        "receipt_digest",
    }
)
_PARITY_SOURCE_FIELDS = frozenset(
    {
        "source_attempt_id",
        "source_authority_envelope_id",
        "source_authority_request_digest",
        "effective_config_digest",
        "model",
        "max_signals_per_drain",
        "max_steps_per_agent",
        "auto_enqueue_ready_tasks",
        "supervision_timeout_seconds",
        "supervision_protocol_schema_id",
        "supervision_contract_digest",
        "max_micu",
        "max_cost_microunits",
        "max_wall_time_seconds",
        "file_digests",
        "source_launch_receipt_digest",
    }
)
_PARITY_TARGET_FIELDS = frozenset(
    {
        "git_commit",
        "config_digest",
        "workflow_ref",
        "model",
        "model_config_digest",
        "driver_limits_digest",
        "writer_policy_digest",
        "tool_response_policy_digest",
        "supervision_timeout_seconds",
        "supervision_protocol_schema_id",
        "supervision_contract_digest",
        "public_observation_contract_digest",
    }
)
_PARITY_DECLARATION_FIELDS = frozenset(
    {
        "schema_id",
        "source_launch_receipt_digest",
        "model_config_digest",
        "driver_limits_digest",
        "writer_policy_digest",
        "tool_response_policy_digest",
        "source_supervision_contract_digest",
        "target_supervision_contract_digest",
        "public_observation_contract_digest",
    }
)
_PARITY_FILE_DIGEST_FIELDS = frozenset(
    {
        "authority",
        "consumption",
        "fatal",
        "campaign_decision",
        "supervision_result",
    }
)
_LIVE_RESULT_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "run_attempt_id",
        "scientific_attempt_id",
        "session_id",
        "status",
        "completed_at",
        "authority",
        "source",
        "reconstruction",
        "parity",
        "runtime",
        "effects",
        "micu",
        "public_observation",
        "supervision",
        "ledger",
        "result_digest",
    }
)
_LIVE_AUTHORITY_FIELDS = frozenset(
    {
        "plan_schema_id",
        "consumption_schema_id",
        "plan_digest",
        "consumption_digest",
        "envelope_id",
        "request_digest",
    }
)
_LIVE_SOURCE_FIELDS = frozenset(
    {
        "manifest_digest",
        "database_sha256_before",
        "database_sha256_after",
        "inventory_digest_before",
        "inventory_digest_after",
        "immutable",
    }
)
_LIVE_RECONSTRUCTION_FIELDS = frozenset(
    {
        "receipt_digest",
        "target_root_identity",
        "canonical_state_digest",
        "scientific_attempt_id",
        "operation_count",
        "operation_universe_digest",
    }
)
_LIVE_PARITY_FIELDS = frozenset(
    {
        "receipt_digest",
        "declaration_digest",
        "target_supervision_contract_digest",
    }
)
_LIVE_RUNTIME_FIELDS = frozenset(
    {
        "summary",
        "child_result_digest",
        "terminal_projection_digest",
        "operation_binding",
        "closure",
    }
)
_LIVE_OPERATION_BINDING_FIELDS = frozenset(
    {
        "scientific_attempt_id",
        "projected_operation_count",
        "terminal_operation_count",
        "terminal_operations",
        "terminal_operations_digest",
        "terminal_operation_universe_digest",
        "reconstruction_operation_count",
        "reconstruction_operation_universe_digest",
        "terminal_projection_digest",
        "binding_digest",
    }
)
_LIVE_TERMINAL_OPERATION_FIELDS = frozenset(
    {
        "operation_id",
        "operation_digest",
        "status",
        "effect_certainty",
    }
)
_LIVE_RUNTIME_SUMMARY_FIELDS = frozenset(
    {
        "session_id",
        "purpose",
        "state",
        "blocker_code",
        "drain_count",
        "approval_count",
        "browser_anchor_observed",
        "browser_anchor_receipt_digest",
        "browser_observation_observed",
        "browser_observation_receipt_digest",
        "task_count",
        "projected_operation_count",
        "workspace_digest",
        "event_receipt",
        "mutation_scope",
        "scientific_attempt_control_digest",
        "failure_task_projection",
        "failure_operation_projection",
    }
)
_LIVE_FAILURE_TASK_PROJECTION_FIELDS = frozenset(
    {
        "task_fact_count",
        "task_facts_digest",
        "task_facts_truncated",
    }
)
_LIVE_FAILURE_OPERATION_PROJECTION_FIELDS = frozenset(
    {
        "operation_fact_count",
        "operation_facts_digest",
        "operation_facts_truncated",
    }
)
_LIVE_CLOSURE_FIELDS = frozenset(
    {
        "task_receipts",
        "report_id",
        "report_content_ref",
        "report_source_link",
        "closure_request_id",
        "closure_response_id",
        "closure_id",
        "scope_rollover",
        "scientific_attempt_control_digest",
    }
)
_LIVE_SCOPE_ROLLOVER_FIELDS = frozenset(
    {
        "phase",
        "attempt_id",
        "attempt_scope_id",
        "attempt_scope_state",
        "post_scope_id",
        "open_scope_count",
        "projection_digest",
    }
)
_LIVE_REPORT_SOURCE_LINK_FIELDS = frozenset(
    {
        "report_ref",
        "primary_pubmed_artifact_ref",
        "primary_pubmed_artifact_digest",
        "source_ref_ids",
        "link_digest",
    }
)
_LIVE_TASK_RECEIPT_FIELDS = frozenset(
    {
        "task_id",
        "role",
        "kind",
        "status",
        "business_exit",
        "assigned_ref",
        "lane_id",
        "finish_ref",
        "finish_payload_digest",
        "finished_by",
        "evidence_refs",
    }
)
_LIVE_EFFECT_FIELDS = frozenset(
    {
        "count_deltas",
        "operation_identity_unchanged",
        "new_artifacts",
        "no_new_session_artifact",
        "new_report_content_documents",
        "report_content_document_only",
        "no_new_scientific_effect",
    }
)
_LIVE_EFFECT_COUNT_FIELDS = frozenset(
    {
        "approval",
        "controlled_operation",
        "controlled_execution",
        "controlled_dispatch",
        "sandbox_run",
        "artifact_materialization",
        "scientific_materialization",
    }
)
_LIVE_REPORT_CONTENT_DOCUMENT_FIELDS = frozenset(
    {
        "document_id",
        "document_kind",
        "payload_digest",
    }
)
_LIVE_MICU_FIELDS = frozenset(
    {
        "attempts",
        "attempt_count",
        "all_bound_to_diagnostic_scenario",
        "authority_max_micu",
        "charged_tokens",
        "within_authority",
    }
)
_LIVE_MICU_ATTEMPT_FIELDS = frozenset(
    {
        "id",
        "scenario",
        "purpose",
        "kind",
        "model",
        "attempt",
        "input_tokens",
        "output_tokens",
        "charged_tokens",
        "estimated",
        "status",
        "reservation_overage_tokens",
        "hard_limit_breached",
        "cumulative_tokens",
    }
)
_LIVE_PUBLIC_OBSERVATION_FIELDS = frozenset(
    {
        "api_receipt_count",
        "api_receipts_digest",
        "browser_required",
        "browser_observed",
        "browser_receipt_digest",
    }
)
_LIVE_LEDGER_FIELDS = frozenset({"before", "after"})
_LIVE_LEDGER_SNAPSHOT_FIELDS = frozenset(
    {
        "hard_limit_tokens",
        "charged_tokens",
        "remaining_tokens",
        "hard_limit_overage_tokens",
        "attempt_count",
        "estimated_attempt_count",
        "input_tokens",
        "output_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "reservation_overage_tokens",
        "hard_limit_breach_count",
        "by_scenario",
        "by_model",
        "ledger_identity_digest",
    }
)
_LIVE_LEDGER_COUNTER_FIELDS = frozenset(
    {
        "attempt_count",
        "charged_tokens",
        "input_tokens",
        "output_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_attempt_count",
        "reservation_overage_tokens",
        "hard_limit_breach_count",
    }
)
_CHILD_EVIDENCE_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "run_attempt_id",
        "scientific_attempt_id",
        "session_id",
        "reconstruction_receipt_digest",
        "health",
        "baseline",
        "terminal",
        "effects",
        "closure",
        "micu_attempts",
        "api_receipts",
        "runtime",
        "product_path",
    }
)
_CHILD_PRODUCT_PATH_FIELDS = frozenset(
    {
        "completed",
        "attempt_supervision",
    }
)
_DECISION_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "attempt_id",
        "status",
        "decided_at",
        "blocker",
        "live_result_digest",
        "source_integrity",
        "formal_adoption",
        "decision_digest",
    }
)
_DECISION_SOURCE_FIELDS = frozenset(
    {
        "manifest_digest",
        "database_sha256_before",
        "database_sha256_after",
        "inventory_digest_before",
        "inventory_digest_after",
        "post_verified",
        "immutable",
    }
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_endpoint_identity(value: str) -> str:
    parsed = urlsplit(value)
    endpoint = {
        "scheme": parsed.scheme.casefold(),
        "host": (parsed.hostname or "").casefold(),
        "port": parsed.port,
        "path": parsed.path.rstrip("/"),
    }
    return canonical_digest(endpoint)


def _require_digest(value: object, *, identity: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise CutoverEvidenceError(
            "closure_stage_live_digest_invalid",
            "closure-stage live evidence contains a malformed digest",
            details={"identity": identity},
        )
    return value


def _source_launch_observation(
    source_inventory: Mapping[str, object],
) -> dict[str, Any]:
    campaign_root = Path(str(source_inventory["campaign_root"]))
    attempt_root = Path(str(source_inventory["attempt_root"]))
    attempt_id = str(source_inventory["attempt_id"])
    authority_path = Path(str(source_inventory["authority_plan_path"]))
    consumption_path = Path(
        str(source_inventory["authority_consumption_path"])
    )
    fatal_path = campaign_root / "failures" / f"{attempt_id}.fatal.json"
    decision_path = campaign_root / "campaign-decision.json"
    supervision_result_path = (
        attempt_root / "evidence" / ".attempt-supervision-result.json"
    )
    database_path = Path(str(source_inventory["database_path"]))
    try:
        authority = json.loads(authority_path.read_bytes())
        fatal = json.loads(fatal_path.read_bytes())
        supervision_result = json.loads(
            supervision_result_path.read_bytes()
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_launch_receipt_invalid",
            "frozen source launch evidence is unreadable",
        ) from exc
    if (
        not isinstance(authority, dict)
        or not isinstance(fatal, dict)
        or not isinstance(supervision_result, dict)
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_launch_receipt_invalid",
            "frozen source launch evidence is malformed",
        )
    slots = authority.get("slots")
    source_slots = (
        [
            dict(item)
            for item in slots
            if isinstance(item, dict)
            and item.get("attempt_id") == attempt_id
        ]
        if isinstance(slots, list)
        else []
    )
    payload = fatal.get("payload")
    if len(source_slots) != 1 or not isinstance(payload, dict):
        raise CutoverEvidenceError(
            "closure_stage_source_launch_receipt_invalid",
            "frozen source launch slot or supervision evidence is ambiguous",
        )
    slot = source_slots[0]
    request = slot.get("authority_request")
    evidence = supervision_result.get("evidence")
    product_path = (
        evidence.get("product_path")
        if isinstance(evidence, dict)
        else None
    )
    launch_receipt = (
        product_path.get("launch_receipt")
        if isinstance(product_path, dict)
        else None
    )
    effective_config = (
        launch_receipt.get("effective_config")
        if isinstance(launch_receipt, dict)
        else None
    )
    effective_config_digest = (
        launch_receipt.get("effective_config_digest")
        if isinstance(launch_receipt, dict)
        else None
    )
    driver = (
        effective_config.get("driver")
        if isinstance(effective_config, dict)
        else None
    )
    llm = (
        effective_config.get("llm")
        if isinstance(effective_config, dict)
        else None
    )
    ledger = payload.get("micu_verified_lower_bound")
    by_model = (
        list(ledger.get("by_model") or [])
        if isinstance(ledger, dict)
        else []
    )
    models = sorted(
        {
            str(item.get("model") or "")
            for item in by_model
            if isinstance(item, dict) and item.get("model")
        }
    )
    connection = sqlite3.connect(
        f"file:{database_path}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        drain_rows = connection.execute(
            """
            SELECT max_signals, max_steps_per_agent,
                   auto_enqueue_ready_tasks, COUNT(*)
            FROM runtime_command_records
            GROUP BY max_signals, max_steps_per_agent,
                     auto_enqueue_ready_tasks
            """
        ).fetchall()
    finally:
        connection.close()
    if (
        not isinstance(request, dict)
        or len(models) != 1
        or drain_rows != [(1, 16, 0, 124)]
        or payload.get("deadline_seconds") != 15060
        or payload.get("descendant_retirement_proven") is not True
        or not isinstance(launch_receipt, dict)
        or not isinstance(effective_config, dict)
        or not isinstance(driver, dict)
        or not isinstance(llm, dict)
        or launch_receipt.get("approval_mode") != "chrome-once"
        or effective_config_digest != canonical_digest(effective_config)
        or product_path.get("runtime_config_digest")
        != effective_config_digest
        or llm.get("model") != models[0]
        or {
            key: driver.get(key)
            for key in (
                "scenario",
                "approval_mode",
                "browser_observation_mode",
                "timeout_seconds",
                "max_drains",
                "max_signals_per_drain",
                "max_steps_per_agent",
                "browser_poll_interval_seconds",
                "browser_approval_timeout_seconds",
                "browser_completion_hold_seconds",
                "browser_observation_submission_timeout_seconds",
                "micu_hard_limit_tokens",
            )
        }
        != {
            "scenario": "aox_blank_world_cutover",
            "approval_mode": "chrome-once",
            "browser_observation_mode": BROWSER_OBSERVATION_MODE,
            "timeout_seconds": 7200,
            "max_drains": 120,
            "max_signals_per_drain": 1,
            "max_steps_per_agent": 16,
            "browser_poll_interval_seconds": 0.5,
            "browser_approval_timeout_seconds": 300,
            "browser_completion_hold_seconds": 60,
            "browser_observation_submission_timeout_seconds": 180,
            "micu_hard_limit_tokens": 500_000_000,
        }
        or _DIGEST_PATTERN.fullmatch(
            str(driver.get("ui_dist_digest") or "")
        )
        is None
        or _DIGEST_PATTERN.fullmatch(
            str(driver.get("micu_ledger_identity_digest") or "")
        )
        is None
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_runtime_parity_unproven",
            "frozen r59 evidence does not reproduce its runtime parity facts",
        )
    file_digests = {
        "authority": _sha256_file(authority_path),
        "consumption": _sha256_file(consumption_path),
        "fatal": _sha256_file(fatal_path),
        "campaign_decision": _sha256_file(decision_path),
        "supervision_result": _sha256_file(supervision_result_path),
    }
    projection = {
        "source_attempt_id": attempt_id,
        "source_authority_envelope_id": slot["envelope_id"],
        "source_authority_request_digest": slot["request_digest"],
        "effective_config_digest": effective_config_digest,
        "model": models[0],
        "max_signals_per_drain": 1,
        "max_steps_per_agent": 16,
        "auto_enqueue_ready_tasks": False,
        "supervision_timeout_seconds": 15060,
        "supervision_protocol_schema_id": SUPERVISION_SCHEMA_ID_V2,
        "supervision_contract_digest": supervision_contract_digest(
            timeout_seconds=15060.0,
            term_grace_seconds=DEFAULT_TERM_GRACE_SECONDS,
            kill_grace_seconds=DEFAULT_KILL_GRACE_SECONDS,
            protocol_schema_id=SUPERVISION_SCHEMA_ID_V2,
        ),
        "max_micu": int(request["max_micu"]),
        "max_cost_microunits": int(request["max_cost_microunits"]),
        "max_wall_time_seconds": int(request["max_wall_time_seconds"]),
        "file_digests": file_digests,
    }
    return {
        **projection,
        "source_launch_receipt_digest": canonical_digest(projection),
    }


def build_aox_closure_stage_runtime_parity(
    *,
    source_inventory: Mapping[str, object],
    effective_config: Mapping[str, object],
    identity: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    ledger_path: Path,
    supervision_timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build current launch bindings and an independently checkable parity receipt."""

    source = _source_launch_observation(source_inventory)
    config = dict(effective_config)
    llm = dict(config.get("llm") or {})
    driver = dict(config.get("driver") or {})
    reliability = dict(config.get("reliability") or {})
    workflow = dict(config.get("scientific_workflow_contract") or {})
    model = str(llm.get("model") or "")
    if (
        model != source["model"]
        or canonical_digest(config) != identity.get("config_digest")
        or identity.get("config_digest")
        != source["effective_config_digest"]
        or driver.get("max_signals_per_drain") != 1
        or driver.get("max_steps_per_agent") != 16
        or driver.get("max_drains") != 120
        or float(supervision_timeout_seconds) != 15060.0
        or workflow.get("workflow_id") != AOX_SELECTED_CHAIN_WORKFLOW_ID
        or workflow.get("workflow_contract_digest")
        != AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
    ):
        raise CutoverEvidenceError(
            "closure_stage_runtime_parity_mismatch",
            "current launch settings do not reproduce the r59 runtime contract",
        )
    canonical_ledger = ledger_path.expanduser().resolve(strict=True)
    source_launch_digest = str(source["source_launch_receipt_digest"])
    model_config = {
        key: llm.get(key)
        for key in (
            "model",
            "base_url_endpoint",
            "extra_body_digest",
            "default_headers_digest",
            "use_responses_api",
            "max_tokens",
            "timeout",
            "max_retries",
            "temperature",
            "structured_output_method",
            "context_window_tokens",
            "default_output_tokens",
        )
    }
    driver_limits = {
        key: driver.get(key)
        for key in (
            "approval_mode",
            "browser_observation_mode",
            "timeout_seconds",
            "max_drains",
            "max_signals_per_drain",
            "max_steps_per_agent",
            "browser_poll_interval_seconds",
            "browser_approval_timeout_seconds",
            "browser_completion_hold_seconds",
            "browser_observation_submission_timeout_seconds",
        )
    }
    writer_policy = {
        key: reliability.get(key)
        for key in (
            "controlled_operation_owner_policy",
            "durable_execution_route_allowlist",
            "runtime_drain_contract",
            "mutation_closure_mode",
        )
    }
    policy_paths = (
        REPO_ROOT
        / "apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_tool_policy.py",
        REPO_ROOT / "packages/openzyme-core/src/openzyme_core/task_board.py",
        REPO_ROOT / "packages/openzyme-core/src/openzyme_core/teammates.py",
    )
    tool_response_policy = {
        str(path.relative_to(REPO_ROOT)): _sha256_file(path)
        for path in policy_paths
    }
    public_contract = {
        "routes": [
            "GET /v3/runtime/health",
            "POST /v3/sessions/{session_id}/runtime/drain",
            "GET /v3/sessions/{session_id}/runtime/commands/{command_id}",
            "GET /v3/sessions/{session_id}/workspace",
            "GET /v3/sessions/{session_id}/events",
        ],
        "ui_dist_digest": driver.get("ui_dist_digest"),
        "browser_observation_mode": driver.get(
            "browser_observation_mode"
        ),
    }
    declaration = {
        "schema_id": (
            AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID
        ),
        "source_launch_receipt_digest": source_launch_digest,
        "model_config_digest": canonical_digest(model_config),
        "driver_limits_digest": canonical_digest(driver_limits),
        "writer_policy_digest": canonical_digest(writer_policy),
        "tool_response_policy_digest": canonical_digest(
            tool_response_policy
        ),
        "source_supervision_contract_digest": source[
            "supervision_contract_digest"
        ],
        "target_supervision_contract_digest": supervision_contract_digest(
            timeout_seconds=supervision_timeout_seconds,
            term_grace_seconds=DEFAULT_TERM_GRACE_SECONDS,
            kill_grace_seconds=DEFAULT_KILL_GRACE_SECONDS,
            protocol_schema_id=SUPERVISION_SCHEMA_ID,
        ),
        "public_observation_contract_digest": canonical_digest(
            public_contract
        ),
    }
    target = {
        "git_commit": identity.get("git_commit"),
        "config_digest": identity.get("config_digest"),
        "workflow_ref": identity.get("workflow_ref"),
        "model": model,
        "model_config_digest": declaration["model_config_digest"],
        "driver_limits_digest": declaration["driver_limits_digest"],
        "writer_policy_digest": declaration["writer_policy_digest"],
        "tool_response_policy_digest": declaration[
            "tool_response_policy_digest"
        ],
        "supervision_timeout_seconds": supervision_timeout_seconds,
        "supervision_protocol_schema_id": SUPERVISION_SCHEMA_ID,
        "supervision_contract_digest": declaration[
            "target_supervision_contract_digest"
        ],
        "public_observation_contract_digest": declaration[
            "public_observation_contract_digest"
        ],
    }
    allowed_differences = [
        "implementation_commit_and_derived_contract_digests",
        "closure_stage_run_authority_root_process_and_evidence_identities",
        "cursor_614_reconstructed_start_projection",
        "diagnostic_micu_scenario_and_non_acceptance_result_schema",
        "supervision_protocol_v2_to_v3_local_settlement_repair",
    ]
    parity_payload = {
        "schema_id": AOX_CLOSURE_STAGE_PARITY_RECEIPT_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "source": source,
        "target": target,
        "allowed_differences": allowed_differences,
        "declaration": declaration,
    }
    parity = {
        **parity_payload,
        "receipt_digest": canonical_digest(parity_payload),
    }
    validate_aox_closure_stage_runtime_parity(parity)
    qualification_digest = canonical_digest(
        dict(architecture_qualification)
    )
    sop_path = (
        REPO_ROOT / "docs/v3/execution-pipeline-docs/aox-hmm-live.md"
    )
    closure_stage_sop_path = (
        REPO_ROOT / "docs/v3/aox-closure-stage-live-diagnostic.md"
    )
    contract_bindings = {
        "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "workflow_contract_digest": (
            AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        ),
        "sop_digest": _sha256_file(sop_path),
        "closure_stage_sop_digest": _sha256_file(
            closure_stage_sop_path
        ),
        "architecture_qualification_digest": qualification_digest,
        "ui_dist_digest": str(driver["ui_dist_digest"]),
        "source_launch_receipt_digest": source_launch_digest,
        "repair_commit": str(identity["git_commit"]),
        "runtime_config_digest": str(identity["config_digest"]),
    }
    micu = {
        "schema_id": AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID,
        "provider": "openai-compatible",
        "endpoint_identity": _safe_endpoint_identity(
            str(llm.get("base_url_endpoint") or "")
        ),
        "model": model,
        "token_scenario": "aox_closure_stage_diagnostic",
        "ledger_path": str(canonical_ledger),
        "ledger_identity": canonical_digest(
            {"ledger_path": str(canonical_ledger)}
        ),
        "effective_config_digest": str(identity["config_digest"]),
    }
    return contract_bindings, declaration, micu, parity


def validate_aox_closure_stage_runtime_parity(
    receipt: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(receipt)
    source = normalized.get("source")
    target = normalized.get("target")
    declaration = normalized.get("declaration")
    differences = normalized.get("allowed_differences")
    file_digests = (
        source.get("file_digests") if isinstance(source, dict) else None
    )
    if (
        set(normalized) != _PARITY_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_PARITY_RECEIPT_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or not isinstance(source, dict)
        or not isinstance(target, dict)
        or not isinstance(declaration, dict)
        or set(source) != _PARITY_SOURCE_FIELDS
        or set(target) != _PARITY_TARGET_FIELDS
        or set(declaration) != _PARITY_DECLARATION_FIELDS
        or not isinstance(file_digests, dict)
        or set(file_digests) != _PARITY_FILE_DIGEST_FIELDS
        or declaration.get("schema_id")
        != AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID
        or differences
        != [
            "implementation_commit_and_derived_contract_digests",
            "closure_stage_run_authority_root_process_and_evidence_identities",
            "cursor_614_reconstructed_start_projection",
            "diagnostic_micu_scenario_and_non_acceptance_result_schema",
            "supervision_protocol_v2_to_v3_local_settlement_repair",
        ]
        or source.get("model") != target.get("model")
        or source.get("effective_config_digest")
        != target.get("config_digest")
        or source.get("max_signals_per_drain") != 1
        or source.get("max_steps_per_agent") != 16
        or source.get("auto_enqueue_ready_tasks") is not False
        or source.get("supervision_timeout_seconds") != 15060
        or source.get("supervision_protocol_schema_id")
        != SUPERVISION_SCHEMA_ID_V2
        or source.get("supervision_contract_digest")
        != supervision_contract_digest(
            timeout_seconds=15060.0,
            term_grace_seconds=DEFAULT_TERM_GRACE_SECONDS,
            kill_grace_seconds=DEFAULT_KILL_GRACE_SECONDS,
            protocol_schema_id=SUPERVISION_SCHEMA_ID_V2,
        )
        or source.get("max_micu") != 20_000_000
        or source.get("max_cost_microunits") != 0
        or source.get("max_wall_time_seconds") != 10_800
        or target.get("supervision_timeout_seconds") != 15060
        or target.get("supervision_protocol_schema_id")
        != SUPERVISION_SCHEMA_ID
        or target.get("supervision_contract_digest")
        != supervision_contract_digest(
            timeout_seconds=15060.0,
            term_grace_seconds=DEFAULT_TERM_GRACE_SECONDS,
            kill_grace_seconds=DEFAULT_KILL_GRACE_SECONDS,
            protocol_schema_id=SUPERVISION_SCHEMA_ID,
        )
        or source.get("supervision_contract_digest")
        != declaration.get("source_supervision_contract_digest")
        or target.get("supervision_contract_digest")
        != declaration.get("target_supervision_contract_digest")
        or source.get("source_launch_receipt_digest")
        != declaration.get("source_launch_receipt_digest")
        or any(
            target.get(field) != declaration.get(field)
            for field in (
                "model_config_digest",
                "driver_limits_digest",
                "writer_policy_digest",
                "tool_response_policy_digest",
                "public_observation_contract_digest",
            )
        )
        or source.get("source_launch_receipt_digest")
        != canonical_digest(
            {
                key: value
                for key, value in source.items()
                if key != "source_launch_receipt_digest"
            }
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_runtime_parity_receipt_invalid",
            "closure-stage runtime parity receipt violates its closed contract",
        )
    for identity, value in (
        ("source_launch_receipt_digest", source.get("source_launch_receipt_digest")),
        ("source.effective_config_digest", source.get("effective_config_digest")),
        ("target.config_digest", target.get("config_digest")),
        ("parity.receipt_digest", normalized.get("receipt_digest")),
        *(
            (f"source.file_digests.{key}", value)
            for key, value in file_digests.items()
        ),
        *(
            (f"declaration.{field}", declaration.get(field))
            for field in _PARITY_DECLARATION_FIELDS - {"schema_id"}
        ),
    ):
        _require_digest(value, identity=identity)
    if normalized.get("receipt_digest") != canonical_digest(
        {
            key: value
            for key, value in normalized.items()
            if key != "receipt_digest"
        }
    ):
        raise CutoverEvidenceError(
            "closure_stage_runtime_parity_digest_mismatch",
            "closure-stage runtime parity digest does not reproduce",
        )
    return normalized


def seal_aox_closure_stage_runtime_parity(
    receipt: Mapping[str, object],
    path: Path,
) -> None:
    normalized = validate_aox_closure_stage_runtime_parity(receipt)
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(normalized) + b"\n",
    )


def _count(
    connection: sqlite3.Connection,
    table: str,
    *,
    column: str,
    value: str,
) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",  # noqa: S608
            (value,),
        ).fetchone()[0]
    )


def _runtime_projection(
    provider: SQLiteRepositoryProvider,
    *,
    session_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    with provider.read() as scope:
        repositories = scope.repositories
        connection = repositories.tasks.connection
        tasks = tuple(repositories.tasks.list_by_session(session_id))
        agents = tuple(repositories.agents.list_by_session(session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(session_id)
        )
        reports = tuple(repositories.reports.list_by_session(session_id))
        drafts = tuple(
            repositories.report_drafts.list_by_session(session_id)
        )
        artifacts = tuple(
            repositories.artifacts.list_by_session(session_id)
        )
        operations = tuple(
            repositories.controlled_operations.list_by_session(session_id)
        )
        executions = tuple(
            repositories.controlled_operation_executions.list_by_session(
                session_id
            )
        )
        execution_by_operation = {
            execution.operation_id: execution for execution in executions
        }
        finish_receipts = [
            {
                "document_id": document.document_id,
                "payload": dict(document.payload or {}),
            }
            for document in documents
            if document.document_kind == "task_finish"
        ]
        closure_requests = [
            dict(row)
            for row in connection.execute(
                """
                SELECT closure_request_id, attempt_id, selection_id, actor_ref,
                       request_digest
                FROM scientific_attempt_closure_request_records
                WHERE attempt_id = ?
                ORDER BY closure_request_id
                """,
                (attempt_id,),
            )
        ]
        closure_responses = [
            dict(row)
            for row in connection.execute(
                """
                SELECT closure_response_id, closure_request_id, attempt_id,
                       message_id, document_id, recipient, recipient_kind,
                       response_digest, binding_digest
                FROM scientific_attempt_closure_response_records
                WHERE attempt_id = ?
                ORDER BY closure_response_id
                """,
                (attempt_id,),
            )
        ]
        closures = [
            dict(row)
            for row in connection.execute(
                """
                SELECT closure_id, closure_request_id, attempt_id, selection_id,
                       operation_universe_digest, actor_ref, request_digest,
                       closure_digest
                FROM scientific_attempt_closure_records
                WHERE attempt_id = ?
                ORDER BY closure_id
                """,
                (attempt_id,),
            )
        ]
        attempt = connection.execute(
            """
            SELECT attempt_id, status, mutation_scope_id
            FROM scientific_attempt_records
            WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if attempt is None:
            raise LiveProductPathError(
                "closure_stage_attempt_missing",
                "closure-stage runtime lost its reconstructed attempt",
            )
        event_rows = [
            {
                "cursor": int(row["cursor"]),
                "event_type": str(row["event_type"]),
                "payload_digest": canonical_digest(
                    json.loads(str(row["payload_json"]))
                ),
            }
            for row in connection.execute(
                """
                SELECT cursor, event_type, payload_json
                FROM durable_event_records
                WHERE session_id = ?
                ORDER BY cursor
                """,
                (session_id,),
            )
        ]
        projection = {
            "tasks": sorted(
                (
                    {
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "status": task.status.value,
                        "assigned_ref": task.assigned_ref,
                        "lane_id": task.lane_id,
                    }
                    for task in tasks
                ),
                key=lambda item: str(item["task_id"]),
            ),
            "agents": sorted(
                (
                    {
                        "agent_id": agent.agent_id,
                        "role": agent.role,
                        "status": agent.status.value,
                        "runtime_state": agent.runtime_state,
                        "task_id": agent.task_id,
                        "lane_id": agent.lane_id,
                    }
                    for agent in agents
                ),
                key=lambda item: str(item["agent_id"]),
            ),
            "task_finishes": sorted(
                finish_receipts,
                key=lambda item: str(item["document_id"]),
            ),
            "report_content_documents": sorted(
                (
                    {
                        "document_id": document.document_id,
                        "document_kind": document.document_kind,
                        "payload_digest": canonical_digest(
                            dict(document.payload or {})
                        ),
                    }
                    for document in documents
                    if document.document_kind == "report_draft_content"
                ),
                key=lambda item: str(item["document_id"]),
            ),
            "reports": [report.to_dict() for report in reports],
            "report_drafts": [draft.to_dict() for draft in drafts],
            "artifacts": sorted(
                (
                    {
                        "artifact_id": artifact.artifact_id,
                        "task_id": artifact.task_id,
                        "lane_id": artifact.lane_id,
                        "kind": artifact.kind.value,
                        "relative_path": artifact.relative_path,
                        "diagnostic_source_copy": bool(
                            dict(artifact.metadata or {}).get(
                                "diagnostic_source_copy"
                            )
                        ),
                    }
                    for artifact in artifacts
                ),
                key=lambda item: str(item["artifact_id"]),
            ),
            "operations": sorted(
                (
                    {
                        "operation_id": operation.operation_id,
                        "operation_digest": operation.operation_digest,
                        "status": operation.status.value,
                        "effect_certainty": (
                            execution_by_operation[
                                operation.operation_id
                            ].effect_certainty.value
                            if operation.operation_id
                            in execution_by_operation
                            else None
                        ),
                    }
                    for operation in operations
                ),
                key=lambda item: str(item["operation_id"]),
            ),
            "attempt": dict(attempt),
            "closure_requests": closure_requests,
            "closure_responses": closure_responses,
            "closures": closures,
            "counts": {
                "approval": _count(
                    connection,
                    "approval_requests",
                    column="session_id",
                    value=session_id,
                ),
                "controlled_operation": len(operations),
                "controlled_execution": _count(
                    connection,
                    "controlled_operation_execution_records",
                    column="session_id",
                    value=session_id,
                ),
                "controlled_dispatch": _count(
                    connection,
                    "controlled_operation_dispatch_requests",
                    column="session_id",
                    value=session_id,
                ),
                "sandbox_run": _count(
                    connection,
                    "sandbox_run_records",
                    column="session_id",
                    value=session_id,
                ),
                "artifact_materialization": int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM artifact_materialization_records AS materialization
                        JOIN session_artifact_records AS artifact
                          ON artifact.artifact_id = materialization.artifact_id
                        WHERE artifact.session_id = ?
                        """,
                        (session_id,),
                    ).fetchone()[0]
                ),
                "scientific_materialization": _count(
                    connection,
                    "scientific_artifact_materialization_records",
                    column="attempt_id",
                    value=attempt_id,
                ),
                "artifact": len(artifacts),
                "report": len(reports),
                "report_draft": len(drafts),
                "pending_signal": int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM agent_runtime_signals
                        WHERE session_id = ? AND status = 'pending'
                        """,
                        (session_id,),
                    ).fetchone()[0]
                ),
                "active_session_lease": int(
                    repositories.session_runtime_leases.get_active(session_id)
                    is not None
                ),
                "active_writer": int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM mutation_writer_records AS writer
                        JOIN mutation_scope_records AS scope
                          ON scope.scope_id = writer.scope_id
                        WHERE scope.session_id = ?
                          AND writer.state IN ('registered', 'retiring')
                        """,
                        (session_id,),
                    ).fetchone()[0]
                ),
                "unsettled_continuation": int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM continuation_state_records
                        WHERE session_id = ?
                          AND status NOT IN ('completed', 'failed', 'cancelled')
                        """,
                        (session_id,),
                    ).fetchone()[0]
                ),
            },
            "events": {
                "count": len(event_rows),
                "first_cursor": (
                    None if not event_rows else event_rows[0]["cursor"]
                ),
                "last_cursor": (
                    None if not event_rows else event_rows[-1]["cursor"]
                ),
                "stream_digest": canonical_digest(event_rows),
            },
        }
    return {
        **projection,
        "projection_digest": canonical_digest(projection),
    }


def _new_micu_receipts(
    path: Path,
    *,
    before_ids: set[int],
    expected_model: str,
) -> list[dict[str, Any]]:
    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, scenario, purpose, kind, model, attempt,
                   input_tokens, output_tokens, charged_tokens, estimated,
                   status, reservation_overage_tokens, hard_limit_breached,
                   cumulative_tokens
            FROM live_micu_token_attempts
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()
    receipts = [
        dict(row) for row in rows if int(row["id"]) not in before_ids
    ]
    if (
        not receipts
        or {str(item["scenario"]) for item in receipts}
        != {"aox_closure_stage_diagnostic"}
        or {str(item["model"]) for item in receipts} != {expected_model}
        or any(
            item["status"] not in _TERMINAL_MICU_STATUSES
            or bool(item["hard_limit_breached"])
            for item in receipts
        )
        or not any(not bool(item["estimated"]) for item in receipts)
    ):
        raise LiveProductPathError(
            "closure_stage_micu_attribution_invalid",
            "closure-stage MICU rows are missing, unbound, nonterminal, or estimated-only",
        )
    return receipts


def _effect_delta(
    baseline: Mapping[str, object],
    terminal: Mapping[str, object],
) -> dict[str, Any]:
    before_counts = dict(baseline["counts"])
    after_counts = dict(terminal["counts"])
    immutable_count_keys = (
        "approval",
        "controlled_operation",
        "controlled_execution",
        "controlled_dispatch",
        "sandbox_run",
        "artifact_materialization",
        "scientific_materialization",
    )
    count_deltas = {
        key: int(after_counts[key]) - int(before_counts[key])
        for key in immutable_count_keys
    }
    operation_identity_unchanged = (
        baseline["operations"] == terminal["operations"]
    )
    before_artifacts = {
        str(item["artifact_id"])
        for item in baseline["artifacts"]
        if isinstance(item, dict)
    }
    after_artifacts = {
        str(item["artifact_id"]): dict(item)
        for item in terminal["artifacts"]
        if isinstance(item, dict)
    }
    new_artifacts = [
        after_artifacts[artifact_id]
        for artifact_id in sorted(set(after_artifacts) - before_artifacts)
    ]
    no_new_session_artifact = (
        baseline["artifacts"] == terminal["artifacts"]
    )
    before_report_documents = {
        str(item["document_id"])
        for item in baseline["report_content_documents"]
        if isinstance(item, dict)
    }
    after_report_documents = {
        str(item["document_id"]): dict(item)
        for item in terminal["report_content_documents"]
        if isinstance(item, dict)
    }
    new_report_content_documents = [
        after_report_documents[document_id]
        for document_id in sorted(
            set(after_report_documents) - before_report_documents
        )
    ]
    published_drafts = [
        dict(item)
        for item in terminal["report_drafts"]
        if isinstance(item, dict) and item.get("status") == "published"
    ]
    published_content_refs = {
        str(item["content_ref"])
        for item in published_drafts
        if item.get("content_ref")
    }
    report_content_document_only = (
        not before_report_documents
        and len(new_report_content_documents) == 1
        and {
            str(item["document_id"])
            for item in new_report_content_documents
        }
        == published_content_refs
    )
    no_new_scientific_effect = (
        all(value == 0 for value in count_deltas.values())
        and operation_identity_unchanged
        and no_new_session_artifact
        and not new_artifacts
        and report_content_document_only
    )
    return {
        "count_deltas": count_deltas,
        "operation_identity_unchanged": operation_identity_unchanged,
        "new_artifacts": new_artifacts,
        "no_new_session_artifact": no_new_session_artifact,
        "new_report_content_documents": new_report_content_documents,
        "report_content_document_only": report_content_document_only,
        "no_new_scientific_effect": no_new_scientific_effect,
    }


def _closure_stage_browser_anchor(
    baseline: Mapping[str, object],
    *,
    ui_dist_digest: str,
    host_process_id: int,
    observation_challenge: str,
) -> dict[str, object]:
    operations = [
        dict(item)
        for item in baseline.get("operations") or []
        if isinstance(item, dict)
    ]
    if len(operations) != 6:
        raise LiveProductPathError(
            "closure_stage_browser_anchor_invalid",
            "closure-stage browser proof requires the exact sealed operation universe",
        )
    operation = operations[-1]
    operation_id = operation.get("operation_id")
    operation_digest = operation.get("operation_digest")
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or not isinstance(operation_digest, str)
        or _DIGEST_PATTERN.fullmatch(operation_digest) is None
        or _DIGEST_PATTERN.fullmatch(observation_challenge) is None
    ):
        raise LiveProductPathError(
            "closure_stage_browser_anchor_invalid",
            "closure-stage browser proof lacks a canonical sealed operation",
        )
    return {
        "approval_id": "closure-stage-no-operation-approval",
        "operation_id": operation_id,
        "operation_digest": operation_digest,
        "page_url": BROWSER_SEALED_PAGE_URL,
        "host_process_id": host_process_id,
        "served_ui_dist_digest": ui_dist_digest,
        "observation_challenge": observation_challenge,
    }


def _closure_stage_runtime_summary(
    formal: SessionDriveResult,
) -> dict[str, object]:
    summary = formal.safe_summary()
    approval_observed = summary.pop("browser_approval_observed")
    approval_digest = summary.pop("browser_approval_receipt_digest")
    return {
        **summary,
        "browser_anchor_observed": approval_observed,
        "browser_anchor_receipt_digest": approval_digest,
    }


def _project_terminal_scope_rollover(
    provider: SQLiteRepositoryProvider,
    *,
    attempt_id: str,
) -> dict[str, object]:
    with provider.read() as scope:
        repositories = scope.repositories
        attempt = repositories.scientific_attempts.get(attempt_id)
        if attempt is None:
            raise LiveProductPathError(
                "closure_stage_attempt_missing",
                "closure-stage runtime lost its reconstructed attempt",
            )
        envelope = ScientificAttemptScopeRolloverEnvelope(
            session_id=attempt.session_id,
            envelope_id=attempt.envelope_id,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            campaign_id=attempt.campaign_id,
            workflow_id=attempt.workflow_id,
            scope=attempt.scope,
            root_ref=attempt.root_ref,
        )
        try:
            projection = ScientificAttemptScopeRolloverProjector(
                repositories
            ).project(envelope)
        except ScientificAttemptScopeRolloverIntegrityError as exc:
            raise LiveProductPathError(
                exc.error_code,
                "closure-stage terminal scope rollover is invalid",
            ) from exc
    payload = {
        "phase": projection.phase.value,
        "attempt_id": projection.attempt_id,
        "attempt_scope_id": projection.attempt_scope_id,
        "attempt_scope_state": projection.attempt_scope_state.value,
        "post_scope_id": projection.post_scope_id,
        "open_scope_count": projection.open_scope_count,
    }
    if (
        projection.phase
        is not ScientificAttemptScopeRolloverPhase.POST_CLOSURE_SCOPE_OPEN
        or projection.open_scope_count != 1
        or projection.post_scope_id is None
    ):
        raise LiveProductPathError(
            "scientific_attempt_scope_rollover_invalid",
            "closure-stage terminal scope rollover is incomplete",
        )
    return {
        **payload,
        "projection_digest": canonical_digest(payload),
    }


def _validate_terminal_projection(
    *,
    provider: SQLiteRepositoryProvider,
    formal: SessionDriveResult,
    terminal: Mapping[str, object],
    execution_task_id: str,
    research_task_id: str,
    report_task_id: str,
    selection_id: str,
    effect_delta: Mapping[str, object],
) -> dict[str, Any]:
    if formal.state != "completed":
        raise LiveProductPathError(
            formal.blocker_code or "closure_stage_runtime_incomplete",
            "closure-stage runtime did not reach the normal completed state",
        )
    with provider.read() as scope:
        repositories = scope.repositories
        tasks = tuple(repositories.tasks.list_by_session(formal.session_id))
        agents = tuple(repositories.agents.list_by_session(formal.session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(formal.session_id)
        )
        reports = tuple(
            repositories.reports.list_by_session(formal.session_id)
        )
        drafts = tuple(
            repositories.report_drafts.list_by_session(formal.session_id)
        )
    task_receipts, task_ids_by_role = _task_receipts(
        tasks=tasks,
        agents=agents,
        documents=documents,
    )
    if task_ids_by_role != {
        "researcher": research_task_id,
        "executor": execution_task_id,
        "reporter": report_task_id,
    }:
        raise LiveProductPathError(
            "closure_stage_task_identity_drift",
            "closure-stage terminal task owners differ from reconstruction",
        )
    execution_receipts = [
        item
        for item in task_receipts
        if item["task_id"] == execution_task_id
    ]
    reporter_receipts = [
        item
        for item in task_receipts
        if item["task_id"] == report_task_id
    ]
    published_reports = [
        report for report in reports if is_published_report_status(report)
    ]
    published_drafts = [
        draft for draft in drafts if draft.status.value == "published"
    ]
    linked_report = (
        len(published_reports) == 1
        and len(published_drafts) == 1
        and is_published_report_link(
            published_reports[0],
            published_drafts[0],
            task_id=report_task_id,
        )
    )
    linked_report_content = (
        None
        if not linked_report
        else next(
            (
                document
                for document in documents
                if document.document_id
                == published_drafts[0].content_ref
                and document.document_kind
                == "report_draft_content"
            ),
            None,
        )
    )
    reporter_evidence_refs = (
        ()
        if len(reporter_receipts) != 1
        else tuple(
            str(item)
            for item in reporter_receipts[0]["evidence_refs"]
        )
    )
    with provider.read() as scope:
        report_source_evaluation = evaluate_aox_source_linked_report(
            scope.repositories,
            session_id=formal.session_id,
            research_task_id=research_task_id,
            report_task_id=report_task_id,
            reporter_evidence_refs=reporter_evidence_refs,
            require_diagnostic_source_copy=True,
        )
    report_source_link = None
    if report_source_evaluation["ready"] is True:
        report_source_link_payload = {
            "report_ref": (
                "report:"
                + str(report_source_evaluation["report_id"])
            ),
            "primary_pubmed_artifact_ref": (
                "artifact:"
                + str(
                    report_source_evaluation[
                        "primary_artifact_id"
                    ]
                )
            ),
            "primary_pubmed_artifact_digest": str(
                report_source_evaluation["primary_artifact_digest"]
            ),
            "source_ref_ids": list(
                report_source_evaluation["source_ref_ids"]
            ),
        }
        report_source_link = {
            **report_source_link_payload,
            "link_digest": canonical_digest(
                report_source_link_payload
            ),
        }
    closure_requests = list(terminal["closure_requests"])
    closure_responses = list(terminal["closure_responses"])
    closures = list(terminal["closures"])
    terminal_counts = dict(terminal["counts"])
    attempt_id = str(dict(terminal["attempt"])["attempt_id"])
    scope_rollover = _project_terminal_scope_rollover(
        provider,
        attempt_id=attempt_id,
    )
    if (
        len(execution_receipts) != 1
        or not execution_receipts[0]["evidence_refs"]
        or len(reporter_receipts) != 1
        or not linked_report
        or linked_report_content is None
        or report_source_link is None
        or published_reports[0].artifact_id is not None
        or len(closure_requests) != 1
        or closure_requests[0]["actor_ref"] != "agent:master"
        or closure_requests[0]["selection_id"] != selection_id
        or len(closure_responses) != 1
        or closure_responses[0]["closure_request_id"]
        != closure_requests[0]["closure_request_id"]
        or len(closures) != 1
        or closures[0]["closure_request_id"]
        != closure_requests[0]["closure_request_id"]
        or closures[0]["actor_ref"] != "agent:master"
        or terminal_counts.get("pending_signal") != 0
        or terminal_counts.get("active_session_lease") != 0
        or terminal_counts.get("active_writer") != 0
        or terminal_counts.get("unsettled_continuation") != 0
        or effect_delta.get("no_new_scientific_effect") is not True
        or formal.scientific_attempt_control is None
    ):
        raise LiveProductPathError(
            "closure_stage_terminal_contract_invalid",
            "closure-stage terminal state is partial, contradictory, or effectful",
        )
    return {
        "task_receipts": task_receipts,
        "report_id": published_reports[0].report_id,
        "report_content_ref": linked_report_content.document_id,
        "report_source_link": report_source_link,
        "closure_request_id": closure_requests[0]["closure_request_id"],
        "closure_response_id": closure_responses[0][
            "closure_response_id"
        ],
        "closure_id": closures[0]["closure_id"],
        "scope_rollover": scope_rollover,
        "scientific_attempt_control_digest": canonical_digest(
            formal.scientific_attempt_control
        ),
    }


@dataclass(slots=True)
class ClosureStageLiveRunner(LiveAoxAttemptRunner):
    diagnostic_id: str = ""
    scientific_attempt_id: str = ""
    selection_id: str = ""
    research_task_id: str = ""
    report_task_id: str = ""
    reconstruction_receipt_digest: str = ""

    def __post_init__(self) -> None:
        LiveAoxAttemptRunner.__post_init__(self)
        if (
            self.run_class
            is not AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC
            or CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(
                self.diagnostic_id
            )
            is None
            or not self.scientific_attempt_id
            or not self.selection_id
            or not self.research_task_id
            or not self.report_task_id
        ):
            raise ValueError(
                "closure-stage live runner requires exact reconstructed identities"
            )
        _require_digest(
            self.reconstruction_receipt_digest,
            identity="reconstruction_receipt_digest",
        )

    def __call__(self, context: AttemptRunContext) -> dict[str, Any]:
        blocker = self._settings_blocker(context)
        if blocker is not None:
            raise LiveProductPathError(
                blocker["code"],
                blocker["message"],
            )
        authority = self._require_selected_chain_attempt_authority(
            context.attempt_authority,
            session_id=str(
                dict(context.attempt_authority or {})["session_id"]
            ),
            expected_scope="formal",
            outer_attempt_id=context.roots.attempt_id,
        )
        session_id = str(authority["session_id"])
        execution_task_id = str(authority["task_id"])
        provider = SQLiteRepositoryProvider(str(context.roots.sqlite_path))
        micu_ids_before = _micu_record_ids(self.ledger_path)
        foundation = build_configured_foundation(
            settings=self.settings,
            token_scenario_override="aox_closure_stage_diagnostic",
        )
        lifecycle_policy = AoxCutoverFormalToolPrecondition(
            session_id=session_id,
            execution_task_id=execution_task_id,
            attempt_kind="positive",
            research_task_id=self.research_task_id,
            report_task_id=self.report_task_id,
            sealed_operation_universe=True,
        )
        dependencies = HostApiDependencies(
            foundation=foundation,
            v3_repository_provider=provider,
            v3_background_runtime_enabled=False,
            v3_tool_dispatch_precondition=lifecycle_policy,
            v3_sandbox_workspace_root=context.roots.sandbox_root,
            v3_artifact_blob_root=context.roots.blob_root,
        )
        browser_enabled = self._browser_gate_enabled(context)
        app = create_app(
            dependencies,
            **(
                {"ui_dist_dir": self.ui_dist_dir}
                if browser_enabled
                else {}
            ),
        )
        with self._host_client(
            app,
            browser_gate_enabled=browser_enabled,
        ) as raw_client:
            from .aox_cutover_live import _PublicHostClient

            api = _PublicHostClient(raw_client)
            health = api.get_json("/v3/runtime/health")
            health_blocker = self._health_blocker(health)
            if health_blocker is not None:
                raise LiveProductPathError(
                    health_blocker["code"],
                    health_blocker["message"],
                )
            writer_factory = MutationWriterTurnFactory(
                repository_scope_factory=lambda: (
                    self._provider_repository_scope(provider)
                )
            )
            with writer_factory.open(
                session_id=session_id,
                owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                owner_ref=(
                    "aox-closure-stage-runtime-bootstrap:"
                    + self.diagnostic_id
                ),
            ) as writer:
                if writer is None:
                    raise LiveProductPathError(
                        "closure_stage_bootstrap_writer_missing",
                        "closure-stage runtime could not bind its bootstrap writer",
                    )
                self._bootstrap_sandbox_runtime_identity(
                    provider,
                    health=health,
                    identity=context.identity,
                )
            baseline = _runtime_projection(
                provider,
                session_id=session_id,
                attempt_id=self.scientific_attempt_id,
            )
            browser_anchor: dict[str, object] | None = None
            if browser_enabled:
                ui_digest = str(
                    dict(
                        dict(self.effective_config or {}).get("driver")
                        or {}
                    ).get("ui_dist_digest")
                    or ""
                )
                browser_anchor = _closure_stage_browser_anchor(
                    baseline,
                    ui_dist_digest=ui_digest,
                    host_process_id=os.getpid(),
                    observation_challenge=(
                        "sha256:"
                        + hashlib.sha256(secrets.token_bytes(32)).hexdigest()
                    ),
                )
                _emit_operator_record(
                    {
                        "schema_id": MANUAL_APPROVAL_HANDOFF_SCHEMA_ID,
                        "status": "closure_stage_page_ready",
                        "session_id": session_id,
                        "ui_url": (
                            f"{api.base_url}/ui/?project_id="
                            "aox-closure-stage-diagnostic"
                        ),
                        "sealed_page_url": BROWSER_SEALED_PAGE_URL,
                        "host_process_id": os.getpid(),
                        "served_ui_dist_digest": ui_digest,
                        "browser_observation_mode": (
                            BROWSER_OBSERVATION_MODE
                        ),
                        "browser_observation_challenge": (
                            browser_anchor["observation_challenge"]
                        ),
                        "browser_observation_receipt_path": str(
                            self.browser_observation_receipt_path
                        ),
                    }
                )
            formal, fault = self._run_session_scoped(
                api,
                provider,
                session_id=session_id,
                purpose="formal",
                message="",
                workflow_refs=(),
                fault_enabled=False,
                fault_blob_root=None,
                browser_gate_enabled=False,
                mutation_scope={},
                attempt_authority=authority,
                post_entry_message=False,
            )
            if fault is not None:
                raise LiveProductPathError(
                    "closure_stage_fault_receipt_unexpected",
                    "closure-stage diagnostic produced a fault-injection receipt",
                )
            if browser_anchor is not None:
                formal = replace(
                    formal,
                    browser_approval_receipt=browser_anchor,
                )
            positive_blocker = self._positive_blocker(
                provider,
                formal,
                browser_gate_required=browser_enabled,
            )
            if positive_blocker is not None:
                raise LiveProductPathError(
                    positive_blocker["code"],
                    positive_blocker["message"],
                )
            if browser_anchor is not None:
                expected_page_state = _terminal_browser_page_state(formal)
                ready_monotonic = time.monotonic()
                ready_wall_ns = time.time_ns()
                not_before_ns = ready_wall_ns + int(
                    round(
                        self.browser_completion_hold_seconds
                        * 1_000_000_000
                    )
                )
                _emit_operator_record(
                    {
                        "schema_id": MANUAL_APPROVAL_HANDOFF_SCHEMA_ID,
                        "status": "ready_for_completion_observation",
                        "session_id": session_id,
                        "hold_seconds": self.browser_completion_hold_seconds,
                        "observation_submission_timeout_seconds": (
                            self.browser_observation_submission_timeout_seconds
                        ),
                        "observation_ready_at_unix_ns": ready_wall_ns,
                        "receipt_not_before_unix_ns": not_before_ns,
                        "workspace_digest": canonical_digest(
                            formal.workspace
                        ),
                        "event_receipt": formal.event_receipt,
                        "expected_page_state": expected_page_state,
                        "expected_page_state_digest": canonical_digest(
                            expected_page_state
                        ),
                        "browser_observation_mode": (
                            BROWSER_OBSERVATION_MODE
                        ),
                        "browser_observation_receipt_schema_id": (
                            BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
                        ),
                        "sealed_page_url": browser_anchor["page_url"],
                        "host_process_id": browser_anchor[
                            "host_process_id"
                        ],
                        "served_ui_dist_digest": browser_anchor[
                            "served_ui_dist_digest"
                        ],
                        "browser_observation_challenge": browser_anchor[
                            "observation_challenge"
                        ],
                        "browser_observation_receipt_path": str(
                            self.browser_observation_receipt_path
                        ),
                    }
                )
                formal = replace(
                    formal,
                    browser_observation_receipt=(
                        self._wait_for_browser_observation(
                            formal,
                            observation_ready_started=ready_monotonic,
                            observation_ready_wall_ns=ready_wall_ns,
                        )
                    ),
                )
            terminal = _runtime_projection(
                provider,
                session_id=session_id,
                attempt_id=self.scientific_attempt_id,
            )
            effects = _effect_delta(baseline, terminal)
            closure = _validate_terminal_projection(
                provider=provider,
                formal=formal,
                terminal=terminal,
                execution_task_id=execution_task_id,
                research_task_id=self.research_task_id,
                report_task_id=self.report_task_id,
                selection_id=self.selection_id,
                effect_delta=effects,
            )
            micu_receipts = _new_micu_receipts(
                self.ledger_path,
                before_ids=micu_ids_before,
                expected_model=self.settings.llm.model,
            )
            api_receipts = [
                receipt.to_dict() for receipt in api.sealed_receipts
            ]
        return {
            "schema_id": AOX_CLOSURE_STAGE_CHILD_EVIDENCE_SCHEMA_ID,
            "run_class": (
                AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
            ),
            "acceptance_eligible": False,
            "diagnostic_id": self.diagnostic_id,
            "run_attempt_id": context.roots.attempt_id,
            "scientific_attempt_id": self.scientific_attempt_id,
            "session_id": session_id,
            "reconstruction_receipt_digest": (
                self.reconstruction_receipt_digest
            ),
            "health": _safe_health(health),
            "baseline": baseline,
            "terminal": terminal,
            "effects": effects,
            "closure": closure,
            "micu_attempts": micu_receipts,
            "api_receipts": api_receipts,
            "runtime": _closure_stage_runtime_summary(formal),
            "product_path": {
                "completed": True,
            },
        }


def _normalize_supervised_child_evidence(
    evidence: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(evidence)
    product_path = normalized.get("product_path")
    if (
        set(normalized) != _CHILD_EVIDENCE_FIELDS
        or not isinstance(product_path, dict)
        or set(product_path) != _CHILD_PRODUCT_PATH_FIELDS
    ):
        raise CutoverEvidenceError(
            "closure_stage_supervised_result_invalid",
            "supervised child evidence violates its closed envelope",
        )
    supervision = product_path.get("attempt_supervision")
    if not isinstance(supervision, dict):
        raise CutoverEvidenceError(
            "closure_stage_supervision_receipt_missing",
            "closure-stage child result lacks parent supervision",
        )
    return normalized


def _build_terminal_operation_binding(
    *,
    runtime_summary: Mapping[str, object],
    terminal: Mapping[str, object],
    reconstruction: ClosureStageReconstruction,
) -> dict[str, Any]:
    scientific_attempt_id = reconstruction.scientific_attempt_id
    target_graph = reconstruction.receipt.get("target_graph")
    terminal_attempt = terminal.get("attempt")
    terminal_counts = terminal.get("counts")
    terminal_operations = terminal.get("operations")
    terminal_closures = terminal.get("closures")
    if (
        not isinstance(target_graph, dict)
        or not isinstance(terminal_attempt, dict)
        or not isinstance(terminal_counts, dict)
        or not isinstance(terminal_operations, list)
        or not isinstance(terminal_closures, list)
        or len(terminal_closures) != 1
        or not isinstance(terminal_closures[0], dict)
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_operation_binding_invalid",
            "closure-stage terminal operation evidence is incomplete",
        )
    terminal_closure = terminal_closures[0]
    terminal_projection_digest = _require_digest(
        terminal.get("projection_digest"),
        identity="child.terminal.projection_digest",
    )
    terminal_universe_digest = _require_digest(
        terminal_closure.get("operation_universe_digest"),
        identity="child.terminal.closures.operation_universe_digest",
    )
    reconstruction_universe_digest = _require_digest(
        target_graph.get("operation_universe_digest"),
        identity="reconstruction.target_graph.operation_universe_digest",
    )
    operation_ids = [
        str(operation.get("operation_id") or "")
        for operation in terminal_operations
        if isinstance(operation, dict)
    ]
    if (
        len(terminal_operations) != 6
        or any(
            not isinstance(operation, dict)
            or set(operation) != _LIVE_TERMINAL_OPERATION_FIELDS
            or not isinstance(operation.get("operation_id"), str)
            or not str(operation["operation_id"]).strip()
            or _DIGEST_PATTERN.fullmatch(
                str(operation.get("operation_digest") or "")
            )
            is None
            or operation.get("status") != "completed"
            or operation.get("effect_certainty") != "terminal_known"
            for operation in terminal_operations
        )
        or len(operation_ids) != len(set(operation_ids))
        or operation_ids != sorted(operation_ids)
        or terminal_projection_digest
        != canonical_digest(
            {
                key: value
                for key, value in terminal.items()
                if key != "projection_digest"
            }
        )
        or terminal_attempt.get("attempt_id") != scientific_attempt_id
        or target_graph.get("attempt_id") != scientific_attempt_id
        or target_graph.get("selection_id") != reconstruction.selection_id
        or terminal_closure.get("attempt_id") != scientific_attempt_id
        or terminal_closure.get("selection_id") != reconstruction.selection_id
        or terminal_counts.get("controlled_operation")
        != len(terminal_operations)
        or runtime_summary.get("projected_operation_count")
        != len(terminal_operations)
        or target_graph.get("operation_count") != len(terminal_operations)
        or terminal_universe_digest != reconstruction_universe_digest
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_operation_binding_invalid",
            "closure-stage operation projections do not reproduce one closed universe",
        )
    payload = {
        "scientific_attempt_id": scientific_attempt_id,
        "projected_operation_count": runtime_summary[
            "projected_operation_count"
        ],
        "terminal_operation_count": len(terminal_operations),
        "terminal_operations": terminal_operations,
        "terminal_operations_digest": canonical_digest(
            terminal_operations
        ),
        "terminal_operation_universe_digest": terminal_universe_digest,
        "reconstruction_operation_count": target_graph[
            "operation_count"
        ],
        "reconstruction_operation_universe_digest": (
            reconstruction_universe_digest
        ),
        "terminal_projection_digest": terminal_projection_digest,
    }
    return {
        **payload,
        "binding_digest": canonical_digest(payload),
    }


def _validate_live_ledger_snapshot(
    value: object,
    *,
    identity: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _LIVE_LEDGER_SNAPSHOT_FIELDS:
        raise CutoverEvidenceError(
            "closure_stage_live_ledger_snapshot_invalid",
            "closure-stage live result contains an unsupported ledger snapshot",
            details={"identity": identity},
        )
    snapshot = dict(value)
    scalar_fields = (
        _LIVE_LEDGER_COUNTER_FIELDS
        | {
            "hard_limit_tokens",
            "remaining_tokens",
            "hard_limit_overage_tokens",
        }
    )
    if any(
        type(snapshot.get(field)) is not int or int(snapshot[field]) < 0
        for field in scalar_fields
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_ledger_snapshot_invalid",
            "closure-stage ledger counters must be non-negative integers",
            details={"identity": identity},
        )
    if (
        snapshot["hard_limit_tokens"] != 500_000_000
        or snapshot["remaining_tokens"]
        != snapshot["hard_limit_tokens"] - snapshot["charged_tokens"]
        or snapshot["hard_limit_overage_tokens"] != 0
        or snapshot["reservation_overage_tokens"] != 0
        or snapshot["hard_limit_breach_count"] != 0
        or snapshot["charged_tokens"]
        != snapshot["input_tokens"] + snapshot["output_tokens"]
        or snapshot["input_tokens"]
        != snapshot["actual_input_tokens"]
        + snapshot["estimated_input_tokens"]
        or snapshot["output_tokens"]
        != snapshot["actual_output_tokens"]
        + snapshot["estimated_output_tokens"]
        or snapshot["estimated_attempt_count"] > snapshot["attempt_count"]
        or _DIGEST_PATTERN.fullmatch(
            str(snapshot["ledger_identity_digest"])
        )
        is None
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_ledger_snapshot_invalid",
            "closure-stage ledger snapshot is internally contradictory",
            details={"identity": identity},
        )
    for collection, identity_field in (
        ("by_scenario", "scenario"),
        ("by_model", "model"),
    ):
        rows = snapshot.get(collection)
        if not isinstance(rows, list):
            raise CutoverEvidenceError(
                "closure_stage_live_ledger_snapshot_invalid",
                "closure-stage ledger groups must be closed arrays",
                details={"identity": f"{identity}.{collection}"},
            )
        totals = {field: 0 for field in _LIVE_LEDGER_COUNTER_FIELDS}
        seen: set[str] = set()
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row)
                != (_LIVE_LEDGER_COUNTER_FIELDS | {identity_field})
                or not isinstance(row.get(identity_field), str)
                or not str(row[identity_field]).strip()
                or str(row[identity_field]) in seen
                or any(
                    type(row.get(field)) is not int
                    or int(row[field]) < 0
                    for field in _LIVE_LEDGER_COUNTER_FIELDS
                )
                or row["charged_tokens"]
                != row["input_tokens"] + row["output_tokens"]
                or row["input_tokens"]
                != row["actual_input_tokens"]
                + row["estimated_input_tokens"]
                or row["output_tokens"]
                != row["actual_output_tokens"]
                + row["estimated_output_tokens"]
                or row["estimated_attempt_count"] > row["attempt_count"]
            ):
                raise CutoverEvidenceError(
                    "closure_stage_live_ledger_snapshot_invalid",
                    "closure-stage ledger group is malformed",
                    details={"identity": f"{identity}.{collection}"},
                )
            seen.add(str(row[identity_field]))
            for field in _LIVE_LEDGER_COUNTER_FIELDS:
                totals[field] += int(row[field])
        if any(
            totals[field] != snapshot[field]
            for field in _LIVE_LEDGER_COUNTER_FIELDS
        ):
            raise CutoverEvidenceError(
                "closure_stage_live_ledger_snapshot_invalid",
                "closure-stage ledger groups do not sum to the snapshot",
                details={"identity": f"{identity}.{collection}"},
            )
    return snapshot


def build_aox_closure_stage_live_result(
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    source_manifest: Mapping[str, object],
    reconstruction: ClosureStageReconstruction,
    parity: Mapping[str, object],
    evidence: Mapping[str, object],
    ledger_before: Mapping[str, object],
    ledger_after: Mapping[str, object],
) -> dict[str, Any]:
    child = _normalize_supervised_child_evidence(evidence)
    slot = dict(plan["slot"])
    product_path = dict(child["product_path"])
    supervision = dict(product_path["attempt_supervision"])
    validate_attempt_supervision_receipt(
        supervision,
        attempt_id=str(slot["attempt_id"]),
        attempt_kind="positive",
        attempt_authority_id=str(slot["envelope_id"]),
        attempt_authority_request_digest=str(slot["request_digest"]),
    )
    independently_verify_aox_closure_stage_source_manifest(source_manifest)
    independently_verify_aox_closure_stage_reconstruction(
        reconstruction.receipt,
        plan=plan,
        source_manifest=source_manifest,
        require_pristine_target=False,
    )
    validated_parity = validate_aox_closure_stage_runtime_parity(parity)
    source = dict(source_manifest["source_inventory"])
    source_database_digest = _sha256_file(
        Path(str(source["database_path"]))
    )
    source_inventory_digest = canonical_digest(
        source_manifest["inventory_entries"]
    )
    runtime_summary = dict(child.get("runtime") or {})
    terminal = dict(child.get("terminal") or {})
    closure = dict(child.get("closure") or {})
    scope_rollover = dict(closure.get("scope_rollover") or {})
    scope_rollover_material = {
        key: value
        for key, value in scope_rollover.items()
        if key != "projection_digest"
    }
    browser_required = plan.get("browser_observation_receipt") is not None
    browser_observed = runtime_summary.get(
        "browser_observation_observed"
    )
    browser_receipt_digest = runtime_summary.get(
        "browser_observation_receipt_digest"
    )
    operation_binding = _build_terminal_operation_binding(
        runtime_summary=runtime_summary,
        terminal=terminal,
        reconstruction=reconstruction,
    )
    target_graph = dict(reconstruction.receipt["target_graph"])
    parity_target = dict(validated_parity["target"])
    target_supervision_contract_digest = str(
        parity_target["supervision_contract_digest"]
    )
    if (
        child.get("schema_id") != AOX_CLOSURE_STAGE_CHILD_EVIDENCE_SCHEMA_ID
        or child.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or child.get("acceptance_eligible") is not False
        or child.get("diagnostic_id") != plan["diagnostic_id"]
        or child.get("run_attempt_id") != slot["attempt_id"]
        or child.get("scientific_attempt_id")
        != reconstruction.scientific_attempt_id
        or child.get("session_id") != slot["session_id"]
        or child.get("reconstruction_receipt_digest")
        != reconstruction.receipt["receipt_digest"]
        or dict(child.get("effects") or {}).get(
            "no_new_scientific_effect"
        )
        is not True
        or runtime_summary.get("state") != "completed"
        or runtime_summary.get("browser_anchor_observed")
        is not browser_required
        or browser_observed is not browser_required
        or (
            browser_required
            and _DIGEST_PATTERN.fullmatch(
                str(browser_receipt_digest or "")
            )
            is None
        )
        or (not browser_required and browser_receipt_digest is not None)
        or dict(product_path).get("completed") is not True
        or set(scope_rollover) != _LIVE_SCOPE_ROLLOVER_FIELDS
        or scope_rollover.get("phase")
        != ScientificAttemptScopeRolloverPhase.POST_CLOSURE_SCOPE_OPEN.value
        or scope_rollover.get("attempt_id")
        != reconstruction.scientific_attempt_id
        or scope_rollover.get("attempt_scope_id")
        != f"mutation_scope_{reconstruction.scientific_attempt_id}"
        or scope_rollover.get("attempt_scope_state") != "sealed"
        or scope_rollover.get("open_scope_count") != 1
        or scope_rollover.get("post_scope_id")
        != f"mutation_scope_post_{reconstruction.scientific_attempt_id}"
        or scope_rollover.get("projection_digest")
        != canonical_digest(scope_rollover_material)
        or supervision.get("nonterminal_mutation_scope_count")
        != scope_rollover.get("open_scope_count")
        or supervision.get("supervisor_contract_digest")
        != target_supervision_contract_digest
        or source_database_digest != source["database_sha256"]
        or source_inventory_digest != source["inventory_digest"]
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_result_semantics_invalid",
            "retired closure-stage child does not prove the isolated closure",
        )
    micu_attempts = list(child["micu_attempts"])
    ledger_before_count = int(ledger_before.get("attempt_count") or 0)
    ledger_after_count = int(ledger_after.get("attempt_count") or 0)
    authority_max_micu = int(dict(plan["resources"])["max_micu"])
    charged_tokens = sum(
        int(item["charged_tokens"])
        for item in micu_attempts
        if isinstance(item, Mapping)
    )
    if (
        ledger_after_count - ledger_before_count != len(micu_attempts)
        or authority_max_micu != 20_000_000
        or charged_tokens > authority_max_micu
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_ledger_transition_invalid",
            "settled MICU transition does not match child attribution or authority",
        )
    payload = {
        "schema_id": AOX_CLOSURE_STAGE_LIVE_RESULT_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": plan["diagnostic_id"],
        "run_attempt_id": slot["attempt_id"],
        "scientific_attempt_id": reconstruction.scientific_attempt_id,
        "session_id": slot["session_id"],
        "status": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
        "authority": {
            "plan_schema_id": AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
            "consumption_schema_id": (
                AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
            ),
            "plan_digest": plan["plan_digest"],
            "consumption_digest": canonical_digest(dict(consumption)),
            "envelope_id": slot["envelope_id"],
            "request_digest": slot["request_digest"],
        },
        "source": {
            "manifest_digest": source_manifest["manifest_digest"],
            "database_sha256_before": source["database_sha256"],
            "database_sha256_after": source_database_digest,
            "inventory_digest_before": source["inventory_digest"],
            "inventory_digest_after": source_inventory_digest,
            "immutable": True,
        },
        "reconstruction": {
            "receipt_digest": reconstruction.receipt["receipt_digest"],
            "target_root_identity": reconstruction.roots.proof[
                "root_identity"
            ],
            "canonical_state_digest": dict(
                reconstruction.receipt["canonical_state"]
            )["canonical_state_digest"],
            "scientific_attempt_id": reconstruction.scientific_attempt_id,
            "operation_count": target_graph["operation_count"],
            "operation_universe_digest": target_graph[
                "operation_universe_digest"
            ],
        },
        "parity": {
            "receipt_digest": validated_parity["receipt_digest"],
            "declaration_digest": canonical_digest(
                validated_parity["declaration"]
            ),
            "target_supervision_contract_digest": (
                target_supervision_contract_digest
            ),
        },
        "runtime": {
            "summary": child["runtime"],
            "child_result_digest": supervision["result_digest"],
            "terminal_projection_digest": terminal[
                "projection_digest"
            ],
            "operation_binding": operation_binding,
            "closure": child["closure"],
        },
        "effects": child["effects"],
        "micu": {
            "attempts": micu_attempts,
            "attempt_count": len(micu_attempts),
            "all_bound_to_diagnostic_scenario": True,
            "authority_max_micu": authority_max_micu,
            "charged_tokens": charged_tokens,
            "within_authority": True,
        },
        "public_observation": {
            "api_receipt_count": len(child["api_receipts"]),
            "api_receipts_digest": canonical_digest(
                child["api_receipts"]
            ),
            "browser_required": browser_required,
            "browser_observed": browser_observed,
            "browser_receipt_digest": browser_receipt_digest,
        },
        "supervision": supervision,
        "ledger": {
            "before": dict(ledger_before),
            "after": dict(ledger_after),
        },
    }
    result = {**payload, "result_digest": canonical_digest(payload)}
    return validate_aox_closure_stage_live_result(result)


def validate_aox_closure_stage_live_result(
    result: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(result)
    authority = normalized.get("authority")
    source = normalized.get("source")
    reconstruction = normalized.get("reconstruction")
    parity = normalized.get("parity")
    runtime = normalized.get("runtime")
    effects = normalized.get("effects")
    micu = normalized.get("micu")
    public = normalized.get("public_observation")
    supervision = normalized.get("supervision")
    ledger = normalized.get("ledger")
    if (
        set(normalized) != _LIVE_RESULT_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_LIVE_RESULT_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or normalized.get("status") != "completed"
        or not isinstance(authority, dict)
        or set(authority) != _LIVE_AUTHORITY_FIELDS
        or authority.get("plan_schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or authority.get("consumption_schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or not isinstance(source, dict)
        or set(source) != _LIVE_SOURCE_FIELDS
        or source.get("immutable") is not True
        or source.get("database_sha256_before")
        != source.get("database_sha256_after")
        or source.get("inventory_digest_before")
        != source.get("inventory_digest_after")
        or not isinstance(reconstruction, dict)
        or set(reconstruction) != _LIVE_RECONSTRUCTION_FIELDS
        or not isinstance(parity, dict)
        or set(parity) != _LIVE_PARITY_FIELDS
        or not isinstance(runtime, dict)
        or set(runtime) != _LIVE_RUNTIME_FIELDS
        or not isinstance(effects, dict)
        or set(effects) != _LIVE_EFFECT_FIELDS
        or effects.get("no_new_scientific_effect") is not True
        or not isinstance(micu, dict)
        or set(micu) != _LIVE_MICU_FIELDS
        or not isinstance(public, dict)
        or set(public) != _LIVE_PUBLIC_OBSERVATION_FIELDS
        or not isinstance(supervision, dict)
        or not isinstance(ledger, dict)
        or set(ledger) != _LIVE_LEDGER_FIELDS
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_result_schema_invalid",
            "closure-stage live result violates its closed success contract",
        )
    run_attempt_id = normalized.get("run_attempt_id")
    scientific_attempt_id = normalized.get("scientific_attempt_id")
    diagnostic_id = normalized.get("diagnostic_id")
    if (
        not isinstance(diagnostic_id, str)
        or CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(
            diagnostic_id
        )
        is None
        or not isinstance(run_attempt_id, str)
        or CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.attempt_id_pattern.fullmatch(
            run_attempt_id
        )
        is None
        or not isinstance(scientific_attempt_id, str)
        or _SCIENTIFIC_ATTEMPT_ID_PATTERN.fullmatch(
            scientific_attempt_id
        )
        is None
        or scientific_attempt_id == run_attempt_id
        or normalized.get("session_id")
        != CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.identities(
            run_attempt_id
        )[0]
        or reconstruction.get("scientific_attempt_id")
        != scientific_attempt_id
        or not isinstance(authority.get("envelope_id"), str)
        or not str(authority["envelope_id"]).strip()
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_result_identity_invalid",
            "closure-stage live result identities do not reproduce",
        )
    for identity, value in (
        ("result_digest", normalized.get("result_digest")),
        ("authority.plan_digest", authority.get("plan_digest")),
        (
            "authority.consumption_digest",
            authority.get("consumption_digest"),
        ),
        ("authority.request_digest", authority.get("request_digest")),
        ("source.manifest_digest", source.get("manifest_digest")),
        (
            "source.database_sha256",
            source.get("database_sha256_before"),
        ),
        (
            "source.inventory_digest",
            source.get("inventory_digest_before"),
        ),
        (
            "reconstruction.receipt_digest",
            reconstruction.get("receipt_digest"),
        ),
        (
            "reconstruction.target_root_identity",
            reconstruction.get("target_root_identity"),
        ),
        (
            "reconstruction.canonical_state_digest",
            reconstruction.get("canonical_state_digest"),
        ),
        (
            "reconstruction.operation_universe_digest",
            reconstruction.get("operation_universe_digest"),
        ),
        ("parity.receipt_digest", parity.get("receipt_digest")),
        (
            "parity.declaration_digest",
            parity.get("declaration_digest"),
        ),
        (
            "parity.target_supervision_contract_digest",
            parity.get("target_supervision_contract_digest"),
        ),
    ):
        _require_digest(value, identity=identity)
    runtime_summary = runtime.get("summary")
    closure = runtime.get("closure")
    operation_binding = runtime.get("operation_binding")
    failure_task_projection = (
        runtime_summary.get("failure_task_projection")
        if isinstance(runtime_summary, dict)
        else None
    )
    failure_operation_projection = (
        runtime_summary.get("failure_operation_projection")
        if isinstance(runtime_summary, dict)
        else None
    )
    bound_terminal_operations = (
        operation_binding.get("terminal_operations")
        if isinstance(operation_binding, dict)
        else None
    )
    scope_rollover = (
        closure.get("scope_rollover")
        if isinstance(closure, dict)
        else None
    )
    if (
        not isinstance(runtime_summary, dict)
        or set(runtime_summary) != _LIVE_RUNTIME_SUMMARY_FIELDS
        or not isinstance(closure, dict)
        or set(closure) != _LIVE_CLOSURE_FIELDS
        or runtime_summary.get("session_id") != normalized["session_id"]
        or runtime_summary.get("purpose") != "formal"
        or runtime_summary.get("state") != "completed"
        or runtime_summary.get("blocker_code") is not None
        or type(runtime_summary.get("drain_count")) is not int
        or int(runtime_summary["drain_count"]) < 1
        or type(runtime_summary.get("approval_count")) is not int
        or int(runtime_summary["approval_count"]) != 0
        or runtime_summary.get("task_count") != 3
        or not isinstance(runtime_summary.get("event_receipt"), dict)
        or not isinstance(runtime_summary.get("mutation_scope"), dict)
        or not isinstance(failure_task_projection, dict)
        or set(failure_task_projection)
        != _LIVE_FAILURE_TASK_PROJECTION_FIELDS
        or type(failure_task_projection.get("task_fact_count")) is not int
        or int(failure_task_projection["task_fact_count"]) < 0
        or type(failure_task_projection.get("task_facts_truncated")) is not bool
        or not isinstance(failure_operation_projection, dict)
        or set(failure_operation_projection)
        != _LIVE_FAILURE_OPERATION_PROJECTION_FIELDS
        or type(
            failure_operation_projection.get("operation_fact_count")
        )
        is not int
        or int(failure_operation_projection["operation_fact_count"]) < 0
        or type(
            failure_operation_projection.get("operation_facts_truncated")
        )
        is not bool
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_runtime_summary_invalid",
            "closure-stage live result lacks one closed completed runtime projection",
        )
    if (
        not isinstance(scope_rollover, dict)
        or set(scope_rollover) != _LIVE_SCOPE_ROLLOVER_FIELDS
        or scope_rollover.get("phase")
        != ScientificAttemptScopeRolloverPhase.POST_CLOSURE_SCOPE_OPEN.value
        or scope_rollover.get("attempt_id") != scientific_attempt_id
        or scope_rollover.get("attempt_scope_id")
        != f"mutation_scope_{scientific_attempt_id}"
        or scope_rollover.get("attempt_scope_state") != "sealed"
        or scope_rollover.get("open_scope_count") != 1
        or scope_rollover.get("post_scope_id")
        != f"mutation_scope_post_{scientific_attempt_id}"
        or scope_rollover.get("projection_digest")
        != canonical_digest(
            {
                key: value
                for key, value in scope_rollover.items()
                if key != "projection_digest"
            }
        )
        or supervision.get("nonterminal_mutation_scope_count")
        != scope_rollover.get("open_scope_count")
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_scope_rollover_invalid",
            "closure-stage live result does not bind the scientific attempt scope rollover",
        )
    if (
        not isinstance(operation_binding, dict)
        or set(operation_binding) != _LIVE_OPERATION_BINDING_FIELDS
        or operation_binding.get("scientific_attempt_id")
        != scientific_attempt_id
        or not isinstance(bound_terminal_operations, list)
        or len(bound_terminal_operations) != 6
        or any(
            not isinstance(operation, dict)
            or set(operation) != _LIVE_TERMINAL_OPERATION_FIELDS
            or not isinstance(operation.get("operation_id"), str)
            or not str(operation["operation_id"]).strip()
            or _DIGEST_PATTERN.fullmatch(
                str(operation.get("operation_digest") or "")
            )
            is None
            or operation.get("status") != "completed"
            or operation.get("effect_certainty") != "terminal_known"
            for operation in bound_terminal_operations
        )
        or [
            str(operation["operation_id"])
            for operation in bound_terminal_operations
        ]
        != sorted(
            {
                str(operation["operation_id"])
                for operation in bound_terminal_operations
            }
        )
        or operation_binding.get("terminal_operations_digest")
        != canonical_digest(bound_terminal_operations)
        or type(reconstruction.get("operation_count")) is not int
        or reconstruction.get("operation_count") != 6
        or any(
            type(operation_binding.get(field)) is not int
            or operation_binding.get(field) != 6
            for field in (
                "projected_operation_count",
                "terminal_operation_count",
                "reconstruction_operation_count",
            )
        )
        or runtime_summary.get("projected_operation_count")
        != operation_binding.get("projected_operation_count")
        or failure_operation_projection.get("operation_fact_count")
        != operation_binding.get("projected_operation_count")
        or reconstruction.get("operation_count")
        != operation_binding.get("reconstruction_operation_count")
        or reconstruction.get("operation_universe_digest")
        != operation_binding.get(
            "reconstruction_operation_universe_digest"
        )
        or operation_binding.get("terminal_operation_universe_digest")
        != operation_binding.get(
            "reconstruction_operation_universe_digest"
        )
        or runtime.get("terminal_projection_digest")
        != operation_binding.get("terminal_projection_digest")
        or operation_binding.get("binding_digest")
        != canonical_digest(
            {
                key: value
                for key, value in operation_binding.items()
                if key != "binding_digest"
            }
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_operation_binding_invalid",
            "closure-stage live result does not close one operation universe across projections",
        )
    if (
        runtime.get("child_result_digest")
        != supervision.get("result_digest")
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_child_binding_invalid",
            "closure-stage runtime does not reference its supervised child result",
        )
    if (
        parity.get("target_supervision_contract_digest")
        != supervision.get("supervisor_contract_digest")
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_supervision_parity_invalid",
            "closure-stage supervision receipt differs from the parity target contract",
        )
    for identity, value in (
        (
            "runtime.child_result_digest",
            runtime.get("child_result_digest"),
        ),
        (
            "runtime.terminal_projection_digest",
            runtime.get("terminal_projection_digest"),
        ),
        (
            "runtime.summary.workspace_digest",
            runtime_summary.get("workspace_digest"),
        ),
        (
            "runtime.summary.scientific_attempt_control_digest",
            runtime_summary.get("scientific_attempt_control_digest"),
        ),
        (
            "runtime.summary.failure_task_projection.task_facts_digest",
            failure_task_projection.get("task_facts_digest"),
        ),
        (
            "runtime.summary.failure_operation_projection.operation_facts_digest",
            failure_operation_projection.get("operation_facts_digest"),
        ),
        (
            "runtime.closure.scientific_attempt_control_digest",
            closure.get("scientific_attempt_control_digest"),
        ),
        (
            "runtime.closure.scope_rollover.projection_digest",
            scope_rollover.get("projection_digest"),
        ),
        (
            "runtime.operation_binding.terminal_operations_digest",
            operation_binding.get("terminal_operations_digest"),
        ),
        (
            "runtime.operation_binding.terminal_operation_universe_digest",
            operation_binding.get(
                "terminal_operation_universe_digest"
            ),
        ),
        (
            "runtime.operation_binding.reconstruction_operation_universe_digest",
            operation_binding.get(
                "reconstruction_operation_universe_digest"
            ),
        ),
        (
            "runtime.operation_binding.binding_digest",
            operation_binding.get("binding_digest"),
        ),
    ):
        _require_digest(value, identity=identity)
    if (
        runtime_summary["scientific_attempt_control_digest"]
        != closure["scientific_attempt_control_digest"]
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_runtime_summary_invalid",
            "closure-stage runtime and closure control projections disagree",
        )
    task_receipts = closure.get("task_receipts")
    if (
        not isinstance(task_receipts, list)
        or len(task_receipts) != 3
        or {
            str(item.get("role") or "")
            for item in task_receipts
            if isinstance(item, dict)
        }
        != {"researcher", "executor", "reporter"}
        or any(
            not isinstance(item, dict)
            or set(item) != _LIVE_TASK_RECEIPT_FIELDS
            or item.get("status") != "completed"
            or item.get("business_exit") != "agent_explicit"
            or item.get("assigned_ref") != item.get("finished_by")
            or not isinstance(item.get("evidence_refs"), list)
            or _DIGEST_PATTERN.fullmatch(
                str(item.get("finish_payload_digest") or "")
            )
            is None
            for item in task_receipts
        )
        or any(
            item.get("role") == "executor"
            and not item.get("evidence_refs")
            for item in task_receipts
            if isinstance(item, dict)
        )
        or any(
            not isinstance(closure.get(field), str)
            or not str(closure[field]).strip()
            for field in (
                "report_id",
                "report_content_ref",
                "closure_request_id",
                "closure_response_id",
                "closure_id",
            )
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_closure_invalid",
            "closure-stage live result lacks exact owner-authored terminal receipts",
        )
    report_source_link = closure.get("report_source_link")
    receipts_by_role = {
        str(item["role"]): item for item in task_receipts
    }
    if (
        not isinstance(report_source_link, dict)
        or set(report_source_link)
        != _LIVE_REPORT_SOURCE_LINK_FIELDS
        or report_source_link.get("report_ref")
        != f"report:{closure['report_id']}"
        or not isinstance(
            report_source_link.get("primary_pubmed_artifact_ref"),
            str,
        )
        or not str(
            report_source_link["primary_pubmed_artifact_ref"]
        ).startswith("artifact:")
        or report_source_link["primary_pubmed_artifact_ref"]
        not in receipts_by_role["researcher"]["evidence_refs"]
        or report_source_link["primary_pubmed_artifact_ref"]
        not in receipts_by_role["reporter"]["evidence_refs"]
        or report_source_link["report_ref"]
        not in receipts_by_role["reporter"]["evidence_refs"]
        or not isinstance(
            report_source_link.get("source_ref_ids"),
            list,
        )
        or not report_source_link["source_ref_ids"]
        or any(
            not isinstance(source_ref_id, str)
            or not source_ref_id.strip()
            for source_ref_id in report_source_link["source_ref_ids"]
        )
        or report_source_link["source_ref_ids"]
        != sorted(set(report_source_link["source_ref_ids"]))
        or report_source_link.get("link_digest")
        != canonical_digest(
            {
                key: value
                for key, value in report_source_link.items()
                if key != "link_digest"
            }
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_report_source_link_invalid",
            "closure-stage report lacks a reproducible durable PubMed source link",
        )
    _require_digest(
        report_source_link.get("primary_pubmed_artifact_digest"),
        identity=(
            "runtime.closure.report_source_link."
            "primary_pubmed_artifact_digest"
        ),
    )
    _require_digest(
        report_source_link.get("link_digest"),
        identity="runtime.closure.report_source_link.link_digest",
    )
    count_deltas = effects.get("count_deltas")
    new_artifacts = effects.get("new_artifacts")
    new_report_documents = effects.get(
        "new_report_content_documents"
    )
    if (
        not isinstance(count_deltas, dict)
        or set(count_deltas) != _LIVE_EFFECT_COUNT_FIELDS
        or any(type(value) is not int or value != 0 for value in count_deltas.values())
        or effects.get("operation_identity_unchanged") is not True
        or effects.get("no_new_session_artifact") is not True
        or effects.get("report_content_document_only") is not True
        or not isinstance(new_artifacts, list)
        or new_artifacts
        or not isinstance(new_report_documents, list)
        or len(new_report_documents) != 1
        or not isinstance(new_report_documents[0], dict)
        or set(new_report_documents[0])
        != _LIVE_REPORT_CONTENT_DOCUMENT_FIELDS
        or new_report_documents[0].get("document_kind")
        != "report_draft_content"
        or new_report_documents[0].get("document_id")
        != closure.get("report_content_ref")
        or _DIGEST_PATTERN.fullmatch(
            str(new_report_documents[0].get("payload_digest") or "")
        )
        is None
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_effect_delta_invalid",
            "closure-stage live result contains an undeclared scientific effect",
        )
    browser_required = public.get("browser_required")
    browser_observed = public.get("browser_observed")
    if (
        type(browser_required) is not bool
        or browser_observed is not browser_required
        or runtime_summary.get("browser_anchor_observed")
        is not browser_required
        or runtime_summary.get("browser_observation_observed")
        is not browser_required
        or type(public.get("api_receipt_count")) is not int
        or int(public["api_receipt_count"]) < 1
        or (
            browser_required
            and (
                _DIGEST_PATTERN.fullmatch(
                    str(public.get("browser_receipt_digest") or "")
                )
                is None
                or public.get("browser_receipt_digest")
                != runtime_summary.get(
                    "browser_observation_receipt_digest"
                )
                or _DIGEST_PATTERN.fullmatch(
                    str(
                        runtime_summary.get(
                            "browser_anchor_receipt_digest"
                        )
                        or ""
                    )
                )
                is None
            )
        )
        or (
            not browser_required
            and (
                public.get("browser_receipt_digest") is not None
                or runtime_summary.get(
                    "browser_anchor_receipt_digest"
                )
                is not None
                or runtime_summary.get(
                    "browser_observation_receipt_digest"
                )
                is not None
            )
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_browser_observation_invalid",
            "closure-stage browser evidence does not match its authority mode",
        )
    _require_digest(
        public.get("api_receipts_digest"),
        identity="public_observation.api_receipts_digest",
    )
    before = _validate_live_ledger_snapshot(
        ledger.get("before"),
        identity="ledger.before",
    )
    after = _validate_live_ledger_snapshot(
        ledger.get("after"),
        identity="ledger.after",
    )
    attempts = micu.get("attempts")
    if (
        not isinstance(attempts, list)
        or not attempts
        or micu.get("attempt_count") != len(attempts)
        or micu.get("all_bound_to_diagnostic_scenario") is not True
        or micu.get("authority_max_micu") != 20_000_000
        or type(micu.get("charged_tokens")) is not int
        or int(micu["charged_tokens"]) < 0
        or micu.get("within_authority") is not True
        or any(
            not isinstance(item, dict)
            or set(item) != _LIVE_MICU_ATTEMPT_FIELDS
            or type(item.get("id")) is not int
            or int(item["id"]) < 1
            or item.get("scenario") != "aox_closure_stage_diagnostic"
            or not all(
                isinstance(item.get(field), str)
                and bool(str(item[field]).strip())
                for field in ("purpose", "kind", "model")
            )
            or type(item.get("attempt")) is not int
            or int(item["attempt"]) < 1
            or any(
                type(item.get(field)) is not int or int(item[field]) < 0
                for field in (
                    "input_tokens",
                    "output_tokens",
                    "charged_tokens",
                    "reservation_overage_tokens",
                    "hard_limit_breached",
                    "cumulative_tokens",
                )
            )
            or item["charged_tokens"]
            != item["input_tokens"] + item["output_tokens"]
            or item["reservation_overage_tokens"] != 0
            or item["hard_limit_breached"] != 0
            or type(item.get("estimated")) is not int
            or item["estimated"] not in {0, 1}
            or item.get("status") not in _TERMINAL_MICU_STATUSES
            for item in attempts
        )
        or len({int(item["id"]) for item in attempts}) != len(attempts)
        or [int(item["id"]) for item in attempts]
        != sorted(int(item["id"]) for item in attempts)
        or not any(item["estimated"] == 0 for item in attempts)
        or micu["charged_tokens"]
        != sum(int(item["charged_tokens"]) for item in attempts)
        or micu["charged_tokens"] > micu["authority_max_micu"]
        or before["ledger_identity_digest"]
        != after["ledger_identity_digest"]
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_micu_invalid",
            "closure-stage live result lacks exact settled MICU attribution",
        )
    ledger_deltas = {
        field: int(after[field]) - int(before[field])
        for field in _LIVE_LEDGER_COUNTER_FIELDS
    }
    actual_attempts = [
        item for item in attempts if int(item["estimated"]) == 0
    ]
    estimated_attempts = [
        item for item in attempts if int(item["estimated"]) == 1
    ]
    expected_deltas = {
        "attempt_count": len(attempts),
        "charged_tokens": sum(int(item["charged_tokens"]) for item in attempts),
        "input_tokens": sum(int(item["input_tokens"]) for item in attempts),
        "output_tokens": sum(int(item["output_tokens"]) for item in attempts),
        "actual_input_tokens": sum(
            int(item["input_tokens"]) for item in actual_attempts
        ),
        "actual_output_tokens": sum(
            int(item["output_tokens"]) for item in actual_attempts
        ),
        "estimated_input_tokens": sum(
            int(item["input_tokens"]) for item in estimated_attempts
        ),
        "estimated_output_tokens": sum(
            int(item["output_tokens"]) for item in estimated_attempts
        ),
        "estimated_attempt_count": len(estimated_attempts),
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
    }
    if ledger_deltas != expected_deltas:
        raise CutoverEvidenceError(
            "closure_stage_live_ledger_transition_invalid",
            "closure-stage MICU receipts do not reproduce the ledger transition",
        )
    validate_attempt_supervision_receipt(
        supervision,
        attempt_id=run_attempt_id,
        attempt_kind="positive",
        attempt_authority_id=str(authority["envelope_id"]),
        attempt_authority_request_digest=str(authority["request_digest"]),
    )
    try:
        completed_at = datetime.fromisoformat(
            str(normalized.get("completed_at") or "")
        )
    except ValueError as exc:
        raise CutoverEvidenceError(
            "closure_stage_live_result_time_invalid",
            "closure-stage live-result timestamp is malformed",
        ) from exc
    if completed_at.tzinfo is None:
        raise CutoverEvidenceError(
            "closure_stage_live_result_time_invalid",
            "closure-stage live-result timestamp must include a timezone",
        )
    if normalized.get("result_digest") != canonical_digest(
        {
            key: value
            for key, value in normalized.items()
            if key != "result_digest"
        }
    ):
        raise CutoverEvidenceError(
            "closure_stage_live_result_digest_mismatch",
            "closure-stage live-result digest does not reproduce",
        )
    return normalized


def build_aox_closure_stage_diagnostic_decision(
    *,
    plan: Mapping[str, object],
    source_manifest: Mapping[str, object],
    source_post_verified: bool,
    live_result: Mapping[str, object] | None,
    failure: Exception | None,
) -> dict[str, Any]:
    if (live_result is None) == (failure is None):
        raise ValueError("decision requires exactly one live result or failure")
    blocker = None
    status = "completed"
    live_result_digest = None
    if live_result is not None:
        normalized_result = validate_aox_closure_stage_live_result(
            live_result
        )
        live_result_digest = str(normalized_result["result_digest"])
    else:
        status = "failed"
        raw_code = getattr(failure, "code", None)
        code = (
            str(raw_code)
            if isinstance(raw_code, str)
            and _ERROR_CODE_PATTERN.fullmatch(raw_code) is not None
            else "closure_stage_diagnostic_failed"
        )
        blocker = {"code": code, "identity": "closure_stage.runner"}
    source_inventory = source_manifest.get("source_inventory")
    if not isinstance(source_inventory, Mapping):
        raise ValueError("decision requires a source inventory")
    manifest_digest = _require_digest(
        source_manifest.get("manifest_digest"),
        identity="source_manifest.manifest_digest",
    )
    database_digest = _require_digest(
        source_inventory.get("database_sha256"),
        identity="source_manifest.source_inventory.database_sha256",
    )
    inventory_digest = _require_digest(
        source_inventory.get("inventory_digest"),
        identity="source_manifest.source_inventory.inventory_digest",
    )
    source_integrity = {
        "manifest_digest": manifest_digest,
        "database_sha256_before": database_digest,
        "database_sha256_after": (
            database_digest if source_post_verified else None
        ),
        "inventory_digest_before": inventory_digest,
        "inventory_digest_after": (
            inventory_digest if source_post_verified else None
        ),
        "post_verified": source_post_verified,
        "immutable": source_post_verified,
    }
    slot = dict(plan["slot"])
    payload = {
        "schema_id": AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": plan["diagnostic_id"],
        "attempt_id": slot["attempt_id"],
        "status": status,
        "decided_at": datetime.now(UTC).isoformat(),
        "blocker": blocker,
        "live_result_digest": live_result_digest,
        "source_integrity": source_integrity,
        "formal_adoption": {
            "eligible": False,
            "formal_bundle_created": False,
            "campaign_reducer_invoked": False,
            "decision": None,
        },
    }
    decision = {
        **payload,
        "decision_digest": canonical_digest(payload),
    }
    return validate_aox_closure_stage_diagnostic_decision(decision)


def validate_aox_closure_stage_diagnostic_decision(
    decision: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(decision)
    formal = normalized.get("formal_adoption")
    blocker = normalized.get("blocker")
    source = normalized.get("source_integrity")
    if (
        set(normalized) != _DECISION_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or normalized.get("status") not in {"completed", "failed"}
        or not isinstance(formal, dict)
        or not isinstance(source, dict)
        or set(source) != _DECISION_SOURCE_FIELDS
        or type(source.get("post_verified")) is not bool
        or source.get("immutable") != source.get("post_verified")
        or (
            source.get("post_verified") is True
            and (
                source.get("database_sha256_before")
                != source.get("database_sha256_after")
                or source.get("inventory_digest_before")
                != source.get("inventory_digest_after")
            )
        )
        or (
            source.get("post_verified") is False
            and (
                source.get("database_sha256_after") is not None
                or source.get("inventory_digest_after") is not None
            )
        )
        or formal
        != {
            "eligible": False,
            "formal_bundle_created": False,
            "campaign_reducer_invoked": False,
            "decision": None,
        }
        or (
            normalized.get("status") == "completed"
            and (
                blocker is not None
                or source.get("post_verified") is not True
                or _DIGEST_PATTERN.fullmatch(
                    str(normalized.get("live_result_digest") or "")
                )
                is None
            )
        )
        or (
            normalized.get("status") == "failed"
            and (
                not isinstance(blocker, dict)
                or set(blocker) != {"code", "identity"}
                or blocker.get("identity") != "closure_stage.runner"
                or normalized.get("live_result_digest") is not None
            )
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_diagnostic_decision_invalid",
            "closure-stage decision violates permanent non-adoption semantics",
        )
    for identity, value in (
        ("source.manifest_digest", source.get("manifest_digest")),
        (
            "source.database_sha256_before",
            source.get("database_sha256_before"),
        ),
        (
            "source.inventory_digest_before",
            source.get("inventory_digest_before"),
        ),
    ):
        _require_digest(value, identity=identity)
    try:
        decided_at = datetime.fromisoformat(str(normalized["decided_at"]))
    except ValueError as exc:
        raise CutoverEvidenceError(
            "closure_stage_diagnostic_decision_time_invalid",
            "closure-stage decision time is malformed",
        ) from exc
    if decided_at.tzinfo is None or normalized.get(
        "decision_digest"
    ) != canonical_digest(
        {
            key: value
            for key, value in normalized.items()
            if key != "decision_digest"
        }
    ):
        raise CutoverEvidenceError(
            "closure_stage_diagnostic_decision_digest_invalid",
            "closure-stage decision digest or time does not reproduce",
        )
    forbidden = (
        b"aox_blank_world_attempt_bundle@3",
        b"aox_blank_world_campaign_decision@1",
        b'"decision":"GO"',
        b'"decision":"NO-GO"',
    )
    serialized = canonical_json_bytes(normalized)
    if any(value in serialized for value in forbidden):
        raise CutoverEvidenceError(
            "closure_stage_formal_adoption_forbidden",
            "closure-stage decision cannot contain formal evidence or verdicts",
        )
    return normalized


def seal_aox_closure_stage_live_result(
    result: Mapping[str, object],
    path: Path,
) -> None:
    normalized = validate_aox_closure_stage_live_result(result)
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(normalized) + b"\n",
    )


def seal_aox_closure_stage_diagnostic_decision(
    decision: Mapping[str, object],
    path: Path,
) -> None:
    normalized = validate_aox_closure_stage_diagnostic_decision(decision)
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(normalized) + b"\n",
    )


@dataclass(slots=True)
class AoxClosureStageDiagnosticRun:
    plan: Mapping[str, object]
    consumption: Mapping[str, object]
    source_manifest: Mapping[str, object]
    reconstruction: ClosureStageReconstruction
    parity: Mapping[str, object]
    identity: Mapping[str, object]
    ledger_path: Path
    runner: ProcessIsolatedAttemptRunner
    launch_guard: Callable[[], None] | None = None

    def run(self) -> dict[str, Any]:
        if self.launch_guard is not None:
            self.launch_guard()
        independently_verify_aox_closure_stage_source_manifest(
            self.source_manifest
        )
        independently_verify_aox_closure_stage_reconstruction(
            self.reconstruction.receipt,
            plan=self.plan,
            source_manifest=self.source_manifest,
        )
        validate_aox_closure_stage_runtime_parity(self.parity)
        ledger_before = safe_micu_ledger_snapshot(self.ledger_path)
        slot = dict(self.plan["slot"])
        context = AttemptRunContext(
            roots=self.reconstruction.roots,
            identity={
                key: str(value)
                for key, value in self.identity.items()
                if isinstance(value, str)
            },
            ledger_before=ledger_before,
            attempt_number=1,
            attempt_authority=slot,
        )
        live_result: dict[str, Any] | None = None
        failure: Exception | None = None
        source_post_verified = False
        try:
            evidence = self.runner(context)
            ledger_after = safe_micu_ledger_snapshot(self.ledger_path)
            live_result = build_aox_closure_stage_live_result(
                plan=self.plan,
                consumption=self.consumption,
                source_manifest=self.source_manifest,
                reconstruction=self.reconstruction,
                parity=self.parity,
                evidence=evidence,
                ledger_before=ledger_before,
                ledger_after=ledger_after,
            )
            source_post_verified = True
            seal_aox_closure_stage_live_result(
                live_result,
                self.reconstruction.roots.evidence_root
                / AOX_CLOSURE_STAGE_LIVE_RESULT_FILENAME,
            )
        except Exception as exc:  # noqa: BLE001 - finite sealed boundary
            failure = exc
            live_result = None
            if not source_post_verified:
                try:
                    independently_verify_aox_closure_stage_source_manifest(
                        self.source_manifest
                    )
                except Exception as source_exc:  # noqa: BLE001
                    failure = source_exc
                else:
                    source_post_verified = True
        decision = build_aox_closure_stage_diagnostic_decision(
            plan=self.plan,
            source_manifest=self.source_manifest,
            source_post_verified=source_post_verified,
            live_result=live_result,
            failure=failure,
        )
        seal_aox_closure_stage_diagnostic_decision(
            decision,
            Path(str(self.plan["target_root"]))
            / AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_FILENAME,
        )
        return decision


__all__ = [
    "AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_FILENAME",
    "AOX_CLOSURE_STAGE_DIAGNOSTIC_DECISION_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_LIVE_RESULT_FILENAME",
    "AOX_CLOSURE_STAGE_LIVE_RESULT_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_PARITY_RECEIPT_FILENAME",
    "AOX_CLOSURE_STAGE_PARITY_RECEIPT_SCHEMA_ID",
    "AoxClosureStageDiagnosticRun",
    "ClosureStageLiveRunner",
    "build_aox_closure_stage_diagnostic_decision",
    "build_aox_closure_stage_live_result",
    "build_aox_closure_stage_runtime_parity",
    "seal_aox_closure_stage_diagnostic_decision",
    "seal_aox_closure_stage_live_result",
    "seal_aox_closure_stage_runtime_parity",
    "validate_aox_closure_stage_diagnostic_decision",
    "validate_aox_closure_stage_live_result",
    "validate_aox_closure_stage_runtime_parity",
]
