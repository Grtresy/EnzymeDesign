from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import tempfile
from typing import Any

from openzyme_core import ScientificWorkflowContract
from openzyme_core import ScientificWorkflowContractError
from openzyme_core import verify_quiescence_evidence_envelope
from openzyme_domain import ScientificAttemptScope

from .aox_cutover_evidence import ATTEMPT_BUNDLE_SCHEMA_ID_V2
from .aox_cutover_evidence import ATTEMPT_BUNDLE_SCHEMA_ID_V3
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import VerificationIssue
from .aox_cutover_evidence import VerificationResult
from .aox_cutover_evidence import _assert_public_safe
from .aox_cutover_evidence import _strict_json_loads
from .aox_cutover_evidence import _validate_effective_config_attestation
from .aox_cutover_evidence import _verify_attempt_bundle_v2
from .aox_cutover_evidence import build_attempt_bundle
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


SCIENTIFIC_ATTEMPT_EVIDENCE_SCHEMA_ID = "scientific_attempt_evidence@1"
SCIENTIFIC_OPERATION_UNIVERSE_SCHEMA_ID = "scientific_operation_universe@2"

_CONTROL_FIELDS = frozenset(
    {
        "schema_id",
        "attempt_authority",
        "admission_request",
        "attempt",
        "operation_universe",
        "selection",
        "dispositions",
        "adoptions",
        "materializations",
        "closure_request",
        "quiescence",
        "closure",
        "evidence_digest",
    }
)
_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "envelope_id",
        "session_id",
        "task_id",
        "campaign_id",
        "workflow_id",
        "root_ref",
        "grantor_kind",
        "grantor_ref",
        "allowed_scopes",
        "allowed_effect_classes",
        "allowed_provider_digests",
        "allowed_hpc_target_digests",
        "max_attempts",
        "max_micu",
        "max_cost_microunits",
        "max_wall_time_seconds",
        "consumed_attempts",
        "reserved_micu",
        "reserved_cost_microunits",
        "reserved_wall_time_seconds",
        "expires_at",
        "policy_digest",
        "idempotency_key",
        "request_digest",
        "status",
        "state_version",
        "created_at",
        "updated_at",
    }
)
_ADMISSION_FIELDS = frozenset(
    {
        "schema_version",
        "admission_request_id",
        "envelope_id",
        "session_id",
        "task_id",
        "lane_id",
        "campaign_id",
        "workflow_id",
        "scope",
        "workflow_contract_digest",
        "requested_effect_classes",
        "provider_digest",
        "hpc_target_digest",
        "reserved_micu",
        "reserved_cost_microunits",
        "reserved_wall_time_seconds",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "schema_version",
        "attempt_id",
        "admission_request_id",
        "envelope_id",
        "session_id",
        "task_id",
        "lane_id",
        "campaign_id",
        "workflow_id",
        "scope",
        "root_ref",
        "mutation_scope_id",
        "ordinal",
        "request_digest",
        "idempotency_key",
        "workflow_contract_digest",
        "requested_effect_classes",
        "provider_digest",
        "hpc_target_digest",
        "reserved_micu",
        "reserved_cost_microunits",
        "reserved_wall_time_seconds",
        "status",
        "state_version",
        "created_by",
        "created_at",
        "updated_at",
    }
)
_UNIVERSE_FIELDS = frozenset(
    {
        "schema_id",
        "attempt_id",
        "run_ids",
        "operation_count",
        "operation_universe_digest",
        "occurrences",
    }
)
_OCCURRENCE_FIELDS = frozenset(
    {
        "attempt_id",
        "operation_id",
        "sandbox_run_id",
        "logical_operation_key",
        "operation_digest",
        "backend_category",
        "sdk_module",
        "function_name",
        "operation_status",
        "approval_id",
        "approval_state",
        "owner_mode",
        "execution",
        "result",
        "occurrence_digest",
    }
)
_EXECUTION_FIELDS = frozenset(
    {
        "execution_id",
        "lifecycle_state",
        "terminal_outcome",
        "effect_certainty",
        "retry_eligibility",
        "state_version",
        "dispatch_generation",
        "result_handle_ref",
        "result_digest",
        "artifact_set_digest",
        "approval_digest",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "result_handle_id",
        "terminal_outcome",
        "result_digest",
        "artifact_set_digest",
        "origin",
    }
)
_SELECTION_FIELDS = frozenset(
    {
        "schema_version",
        "selection_id",
        "attempt_id",
        "revision",
        "parent_selection_id",
        "state",
        "operation_universe_digest",
        "operation_count",
        "disposition_digest",
        "adoption_digest",
        "workflow_contract_digest",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
        "sealed_at",
    }
)
_DISPOSITION_FIELDS = frozenset(
    {
        "schema_version",
        "disposition_id",
        "selection_id",
        "attempt_id",
        "operation_id",
        "kind",
        "workflow_role",
        "reason_code",
        "replacement_operation_id",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
)
_ADOPTION_FIELDS = frozenset(
    {
        "schema_version",
        "adoption_id",
        "selection_id",
        "attempt_id",
        "workflow_role",
        "operation_id",
        "execution_id",
        "result_handle_id",
        "result_digest",
        "artifact_set_digest",
        "source_sandbox_run_id",
        "effect_certainty",
        "approval_digest",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
)
_MATERIALIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "selection_id",
        "attempt_id",
        "adoption_id",
        "source_artifact_id",
        "source_artifact_digest",
        "source_sandbox_run_id",
        "target_sandbox_workspace_id",
        "target_sandbox_run_id",
        "target_path",
        "boundary_materialization_id",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
)
_CLOSURE_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "closure_request_id",
        "attempt_id",
        "selection_id",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
)
_CLOSURE_FIELDS = frozenset(
    {
        "schema_version",
        "closure_id",
        "closure_request_id",
        "attempt_id",
        "selection_id",
        "operation_universe_digest",
        "disposition_digest",
        "adoption_digest",
        "materialization_digest",
        "authority_consumption_digest",
        "quiescence_receipt_id",
        "quiescence_receipt_digest",
        "closure_digest",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
)


def build_selected_chain_attempt_bundle(
    *,
    attempt_id: str,
    attempt_kind: str,
    identity: Mapping[str, object],
    clean_world: Mapping[str, object],
    ledger_before: Mapping[str, object],
    ledger_after: Mapping[str, object],
    artifact_root: Path,
    evidence: Mapping[str, object],
    scientific_attempt_control: Mapping[str, object],
    sealed_at: str | None = None,
) -> dict[str, Any]:
    """Build @3 only after the frozen @2 scientific verifier accepts the payload."""

    legacy_evidence = _project_authorized_supervision_to_v1(evidence)
    payload = build_attempt_bundle(
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        identity=identity,
        clean_world=clean_world,
        ledger_before=ledger_before,
        ledger_after=ledger_after,
        artifact_root=artifact_root,
        evidence=legacy_evidence,
        sealed_at=sealed_at,
    )
    original_product_path = dict(evidence.get("product_path") or {})
    if isinstance(original_product_path.get("attempt_supervision"), dict):
        product_path = dict(payload.get("product_path") or {})
        product_path["attempt_supervision"] = dict(
            original_product_path["attempt_supervision"]
        )
        payload["product_path"] = product_path
    control = dict(scientific_attempt_control)
    issues: list[VerificationIssue] = []
    _verify_selected_chain_control(payload, control=control, issues=issues)
    if issues:
        first = issues[0]
        raise CutoverEvidenceError(
            first.code,
            first.message,
            details={"identity": first.identity},
        )
    selected_payload = {
        **payload,
        "schema_id": ATTEMPT_BUNDLE_SCHEMA_ID_V3,
        "scientific_attempt_control": control,
    }
    _assert_public_safe(
        selected_payload,
        identity="selected_chain_attempt_bundle",
    )
    return selected_payload


def verify_selected_chain_attempt_bundle(
    bundle_path: Path,
    *,
    artifact_root: Path,
) -> VerificationResult:
    issues: list[VerificationIssue] = []
    try:
        bundle_bytes = bundle_path.read_bytes()
        envelope = _strict_json_loads(bundle_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _failed_result(
            "bundle_unreadable",
            "bundle",
            f"bundle is not readable canonical JSON: {type(exc).__name__}",
        )
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"payload", "bundle_digest"}
        or not isinstance(envelope.get("payload"), dict)
    ):
        return _failed_result(
            "bundle_envelope_invalid",
            "bundle",
            "bundle envelope requires exactly payload and bundle_digest",
        )
    payload = dict(envelope["payload"])
    attempt_id = _text_or_none(payload.get("attempt_id"))
    attempt_kind = _text_or_none(payload.get("attempt_kind"))
    declared_digest = envelope.get("bundle_digest")
    if bundle_bytes != canonical_json_bytes(envelope) + b"\n":
        _issue(
            issues,
            "bundle_noncanonical",
            "bundle",
            "bundle bytes are not canonical UTF-8 JSON",
        )
    if payload.get("schema_id") != ATTEMPT_BUNDLE_SCHEMA_ID_V3:
        _issue(
            issues,
            "bundle_schema_invalid",
            "bundle.schema_id",
            "selected-chain verifier accepts only exact @3 bundles",
        )
    actual_digest = canonical_digest(payload)
    if declared_digest != actual_digest:
        _issue(
            issues,
            "bundle_digest_mismatch",
            "bundle.bundle_digest",
            "canonical @3 bundle digest does not match",
            expected=declared_digest,
            actual=actual_digest,
        )
    try:
        _assert_public_safe(
            envelope,
            identity="selected_chain_attempt_bundle_envelope",
        )
    except CutoverEvidenceError as exc:
        _issue(
            issues,
            exc.code,
            str(exc.details.get("identity") or "bundle"),
            "selected-chain bundle contains non-public evidence",
        )

    control = payload.get("scientific_attempt_control")
    if not isinstance(control, dict):
        _issue(
            issues,
            "scientific_attempt_control_missing",
            "scientific_attempt_control",
            "@3 requires exact closed scientific-attempt evidence",
        )
    else:
        _verify_selected_chain_control(payload, control=control, issues=issues)

    try:
        _validate_effective_config_attestation(payload)
    except CutoverEvidenceError as exc:
        _issue(
            issues,
            exc.code,
            str(
                exc.details.get("identity")
                or "product_path.launch_receipt.effective_config"
            ),
            str(exc),
        )

    projected_v2 = {
        key: value
        for key, value in payload.items()
        if key != "scientific_attempt_control"
    }
    projected_v2["schema_id"] = ATTEMPT_BUNDLE_SCHEMA_ID_V2
    projected_v2 = _project_authorized_supervision_to_v1(projected_v2)
    projected_envelope = {
        "payload": projected_v2,
        "bundle_digest": canonical_digest(projected_v2),
    }
    with tempfile.TemporaryDirectory(prefix="openzyme-aox-v2-verify-") as raw:
        projected_path = Path(raw) / "attempt-bundle-v2.json"
        projected_path.write_bytes(
            canonical_json_bytes(projected_envelope) + b"\n"
        )
        historical = _verify_attempt_bundle_v2(
            projected_path,
            artifact_root=artifact_root,
        )
    issues.extend(historical.issues)
    return VerificationResult(
        passed=not issues,
        bundle_digest=(
            declared_digest if isinstance(declared_digest, str) else None
        ),
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        issues=tuple(issues),
    )


