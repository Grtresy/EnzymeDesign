from __future__ import annotations

from copy import deepcopy

import pytest

from .external_ports import ControlledPortOutcome
from .external_ports import EffectAcceptance
from .external_ports import ExternalEffectLedger
from .oracles import assert_effect_ledger_oracle
from .oracles import assert_operation_oracle
from .oracles import assert_public_authority_absent


def _records() -> dict[str, object]:
    return {
        "approvals": [{"approval_id": "appr_oracle"}],
        "events": [
            {
                "lifecycle_state": "awaiting_approval",
                "previous_lifecycle_state": None,
                "state_version": 1,
            },
            {
                "lifecycle_state": "result_ready",
                "previous_lifecycle_state": "awaiting_approval",
                "state_version": 2,
            },
            {
                "lifecycle_state": "result_ready",
                "previous_lifecycle_state": "result_ready",
                "state_version": 3,
            },
            {
                "lifecycle_state": "terminal",
                "previous_lifecycle_state": "result_ready",
                "state_version": 4,
            },
        ],
        "execution": {
            "lifecycle_state": "terminal",
            "terminal_outcome": "succeeded",
        },
        "result": {
            "bounded_result_envelope": {
                "output_artifact_ids": [],
                "status": "succeeded",
            }
        },
        "tasks": [],
    }


def test_cross_layer_oracles_accept_closed_outcome_and_exact_effects() -> None:
    records = _records()
    assert_operation_oracle(
        records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    ledger = ExternalEffectLedger()
    ledger.append(
        port_id="bio.provider_http",
        operation="dispatch",
        request={"request": "qualified"},
        outcome=ControlledPortOutcome(
            acceptance=EffectAcceptance.TERMINAL,
            effect_attempted=True,
            response={"status": "completed"},
        ),
    )
    assert_effect_ledger_oracle(
        ledger,
        allowed_calls={("bio.provider_http", "dispatch"): 1},
        expected_effect_count=1,
    )
    assert_public_authority_absent({"result": {"status": "succeeded"}})


@pytest.mark.parametrize(
    "mutation",
    ["approval", "task", "fallback", "private", "extra-terminal"],
)
def test_operation_oracle_rejects_forbidden_cross_layer_outcomes(
    mutation: str,
) -> None:
    records = deepcopy(_records())
    if mutation == "approval":
        records["approvals"].append({"approval_id": "appr_extra"})  # type: ignore[union-attr]
    elif mutation == "task":
        records["tasks"] = [{"status": "completed"}]
    elif mutation == "fallback":
        records["result"]["bounded_result_envelope"]["status"] = "recovered"  # type: ignore[index]
    elif mutation == "private":
        records["result"]["bounded_result_envelope"]["lease_token"] = "secret"  # type: ignore[index]
    else:
        records["events"].append(  # type: ignore[union-attr]
            {
                "lifecycle_state": "terminal",
                "previous_lifecycle_state": "terminal",
                "state_version": 5,
            }
        )
    with pytest.raises(AssertionError):
        assert_operation_oracle(
            records,
            expected_lifecycle="terminal",
            expected_terminal_outcome="succeeded",
            expected_result_ready_transitions=1,
            expected_terminal_transitions=1,
        )


def test_effect_and_projection_oracles_reject_fallback_and_private_authority() -> None:
    ledger = ExternalEffectLedger()
    ledger.append(
        port_id="bio.provider_http",
        operation="fallback",
        request={"request": "unexpected"},
        outcome=ControlledPortOutcome(
            acceptance=EffectAcceptance.TERMINAL,
            effect_attempted=True,
            response={"status": "completed"},
        ),
    )
    with pytest.raises(AssertionError):
        assert_effect_ledger_oracle(
            ledger,
            allowed_calls={("bio.provider_http", "dispatch"): 1},
            expected_effect_count=1,
        )
    with pytest.raises(AssertionError):
        assert_public_authority_absent({"lease_token": "private"})
