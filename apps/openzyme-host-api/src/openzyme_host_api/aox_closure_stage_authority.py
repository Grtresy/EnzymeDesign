from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from openzyme_core import scientific_attempt_authorization_identity
from openzyme_runtime import REPO_ROOT

from .aox_attempt_authority import AOX_ATTEMPT_AUTHORITY_GRANTOR_REF
from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY
from .aox_live_run_class import FORMAL_ACCEPTANCE_RUN_POLICY
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID = (
    "aox_closure_stage_diagnostic_authority_plan@1"
)
AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID = (
    "aox_closure_stage_diagnostic_authority_consumption@1"
)
AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID = (
    "aox_closure_stage_source_inventory@1"
)
AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID = (
    "aox_closure_stage_runtime_parity_declaration@1"
)
AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID = (
    "aox_closure_stage_micu_binding@1"
)

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
_PROCESS_EPOCH_PATTERN = re.compile(
    r"^closure-stage-process-[a-f0-9]{32}$"
)
_EXECUTOR_PATTERN = re.compile(r"^agent:executor:[a-f0-9]{12}$")
_SELECTION_PATTERN = re.compile(r"^selection_[a-f0-9]{24}$")
_NUMBERED_COMPONENT_PATTERN = re.compile(r"^r[0-9]+(?:[-_].*)?$")

_PLAN_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "root_namespace",
        "target_root",
        "browser_observation_receipt",
        "process_epoch",
        "source_inventory",
        "identity_digest",
        "allowed_prerequisite_digest",
        "architecture_qualification_digest",
        "contract_bindings",
        "runtime_parity",
        "micu",
        "issued_at",
        "expires_at",
        "resources",
        "slot",
        "plan_digest",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "schema_id",
        "campaign_root",
        "attempt_root",
        "database_path",
        "authority_plan_path",
        "authority_consumption_path",
        "campaign_id",
        "attempt_id",
        "session_id",
        "execution_task_id",
        "executor_agent_id",
        "selection_id",
        "operation_universe_digest",
        "source_root_identity",
        "database_sha256",
        "inventory_digest",
        "frozen_paths_digest",
        "cut_cursor",
        "first_post_cut_cursor",
    }
)
_CONTRACT_FIELDS = frozenset(
    {
        "workflow_id",
        "workflow_contract_digest",
        "sop_digest",
        "closure_stage_sop_digest",
        "architecture_qualification_digest",
        "ui_dist_digest",
        "source_launch_receipt_digest",
        "repair_commit",
        "runtime_config_digest",
    }
)
_PARITY_FIELDS = frozenset(
    {
        "schema_id",
        "source_launch_receipt_digest",
        "model_config_digest",
        "driver_limits_digest",
        "writer_policy_digest",
        "tool_response_policy_digest",
        "supervision_contract_digest",
        "public_observation_contract_digest",
    }
)
_MICU_FIELDS = frozenset(
    {
        "schema_id",
        "provider",
        "endpoint_identity",
        "model",
        "token_scenario",
        "ledger_path",
        "ledger_identity",
        "effective_config_digest",
    }
)
_RESOURCE_FIELDS = frozenset(
    {
        "max_micu",
        "max_cost_microunits",
        "max_wall_time_seconds",
    }
)
_SLOT_FIELDS = frozenset(
    {
        "run_class",
        "ordinal",
        "attempt_kind",
        "attempt_id",
        "session_id",
        "task_id",
        "lane_id",
        "scope",
        "authority_request",
        "envelope_id",
        "request_digest",
    }
)
_CONSUMPTION_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "plan_schema_id",
        "plan_digest",
        "diagnostic_id",
        "root_namespace",
        "target_root",
        "process_epoch",
        "consumption_file",
        "consumed_at",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_timestamp(
    value: object,
    *,
    code: str,
    label: str,
) -> datetime:
    if not isinstance(value, str) or not value:
        raise CutoverEvidenceError(
            code,
            f"closure-stage authority {label} must be an ISO-8601 timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CutoverEvidenceError(
            code,
            f"closure-stage authority {label} is not valid ISO-8601",
        ) from exc
    if parsed.tzinfo is None:
        raise CutoverEvidenceError(
            code,
            f"closure-stage authority {label} must include a timezone",
        )
    return parsed.astimezone(UTC)


def _validate_time_window(
    *,
    issued_at: object,
    expires_at: object,
) -> None:
    issued = _parse_timestamp(
        issued_at,
        code="closure_stage_authority_issued_at_invalid",
        label="issued_at",
    )
    expiry = _parse_timestamp(
        expires_at,
        code="closure_stage_authority_expiry_invalid",
        label="expiry",
    )
    now = datetime.now(UTC)
    if expiry <= now:
        raise CutoverEvidenceError(
            "closure_stage_authority_expired",
            "closure-stage authority plan has expired",
        )
    if issued > expiry:
        raise CutoverEvidenceError(
            "closure_stage_authority_time_order_invalid",
            "closure-stage authority issued_at must not follow expires_at",
        )
    if issued > now:
        raise CutoverEvidenceError(
            "closure_stage_authority_not_yet_valid",
            "closure-stage authority issued_at is in the future",
        )