def _project_authorized_supervision_to_v1(
    payload: Mapping[str, object],
) -> dict[str, Any]:
    """Create the exact historical receipt view used only by frozen @2 checks."""

    projected = dict(payload)
    product_path = projected.get("product_path")
    if not isinstance(product_path, Mapping):
        return projected
    normalized_product_path = dict(product_path)
    receipt = normalized_product_path.get("attempt_supervision")
    if not isinstance(receipt, Mapping):
        projected["product_path"] = normalized_product_path
        return projected
    normalized_receipt = dict(receipt)
    if normalized_receipt.get("schema_id") != (
        "aox_live_attempt_supervision_receipt@2"
    ):
        projected["product_path"] = normalized_product_path
        return projected
    normalized_receipt.pop("attempt_authority_id", None)
    normalized_receipt.pop("attempt_authority_request_digest", None)
    normalized_receipt["schema_id"] = "aox_live_attempt_supervision_receipt@1"
    try:
        from .aox_attempt_supervision import SUPERVISION_SCHEMA_ID_V1
        from .aox_attempt_supervision import supervision_contract_digest

        normalized_receipt["supervisor_contract_digest"] = (
            supervision_contract_digest(
                timeout_seconds=float(normalized_receipt["timeout_seconds"]),
                term_grace_seconds=float(
                    normalized_receipt["term_grace_seconds"]
                ),
                kill_grace_seconds=float(
                    normalized_receipt["kill_grace_seconds"]
                ),
                protocol_schema_id=SUPERVISION_SCHEMA_ID_V1,
            )
        )
    except (KeyError, TypeError, ValueError):
        pass
    normalized_product_path["attempt_supervision"] = normalized_receipt
    projected["product_path"] = normalized_product_path
    return projected


