from __future__ import annotations

import json

import pytest

from openzyme_host_api.aox_launch_failure import (
    AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID,
    LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID,
    AoxCutoverLaunchError,
    AoxLaunchFailureSchemaError,
    aox_cutover_launch_failure_payload,
    normalize_aox_cutover_launch_failure,
)


def _candidate_occurrence() -> dict[str, object]:
    candidate_id = "aox-config-" + "a" * 32
    return {
        "kind": "config_candidate",
        "phase": "validation",
        "effect_certainty": "no_effect",
        "retry_eligibility": "terminal",
        "reconciliation_required": False,
        "terminal_scope": "config_candidate_occurrence",
        "request_digest": "sha256:" + "b" * 64,
        "idempotency_key": candidate_id,
        "exact_handle": candidate_id,
        "contract_digest": "sha256:" + "c" * 64,
        "candidate_id": candidate_id,
    }


def _runner_occurrence() -> dict[str, object]:
    return {
        "kind": "runner_attestation",
        "tool_id": "bio_tools.mafft",
        "stage": "runner_result",
        "phase": "terminal",
        "effect_certainty": "no_effect",
        "retry_eligibility": "terminal",
        "reconciliation_required": False,
        "terminal_scope": "runner_operation_occurrence",
        "authority_scope": "preparation_only",
        "scientific_attempt_counted": False,
        "runner_run_id": "run_aox_pin_mafft",
        "runner_attempt_receipt_digest": "sha256:" + "d" * 64,
    }


def test_launch_failure_composes_candidate_occurrence_and_schema_cause() -> None:
    private_value = "credential-and-private-config-value"
    error = AoxCutoverLaunchError(
        "aox_launch_effective_config_schema_invalid",
        "safe boundary message",
        details={"private": private_value},
        public_occurrence=_candidate_occurrence(),
        public_cause={
            "kind": "schema_field",
            "identity": "effective_config.reliability.owner_policy",
            "missing": ["enabled"],
        },
    )

    payload = aox_cutover_launch_failure_payload(error)

    assert payload == {
        "schema_id": AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID,
        "status": "failed",
        "failure_code": "aox_launch_effective_config_schema_invalid",
        "failure_occurrence": _candidate_occurrence(),
        "failure_cause": {
            "kind": "schema_field",
            "identity": "effective_config.reliability.owner_policy",
            "missing": ["enabled"],
        },
    }
    assert private_value not in json.dumps(payload)
    assert normalize_aox_cutover_launch_failure(payload) == payload


def test_launch_failure_sanitizes_orthogonal_projections_independently() -> None:
    occurrence = _candidate_occurrence()
    invalid_cause = {
        "kind": "schema_field",
        "identity": "effective_config.llm",
        "private": "credential",
    }
    occurrence_only = aox_cutover_launch_failure_payload(
        AoxCutoverLaunchError(
            "aox_launch_effective_config_schema_invalid",
            "safe",
            public_occurrence=occurrence,
            public_cause=invalid_cause,
        )
    )
    assert occurrence_only["failure_occurrence"] == occurrence
    assert "failure_cause" not in occurrence_only

    cause = {"kind": "sandbox_runtime", "failure_code": "sandbox_image_unavailable"}
    cause_only = aox_cutover_launch_failure_payload(
        AoxCutoverLaunchError(
            "aox_launch_sandbox_preflight_failed",
            "safe",
            public_occurrence={**occurrence, "candidate_id": "private/path"},
            public_cause=cause,
        )
    )
    assert "failure_occurrence" not in cause_only
    assert cause_only["failure_cause"] == cause


@pytest.mark.parametrize(
    "failure_code",
    ["SSH_CONNECTION_TIMEOUT", "transport_connect_failed"],
)
def test_launch_failure_splits_runner_occurrence_from_safe_cause(
    failure_code: str,
) -> None:
    payload = aox_cutover_launch_failure_payload(
        AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_execution_failed",
            "safe",
            public_occurrence=_runner_occurrence(),
            public_cause={"kind": "runner_error", "failure_code": failure_code},
        )
    )

    assert payload["failure_occurrence"] == _runner_occurrence()
    assert payload["failure_cause"] == {
        "kind": "runner_error",
        "failure_code": failure_code,
    }


def test_launch_failure_keeps_unproven_runner_occurrence_without_unsafe_cause() -> None:
    occurrence = {
        **_runner_occurrence(),
        "stage": "runner_call",
        "phase": "allocated",
        "effect_certainty": "unproven",
        "retry_eligibility": "reconcile_required",
        "reconciliation_required": True,
    }
    payload = aox_cutover_launch_failure_payload(
        AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_execution_failed",
            "safe",
            public_occurrence=occurrence,
            public_cause={
                "kind": "runner_error",
                "failure_code": "Private_Path",
            },
        )
    )

    assert payload["failure_occurrence"] == occurrence
    assert "failure_cause" not in payload


def test_launch_failure_legacy_v3_is_read_only_and_not_current() -> None:
    historical = {
        "schema_id": LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID,
        "status": "failed",
        "failure_code": "aox_launch_effective_config_schema_invalid",
        "failure_details": {
            "kind": "schema_field",
            "identity": "effective_config.llm",
        },
    }

    with pytest.raises(AoxLaunchFailureSchemaError):
        normalize_aox_cutover_launch_failure(historical)
    assert (
        normalize_aox_cutover_launch_failure(historical, allow_legacy_v3=True)
        == historical
    )
    assert aox_cutover_launch_failure_payload(
        AoxCutoverLaunchError("aox_launch_unknown", "safe")
    )["schema_id"] == AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID
