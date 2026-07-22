from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_domain import ArtifactKind

from ..composition import ProductionCompositionFactory
from ..driver import QualificationDriver
from ..driver import materialized_observation_response
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..observation import collect_observation
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent
from ..probes import probe_identity_semantics


def _artifact_ref(record: dict[str, object]) -> dict[str, str]:
    metadata = record["metadata"]
    if not isinstance(metadata, dict):
        raise AssertionError("qualification artifact metadata is absent")
    digest = str(
        metadata.get("sealed_digest")
        or metadata.get("content_digest")
        or metadata.get("tree_digest")
        or metadata.get("source_tree_digest")
        or ""
    )
    return {
        "artifact_digest": digest,
        "artifact_id": str(record["artifact_id"]),
        "kind": str(record["kind"]),
        "relative_path": str(record["relative_path"]),
    }


@pytest.mark.architecture_qualification_scenario(
    scenario_id="identity-semantics.member-set-versus-ordered",
    family="identity-semantics",
    selections=("full", "premerge_subset"),
)
def test_member_set_identity_is_order_insensitive_but_ordered_digest_is_not(
    tmp_path: Path,
) -> None:
    probe = probe_identity_semantics()
    assert probe.member_set_digest_forward == probe.member_set_digest_reverse
    assert probe.ordered_digest_forward != probe.ordered_digest_reverse
    assert probe.duplicate_member_rejected is True

    factory = ProductionCompositionFactory.create(tmp_path / "identity-semantics")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        session_id = "sess_identity_semantics"
        driver.create_session(session_id)
        member_a = driver.seal_external_input(
            session_id=session_id,
            filename="member_a.json",
            content='{"member":"a"}\n',
            format="json",
        )
        member_b = driver.seal_external_input(
            session_id=session_id,
            filename="member_b.json",
            content='{"member":"b"}\n',
            format="json",
        )
        refs = (_artifact_ref(member_a), _artifact_ref(member_b))
        expected_set_digest = controlled_operation_artifact_set_digest(
            tuple(
                ControlledOperationResultArtifactRef(
                    artifact_id=item["artifact_id"],
                    kind=ArtifactKind(item["kind"]),
                    relative_path=item["relative_path"],
                    artifact_digest=item["artifact_digest"],
                )
                for item in refs
            )
        )
        reversed_refs = tuple(reversed(refs))
        ids = driver.admit_durable_operation(
            session_id=session_id,
            scenario_key="identity_reverse",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        ordered_artifact_ids = [item["artifact_id"] for item in reversed_refs]
        envelope = {
            "bounded_summary": {
                "artifact_count": len(ordered_artifact_ids),
                "ordered_artifact_ids": ordered_artifact_ids,
                "status": "completed",
            },
            "output_artifact_ids": ordered_artifact_ids,
            "registered_artifact_ids": ordered_artifact_ids,
            "status": "succeeded",
        }
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=materialized_observation_response(
                    bounded_result_envelope=envelope,
                    backend_handle_ref=None,
                    artifact_refs=reversed_refs,
                ),
            ),
        )
        driver.resolve_approval(ids.approval_id)
        assert driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:identity:reverse",
        )["lifecycle_state"] == "result_ready"
        assert driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:identity:reverse",
        )["lifecycle_state"] == "terminal"
        records = driver.canonical_records(ids)
        observation = collect_observation(running, session_ids=(session_id,))

    assert records["result"]["artifact_set_digest"] == expected_set_digest  # type: ignore[index]
    assert [
        item["artifact_id"]
        for item in records["result_artifacts"]  # type: ignore[union-attr]
    ] == sorted(item["artifact_id"] for item in refs)
    assert records["result"]["bounded_result_envelope"] == envelope  # type: ignore[index]
    assert_operation_oracle(
        records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={("bio.provider_http", "dispatch"): 1},
        expected_effect_count=1,
    )
    assert_public_authority_absent(observation.payload["public_projection"])