def _verify_selected_chain_control(
    payload: Mapping[str, Any],
    *,
    control: Mapping[str, Any],
    issues: list[VerificationIssue],
) -> None:
    if set(control) != _CONTROL_FIELDS:
        _issue(
            issues,
            "scientific_attempt_control_schema_invalid",
            "scientific_attempt_control",
            "scientific attempt control fields do not match @1",
        )
        return
    if control.get("schema_id") != SCIENTIFIC_ATTEMPT_EVIDENCE_SCHEMA_ID:
        _issue(
            issues,
            "scientific_attempt_control_schema_invalid",
            "scientific_attempt_control.schema_id",
            "scientific attempt control schema is unsupported",
        )
    expected_evidence_digest = canonical_digest(
        {
            key: value
            for key, value in control.items()
            if key != "evidence_digest"
        }
    )
    if control.get("evidence_digest") != expected_evidence_digest:
        _issue(
            issues,
            "scientific_attempt_control_digest_mismatch",
            "scientific_attempt_control.evidence_digest",
            "scientific attempt evidence digest does not reproduce",
        )

    records: dict[str, dict[str, Any]] = {}
    for name, fields, schema in (
        (
            "attempt_authority",
            _AUTHORIZATION_FIELDS,
            "scientific_attempt_authorization@1",
        ),
        (
            "admission_request",
            _ADMISSION_FIELDS,
            "scientific_attempt_admission_request@1",
        ),
        ("attempt", _ATTEMPT_FIELDS, "scientific_attempt@1"),
        ("selection", _SELECTION_FIELDS, "scientific_chain_selection@1"),
        (
            "closure_request",
            _CLOSURE_REQUEST_FIELDS,
            "scientific_attempt_closure_request@1",
        ),
        ("closure", _CLOSURE_FIELDS, "scientific_attempt_closure@1"),
    ):
        record = control.get(name)
        if (
            not isinstance(record, dict)
            or set(record) != fields
            or record.get("schema_version") != schema
        ):
            _issue(
                issues,
                "scientific_attempt_record_schema_invalid",
                f"scientific_attempt_control.{name}",
                f"{name} does not match its exact canonical schema",
            )
            return
        records[name] = dict(record)

    authorization = records["attempt_authority"]
    admission = records["admission_request"]
    attempt = records["attempt"]
    selection = records["selection"]
    closure_request = records["closure_request"]
    closure = records["closure"]
    attempt_id = str(attempt.get("attempt_id") or "")
    selection_id = str(selection.get("selection_id") or "")
    envelope_id = str(authorization.get("envelope_id") or "")

    contract = _verify_authority_and_attempt(
        payload,
        authorization=authorization,
        admission=admission,
        attempt=attempt,
        issues=issues,
    )

    universe = control.get("operation_universe")
    if (
        not isinstance(universe, dict)
        or set(universe) != _UNIVERSE_FIELDS
        or universe.get("schema_id") != SCIENTIFIC_OPERATION_UNIVERSE_SCHEMA_ID
    ):
        _issue(
            issues,
            "scientific_operation_universe_schema_invalid",
            "scientific_attempt_control.operation_universe",
            "operation universe does not match its exact schema",
        )
        return
    occurrences = universe.get("occurrences")
    run_ids = universe.get("run_ids")
    if (
        not isinstance(occurrences, list)
        or not all(isinstance(item, dict) for item in occurrences)
        or not isinstance(run_ids, list)
        or not all(isinstance(item, str) and item for item in run_ids)
    ):
        _issue(
            issues,
            "scientific_operation_universe_shape_invalid",
            "scientific_attempt_control.operation_universe",
            "operation universe arrays are malformed",
        )
        return
    occurrence_by_id = _verify_occurrence_universe(
        payload,
        attempt=attempt,
        universe=universe,
        occurrences=[dict(item) for item in occurrences],
        run_ids=list(run_ids),
        issues=issues,
    )

    dispositions = _record_array(
        control,
        "dispositions",
        fields=_DISPOSITION_FIELDS,
        schema="scientific_operation_disposition@1",
        issues=issues,
    )
    adoptions = _record_array(
        control,
        "adoptions",
        fields=_ADOPTION_FIELDS,
        schema="scientific_effect_adoption@1",
        issues=issues,
    )
    materializations = _record_array(
        control,
        "materializations",
        fields=_MATERIALIZATION_FIELDS,
        schema="scientific_artifact_materialization@1",
        issues=issues,
    )
    if dispositions is None or adoptions is None or materializations is None:
        return
    if (
        selection.get("attempt_id") != attempt_id
        or selection.get("state") != "sealed"
        or not selection.get("sealed_at")
        or selection.get("workflow_contract_digest")
        != attempt.get("workflow_contract_digest")
        or selection.get("operation_universe_digest")
        != universe.get("operation_universe_digest")
        or selection.get("operation_count") != len(occurrence_by_id)
    ):
        _issue(
            issues,
            "scientific_selection_identity_mismatch",
            "scientific_attempt_control.selection",
            "sealed selection does not bind the exact attempt universe",
        )
    if selection.get("disposition_digest") != canonical_digest(dispositions):
        _issue(
            issues,
            "scientific_disposition_digest_mismatch",
            "scientific_attempt_control.selection.disposition_digest",
            "sealed disposition digest does not reproduce",
        )
    if selection.get("adoption_digest") != canonical_digest(adoptions):
        _issue(
            issues,
            "scientific_adoption_digest_mismatch",
            "scientific_attempt_control.selection.adoption_digest",
            "sealed adoption digest does not reproduce",
        )

    disposition_by_operation = _verify_dispositions_and_adoptions(
        payload,
        attempt_id=attempt_id,
        selection_id=selection_id,
        occurrence_by_id=occurrence_by_id,
        dispositions=dispositions,
        adoptions=adoptions,
        contract=contract,
        attempt_scope=str(attempt.get("scope") or ""),
        issues=issues,
    )
    _verify_materializations(
        payload,
        attempt_id=attempt_id,
        selection_id=selection_id,
        run_ids=set(run_ids),
        adoptions=adoptions,
        materializations=materializations,
        issues=issues,
    )
    _verify_closure(
        authorization=authorization,
        attempt=attempt,
        selection=selection,
        disposition_by_operation=disposition_by_operation,
        dispositions=dispositions,
        adoptions=adoptions,
        materializations=materializations,
        closure_request=closure_request,
        closure=closure,
        quiescence=control.get("quiescence"),
        issues=issues,
    )
    if admission.get("envelope_id") != envelope_id:
        _issue(
            issues,
            "scientific_admission_authority_mismatch",
            "scientific_attempt_control.admission_request.envelope_id",
            "admission request does not consume the exact envelope",
        )


