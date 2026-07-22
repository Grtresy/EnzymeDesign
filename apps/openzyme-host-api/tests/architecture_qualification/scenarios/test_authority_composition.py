from __future__ import annotations

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
from ..probes import probe_authority_composition
from ..probes import probe_execution_delivery_authority


@pytest.mark.architecture_qualification_scenario(
    scenario_id="authority-composition.typed-host-gateway",
    family="authority-composition",
    selections=("full", "premerge_subset"),
)
def test_host_gateway_rejects_stale_and_caller_supplied_authority(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "authority-composition")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        driver.create_session("sess_authority_composition")
        probe = probe_authority_composition(
            running,
            session_id="sess_authority_composition",
        )

        driver.create_session("sess_authority_execution")
        execution_ids = driver.admit_durable_operation(
            session_id="sess_authority_execution",
            scenario_key="authority_execution",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        driver.resolve_approval(execution_ids.approval_id)

        driver.create_session("sess_authority_delivery")
        delivery_ids = driver.admit_durable_operation(
            session_id="sess_authority_delivery",
            scenario_key="authority_delivery",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
            attached_process=True,
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=materialized_observation_response(
                    bounded_result_envelope={
                        "bounded_summary": {"status": "completed"},
                        "output_artifact_ids": [],
                        "registered_artifact_ids": [],
                        "status": "succeeded",
                    },
                    backend_handle_ref=None,
                ),
            ),
        )
        driver.resolve_approval(delivery_ids.approval_id)
        delivery_result = driver.run_execution_once(
            delivery_ids.execution_id,
            worker_id="qualification:authority-delivery-result",
        )
        assert delivery_result["lifecycle_state"] == "result_ready"
        execution_delivery_probe = probe_execution_delivery_authority(
            running,
            execution_id=execution_ids.execution_id,
            delivery_continuation_id=delivery_ids.continuation_id,
        )
        delivery_records = driver.canonical_records(delivery_ids)
        observation = collect_observation(
            running,
            session_ids=(
                "sess_authority_composition",
                "sess_authority_delivery",
                "sess_authority_execution",
            ),
        )

    assert probe.process_authority_succeeded is True
    assert probe.stale_turn_authority_rejected is True
    assert probe.caller_authority_rejected is True
    assert probe.continuation_fencing_token == probe.launching_fencing_token + 1
    assert probe.persisted_objective == (
        "continued under typed sandbox-process authority"
    )
    assert execution_delivery_probe.execution_authority_succeeded is True
    assert execution_delivery_probe.stale_execution_authority_rejected is True
    assert execution_delivery_probe.delivery_authority_succeeded is True
    assert execution_delivery_probe.mixed_delivery_authority_rejected is True
    assert execution_delivery_probe.execution_fencing_token == 1
    assert execution_delivery_probe.delivery_fencing_token == 1
    assert_operation_oracle(
        delivery_records,
        expected_lifecycle="result_ready",
        expected_terminal_outcome=None,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=0,
    )
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={("bio.provider_http", "dispatch"): 1},
        expected_effect_count=1,
    )
    assert_public_authority_absent(observation.payload["public_projection"])
    assert factory.external_effect_ledger.count_effects() == 1
    assert factory.external_effect_ledger.count(operation="dispatch") == 1
