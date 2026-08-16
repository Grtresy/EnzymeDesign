from __future__ import annotations

from pathlib import Path

from openzyme_domain import SessionStatus

from .composition import QUALIFICATION_WORKSPACE_READINESS_PROVIDER
from .composition import ProductionCompositionFactory
from .composition import assert_production_owner_shape


def _create_session(client, *, session_id: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v3/sessions",
        headers={"Idempotency-Key": f"qualification:create:{session_id}"},
        json={
            "session_id": session_id,
            "project_id": "proj_architecture_qualification",
            "objective": "Observe the production composition without agent work.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_file_backed_production_composition_exposes_real_owners_and_projection(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "production-composition")
    composition = factory.build()

    with composition as running:
        assert running.client is not None
        assert_production_owner_shape(running)
        assert running.dependencies.v3_agent_workspace_readiness_providers == {
            QUALIFICATION_WORKSPACE_READINESS_PROVIDER.provider_id: (
                QUALIFICATION_WORKSPACE_READINESS_PROVIDER
            )
        }
        assert (
            running.dependencies.v3_session_creation_readiness_provider_id
            == QUALIFICATION_WORKSPACE_READINESS_PROVIDER.provider_id
        )
        assert (
            running.dependencies.v3_delegation_readiness_provider_id
            == QUALIFICATION_WORKSPACE_READINESS_PROVIDER.provider_id
        )
        assert QUALIFICATION_WORKSPACE_READINESS_PROVIDER.qualification_fixture_non_cutover
        created = _create_session(
            running.client,
            session_id="sess_qualification_composition",
        )
        workspace = running.client.get(
            "/v3/sessions/sess_qualification_composition/workspace"
        )
        assert workspace.status_code == 200, workspace.text
        with running.dependencies.v3_repository_scope(mode="read") as repositories:
            stored = repositories.sessions.get("sess_qualification_composition")
            tasks = repositories.tasks.list_by_session(
                "sess_qualification_composition"
            )
            events = repositories.durable_events.list_by_session(
                "sess_qualification_composition"
            )
        assert stored is not None
        assert stored.status is SessionStatus.ACTIVE
        assert created["session_id"] == stored.session_id
        assert workspace.json()["session"]["session_id"] == stored.session_id
        assert tasks == []
        assert [event.event_type for event in events] == ["session.created"]
        assert running.durable_supervisor.status()["running"] is True
        assert running.background_runtime.status()["running"] is False

    assert composition.retired is True
    assert composition.durable_supervisor.status()["running"] is False
    assert composition.background_runtime.status()["running"] is False
    assert factory.roots.database_path.is_file()
    assert len(
        {
            factory.roots.artifact_root,
            factory.roots.blob_root,
            factory.roots.sandbox_root,
            factory.roots.workspace_root,
        }
    ) == 4


def test_restart_retires_complete_app_and_rebuilds_over_exact_persistent_roots(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "production-restart")
    first = factory.build()
    with first as running:
        assert running.client is not None
        _create_session(running.client, session_id="sess_qualification_restart")
        first_app_id = id(running.app)
        first_dependencies_id = id(running.dependencies)
        first_provider_id = id(running.repository_provider)

    restarted = factory.restart(first)
    assert restarted.generation == first.generation + 1
    assert id(restarted.app) != first_app_id
    assert id(restarted.dependencies) != first_dependencies_id
    assert id(restarted.repository_provider) != first_provider_id
    assert restarted.roots == first.roots

    with restarted as running:
        assert running.client is not None
        assert_production_owner_shape(running)
        workspace = running.client.get(
            "/v3/sessions/sess_qualification_restart/workspace"
        )
        assert workspace.status_code == 200, workspace.text
        with running.dependencies.v3_repository_scope(mode="read") as repositories:
            stored = repositories.sessions.get("sess_qualification_restart")
            events = repositories.durable_events.list_by_session(
                "sess_qualification_restart"
            )
        assert stored is not None
        assert workspace.json()["session"]["session_id"] == stored.session_id
        assert [event.event_type for event in events] == ["session.created"]

    assert restarted.durable_supervisor.status()["running"] is False


def test_open_existing_rebuilds_after_the_original_factory_is_lost(
    tmp_path: Path,
) -> None:
    root = tmp_path / "production-crash-attach"
    original_factory = ProductionCompositionFactory.create(root)
    original = original_factory.build()
    with original as running:
        assert running.client is not None
        _create_session(running.client, session_id="sess_qualification_attach")

    attached_factory = ProductionCompositionFactory.open_existing(root)
    assert attached_factory is not original_factory
    assert attached_factory.roots == original_factory.roots
    assert attached_factory.external_effect_ledger is not (
        original_factory.external_effect_ledger
    )
    attached = attached_factory.build()
    with attached as running:
        assert running.client is not None
        workspace = running.client.get(
            "/v3/sessions/sess_qualification_attach/workspace"
        )
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()["session"]["session_id"] == (
            "sess_qualification_attach"
        )


def test_owner_shape_rejects_a_fixture_model_factory(tmp_path: Path) -> None:
    from dataclasses import replace

    factory = ProductionCompositionFactory.create(tmp_path / "forbidden-eval-owner")
    composition = factory.build()
    original = composition.dependencies.foundation
    composition.dependencies.foundation = replace(original, model_factory=object())
    try:
        try:
            assert_production_owner_shape(composition)
        except AssertionError as exc:
            assert str(exc) == "qualification installed a model/eval factory"
        else:  # pragma: no cover - clear failure for a guard regression
            raise AssertionError("fixture model factory entered qualification")
    finally:
        composition.dependencies.foundation = original