def _verify_authority_and_attempt(
    payload: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    admission: Mapping[str, Any],
    attempt: Mapping[str, Any],
    issues: list[VerificationIssue],
) -> ScientificWorkflowContract | None:
    expected_scope = "fault" if payload.get("attempt_kind") == "fault" else "formal"
    contract: ScientificWorkflowContract | None = None
    try:
        resolved = AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
            workflow_id=str(attempt.get("workflow_id") or ""),
            workflow_contract_digest=str(
                attempt.get("workflow_contract_digest") or ""
            ),
            for_new_attempt=True,
        )
        if not isinstance(resolved, ScientificWorkflowContract):
            raise ScientificWorkflowContractError(
                "workflow_contract_historical_read_only",
                "historical contract is not valid selected-chain evidence",
            )
        resolved.scope_policy(ScientificAttemptScope(expected_scope))
        contract = resolved
    except (ScientificWorkflowContractError, ValueError) as exc:
        _issue(
            issues,
            "scientific_workflow_contract_invalid",
            "scientific_attempt_control.attempt.workflow_contract_digest",
            (
                exc.error_code
                if isinstance(exc, ScientificWorkflowContractError)
                else "workflow_contract_scope_unsupported"
            ),
        )
    expected_grant_route = (
        f"/v3/sessions/{attempt.get('session_id')}/"
        "scientific-attempt-authorizations"
    )
    grant_receipts = [
        item
        for item in dict(payload.get("product_path") or {}).get(
            "public_api_receipts"
        )
        or []
        if isinstance(item, dict)
        and item.get("method") == "POST"
        and item.get("route") == expected_grant_route
        and item.get("status_code") == 200
    ]
    common_fields = ("session_id", "task_id", "campaign_id", "workflow_id")
    if (
        attempt.get("root_ref") != f"attempts/{payload.get('attempt_id')}"
        or authorization.get("root_ref") != attempt.get("root_ref")
        or attempt.get("scope") != expected_scope
        or attempt.get("workflow_id") != AOX_SELECTED_CHAIN_WORKFLOW_ID
        or contract is None
        or attempt.get("status") != "closed"
        or admission.get("admission_request_id")
        != attempt.get("admission_request_id")
        or admission.get("envelope_id") != attempt.get("envelope_id")
        or admission.get("scope") != attempt.get("scope")
        or admission.get("workflow_contract_digest")
        != attempt.get("workflow_contract_digest")
        or authorization.get("envelope_id") != attempt.get("envelope_id")
        or expected_scope not in (authorization.get("allowed_scopes") or [])
        or any(
            authorization.get(field) != attempt.get(field)
            or admission.get(field) != attempt.get(field)
            for field in common_fields
        )
        or len(grant_receipts) != 1
    ):
        _issue(
            issues,
            "scientific_attempt_authority_mismatch",
            "scientific_attempt_control.attempt",
            "attempt, admission, root, workflow, and authority identities diverge",
        )
    for field in (
        "requested_effect_classes",
        "reserved_micu",
        "reserved_cost_microunits",
        "reserved_wall_time_seconds",
        "provider_digest",
        "hpc_target_digest",
        "request_digest",
        "idempotency_key",
    ):
        if admission.get(field) != attempt.get(field):
            _issue(
                issues,
                "scientific_admission_attempt_mismatch",
                f"scientific_attempt_control.attempt.{field}",
                "admitted attempt differs from its immutable request",
            )
    requested_effects = attempt.get("requested_effect_classes")
    allowed_effects = authorization.get("allowed_effect_classes")
    if (
        not isinstance(requested_effects, list)
        or not isinstance(allowed_effects, list)
        or not set(requested_effects).issubset(set(allowed_effects))
    ):
        _issue(
            issues,
            "scientific_attempt_effect_authority_invalid",
            "scientific_attempt_control.attempt_authority.allowed_effect_classes",
            "attempt effects exceed the authorization envelope",
        )
    provider_digest = attempt.get("provider_digest")
    hpc_target_digest = attempt.get("hpc_target_digest")
    if provider_digest is not None and provider_digest not in (
        authorization.get("allowed_provider_digests") or []
    ):
        _issue(
            issues,
            "scientific_attempt_provider_authority_invalid",
            "scientific_attempt_control.attempt.provider_digest",
            "attempt provider is not authorized",
        )
    if hpc_target_digest is not None and hpc_target_digest not in (
        authorization.get("allowed_hpc_target_digests") or []
    ):
        _issue(
            issues,
            "scientific_attempt_hpc_authority_invalid",
            "scientific_attempt_control.attempt.hpc_target_digest",
            "attempt HPC target is not authorized",
        )
    ordinal = _integer(attempt.get("ordinal"))
    consumed = _integer(authorization.get("consumed_attempts"))
    maximum = _integer(authorization.get("max_attempts"))
    if (
        ordinal is None
        or consumed is None
        or maximum is None
        or ordinal < 1
        or ordinal != 1
        or consumed != 1
        or maximum != 1
        or authorization.get("status") != "exhausted"
    ):
        _issue(
            issues,
            "scientific_attempt_authority_consumption_invalid",
            "scientific_attempt_control.attempt_authority",
            "attempt ordinal is not covered by durable envelope consumption",
        )
    for reserved_name, maximum_name in (
        ("reserved_micu", "max_micu"),
        ("reserved_cost_microunits", "max_cost_microunits"),
        ("reserved_wall_time_seconds", "max_wall_time_seconds"),
    ):
        reserved = _integer(authorization.get(reserved_name))
        maximum_value = _integer(authorization.get(maximum_name))
        attempt_reserved = _integer(attempt.get(reserved_name))
        if (
            reserved is None
            or maximum_value is None
            or attempt_reserved is None
            or attempt_reserved < 0
            or reserved < attempt_reserved
            or reserved > maximum_value
        ):
            _issue(
                issues,
                "scientific_attempt_resource_authority_invalid",
                f"scientific_attempt_control.attempt_authority.{reserved_name}",
                "attempt resource reservation exceeds its envelope",
            )
    return contract


