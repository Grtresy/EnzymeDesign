from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ..composition import ProductionCompositionFactory
from ..driver import QualificationDriver
from ..driver import materialized_observation_response
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..observation import collect_observation
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent
from ..probes import controlled_observation_rejection_code
from ..probes import decode_controlled_observation


def _provider_envelope(label: str) -> dict[str, object]:
    return {
        "bounded_summary": {
            "record_count": 2,
            "status": "completed",
            "transcript_manifest": {
                "files": ["provider_request.json", "provider_observation.json"],
                "provider_request_id": f"provider_{label}",
            },
        },
        "output_artifact_ids": [],
        "provider_request_id": f"provider_{label}",
        "registered_artifact_ids": [],
        "status": "succeeded",
    }


@pytest.mark.architecture_qualification_scenario(
    scenario_id="wire-contract.provider-envelope-parity",
    family="wire-contract",
    selections=("full", "premerge_subset"),
)
def test_provider_envelope_is_exact_across_direct_durable_and_recovery(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "wire-contract")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        driver.create_session("sess_wire_contract")

        direct_ids = driver.admit_durable_operation(
            session_id="sess_wire_contract",
            scenario_key="wire_direct",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        direct_envelope = _provider_envelope("direct")
        direct_response = materialized_observation_response(
            bounded_result_envelope=direct_envelope,
            backend_handle_ref=None,
        )
        decoded = decode_controlled_observation(
            running,
            execution_id=direct_ids.execution_id,
            response=direct_response,
        )
        assert decoded["materialized_envelope"] == direct_envelope

        nested = deepcopy(direct_response)
        nested["materialized_result"] = {
            "materialized_result": nested["materialized_result"]
        }
        missing = deepcopy(direct_response)
        del missing["safe_summary"]
        unknown = deepcopy(direct_response)
        unknown["unexpected_result_field"] = True
        assert controlled_observation_rejection_code(
            running,
            execution_id=direct_ids.execution_id,
            response=nested,
        ) == "qualification_durable_materialized_result_invalid"
        for invalid in (missing, unknown):
            assert controlled_observation_rejection_code(
                running,
                execution_id=direct_ids.execution_id,
                response=invalid,
            ) == "qualification_durable_observation_invalid"

        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=direct_response,
            ),
        )
        driver.resolve_approval(direct_ids.approval_id)
        assert driver.run_execution_once(
            direct_ids.execution_id,
            worker_id="qualification:wire-direct",
        )["lifecycle_state"] == "result_ready"
        assert driver.run_execution_once(
            direct_ids.execution_id,
            worker_id="qualification:wire-direct",
        )["lifecycle_state"] == "terminal"
        durable_records = driver.canonical_records(direct_ids)

        driver.create_session("sess_wire_recovered")
        recovered_ids = driver.admit_durable_operation(
            session_id="sess_wire_recovered",
            scenario_key="wire_recovered",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        recovered_envelope = _provider_envelope("recovered")
        recovered_response = materialized_observation_response(
            bounded_result_envelope=recovered_envelope,
            backend_handle_ref=None,
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.ACCEPTED,
                effect_attempted=True,
                response=recovered_response,
                error_code="simulated_lost_callback",
            ),
        )
        driver.queue_external(
            "bio.provider_http",
            "reconcile",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                response=recovered_response,
            ),
        )
        driver.resolve_approval(recovered_ids.approval_id)
        assert driver.run_execution_once(
            recovered_ids.execution_id,
            worker_id="qualification:wire-recovered",
        )["lifecycle_state"] == "reconcile_required"
        assert driver.run_execution_once(
            recovered_ids.execution_id,
            worker_id="qualification:wire-recovered",
        )["lifecycle_state"] == "result_ready"
        assert driver.run_execution_once(
            recovered_ids.execution_id,
            worker_id="qualification:wire-recovered",
        )["lifecycle_state"] == "terminal"
        recovered_records = driver.canonical_records(recovered_ids)
        observation = collect_observation(
            running,
            session_ids=("sess_wire_contract", "sess_wire_recovered"),
        )

    assert durable_records["result"]["bounded_result_envelope"] == direct_envelope  # type: ignore[index]
    assert durable_records["operation"]["adapter_result_envelope"] == direct_envelope  # type: ignore[index]
    assert durable_records["operation"]["result_summary"] == direct_envelope[  # type: ignore[index]
        "bounded_summary"
    ]
    assert recovered_records["result"][  # type: ignore[index]
        "bounded_result_envelope"
    ] == recovered_envelope
    assert recovered_records["operation"][  # type: ignore[index]
        "adapter_result_envelope"
    ] == recovered_envelope
    assert recovered_records["operation"]["result_summary"] == (  # type: ignore[index]
        recovered_envelope["bounded_summary"]
    )
    assert_operation_oracle(
        durable_records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=direct_envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    assert_operation_oracle(
        recovered_records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=recovered_envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={
            ("bio.provider_http", "dispatch"): 2,
            ("bio.provider_http", "reconcile"): 1,
        },
        expected_effect_count=2,
    )
    assert_public_authority_absent(observation.payload["public_projection"])
    assert durable_records["tasks"] == []
    assert recovered_records["tasks"] == []
    assert factory.external_effect_ledger.count_effects() == 2
    assert factory.external_effect_ledger.count(operation="dispatch") == 2
    assert factory.external_effect_ledger.count(operation="reconcile") == 1
