from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import (
    canonical_json_document_bytes,
)

from .budgets import QualificationScenarioStatus
from .budgets import ScenarioBudget
from .budgets import ScenarioBudgetTracker
from .composition import ProductionCompositionFactory
from .driver import QualificationDriver
from .observation import QualificationObservationError
from .observation import collect_observation
from .observation import find_private_projection_fields
from .observation import verify_observation_offline


def _create_session(client, session_id: str) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v3/sessions",
        headers={"Idempotency-Key": f"qualification:observe:{session_id}"},
        json={
            "session_id": session_id,
            "project_id": "proj_architecture_qualification",
            "objective": "Observe canonical and public state together.",
        },
    )
    assert response.status_code == 200, response.text


def test_collector_closes_sqlite_files_workers_effects_and_public_projection(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "observation")
    composition = factory.build()
    with composition as running:
        assert running.client is not None
        before = collect_observation(running)
        _create_session(running.client, "sess_qualification_observation")
        (running.roots.artifact_root / "result.bin").write_bytes(b"canonical-result")
        after = collect_observation(
            running,
            session_ids=("sess_qualification_observation",),
        )

    assert before.observation_digest != after.observation_digest
    assert after.counts.row_count > before.counts.row_count
    assert after.counts.event_count > before.counts.event_count
    artifact_files = after.payload["roots"]["artifacts"]["files"]  # type: ignore[index]
    assert artifact_files == [
        {
            "byte_length": len(b"canonical-result"),
            "path": "result.bin",
            "sha256": "sha256:4777603f31ecbb9029746908751650419306bec90b779d58db3f95639ada4477",
        }
    ]
    public = after.payload["public_projection"]
    assert public["sessions"][0]["session_id"] == "sess_qualification_observation"  # type: ignore[index]
    assert find_private_projection_fields(
        public,
        forbidden_fields=frozenset(
            {"mutation_authority", "private_authority", "lease_token"}
        ),
    ) == ()


def test_budget_tracker_never_turns_exhaustion_or_missing_evidence_green(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "budget")
    composition = factory.build()
    with composition as running:
        assert running.client is not None
        before = collect_observation(running)
        budget = ScenarioBudget(
            max_steps=1,
            max_ticks=10,
            max_state_version_delta=10,
            max_event_delta=10,
            max_effect_count=0,
            deadline_seconds=5,
        )
        tracker = ScenarioBudgetTracker(budget=budget, before=before)
        tracker.step(2)
        after = collect_observation(running)
        exceeded = tracker.evaluate(
            after=after,
            allowed_terminal_observed=True,
            evidence_complete=True,
        )
        assert exceeded.status is QualificationScenarioStatus.VIOLATED
        assert exceeded.rejection_reasons == ("max_steps:2>1",)

        unproven_tracker = ScenarioBudgetTracker(budget=budget, before=after)
        unproven = unproven_tracker.evaluate(
            after=after,
            allowed_terminal_observed=True,
            evidence_complete=False,
        )
        assert unproven.status is QualificationScenarioStatus.UNPROVEN
        assert unproven.rejection_reasons == (
            "required_cross_layer_evidence_missing",
        )


def test_offline_observation_verifier_recomputes_bytes_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "offline-observation")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        session_id = "sess_offline_observation"
        driver.create_session(session_id)
        driver.seal_external_input(
            session_id=session_id,
            filename="offline-evidence.json",
            content='{"status":"captured"}\n',
            format="json",
        )
        driver.admit_durable_operation(
            session_id=session_id,
            scenario_key="offline_observation",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        observation = collect_observation(running, session_ids=(session_id,))
        content = canonical_json_document_bytes(observation.payload)

    receipt = verify_observation_offline(
        content,
        expected_observation_digest=observation.observation_digest,
    )
    assert receipt.payload["artifact_digest_count"] > 0  # type: ignore[operator]

    tampered = json.loads(content)
    tampered["roots"]["sandboxes"]["root_digest"] = "sha256:" + "0" * 64
    tampered_content = canonical_json_document_bytes(tampered)
    tampered_digest = "sha256:" + hashlib.sha256(
        canonical_json_bytes(tampered)
    ).hexdigest()
    with pytest.raises(QualificationObservationError, match="root .* digest mismatch"):
        verify_observation_offline(
            tampered_content,
            expected_observation_digest=tampered_digest,
        )


def test_registry_budget_loader_is_closed_and_rejects_boolean() -> None:
    valid = {
        "deadline_seconds": 5,
        "max_effect_count": 1,
        "max_event_delta": 4,
        "max_state_version_delta": 3,
        "max_steps": 2,
        "max_ticks": 2,
    }
    assert ScenarioBudget.from_registry(valid).max_event_delta == 4

    invalid = {**valid, "max_steps": True}
    try:
        ScenarioBudget.from_registry(invalid)
    except ValueError as exc:
        assert str(exc) == "registry scenario budget is not closed integer data"
    else:  # pragma: no cover - fail clearly if bool is silently treated as int
        raise AssertionError("boolean scenario budget was accepted")