def _verify_occurrence_universe(
    payload: Mapping[str, Any],
    *,
    attempt: Mapping[str, Any],
    universe: Mapping[str, Any],
    occurrences: list[dict[str, Any]],
    run_ids: list[str],
    issues: list[VerificationIssue],
) -> dict[str, dict[str, Any]]:
    occurrence_by_id: dict[str, dict[str, Any]] = {}
    for index, occurrence in enumerate(occurrences):
        identity = (
            f"scientific_attempt_control.operation_universe.occurrences[{index}]"
        )
        execution = occurrence.get("execution")
        result = occurrence.get("result")
        if (
            set(occurrence) != _OCCURRENCE_FIELDS
            or not isinstance(execution, dict)
            or set(execution) != _EXECUTION_FIELDS
            or (
                result is not None
                and (
                    not isinstance(result, dict)
                    or set(result) != _RESULT_FIELDS
                )
            )
        ):
            _issue(
                issues,
                "scientific_occurrence_schema_invalid",
                identity,
                "operation occurrence does not match the exact schema",
            )
            continue
        operation_id = str(occurrence.get("operation_id") or "")
        if not operation_id or operation_id in occurrence_by_id:
            _issue(
                issues,
                "scientific_occurrence_identity_duplicate",
                identity,
                "operation occurrence identity is empty or duplicated",
            )
            continue
        expected_occurrence_digest = canonical_digest(
            {
                key: value
                for key, value in occurrence.items()
                if key != "occurrence_digest"
            }
        )
        if occurrence.get("occurrence_digest") != expected_occurrence_digest:
            _issue(
                issues,
                "scientific_occurrence_digest_mismatch",
                identity,
                "operation occurrence digest does not reproduce",
            )
        if (
            occurrence.get("attempt_id") != attempt.get("attempt_id")
            or occurrence.get("sandbox_run_id") not in run_ids
            or execution.get("lifecycle_state") != "terminal"
            or execution.get("effect_certainty") == "dispatch_in_doubt"
        ):
            _issue(
                issues,
                "scientific_occurrence_not_closed",
                identity,
                "occurrence is outside the attempt or lacks terminal-known effect",
            )
        if execution.get("terminal_outcome") == "succeeded":
            if (
                not isinstance(result, dict)
                or result.get("terminal_outcome") != "succeeded"
                or result.get("result_handle_id")
                != execution.get("result_handle_ref")
                or result.get("result_digest") != execution.get("result_digest")
                or result.get("artifact_set_digest")
                != execution.get("artifact_set_digest")
            ):
                _issue(
                    issues,
                    "scientific_occurrence_result_mismatch",
                    identity,
                    "successful occurrence lacks its exact immutable result",
                )
        occurrence_by_id[operation_id] = occurrence

    if len(run_ids) != len(set(run_ids)) or run_ids != sorted(run_ids):
        _issue(
            issues,
            "scientific_attempt_run_universe_invalid",
            "scientific_attempt_control.operation_universe.run_ids",
            "attempt run ids must be unique and canonically sorted",
        )
    if (
        universe.get("attempt_id") != attempt.get("attempt_id")
        or universe.get("operation_count") != len(occurrences)
    ):
        _issue(
            issues,
            "scientific_operation_universe_count_mismatch",
            "scientific_attempt_control.operation_universe",
            "operation universe identity or count is inconsistent",
        )
    universe_identity = {
        "attempt_id": attempt.get("attempt_id"),
        "session_id": attempt.get("session_id"),
        "task_id": attempt.get("task_id"),
        "lane_id": attempt.get("lane_id"),
        "campaign_id": attempt.get("campaign_id"),
        "workflow_id": attempt.get("workflow_id"),
        "scope": attempt.get("scope"),
        "run_ids": run_ids,
        "occurrences": occurrences,
    }
    if universe.get("operation_universe_digest") != canonical_digest(
        universe_identity
    ):
        _issue(
            issues,
            "scientific_operation_universe_digest_mismatch",
            "scientific_attempt_control.operation_universe.operation_universe_digest",
            "Host-derived operation universe digest does not reproduce",
        )
    bundle_operations = {
        str(item.get("operation_id") or ""): dict(item)
        for item in payload.get("operations") or []
        if isinstance(item, dict)
        and item.get("scope") == "formal"
        and item.get("canonical_ref_kind") == "controlled_operation"
    }
    if set(bundle_operations) != set(occurrence_by_id):
        _issue(
            issues,
            "scientific_operation_universe_bundle_mismatch",
            "scientific_attempt_control.operation_universe",
            "formal controlled-operation projection differs from the Host universe",
        )
    for operation_id in set(bundle_operations) & set(occurrence_by_id):
        operation = bundle_operations[operation_id]
        occurrence = occurrence_by_id[operation_id]
        if operation.get("status") != occurrence.get("operation_status"):
            _issue(
                issues,
                "scientific_occurrence_status_mismatch",
                f"operations.{operation_id}",
                "AOX operation status differs from canonical occurrence state",
            )
    return occurrence_by_id