def _require_digest(value: object, *, identity: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise CutoverEvidenceError(
            "closure_stage_authority_digest_invalid",
            "closure-stage authority contains a malformed digest",
            details={"identity": identity},
        )
    return value


def _canonical_existing_path(
    value: object,
    *,
    identity: str,
    directory: bool,
) -> Path:
    if not isinstance(value, str) or not value:
        raise CutoverEvidenceError(
            "closure_stage_source_path_invalid",
            "closure-stage source paths must be absolute canonical paths",
            details={"identity": identity},
        )
    requested = Path(value).expanduser()
    try:
        metadata = requested.lstat()
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_path_invalid",
            "closure-stage source path is missing or unreadable",
            details={"identity": identity},
        ) from exc
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not requested.is_absolute()
        or stat.S_ISLNK(metadata.st_mode)
        or not expected_kind(metadata.st_mode)
        or str(resolved) != value
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_path_invalid",
            "closure-stage source path is not a canonical non-symlink path",
            details={"identity": identity},
        )
    return resolved


def _canonical_target_parent(value: Path | str) -> Path:
    requested = Path(value).expanduser()
    try:
        metadata = requested.lstat()
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_target_parent_invalid",
            "closure-stage target parent must be an existing directory",
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or not requested.is_absolute()
    ):
        raise CutoverEvidenceError(
            "closure_stage_target_parent_invalid",
            "closure-stage target parent must be an absolute non-symlink directory",
        )
    return resolved


def _validate_source_inventory(
    source_inventory: Mapping[str, object],
) -> dict[str, Any]:
    source = dict(source_inventory)
    if (
        set(source) != _SOURCE_FIELDS
        or source.get("schema_id")
        != AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_inventory_schema_invalid",
            "closure-stage source inventory has an unsupported closed schema",
        )
    campaign_root = _canonical_existing_path(
        source.get("campaign_root"),
        identity="source_inventory.campaign_root",
        directory=True,
    )
    attempt_root = _canonical_existing_path(
        source.get("attempt_root"),
        identity="source_inventory.attempt_root",
        directory=True,
    )
    database_path = _canonical_existing_path(
        source.get("database_path"),
        identity="source_inventory.database_path",
        directory=False,
    )
    authority_plan_path = _canonical_existing_path(
        source.get("authority_plan_path"),
        identity="source_inventory.authority_plan_path",
        directory=False,
    )
    authority_consumption_path = _canonical_existing_path(
        source.get("authority_consumption_path"),
        identity="source_inventory.authority_consumption_path",
        directory=False,
    )
    campaign_id = source.get("campaign_id")
    attempt_id = source.get("attempt_id")
    if (
        not isinstance(campaign_id, str)
        or FORMAL_ACCEPTANCE_RUN_POLICY.campaign_id_pattern.fullmatch(
            campaign_id
        )
        is None
        or not isinstance(attempt_id, str)
        or FORMAL_ACCEPTANCE_RUN_POLICY.attempt_id_pattern.fullmatch(attempt_id)
        is None
        or not attempt_id.startswith("positive-")
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_identity_invalid",
            "closure-stage source must bind one formal positive r-series attempt",
        )
    expected_session, expected_task, _, _ = (
        FORMAL_ACCEPTANCE_RUN_POLICY.identities(attempt_id)
    )
    if (
        attempt_root.parent != campaign_root
        or attempt_root.name != attempt_id
        or database_path != attempt_root / "control-plane.sqlite3"
        or source.get("session_id") != expected_session
        or source.get("execution_task_id") != expected_task
        or not isinstance(source.get("executor_agent_id"), str)
        or _EXECUTOR_PATTERN.fullmatch(str(source["executor_agent_id"])) is None
        or not isinstance(source.get("selection_id"), str)
        or _SELECTION_PATTERN.fullmatch(str(source["selection_id"])) is None
        or source.get("cut_cursor") != 614
        or source.get("first_post_cut_cursor") != 615
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_identity_invalid",
            "closure-stage source identities do not reproduce the cursor-614 cut",
        )
    for field in (
        "operation_universe_digest",
        "source_root_identity",
        "database_sha256",
        "inventory_digest",
        "frozen_paths_digest",
    ):
        _require_digest(source.get(field), identity=f"source_inventory.{field}")
    if (
        authority_plan_path == authority_consumption_path
        or authority_plan_path.is_relative_to(campaign_root)
        or authority_consumption_path.is_relative_to(campaign_root)
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_authority_identity_invalid",
            "frozen source authority must remain outside the source campaign root",
        )
    return source


