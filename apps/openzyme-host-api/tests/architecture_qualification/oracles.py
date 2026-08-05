from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .external_ports import ExternalEffectLedger
from .observation import find_private_projection_fields


PRIVATE_AUTHORITY_FIELDS = frozenset(
    {
        "fencing_token",
        "lease_owner",
        "lease_token",
        "mutation_authority",
        "owner_ref",
        "process_epoch",
        "session_runtime_lease",
    }
)
_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "alternate_route",
        "fallback",
        "fallback_result",
        "fallback_summary",
        "private_authority",
        "synthetic_result",
    }
)
_FORBIDDEN_RESULT_STATUSES = frozenset({"fallback", "recovered", "synthetic"})


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"{label} is not a mapping")
    return value


def _assert_no_fallback_or_private_result(value: object) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold()
            if key in _FORBIDDEN_RESULT_KEYS or key in PRIVATE_AUTHORITY_FIELDS:
                raise AssertionError(f"result exposed forbidden field {raw_key!r}")
            if key == "status" and str(item).casefold() in _FORBIDDEN_RESULT_STATUSES:
                raise AssertionError(f"result used forbidden status {item!r}")
            _assert_no_fallback_or_private_result(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_fallback_or_private_result(item)


def assert_operation_oracle(
    records: Mapping[str, object],
    *,
    expected_lifecycle: str,
    expected_terminal_outcome: str | None,
    expected_approval_count: int = 1,
    expected_envelope: Mapping[str, object] | None = None,
    expected_result_ready_transitions: int | None = None,
    expected_terminal_transitions: int | None = None,
) -> None:
    """Assert allowed canonical outcome and reject cross-layer side effects."""

    execution = _require_mapping(records.get("execution"), label="execution")
    result = _require_mapping(records.get("result"), label="result")
    approvals = records.get("approvals")
    tasks = records.get("tasks")
    events = records.get("events")
    if not isinstance(approvals, list) or len(approvals) != expected_approval_count:
        raise AssertionError("approval cardinality drifted")
    if tasks != []:
        raise AssertionError("runtime mechanics inferred a task business transition")
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise AssertionError("execution events are not a closed list")
    if execution.get("lifecycle_state") != expected_lifecycle:
        raise AssertionError("execution lifecycle left its allowed outcome")
    if execution.get("terminal_outcome") != expected_terminal_outcome:
        raise AssertionError("execution terminal outcome drifted")
    state_versions = [int(item["state_version"]) for item in events]
    if state_versions != list(range(1, len(state_versions) + 1)):
        raise AssertionError("execution event state versions are not contiguous monotonic")
    result_ready_count = sum(
        item.get("lifecycle_state") == "result_ready"
        and item.get("previous_lifecycle_state") != "result_ready"
        for item in events
    )
    terminal_count = sum(
        item.get("lifecycle_state") == "terminal"
        and item.get("previous_lifecycle_state") != "terminal"
        for item in events
    )
    terminal_event_count = sum(
        item.get("lifecycle_state") == "terminal" for item in events
    )
    if (
        expected_result_ready_transitions is not None
        and result_ready_count != expected_result_ready_transitions
    ):
        raise AssertionError("result-ready transition cardinality drifted")
    if (
        expected_terminal_transitions is not None
        and terminal_count != expected_terminal_transitions
    ):
        raise AssertionError("terminal transition cardinality drifted")
    if (
        expected_terminal_transitions is not None
        and terminal_event_count != expected_terminal_transitions
    ):
        raise AssertionError("terminal event cardinality drifted")
    envelope = _require_mapping(
        result.get("bounded_result_envelope"),
        label="bounded result envelope",
    )
    _assert_no_fallback_or_private_result(envelope)
    if expected_envelope is not None and dict(envelope) != dict(expected_envelope):
        raise AssertionError("canonical result envelope drifted")


def assert_effect_ledger_oracle(
    ledger: ExternalEffectLedger,
    *,
    allowed_calls: Mapping[tuple[str, str], int],
    expected_effect_count: int,
) -> None:
    entries = ledger.entries()
    actual_calls = Counter((entry.port_id, entry.operation) for entry in entries)
    if actual_calls != Counter(allowed_calls):
        raise AssertionError(
            f"external call allowlist drifted: actual={dict(actual_calls)!r}"
        )
    if ledger.count_effects() != expected_effect_count:
        raise AssertionError("external effect cardinality drifted")
    if any(entry.port_id not in {port for port, _ in allowed_calls} for entry in entries):
        raise AssertionError("an undeclared external port was called")


def assert_public_authority_absent(public_projection: object) -> None:
    leaks = find_private_projection_fields(
        public_projection,
        forbidden_fields=PRIVATE_AUTHORITY_FIELDS,
    )
    if leaks:
        raise AssertionError(f"public projection exposed private authority: {leaks!r}")


def assert_strategy_neutrality_oracle(
    observations: Mapping[str, Mapping[str, object]],
) -> None:
    """Require ordinary strategy transformations to preserve product meaning.

    The oracle compares canonical outcomes, not exact action traces. A test may
    reorder legal actions, insert reads or prose, continue after a typed safe
    rejection, or split work across bounded turns without matching one script.
    """

    required = {
        "baseline",
        "bounded_turn_split",
        "early_reporting_delegation",
        "inserted_read_and_prose",
        "reordered_safe_actions",
        "safe_rejection_followup",
    }
    if set(observations) != required:
        raise AssertionError("strategy transformation set is not closed")
    baseline = _require_mapping(observations["baseline"], label="baseline")
    expected = {
        "business_outcome": baseline.get("business_outcome"),
        "canonical_task_kinds": baseline.get("canonical_task_kinds"),
        "composition_reachable": baseline.get("composition_reachable"),
        "external_effect_count": baseline.get("external_effect_count"),
    }
    for name in sorted(observations):
        observation = _require_mapping(observations[name], label=name)
        if any(observation.get(key) != value for key, value in expected.items()):
            raise AssertionError(f"{name} changed the canonical product outcome")
        if observation.get("phase_veto_codes") not in ([], ()):
            raise AssertionError(f"{name} was rejected by a strategy phase veto")
        if observation.get("synthetic_reachability") is not False:
            raise AssertionError(f"{name} used synthetic positive reachability")


def assert_world_fidelity_oracle(observation: Mapping[str, object]) -> None:
    """Require the original typed world fact to survive every public wrapper."""

    earliest = observation.get("earliest_typed_cause")
    if not isinstance(earliest, str) or not earliest:
        raise AssertionError("earliest typed cause is absent")
    if observation.get("sealed_terminal_cause") != earliest:
        raise AssertionError("terminal sealing overwrote the earliest typed cause")
    if observation.get("next_decision_visible_cause") != earliest:
        raise AssertionError("the next agent decision could not see the typed cause")
    wrapper_chain = observation.get("wrapper_chain")
    if not isinstance(wrapper_chain, list) or not wrapper_chain:
        raise AssertionError("typed wrapper chain is absent")
    if any(not isinstance(item, str) or not item for item in wrapper_chain):
        raise AssertionError("typed wrapper chain is malformed")
    if observation.get("source_bound") is not True:
        raise AssertionError("failure evidence is not source-bound")
    if observation.get("automatic_recovery_count") != 0:
        raise AssertionError("failure triggered automatic recovery work")
    if observation.get("synthetic_fallback") is not False:
        raise AssertionError("failure used a synthetic fallback")


__all__ = [
    "PRIVATE_AUTHORITY_FIELDS",
    "assert_effect_ledger_oracle",
    "assert_operation_oracle",
    "assert_public_authority_absent",
    "assert_strategy_neutrality_oracle",
    "assert_world_fidelity_oracle",
]