def _verify_dispositions_and_adoptions(
    payload: Mapping[str, Any],
    *,
    attempt_id: str,
    selection_id: str,
    occurrence_by_id: Mapping[str, Mapping[str, Any]],
    dispositions: list[dict[str, Any]],
    adoptions: list[dict[str, Any]],
    contract: ScientificWorkflowContract | None,
    attempt_scope: str,
    issues: list[VerificationIssue],
) -> dict[str, dict[str, Any]]:
    disposition_by_operation = {
        str(item.get("operation_id") or ""): item for item in dispositions
    }
    if (
        len(disposition_by_operation) != len(dispositions)
        or set(disposition_by_operation) != set(occurrence_by_id)
    ):
        _issue(
            issues,
            "scientific_disposition_universe_incomplete",
            "scientific_attempt_control.dispositions",
            "every occurrence requires exactly one disposition",
        )
    adoption_by_operation = {
        str(item.get("operation_id") or ""): item for item in adoptions
    }
    adoption_by_role = {
        str(item.get("workflow_role") or ""): item for item in adoptions
    }
    if (
        not adoptions
        or len(adoption_by_operation) != len(adoptions)
        or len(adoption_by_role) != len(adoptions)
    ):
        _issue(
            issues,
            "scientific_adopted_chain_invalid",
            "scientific_attempt_control.adoptions",
            "selected chain must contain unique non-empty roles and operations",
        )
    adopted_disposition_ids = {
        operation_id
        for operation_id, disposition in disposition_by_operation.items()
        if disposition.get("kind") == "adopted"
    }
    if set(adoption_by_operation) != adopted_disposition_ids:
        _issue(
            issues,
            "scientific_adoption_disposition_set_mismatch",
            "scientific_attempt_control.adoptions",
            "adoption set differs from the exact adopted dispositions",
        )
    for operation_id, disposition in disposition_by_operation.items():
        occurrence = occurrence_by_id.get(operation_id)
        if (
            disposition.get("attempt_id") != attempt_id
            or disposition.get("selection_id") != selection_id
        ):
            _issue(
                issues,
                "scientific_disposition_scope_mismatch",
                f"scientific_attempt_control.dispositions.{operation_id}",
                "disposition crossed its exact attempt or selection",
            )
        kind = disposition.get("kind")
        execution = (
            {} if occurrence is None else dict(occurrence.get("execution") or {})
        )
        outcome = execution.get("terminal_outcome")
        certainty = execution.get("effect_certainty")
        if kind == "adopted":
            adoption = adoption_by_operation.get(operation_id)
            if (
                adoption is None
                or adoption.get("workflow_role")
                != disposition.get("workflow_role")
                or outcome != "succeeded"
            ):
                _issue(
                    issues,
                    "scientific_adoption_disposition_mismatch",
                    f"scientific_attempt_control.dispositions.{operation_id}",
                    "adopted disposition lacks its exact successful adoption",
                )
            if contract is not None and occurrence is not None:
                try:
                    compatible_roles = (
                        contract.compatible_roles_for_signature(
                            ScientificAttemptScope(attempt_scope),
                            sdk_module=occurrence.get("sdk_module"),
                            function_name=occurrence.get("function_name"),
                        )
                    )
                except (ScientificWorkflowContractError, ValueError):
                    compatible_roles = ()
                if disposition.get("workflow_role") not in compatible_roles:
                    _issue(
                        issues,
                        "scientific_workflow_role_operation_kind_invalid",
                        (
                            "scientific_attempt_control.dispositions."
                            f"{operation_id}.workflow_role"
                        ),
                        (
                            "adopted role does not match the digest-bound "
                            "operation signature"
                        ),
                    )
        elif kind == "superseded":
            replacement = str(
                disposition.get("replacement_operation_id") or ""
            )
            replacement_disposition = disposition_by_operation.get(replacement)
            if (
                not replacement
                or replacement_disposition is None
                or replacement_disposition.get("kind") != "adopted"
            ):
                _issue(
                    issues,
                    "scientific_supersession_invalid",
                    f"scientific_attempt_control.dispositions.{operation_id}",
                    "superseded occurrence must point to an adopted replacement",
                )
        elif kind == "failed":
            if outcome == "succeeded":
                _issue(
                    issues,
                    "scientific_failed_disposition_invalid",
                    f"scientific_attempt_control.dispositions.{operation_id}",
                    "successful occurrence cannot be disposed as failed",
                )
        elif kind == "abandoned":
            if certainty != "no_effect":
                _issue(
                    issues,
                    "scientific_abandonment_effect_unknown",
                    f"scientific_attempt_control.dispositions.{operation_id}",
                    "abandoned occurrence requires canonical no-effect proof",
                )
        else:
            _issue(
                issues,
                "scientific_disposition_kind_invalid",
                f"scientific_attempt_control.dispositions.{operation_id}",
                "disposition kind is unsupported",
            )
    for operation_id, adoption in adoption_by_operation.items():
        occurrence = occurrence_by_id.get(operation_id)
        execution = (
            {} if occurrence is None else dict(occurrence.get("execution") or {})
        )
        result = (
            {} if occurrence is None else dict(occurrence.get("result") or {})
        )
        if (
            adoption.get("attempt_id") != attempt_id
            or adoption.get("selection_id") != selection_id
            or adoption.get("execution_id") != execution.get("execution_id")
            or adoption.get("result_handle_id")
            != result.get("result_handle_id")
            or adoption.get("result_digest") != result.get("result_digest")
            or adoption.get("artifact_set_digest")
            != result.get("artifact_set_digest")
            or adoption.get("source_sandbox_run_id")
            != (None if occurrence is None else occurrence.get("sandbox_run_id"))
            or adoption.get("effect_certainty")
            not in {"effect_known", "terminal_known"}
        ):
            _issue(
                issues,
                "scientific_adoption_result_mismatch",
                f"scientific_attempt_control.adoptions.{operation_id}",
                "adoption does not bind the exact terminal-known result",
            )
        if (
            occurrence is not None
            and occurrence.get("approval_id") is not None
            and (
                occurrence.get("approval_state") != "approved"
                or adoption.get("approval_digest") is None
            )
        ):
            _issue(
                issues,
                "scientific_adoption_approval_invalid",
                f"scientific_attempt_control.adoptions.{operation_id}",
                "adopted approved effect lacks exact approval authority",
            )
    chain = dict(
        dict(payload.get("scientific_checks") or {}).get("aox_chain") or {}
    )
    role_operations = chain.get("operation_roles")
    if payload.get("attempt_kind") == "positive":
        if not isinstance(role_operations, dict):
            _issue(
                issues,
                "scientific_aox_role_map_missing",
                "scientific_checks.aox_chain.operation_roles",
                "positive @3 attempt requires the exact AOX role map",
            )
        else:
            controlled_operation_ids = {
                str(item.get("operation_id") or "")
                for item in payload.get("operations") or []
                if isinstance(item, dict)
                and item.get("scope") == "formal"
                and item.get("canonical_ref_kind") == "controlled_operation"
            }
            selected_role_operations = {
                str(role): str(operation_id)
                for role, operation_id in role_operations.items()
                if str(operation_id) in controlled_operation_ids
            }
            for role, operation_id in selected_role_operations.items():
                adoption = adoption_by_role.get(str(role))
                if adoption is None or adoption.get("operation_id") != operation_id:
                    _issue(
                        issues,
                        "scientific_aox_role_adoption_mismatch",
                        f"scientific_checks.aox_chain.operation_roles.{role}",
                        "AOX role does not resolve to its unique adopted operation",
                    )
            if (
                set(adoption_by_role) != set(selected_role_operations)
                or set(adoption_by_operation)
                != set(selected_role_operations.values())
            ):
                _issue(
                    issues,
                    "scientific_aox_role_unexpected",
                    "scientific_attempt_control.adoptions",
                    "selected chain differs from the controlled AOX role projection",
                )
    elif contract is not None:
        try:
            allowed_roles = set(
                contract.allowed_roles(
                    ScientificAttemptScope(attempt_scope)
                )
            )
        except (ScientificWorkflowContractError, ValueError):
            allowed_roles = set()
        if any(role not in allowed_roles for role in adoption_by_role):
            _issue(
                issues,
                "scientific_aox_role_unexpected",
                "scientific_attempt_control.adoptions",
                "fault selected chain contains roles outside the AOX contract",
            )
    return disposition_by_operation