def validate_aox_closure_stage_source_inventory(
    source_inventory: Mapping[str, object],
) -> dict[str, Any]:
    """Validate the closed pre-authority inventory binding."""

    return _validate_source_inventory(source_inventory)


def _validate_contract_bindings(
    contract_bindings: Mapping[str, object],
    *,
    identity: Mapping[str, object],
    architecture_qualification_digest: str,
) -> dict[str, Any]:
    bindings = dict(contract_bindings)
    if set(bindings) != _CONTRACT_FIELDS:
        raise CutoverEvidenceError(
            "closure_stage_contract_binding_schema_invalid",
            "closure-stage contract bindings have an unsupported closed schema",
        )
    if bindings.get("workflow_id") != AOX_SELECTED_CHAIN_WORKFLOW_ID:
        raise CutoverEvidenceError(
            "closure_stage_workflow_identity_invalid",
            "closure-stage authority requires the selected-chain workflow",
        )
    for field in (
        "workflow_contract_digest",
        "sop_digest",
        "closure_stage_sop_digest",
        "architecture_qualification_digest",
        "ui_dist_digest",
        "source_launch_receipt_digest",
        "runtime_config_digest",
    ):
        _require_digest(bindings.get(field), identity=f"contract_bindings.{field}")
    repair_commit = bindings.get("repair_commit")
    if (
        not isinstance(repair_commit, str)
        or _COMMIT_PATTERN.fullmatch(repair_commit) is None
        or repair_commit != identity.get("git_commit")
        or bindings.get("architecture_qualification_digest")
        != architecture_qualification_digest
        or (
            isinstance(identity.get("config_digest"), str)
            and bindings.get("runtime_config_digest")
            != identity.get("config_digest")
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_contract_binding_mismatch",
            "closure-stage contracts do not bind the current implementation",
        )
    return bindings


def _validate_runtime_parity(
    runtime_parity: Mapping[str, object],
) -> dict[str, Any]:
    parity = dict(runtime_parity)
    if (
        set(parity) != _PARITY_FIELDS
        or parity.get("schema_id")
        != AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID
    ):
        raise CutoverEvidenceError(
            "closure_stage_runtime_parity_schema_invalid",
            "closure-stage runtime parity has an unsupported closed schema",
        )
    for field in _PARITY_FIELDS - {"schema_id"}:
        _require_digest(parity.get(field), identity=f"runtime_parity.{field}")
    return parity


def _validate_micu_binding(
    micu: Mapping[str, object],
    *,
    effective_config_digest: object,
) -> dict[str, Any]:
    binding = dict(micu)
    if (
        set(binding) != _MICU_FIELDS
        or binding.get("schema_id") != AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID
        or binding.get("token_scenario") != "aox_closure_stage_diagnostic"
        or not isinstance(binding.get("provider"), str)
        or not str(binding["provider"]).strip()
        or not isinstance(binding.get("model"), str)
        or not str(binding["model"]).strip()
    ):
        raise CutoverEvidenceError(
            "closure_stage_micu_binding_schema_invalid",
            "closure-stage MICU binding has an unsupported closed schema",
        )
    for field in (
        "endpoint_identity",
        "ledger_identity",
        "effective_config_digest",
    ):
        _require_digest(binding.get(field), identity=f"micu.{field}")
    ledger_path = _canonical_existing_path(
        binding.get("ledger_path"),
        identity="micu.ledger_path",
        directory=False,
    )
    if (
        str(ledger_path) != binding.get("ledger_path")
        or binding.get("ledger_identity")
        != canonical_digest({"ledger_path": str(ledger_path)})
        or binding.get("effective_config_digest")
        != effective_config_digest
    ):
        raise CutoverEvidenceError(
            "closure_stage_micu_binding_identity_invalid",
            (
                "closure-stage MICU ledger and effective configuration "
                "must reproduce their pinned identities"
            ),
        )
    return binding


def _validate_resources(resources: Mapping[str, object]) -> dict[str, int]:
    normalized = dict(resources)
    if (
        set(normalized) != _RESOURCE_FIELDS
        or any(
            type(normalized.get(field)) is not int
            or int(normalized[field]) < 0
            for field in _RESOURCE_FIELDS
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_resource_invalid",
            "closure-stage resource ceilings must be non-negative integers",
        )
    return {
        field: int(normalized[field])
        for field in sorted(_RESOURCE_FIELDS)
    }


def _assert_target_disjoint_and_fresh(
    *,
    target_root: Path,
    source: Mapping[str, object],
) -> None:
    if target_root.exists() or target_root.is_symlink():
        raise CutoverEvidenceError(
            "closure_stage_target_not_fresh",
            "closure-stage target root must not exist before authority consumption",
        )
    if any(
        _NUMBERED_COMPONENT_PATTERN.fullmatch(component) is not None
        for component in target_root.parts
    ):
        raise CutoverEvidenceError(
            "closure_stage_target_numbered_identity_forbidden",
            "closure-stage target cannot use an rNN identity",
        )
    _assert_mutable_path_outside_checkout(
        target_root,
        code="closure_stage_target_inside_checkout",
        label="target root",
    )
    source_paths = (
        Path(str(source["campaign_root"])),
        Path(str(source["attempt_root"])),
        Path(str(source["database_path"])),
        Path(str(source["authority_plan_path"])),
        Path(str(source["authority_consumption_path"])),
    )
    if any(
        target_root == path
        or target_root.is_relative_to(path)
        or path.is_relative_to(target_root)
        for path in source_paths
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_target_overlap",
            "closure-stage source and target paths must be fully disjoint",
        )


def _assert_mutable_path_disjoint_from_source(
    path: Path,
    *,
    source: Mapping[str, object],
    code: str,
    label: str,
) -> None:
    campaign_root = Path(str(source["campaign_root"]))
    attempt_root = Path(str(source["attempt_root"]))
    frozen_files = {
        Path(str(source["database_path"])),
        Path(str(source["authority_plan_path"])),
        Path(str(source["authority_consumption_path"])),
    }
    if (
        path == campaign_root
        or path == attempt_root
        or path.is_relative_to(campaign_root)
        or path.is_relative_to(attempt_root)
        or path in frozen_files
    ):
        raise CutoverEvidenceError(
            code,
            f"closure-stage {label} cannot write into the frozen r-series source",
        )


def _assert_mutable_path_outside_checkout(
    path: Path,
    *,
    code: str,
    label: str,
) -> None:
    checkout = REPO_ROOT.resolve()
    if path == checkout or checkout in path.parents:
        raise CutoverEvidenceError(
            code,
            f"closure-stage {label} must stay outside the clean checkout",
        )


def _canonical_browser_observation_target(
    value: object,
    *,
    source: Mapping[str, object],
    target_root: Path,
) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        raise CutoverEvidenceError(
            "closure_stage_browser_target_invalid",
            "closure-stage browser receipt target must be a canonical path or null",
        )
    requested = Path(value).expanduser()
    try:
        metadata = requested.parent.lstat()
        parent = requested.parent.resolve(strict=True)
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_browser_target_invalid",
            "closure-stage browser receipt requires an existing real parent",
        ) from exc
    target = parent / requested.name
    if (
        not requested.is_absolute()
        or requested.parent != parent
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise CutoverEvidenceError(
            "closure_stage_browser_target_invalid",
            "closure-stage browser receipt parent must be canonical and non-symlinked",
        )
    if target.exists() or target.is_symlink():
        raise CutoverEvidenceError(
            "closure_stage_browser_target_exists",
            "closure-stage browser receipt is append-only and must not exist",
        )
    _assert_mutable_path_disjoint_from_source(
        target,
        source=source,
        code="closure_stage_browser_target_source_overlap",
        label="browser receipt",
    )
    _assert_mutable_path_outside_checkout(
        target,
        code="closure_stage_browser_target_inside_checkout",
        label="browser receipt",
    )
    if (
        target == target_root
        or target.is_relative_to(target_root)
        or target_root.is_relative_to(target)
    ):
        raise CutoverEvidenceError(
            "closure_stage_browser_target_root_overlap",
            "closure-stage browser receipt must stay outside the isolated target root",
        )
    return target


def build_aox_closure_stage_authority_plan(
    *,
    source_inventory: Mapping[str, object],
    target_parent: Path,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    contract_bindings: Mapping[str, object],
    runtime_parity: Mapping[str, object],
    micu: Mapping[str, object],
    browser_observation_receipt: Path | None,
    expires_at: str,
    max_micu: int,
    max_cost_microunits: int,
    max_wall_time_seconds: int,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build one reviewable closure-stage authority without creating a root."""

    effective_issued_at = issued_at or _utc_now()
    _validate_time_window(
        issued_at=effective_issued_at,
        expires_at=expires_at,
    )
    source = _validate_source_inventory(source_inventory)
    normalized_parent = _canonical_target_parent(target_parent)
    identity_digest = canonical_digest(dict(identity))
    prerequisite_digest = canonical_digest(dict(allowed_prerequisites))
    qualification_digest = canonical_digest(dict(architecture_qualification))
    bindings = _validate_contract_bindings(
        contract_bindings,
        identity=identity,
        architecture_qualification_digest=qualification_digest,
    )
    parity = _validate_runtime_parity(runtime_parity)
    micu_binding = _validate_micu_binding(
        micu,
        effective_config_digest=identity.get("config_digest"),
    )
    _assert_mutable_path_disjoint_from_source(
        Path(str(micu_binding["ledger_path"])),
        source=source,
        code="closure_stage_micu_ledger_source_overlap",
        label="MICU ledger",
    )
    resources = _validate_resources(
        {
            "max_micu": max_micu,
            "max_cost_microunits": max_cost_microunits,
            "max_wall_time_seconds": max_wall_time_seconds,
        }
    )
    diagnostic_id = (
        "aox_closure_stage_"
        + canonical_digest(
            {
                "source_inventory_digest": source["inventory_digest"],
                "identity_digest": identity_digest,
                "runtime_parity_digest": canonical_digest(parity),
                "nonce": secrets.token_hex(32),
            }
        ).removeprefix("sha256:")[:24]
    )
    root_namespace = diagnostic_id.replace("_", "-")
    target_root = normalized_parent / root_namespace
    _assert_target_disjoint_and_fresh(
        target_root=target_root,
        source=source,
    )
    browser_target = _canonical_browser_observation_target(
        browser_observation_receipt,
        source=source,
        target_root=target_root,
    )
    if (
        browser_target is not None
        and browser_target == Path(str(micu_binding["ledger_path"]))
    ):
        raise CutoverEvidenceError(
            "closure_stage_browser_target_ledger_collision",
            "closure-stage browser receipt and MICU ledger must be distinct",
        )
    process_epoch = f"closure-stage-process-{secrets.token_hex(16)}"
    attempt_id = f"closure-stage-{secrets.token_hex(16)}"
    session_id, task_id, lane_id, root_ref = (
        CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.identities(attempt_id)
    )
    provider_token = f"aox-provider-routes@{identity_digest}"
    hpc_target_token = f"aox-hpc-routes@{identity_digest}"
    authority_arguments = {
        "session_id": session_id,
        "task_id": task_id,
        "campaign_id": diagnostic_id,
        "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "root_ref": root_ref,
        "grantor_kind": "operator",
        "grantor_ref": AOX_ATTEMPT_AUTHORITY_GRANTOR_REF,
        "allowed_scopes": ("formal",),
        "allowed_effect_classes": ("hpc", "provider"),
        "allowed_providers": (provider_token,),
        "allowed_hpc_targets": (hpc_target_token,),
        "max_attempts": 1,
        "max_micu": resources["max_micu"],
        "max_cost_microunits": resources["max_cost_microunits"],
        "max_wall_time_seconds": resources["max_wall_time_seconds"],
        "expires_at": expires_at,
        "idempotency_key": f"{diagnostic_id}:authority:1",
    }
    envelope_id, request_digest, request = (
        scientific_attempt_authorization_identity(**authority_arguments)
    )
    slot = {
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "ordinal": 1,
        "attempt_kind": "positive",
        "attempt_id": attempt_id,
        "session_id": session_id,
        "task_id": task_id,
        "lane_id": lane_id,
        "scope": "formal",
        "authority_request": request,
        "envelope_id": envelope_id,
        "request_digest": request_digest,
    }
    payload: dict[str, Any] = {
        "schema_id": AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": diagnostic_id,
        "root_namespace": root_namespace,
        "target_root": str(target_root),
        "browser_observation_receipt": (
            None if browser_target is None else str(browser_target)
        ),
        "process_epoch": process_epoch,
        "source_inventory": source,
        "identity_digest": identity_digest,
        "allowed_prerequisite_digest": prerequisite_digest,
        "architecture_qualification_digest": qualification_digest,
        "contract_bindings": bindings,
        "runtime_parity": parity,
        "micu": micu_binding,
        "issued_at": effective_issued_at,
        "expires_at": expires_at,
        "resources": resources,
        "slot": slot,
    }
    return {**payload, "plan_digest": canonical_digest(payload)}


def validate_aox_closure_stage_authority_plan(
    plan: Mapping[str, object],
    *,
    source_inventory: Mapping[str, object],
    target_parent: Path,
    process_epoch: str,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    contract_bindings: Mapping[str, object],
    runtime_parity: Mapping[str, object],
    micu: Mapping[str, object],
    browser_observation_receipt: Path | None,
) -> dict[str, Any]:
    normalized = dict(plan)
    if (
        set(normalized) != _PLAN_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_schema_invalid",
            "closure-stage authority plan has an unsupported closed schema",
        )
    _validate_time_window(
        issued_at=normalized.get("issued_at"),
        expires_at=normalized.get("expires_at"),
    )
    expected_source = _validate_source_inventory(source_inventory)
    observed_source = normalized.get("source_inventory")
    if not isinstance(observed_source, dict):
        raise CutoverEvidenceError(
            "closure_stage_source_inventory_schema_invalid",
            "closure-stage plan lacks its closed source inventory",
        )
    validated_source = _validate_source_inventory(observed_source)
    diagnostic_id = normalized.get("diagnostic_id")
    root_namespace = normalized.get("root_namespace")
    parent = _canonical_target_parent(target_parent)
    expected_target = parent / str(root_namespace)
    if (
        not isinstance(diagnostic_id, str)
        or CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(
            diagnostic_id
        )
        is None
        or root_namespace != diagnostic_id.replace("_", "-")
        or normalized.get("target_root") != str(expected_target)
        or not isinstance(process_epoch, str)
        or _PROCESS_EPOCH_PATTERN.fullmatch(process_epoch) is None
        or normalized.get("process_epoch") != process_epoch
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_identity_invalid",
            "closure-stage plan target or process identity does not reproduce",
        )
    _assert_target_disjoint_and_fresh(
        target_root=expected_target,
        source=validated_source,
    )
    qualification_digest = canonical_digest(
        dict(architecture_qualification)
    )
    expected_bindings = _validate_contract_bindings(
        contract_bindings,
        identity=identity,
        architecture_qualification_digest=qualification_digest,
    )
    expected_parity = _validate_runtime_parity(runtime_parity)
    expected_micu = _validate_micu_binding(
        micu,
        effective_config_digest=identity.get("config_digest"),
    )
    _assert_mutable_path_disjoint_from_source(
        Path(str(expected_micu["ledger_path"])),
        source=validated_source,
        code="closure_stage_micu_ledger_source_overlap",
        label="MICU ledger",
    )
    expected_browser_target = _canonical_browser_observation_target(
        browser_observation_receipt,
        source=validated_source,
        target_root=expected_target,
    )
    observed_browser_target = _canonical_browser_observation_target(
        normalized.get("browser_observation_receipt"),
        source=validated_source,
        target_root=expected_target,
    )
    ledger_target = Path(str(expected_micu["ledger_path"]))
    if any(
        browser_target is not None and browser_target == ledger_target
        for browser_target in (
            expected_browser_target,
            observed_browser_target,
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_browser_target_ledger_collision",
            "closure-stage browser receipt and MICU ledger must be distinct",
        )
    observed_bindings = normalized.get("contract_bindings")
    observed_parity = normalized.get("runtime_parity")
    observed_micu = normalized.get("micu")
    if (
        not isinstance(observed_bindings, dict)
        or not isinstance(observed_parity, dict)
        or not isinstance(observed_micu, dict)
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_binding_schema_invalid",
            "closure-stage plan lacks one of its closed launch bindings",
        )
    _validate_contract_bindings(
        observed_bindings,
        identity=identity,
        architecture_qualification_digest=qualification_digest,
    )
    _validate_runtime_parity(observed_parity)
    validated_observed_micu = _validate_micu_binding(
        observed_micu,
        effective_config_digest=identity.get("config_digest"),
    )
    _assert_mutable_path_disjoint_from_source(
        Path(str(validated_observed_micu["ledger_path"])),
        source=validated_source,
        code="closure_stage_micu_ledger_source_overlap",
        label="MICU ledger",
    )
    expected_digests = {
        "identity_digest": canonical_digest(dict(identity)),
        "allowed_prerequisite_digest": canonical_digest(
            dict(allowed_prerequisites)
        ),
        "architecture_qualification_digest": qualification_digest,
    }
    drift: dict[str, object] = {
        key: {"expected": expected, "actual": normalized.get(key)}
        for key, expected in expected_digests.items()
        if normalized.get(key) != expected
    }
    for field, observed, expected in (
        ("source_inventory", validated_source, expected_source),
        ("contract_bindings", observed_bindings, expected_bindings),
        ("runtime_parity", observed_parity, expected_parity),
        ("micu", observed_micu, expected_micu),
        (
            "browser_observation_receipt",
            (
                None
                if observed_browser_target is None
                else str(observed_browser_target)
            ),
            (
                None
                if expected_browser_target is None
                else str(expected_browser_target)
            ),
        ),
    ):
        if observed != expected:
            drift[field] = {
                "expected_digest": canonical_digest(expected),
                "actual_digest": canonical_digest(observed),
            }
    resources_raw = normalized.get("resources")
    if not isinstance(resources_raw, dict):
        raise CutoverEvidenceError(
            "closure_stage_authority_resource_invalid",
            "closure-stage plan lacks closed resource ceilings",
        )
    resources = _validate_resources(resources_raw)
    unsigned = {
        key: value
        for key, value in normalized.items()
        if key != "plan_digest"
    }
    expected_plan_digest = canonical_digest(unsigned)
    if normalized.get("plan_digest") != expected_plan_digest:
        drift["plan_digest"] = {
            "expected": expected_plan_digest,
            "actual": normalized.get("plan_digest"),
        }
    if drift:
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_binding_mismatch",
            "closure-stage authority plan does not bind current declarations",
            details={"drift": drift},
        )
    raw_slot = normalized.get("slot")
    if not isinstance(raw_slot, dict) or set(raw_slot) != _SLOT_FIELDS:
        raise CutoverEvidenceError(
            "closure_stage_authority_slot_schema_invalid",
            "closure-stage authority slot has an unsupported closed schema",
        )
    slot = dict(raw_slot)
    attempt_id = slot.get("attempt_id")
    (
        expected_session,
        expected_task,
        expected_lane,
        expected_root_ref,
    ) = CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.identities(
        "" if not isinstance(attempt_id, str) else attempt_id
    )
    request = slot.get("authority_request")
    if (
        slot.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or slot.get("ordinal") != 1
        or slot.get("attempt_kind") != "positive"
        or not isinstance(attempt_id, str)
        or CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.attempt_id_pattern.fullmatch(
            attempt_id
        )
        is None
        or slot.get("session_id") != expected_session
        or slot.get("task_id") != expected_task
        or slot.get("lane_id") != expected_lane
        or slot.get("scope") != "formal"
        or not isinstance(request, dict)
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_slot_identity_invalid",
            "closure-stage authority slot identities do not reproduce",
        )
    request_arguments = {
        key: value
        for key, value in request.items()
        if key not in {"command", "policy_digest"}
    }
    try:
        envelope_id, request_digest, expected_request = (
            scientific_attempt_authorization_identity(**request_arguments)
        )
    except (TypeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_authority_slot_request_invalid",
            "closure-stage authority request is malformed",
        ) from exc
    expected_provider = f"aox-provider-routes@{expected_digests['identity_digest']}"
    expected_hpc = f"aox-hpc-routes@{expected_digests['identity_digest']}"
    if (
        request != expected_request
        or request.get("session_id") != expected_session
        or request.get("task_id") != expected_task
        or request.get("campaign_id") != diagnostic_id
        or request.get("workflow_id") != AOX_SELECTED_CHAIN_WORKFLOW_ID
        or request.get("root_ref") != expected_root_ref
        or request.get("grantor_kind") != "operator"
        or request.get("grantor_ref") != AOX_ATTEMPT_AUTHORITY_GRANTOR_REF
        or request.get("allowed_scopes") != ["formal"]
        or request.get("allowed_effect_classes") != ["hpc", "provider"]
        or request.get("allowed_providers") != [expected_provider]
        or request.get("allowed_hpc_targets") != [expected_hpc]
        or request.get("max_attempts") != 1
        or request.get("max_micu") != resources["max_micu"]
        or request.get("max_cost_microunits")
        != resources["max_cost_microunits"]
        or request.get("max_wall_time_seconds")
        != resources["max_wall_time_seconds"]
        or request.get("expires_at") != normalized["expires_at"]
        or request.get("idempotency_key")
        != f"{diagnostic_id}:authority:1"
        or slot.get("envelope_id") != envelope_id
        or slot.get("request_digest") != request_digest
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_slot_request_mismatch",
            "closure-stage slot does not reproduce its exact durable grant",
        )
    return normalized


def load_aox_closure_stage_authority_plan(
    path: Path,
    *,
    source_inventory: Mapping[str, object],
    target_parent: Path,
    process_epoch: str,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    contract_bindings: Mapping[str, object],
    runtime_parity: Mapping[str, object],
    micu: Mapping[str, object],
    browser_observation_receipt: Path | None,
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_unreadable",
            "closure-stage authority plan is not a readable private file",
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_file_invalid",
            "closure-stage authority plan must be a private regular file",
        )
    try:
        content = path.read_bytes()
        plan = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_unreadable",
            "closure-stage authority plan is not readable JSON",
        ) from exc
    if (
        not isinstance(plan, dict)
        or content != canonical_json_bytes(plan) + b"\n"
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_noncanonical",
            "closure-stage authority plan must use canonical JSON bytes",
        )
    return validate_aox_closure_stage_authority_plan(
        plan,
        source_inventory=source_inventory,
        target_parent=target_parent,
        process_epoch=process_epoch,
        identity=identity,
        allowed_prerequisites=allowed_prerequisites,
        architecture_qualification=architecture_qualification,
        contract_bindings=contract_bindings,
        runtime_parity=runtime_parity,
        micu=micu,
        browser_observation_receipt=browser_observation_receipt,
    )


def _source_authority_paths(plan: Mapping[str, object]) -> tuple[Path, Path]:
    source = plan.get("source_inventory")
    if not isinstance(source, Mapping):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_class_mismatch",
            "closure-stage plan lacks its frozen source binding",
        )
    try:
        return (
            Path(str(source["authority_plan_path"])).resolve(strict=True),
            Path(str(source["authority_consumption_path"])).resolve(strict=True),
        )
    except (KeyError, OSError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_class_mismatch",
            "closure-stage plan has invalid frozen authority paths",
        ) from exc


def publish_aox_closure_stage_authority_plan(
    plan: Mapping[str, object],
    path: Path,
) -> None:
    if (
        plan.get("schema_id") != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or plan.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or plan.get("acceptance_eligible") is not False
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_class_mismatch",
            "closure-stage publisher rejects other run classes",
        )
    source_authorities = _source_authority_paths(plan)
    destination = path.expanduser().resolve(strict=False)
    source = dict(plan["source_inventory"])
    if destination in source_authorities:
        raise CutoverEvidenceError(
            "closure_stage_source_authority_reuse_forbidden",
            "closure-stage authority cannot replace an r-series authority file",
        )
    _assert_mutable_path_disjoint_from_source(
        destination,
        source=source,
        code="closure_stage_authority_output_source_overlap",
        label="authority output",
    )
    _assert_mutable_path_outside_checkout(
        destination,
        code="closure_stage_authority_output_inside_checkout",
        label="authority output",
    )
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(dict(plan)) + b"\n",
    )


def closure_stage_authority_consumption_path(plan_path: Path) -> Path:
    return plan_path.with_name(
        f"{plan_path.name}.closure-stage-consumed.json"
    )


def consume_aox_closure_stage_authority_plan(
    plan: Mapping[str, object],
    *,
    plan_path: Path,
    path: Path,
) -> dict[str, Any]:
    if (
        plan.get("schema_id") != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or plan.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or plan.get("acceptance_eligible") is not False
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_class_mismatch",
            "closure-stage consumption rejects other run classes",
        )
    source_authorities = _source_authority_paths(plan)
    canonical_plan_path = plan_path.expanduser().resolve(strict=False)
    if canonical_plan_path in source_authorities:
        raise CutoverEvidenceError(
            "closure_stage_source_authority_reuse_forbidden",
            "closure-stage consumption cannot reuse an r-series authority path",
        )
    source = dict(plan["source_inventory"])
    _assert_mutable_path_disjoint_from_source(
        canonical_plan_path,
        source=source,
        code="closure_stage_authority_output_source_overlap",
        label="authority plan",
    )
    _assert_mutable_path_outside_checkout(
        canonical_plan_path,
        code="closure_stage_authority_output_inside_checkout",
        label="authority plan",
    )
    expected_path = closure_stage_authority_consumption_path(plan_path)
    if path != expected_path:
        raise CutoverEvidenceError(
            "closure_stage_authority_consumption_target_mismatch",
            "closure-stage consumption must use its deterministic sibling",
            details={"expected_file": expected_path.name},
        )
    canonical_consumption_path = path.expanduser().resolve(strict=False)
    _assert_mutable_path_disjoint_from_source(
        canonical_consumption_path,
        source=source,
        code="closure_stage_authority_consumption_source_overlap",
        label="authority consumption",
    )
    _assert_mutable_path_outside_checkout(
        canonical_consumption_path,
        code="closure_stage_authority_consumption_inside_checkout",
        label="authority consumption",
    )
    receipt = {
        "schema_id": AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "plan_schema_id": AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": plan["plan_digest"],
        "diagnostic_id": plan["diagnostic_id"],
        "root_namespace": plan["root_namespace"],
        "target_root": plan["target_root"],
        "process_epoch": plan["process_epoch"],
        "consumption_file": path.name,
        "consumed_at": _utc_now(),
    }
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(receipt) + b"\n",
    )
    return receipt


def validate_aox_closure_stage_authority_consumption(
    receipt: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    plan_path: Path,
) -> dict[str, Any]:
    normalized = dict(receipt)
    if (
        plan.get("schema_id") != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or plan.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or plan.get("acceptance_eligible") is not False
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_plan_class_mismatch",
            "closure-stage receipt validation rejects other run classes",
        )
    expected_path = closure_stage_authority_consumption_path(plan_path)
    if (
        set(normalized) != _CONSUMPTION_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or normalized.get("plan_schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or normalized.get("plan_digest") != plan.get("plan_digest")
        or normalized.get("diagnostic_id") != plan.get("diagnostic_id")
        or normalized.get("root_namespace") != plan.get("root_namespace")
        or normalized.get("target_root") != plan.get("target_root")
        or normalized.get("process_epoch") != plan.get("process_epoch")
        or normalized.get("consumption_file") != expected_path.name
    ):
        raise CutoverEvidenceError(
            "closure_stage_authority_consumption_invalid",
            "closure-stage consumption receipt does not bind its exact plan",
        )
    _parse_timestamp(
        normalized.get("consumed_at"),
        code="closure_stage_authority_consumption_invalid",
        label="consumed_at",
    )
    return normalized


__all__ = [
    "AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID",
    "build_aox_closure_stage_authority_plan",
    "closure_stage_authority_consumption_path",
    "consume_aox_closure_stage_authority_plan",
    "load_aox_closure_stage_authority_plan",
    "publish_aox_closure_stage_authority_plan",
    "validate_aox_closure_stage_authority_consumption",
    "validate_aox_closure_stage_authority_plan",
    "validate_aox_closure_stage_source_inventory",
]
