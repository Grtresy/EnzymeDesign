from __future__ import annotations

import json

import pytest

from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationWriterKind
from openzyme_runtime import ControlledOperationOwnerPolicy
from openzyme_runtime import MutationClosureMode
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import ReliabilityShadowObserver
from openzyme_runtime import RuntimeDrainContract
from openzyme_runtime import ShadowObservabilityMode


def test_default_reliability_gates_preserve_legacy_dispatch() -> None:
    settings = ReliabilityRefactorSettings()

    assert settings.owner_mode_for_route("execution.pipeline.run") is (
        ControlledOperationOwnerMode.LEGACY_SYNC
    )
    assert settings.shadow_observability is ShadowObservabilityMode.DISABLED
    assert settings.runtime_drain_contract is RuntimeDrainContract.COMMAND_V1
    assert settings.mutation_closure_mode is MutationClosureMode.LEGACY_V1


def test_durable_owner_admission_is_an_exact_frozen_route_policy() -> None:
    settings = ReliabilityRefactorSettings(
        controlled_operation_owner_policy=(
            ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
        ),
        durable_execution_route_allowlist=("execution.pipeline.run",),
    )

    assert settings.owner_mode_for_route("execution.pipeline.run") is (
        ControlledOperationOwnerMode.DURABLE_ASYNC_V1
    )
    assert settings.owner_mode_for_route("execution.pipeline.run.extra") is (
        ControlledOperationOwnerMode.LEGACY_SYNC
    )
    with pytest.raises(ValueError, match="route_policy_id"):
        settings.owner_mode_for_route(" unsafe route ")


def test_reliability_settings_reject_unknown_or_unbounded_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY",
        "guess_what_works",
    )
    with pytest.raises(ValueError, match="must be one of"):
        ReliabilityRefactorSettings.from_env()

    monkeypatch.delenv(
        "OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY",
        raising=False,
    )
    monkeypatch.setenv("OPENZYME_RELIABILITY_SHADOW_MAX_OBSERVATIONS", "4097")
    with pytest.raises(ValueError, match="between 1 and 4096"):
        ReliabilityRefactorSettings.from_env()


def test_reliability_config_digest_covers_authority_fields() -> None:
    baseline = ReliabilityRefactorSettings()
    changed = ReliabilityRefactorSettings(
        controlled_operation_owner_policy=(
            ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
        ),
        durable_execution_route_allowlist=("execution.pipeline.run",),
    )

    assert baseline.config_digest.startswith("sha256:")
    assert baseline.config_digest != changed.config_digest


def test_disabled_shadow_observer_is_a_behavior_neutral_noop() -> None:
    observer = ReliabilityShadowObserver(ReliabilityRefactorSettings())

    observer.observe_approval_wait(
        operation_id="op-secret",
        elapsed_ms=5,
        resolution="approved",
    )

    assert observer.enabled is False
    assert observer.snapshot() == ()


def test_shadow_observer_is_bounded_closed_and_identifier_safe() -> None:
    observer = ReliabilityShadowObserver(
        ReliabilityRefactorSettings(
            shadow_observability=ShadowObservabilityMode.SHADOW_V1,
            shadow_max_observations=3,
        )
    )

    observer.observe_approval_wait(
        operation_id="op-secret-canary",
        elapsed_ms=90_000_000,
        resolution="approved",
    )
    observer.observe_runtime_authority_hold(
        signal_id="signal-secret-canary",
        signal_hold_ms=10,
        session_lease_hold_ms=11,
    )
    observer.observe_runner_phase_effect(
        operation_id="runner-secret-canary",
        phase="dispatch",
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
    )
    observer.observe_mutation_writer_category(
        scope_id="scope-secret-canary",
        writer_kind=MutationWriterKind.ATTEMPT_DRIVER,
        admitted=True,
    )
    observer.observe_public_redaction(
        projection_name="controlled_operation",
        removed_field_count=4,
        residual_private_marker_detected=False,
    )

    snapshot = observer.snapshot()
    encoded = json.dumps(snapshot, sort_keys=True)
    assert observer.enabled is True
    assert len(snapshot) == 3
    assert [item["sequence"] for item in snapshot] == [3, 4, 5]
    assert all(str(item["subject_digest"]).startswith("sha256:") for item in snapshot)
    assert "secret-canary" not in encoded
    assert "retry" not in encoded
    assert snapshot[0]["dimensions"] == {
        "phase": "dispatch",
        "effect_certainty": "dispatch_in_doubt",
    }


@pytest.mark.parametrize(
    ("method_name", "kwargs", "error"),
    [
        (
            "observe_approval_wait",
            {"operation_id": "op", "elapsed_ms": 0, "resolution": "maybe"},
            "not closed",
        ),
        (
            "observe_runner_phase_effect",
            {
                "operation_id": "op",
                "phase": "magic",
                "effect_certainty": ExternalEffectCertainty.NO_EFFECT,
            },
            "phase is not closed",
        ),
        (
            "observe_public_redaction",
            {
                "projection_name": "unsafe projection",
                "removed_field_count": 0,
                "residual_private_marker_detected": False,
            },
            "projection_name is invalid",
        ),
    ],
)
def test_shadow_observer_rejects_open_dimensions(
    method_name: str,
    kwargs: dict[str, object],
    error: str,
) -> None:
    observer = ReliabilityShadowObserver(
        ReliabilityRefactorSettings(
            shadow_observability=ShadowObservabilityMode.SHADOW_V1
        )
    )

    with pytest.raises(ValueError, match=error):
        getattr(observer, method_name)(**kwargs)