def _verify_materializations(
    payload: Mapping[str, Any],
    *,
    attempt_id: str,
    selection_id: str,
    run_ids: set[str],
    adoptions: list[dict[str, Any]],
    materializations: list[dict[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    adoption_by_id = {
        str(item.get("adoption_id") or ""): item for item in adoptions
    }
    artifact_by_id = {
        str(item.get("artifact_id") or ""): dict(item)
        for item in payload.get("artifacts") or []
        if isinstance(item, dict)
    }
    for item in materializations:
        receipt_id = str(item.get("receipt_id") or "")
        adoption = adoption_by_id.get(str(item.get("adoption_id") or ""))
        artifact = artifact_by_id.get(
            str(item.get("source_artifact_id") or "")
        )
        if (
            item.get("attempt_id") != attempt_id
            or item.get("selection_id") != selection_id
            or adoption is None
            or artifact is None
            or item.get("source_sandbox_run_id")
            != adoption.get("source_sandbox_run_id")
            or item.get("target_sandbox_run_id") not in run_ids
            or item.get("source_artifact_digest")
            != artifact.get("content_digest")
            or not str(item.get("boundary_materialization_id") or "")
            or not str(item.get("target_path") or "").startswith(
                "/workspace/input/"
            )
        ):
            _issue(
                issues,
                "scientific_materialization_identity_invalid",
                f"scientific_attempt_control.materializations.{receipt_id}",
                "materialization is not an exact same-attempt Host receipt",
            )


def _verify_closure(
    *,
    authorization: Mapping[str, Any],
    attempt: Mapping[str, Any],
    selection: Mapping[str, Any],
    disposition_by_operation: Mapping[str, Mapping[str, Any]],
    dispositions: list[dict[str, Any]],
    adoptions: list[dict[str, Any]],
    materializations: list[dict[str, Any]],
    closure_request: Mapping[str, Any],
    closure: Mapping[str, Any],
    quiescence: object,
    issues: list[VerificationIssue],
) -> None:
    del disposition_by_operation
    attempt_id = str(attempt.get("attempt_id") or "")
    selection_id = str(selection.get("selection_id") or "")
    if (
        closure_request.get("attempt_id") != attempt_id
        or closure_request.get("selection_id") != selection_id
        or closure.get("closure_request_id")
        != closure_request.get("closure_request_id")
        or closure.get("attempt_id") != attempt_id
        or closure.get("selection_id") != selection_id
        or closure.get("actor_ref") != closure_request.get("actor_ref")
        or closure.get("idempotency_key")
        != closure_request.get("idempotency_key")
    ):
        _issue(
            issues,
            "scientific_closure_identity_mismatch",
            "scientific_attempt_control.closure",
            "closure does not consume the exact agent request and selection",
        )
    expected_closure_request_digest = canonical_digest(
        {
            "command": "scientific.attempt.close",
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "actor_ref": closure_request.get("actor_ref"),
            "idempotency_key": closure_request.get("idempotency_key"),
        }
    )
    if closure_request.get("request_digest") != expected_closure_request_digest:
        _issue(
            issues,
            "scientific_closure_request_digest_mismatch",
            "scientific_attempt_control.closure_request.request_digest",
            "agent closure request digest does not reproduce",
        )
    authority_consumption = {
        "envelope_id": authorization.get("envelope_id"),
        "attempt_id": attempt_id,
        "ordinal": attempt.get("ordinal"),
        "consumed_attempts": authorization.get("consumed_attempts"),
        "reserved_micu": authorization.get("reserved_micu"),
        "reserved_cost_microunits": authorization.get(
            "reserved_cost_microunits"
        ),
        "reserved_wall_time_seconds": authorization.get(
            "reserved_wall_time_seconds"
        ),
        "state_version": authorization.get("state_version"),
    }
    authority_consumption_digest = canonical_digest(authority_consumption)
    materialization_digest = canonical_digest(materializations)
    if (
        closure.get("operation_universe_digest")
        != selection.get("operation_universe_digest")
        or closure.get("disposition_digest") != canonical_digest(dispositions)
        or closure.get("adoption_digest") != canonical_digest(adoptions)
        or closure.get("materialization_digest") != materialization_digest
        or closure.get("authority_consumption_digest")
        != authority_consumption_digest
    ):
        _issue(
            issues,
            "scientific_closure_component_digest_mismatch",
            "scientific_attempt_control.closure",
            "closure component digests do not reproduce",
        )
    if not isinstance(quiescence, dict):
        _issue(
            issues,
            "scientific_quiescence_evidence_missing",
            "scientific_attempt_control.quiescence",
            "closure requires exact Host quiescence evidence",
        )
        return
    try:
        verify_quiescence_evidence_envelope(quiescence)
    except Exception:
        _issue(
            issues,
            "scientific_quiescence_evidence_invalid",
            "scientific_attempt_control.quiescence",
            "Host quiescence receipt or snapshot does not reproduce",
        )
        return
    receipt = quiescence.get("receipt")
    if not isinstance(receipt, dict):
        _issue(
            issues,
            "scientific_quiescence_evidence_invalid",
            "scientific_attempt_control.quiescence.receipt",
            "quiescence receipt is malformed",
        )
        return
    if (
        closure.get("quiescence_receipt_id") != receipt.get("receipt_id")
        or closure.get("quiescence_receipt_digest")
        != receipt.get("receipt_digest")
        or receipt.get("scope_id") != attempt.get("mutation_scope_id")
    ):
        _issue(
            issues,
            "scientific_closure_quiescence_mismatch",
            "scientific_attempt_control.closure.quiescence_receipt_id",
            "closure does not bind the exact quiescence receipt",
        )
    expected_close_request_digest = canonical_digest(
        {
            "command": "scientific.attempt.close",
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "closure_request_id": closure_request.get("closure_request_id"),
            "quiescence_receipt_id": receipt.get("receipt_id"),
            "actor_ref": closure_request.get("actor_ref"),
            "idempotency_key": closure_request.get("idempotency_key"),
        }
    )
    if closure.get("request_digest") != expected_close_request_digest:
        _issue(
            issues,
            "scientific_closure_request_binding_mismatch",
            "scientific_attempt_control.closure.request_digest",
            "Host closure request binding digest does not reproduce",
        )
    closure_payload = {
        "closure_request_id": closure_request.get("closure_request_id"),
        "attempt_id": attempt_id,
        "selection_id": selection_id,
        "operation_universe_digest": selection.get(
            "operation_universe_digest"
        ),
        "disposition_digest": selection.get("disposition_digest"),
        "adoption_digest": selection.get("adoption_digest"),
        "materialization_digest": materialization_digest,
        "authority_consumption_digest": authority_consumption_digest,
        "quiescence_receipt_id": receipt.get("receipt_id"),
        "quiescence_receipt_digest": receipt.get("receipt_digest"),
    }
    if closure.get("closure_digest") != canonical_digest(closure_payload):
        _issue(
            issues,
            "scientific_closure_digest_mismatch",
            "scientific_attempt_control.closure.closure_digest",
            "scientific closure digest does not reproduce",
        )


def _record_array(
    control: Mapping[str, Any],
    key: str,
    *,
    fields: frozenset[str],
    schema: str,
    issues: list[VerificationIssue],
) -> list[dict[str, Any]] | None:
    value = control.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        _issue(
            issues,
            "scientific_attempt_record_array_invalid",
            f"scientific_attempt_control.{key}",
            f"{key} must be an array of canonical records",
        )
        return None
    records = [dict(item) for item in value]
    if any(
        set(item) != fields or item.get("schema_version") != schema
        for item in records
    ):
        _issue(
            issues,
            "scientific_attempt_record_schema_invalid",
            f"scientific_attempt_control.{key}",
            f"{key} contains a record outside its exact schema",
        )
        return None
    return records


def _failed_result(code: str, identity: str, message: str) -> VerificationResult:
    return VerificationResult(
        passed=False,
        bundle_digest=None,
        attempt_id=None,
        attempt_kind=None,
        issues=(
            VerificationIssue(
                code=code,
                identity=identity,
                message=message,
            ),
        ),
    )


def _issue(
    issues: list[VerificationIssue],
    code: str,
    identity: str,
    message: str,
    *,
    expected: object | None = None,
    actual: object | None = None,
) -> None:
    issues.append(
        VerificationIssue(
            code=code,
            identity=identity,
            message=message,
            expected=expected,
            actual=actual,
        )
    )


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "SCIENTIFIC_ATTEMPT_EVIDENCE_SCHEMA_ID",
    "SCIENTIFIC_OPERATION_UNIVERSE_SCHEMA_ID",
    "build_selected_chain_attempt_bundle",
    "verify_selected_chain_attempt_bundle",
]
