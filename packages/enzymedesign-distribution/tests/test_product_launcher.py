from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient
import pytest

from test_resident_product_loop import _build_launcher as _build_real_launcher
from test_resident_product_loop import _initialize_file_store
from enzymedesign_distribution import launcher as launcher_module
from enzymedesign_distribution.launcher import ENZYMEDESIGN_LAUNCHER_SCHEMA_VERSION
from enzymedesign_distribution.launcher import EnzymeDesignHostLauncher
from enzymedesign_distribution.launcher import EnzymeDesignLauncherError
from enzymedesign_distribution.launcher import EnzymeDesignLauncherPreflightReceipt
from enzymedesign_distribution.launcher import EnzymeDesignProductLifecycleState
from enzymedesign_distribution.launcher import EnzymeDesignProductWorkerBounds
from enzymedesign_distribution.launcher import load_enzymedesign_launcher_config
from openzyme_contracts import canonical_sha256_digest
from openzyme_host_api import HostSecurityPolicy
from openzyme_store_sqlite import SQLiteControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _config_payload(database_path: Path) -> dict[str, object]:
    return {
        "schema_version": ENZYMEDESIGN_LAUNCHER_SCHEMA_VERSION,
        "database_path": str(database_path),
        "component_factory": {
            "locator": "deployment.enzymedesign:create_launcher",
            "factory_id": "deployment.enzymedesign.factory",
            "factory_digest": _digest("deployment-enzymedesign-factory"),
            "configuration": {"project_config_path": "/configuration/projects.json"},
        },
        "worker_bounds": {
            "poll_interval_seconds": 0.5,
            "maximum_sessions_per_tick": 8,
            "maximum_provisioning_per_session": 2,
            "maximum_runtime_commands_per_session": 3,
            "shutdown_timeout_seconds": 3,
        },
        "server": {"host": "127.0.0.1", "port": 8766},
    }


def test_launcher_config_is_closed_absolute_and_bounded(tmp_path: Path) -> None:
    database_path = tmp_path / "enzymedesign.sqlite3"
    config_path = tmp_path / "enzymedesign-launcher.json"
    payload = _config_payload(database_path)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_enzymedesign_launcher_config(config_path)

    assert config.database_path == database_path
    assert config.factory_locator == "deployment.enzymedesign:create_launcher"
    assert config.worker_bounds.maximum_provisioning_per_session == 2
    assert dict(config.component_configuration) == {
        "project_config_path": "/configuration/projects.json"
    }

    payload["implicit_provider_fallback"] = True
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EnzymeDesignLauncherError) as unknown:
        load_enzymedesign_launcher_config(config_path)
    assert unknown.value.code == "enzymedesign_launcher_config_keys_invalid"

    with pytest.raises(EnzymeDesignLauncherError) as relative:
        load_enzymedesign_launcher_config(Path("enzymedesign-launcher.json"))
    assert relative.value.code == "enzymedesign_launcher_config_path_invalid"


def test_factory_identity_drift_fails_before_factory_or_store_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "identity-drift.sqlite3"
    config_path = tmp_path / "enzymedesign-launcher.json"
    config_path.write_text(
        json.dumps(_config_payload(database_path)),
        encoding="utf-8",
    )
    config = load_enzymedesign_launcher_config(config_path)
    calls: list[str] = []

    def wrong_factory(_config):  # noqa: ANN001, ANN202
        calls.append("factory")
        raise AssertionError("identity drift must fail before factory invocation")

    wrong_factory.factory_id = "deployment.enzymedesign.drifted"  # type: ignore[attr-defined]
    wrong_factory.factory_digest = _digest("drifted-factory")  # type: ignore[attr-defined]
    module = SimpleNamespace(create_launcher=wrong_factory)
    monkeypatch.setattr(
        launcher_module.importlib,
        "import_module",
        lambda _module_name: module,
    )

    with pytest.raises(EnzymeDesignLauncherError) as caught:
        launcher_module._load_launcher(config)

    assert caught.value.code == "enzymedesign_launcher_factory_identity_drift"
    assert caught.value.mutation_applied is False
    assert caught.value.fallback_performed is False
    assert calls == []
    assert not database_path.exists()


def _load_real_launcher_config(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured_path: Path,
    actual_path: Path,
) -> tuple[object, object, list[int]]:
    connection, seed, wheel_digest = _initialize_file_store(actual_path)
    launcher, _, _ = _build_real_launcher(
        connection,
        seed=seed,
        wheel_digest=wheel_digest,
    )
    observed_changes_on_close: list[int] = []

    def close_store() -> None:
        observed_changes_on_close.append(connection.total_changes)
        connection.close()

    launcher.close_callback = close_store
    config_path = tmp_path / f"launcher-{configured_path.name}.json"
    config_path.write_text(
        json.dumps(_config_payload(configured_path)),
        encoding="utf-8",
    )
    config = load_enzymedesign_launcher_config(config_path)

    def create_launcher(factory_config):  # noqa: ANN001, ANN202
        launcher.database_path = factory_config.database_path
        launcher.worker_bounds = factory_config.worker_bounds
        return launcher

    create_launcher.factory_id = config.expected_factory_id  # type: ignore[attr-defined]
    create_launcher.factory_digest = config.expected_factory_digest  # type: ignore[attr-defined]
    real_import_module = launcher_module.importlib.import_module
    monkeypatch.setattr(
        launcher_module.importlib,
        "import_module",
        lambda module_name: (
            SimpleNamespace(create_launcher=create_launcher)
            if module_name == "deployment.enzymedesign"
            else real_import_module(module_name)
        ),
    )
    return config, launcher, observed_changes_on_close


def test_launcher_preflight_binds_exact_file_store_and_runtime_identities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "exact-preflight.sqlite3"
    config, launcher, observed_changes = _load_real_launcher_config(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        configured_path=database_path,
        actual_path=database_path,
    )
    before = launcher.runtime.store.connection.total_changes

    loaded = launcher_module._load_launcher(config)
    receipt = loaded.preflight_receipt

    assert loaded is launcher
    assert launcher.runtime.store.connection.total_changes == before
    assert receipt.database_path == str(database_path.resolve())
    assert receipt.file_backed is True
    assert receipt.store_provider_id == "openzyme.store.sqlite"
    assert receipt.active_epoch_id == launcher.runtime.active_epoch_id
    assert receipt.active_release_digest == launcher.runtime.active_release_digest
    assert receipt.activation_digest == launcher.runtime.activation_digest
    assert receipt.extension_bundle_digest == (launcher.runtime.extension_bundle_digest)
    assert receipt.declared_tool_catalog_digest == (
        launcher.runtime.declared_tool_catalog_digest
    )
    assert receipt.adapter_runtime_digest == launcher.runtime.adapter_runtime_digest
    assert receipt.runtime_proof_digest == launcher.runtime.proof_digest
    assert receipt.workflow_registry_snapshot_digest == (
        launcher.runtime.workflow_registry_snapshot_digest
    )
    assert receipt.role_policy_digest == launcher.runtime.role_policy_digest
    assert receipt.workspace_adapter_binding_digest == (
        launcher.runtime.workspace_adapter_binding_digest
    )
    payload = receipt.to_dict()
    assert payload["schema_version"] == "enzymedesign_launcher_preflight@1"
    assert payload["receipt_digest"] == receipt.receipt_digest
    assert payload["fallback_performed"] is False

    launcher.close()
    assert observed_changes == [before]


@pytest.mark.parametrize("drift", ("memory", "mismatched_path", "attached"))
def test_launcher_store_identity_drift_closes_without_mutation_or_fallback(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_path = tmp_path / f"configured-{drift}.sqlite3"
    actual_path = (
        Path(":memory:")
        if drift == "memory"
        else (
            tmp_path / "actual-mismatched.sqlite3"
            if drift == "mismatched_path"
            else configured_path
        )
    )
    config, launcher, observed_changes = _load_real_launcher_config(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        configured_path=configured_path,
        actual_path=actual_path,
    )
    connection = launcher.runtime.store.connection
    if drift == "attached":
        connection.execute(
            "ATTACH DATABASE ? AS unexpected",
            (str(tmp_path / "unexpected.sqlite3"),),
        )
    before = connection.total_changes

    with pytest.raises(EnzymeDesignLauncherError) as caught:
        launcher_module._load_launcher(config)

    assert caught.value.code == "enzymedesign_launcher_store_identity_drift"
    assert caught.value.effect_certainty == "no_effect"
    assert caught.value.mutation_applied is False
    assert caught.value.fallback_performed is False
    assert launcher.state is EnzymeDesignProductLifecycleState.STOPPED
    assert observed_changes == [before]


@pytest.mark.parametrize(
    "drift",
    ("route_catalog", "workflow_registry_object", "runtime_admission_policy"),
)
def test_launcher_runtime_execution_identity_drift_closes_without_mutation(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / f"runtime-{drift}.sqlite3"
    config, launcher, observed_changes = _load_real_launcher_config(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        configured_path=database_path,
        actual_path=database_path,
    )
    runtime = launcher.runtime
    frozen_identity = (
        runtime.workflow_registry_snapshot_digest,
        runtime.role_policy_digest,
        runtime.runtime_admission_identity_digest,
    )
    if drift == "route_catalog":
        object.__setattr__(
            runtime,
            "composition",
            replace(
                runtime.composition,
                route_catalog=replace(
                    runtime.composition.route_catalog,
                    catalog_digest=_digest("drifted-route-catalog"),
                ),
            ),
        )
    elif drift == "workflow_registry_object":
        workflow_registry_substitute = SimpleNamespace(
            distribution_id=runtime.workflow_registry.distribution_id,
            registry_id=runtime.workflow_registry.registry_id,
            registry_snapshot_digest=(
                runtime.workflow_registry.registry_snapshot_digest
            ),
            resolve=runtime.workflow_registry.resolve,
        )
        object.__setattr__(
            runtime,
            "workflow_registry",
            workflow_registry_substitute,
        )
        object.__setattr__(
            runtime.coordination.message_ingress,
            "_workflow_registry",
            workflow_registry_substitute,
        )
    else:
        runtime.runtime_admission.subject_policy_decisions_by_role = {
            role: decisions
            for role, decisions in (
                runtime.runtime_admission.subject_policy_decisions_by_role.items()
            )
            if role != "master"
        }
    before = runtime.store.connection.total_changes

    with pytest.raises(EnzymeDesignLauncherError) as caught:
        launcher_module._load_launcher(config)

    assert caught.value.code == "enzymedesign_launcher_runtime_identity_drift"
    assert caught.value.effect_certainty == "no_effect"
    assert caught.value.mutation_applied is False
    assert caught.value.fallback_performed is False
    assert (
        runtime.workflow_registry_snapshot_digest,
        runtime.role_policy_digest,
        runtime.runtime_admission_identity_digest,
    ) == frozen_identity
    assert launcher.state is EnzymeDesignProductLifecycleState.STOPPED
    assert observed_changes == [before]


def test_preflight_cli_prints_only_the_structured_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "cli-preflight.sqlite3"
    config_path = tmp_path / "cli-preflight.json"
    config_path.write_text(
        json.dumps(_config_payload(database_path)),
        encoding="utf-8",
    )
    receipt = EnzymeDesignLauncherPreflightReceipt(
        database_path=str(database_path),
        store_provider_id="openzyme.store.sqlite",
        store_provider_contract_digest=(SQLiteControlStore.provider_contract_digest),
        store_identity_digest=_digest("store-identity"),
        active_epoch_id="enzymedesign-active-1",
        active_release_digest=_digest("release"),
        activation_digest=_digest("activation"),
        extension_bundle_digest=_digest("extension-bundle"),
        declared_tool_catalog_digest=_digest("declared-tool-catalog"),
        adapter_runtime_digest=_digest("adapter-runtime"),
        runtime_proof_digest=_digest("runtime-proof"),
        workflow_registry_snapshot_digest=_digest("workflow-registry"),
        role_policy_digest=_digest("role-policy"),
        workspace_adapter_binding_digest=_digest("workspace-adapter"),
        file_backed=True,
    )
    started: list[bool] = []
    closed: list[bool] = []
    launcher = SimpleNamespace(
        preflight_receipt=receipt,
        start=lambda **_kwargs: started.append(True),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(
        launcher_module,
        "_load_launcher",
        lambda _config: launcher,
    )

    launcher_module.main(["--config", str(config_path), "preflight"])

    output = capsys.readouterr()
    assert json.loads(output.out) == receipt.to_dict()
    assert output.err == ""
    assert started == []
    assert closed == [True]


@dataclass(slots=True)
class _Worker:
    signalled: Event | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    def tick(self, *, session_id: str, maximum: int) -> tuple[object, ...]:
        self.calls.append((session_id, maximum))
        if self.signalled is not None:
            self.signalled.set()
        return (object(),)


@dataclass(slots=True)
class _Connection:
    retired: list[str]

    def close(self) -> None:
        self.retired.append("store")


@dataclass(slots=True)
class _Records:
    connection: _Connection
    session_ids: tuple[str, ...]

    def list_session_ids(
        self,
        *,
        after_session_id: str | None,
        max_items: int,
    ) -> tuple[str, ...]:
        return tuple(
            session_id
            for session_id in sorted(self.session_ids)
            if after_session_id is None or session_id > after_session_id
        )[:max_items]


def _launcher(
    *,
    provisioning: _Worker,
    runtime_worker: _Worker,
    retired: list[str],
    bounds: EnzymeDesignProductWorkerBounds,
) -> EnzymeDesignHostLauncher:
    app = FastAPI()

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    store = _Records(
        connection=_Connection(retired),
        session_ids=("session-b", "session-a"),
    )
    launcher = EnzymeDesignHostLauncher(
        runtime=SimpleNamespace(
            startup=SimpleNamespace(gate=SimpleNamespace(active_epoch=object())),
            store=store,
            workspace_provisioning_lifecycle_worker=provisioning,
            runtime_worker=runtime_worker,
        ),  # type: ignore[arg-type]
        security_policy=HostSecurityPolicy.from_settings(None),
        retirement_hooks=(lambda: retired.append("runtime-owner"),),
        worker_bounds=bounds,
    )
    launcher._app = app
    return launcher


def test_launcher_gates_http_ticks_both_workers_and_retires_in_order() -> None:
    retired: list[str] = []
    provisioning = _Worker()
    runtime_worker = _Worker()
    launcher = _launcher(
        provisioning=provisioning,
        runtime_worker=runtime_worker,
        retired=retired,
        bounds=EnzymeDesignProductWorkerBounds(
            poll_interval_seconds=60,
            maximum_sessions_per_tick=1,
            maximum_provisioning_per_session=2,
            maximum_runtime_commands_per_session=3,
            shutdown_timeout_seconds=1,
        ),
    )
    asgi_app = launcher.app

    async def request() -> tuple[int, dict[str, object]]:
        async with AsyncClient(
            transport=ASGITransport(app=asgi_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/healthz")
            return response.status_code, response.json()

    assert asyncio.run(request())[0] == 503
    launcher.start(background=False)
    assert asyncio.run(request()) == (200, {"ok": True})

    first = launcher.tick_once()
    second = launcher.tick_once()
    boundary = launcher.tick_once()
    wrapped = launcher.tick_once()

    assert first.session_ids == ("session-a",)
    assert second.session_ids == ("session-b",)
    assert boundary.session_ids == ()
    assert wrapped.session_ids == ("session-a",)
    assert first.provisioning_receipt_count == 1
    assert first.runtime_receipt_count == 1
    assert provisioning.calls == [
        ("session-a", 2),
        ("session-b", 2),
        ("session-a", 2),
    ]
    assert runtime_worker.calls == [
        ("session-a", 3),
        ("session-b", 3),
        ("session-a", 3),
    ]

    launcher.close()
    assert launcher.state is EnzymeDesignProductLifecycleState.STOPPED
    assert retired == ["runtime-owner", "store"]
    assert asyncio.run(request())[0] == 503


def test_launcher_background_loop_is_explicit_bounded_and_stoppable() -> None:
    retired: list[str] = []
    signalled = Event()
    provisioning = _Worker(signalled=signalled)
    runtime_worker = _Worker()
    launcher = _launcher(
        provisioning=provisioning,
        runtime_worker=runtime_worker,
        retired=retired,
        bounds=EnzymeDesignProductWorkerBounds(
            poll_interval_seconds=0.01,
            maximum_sessions_per_tick=1,
            shutdown_timeout_seconds=1,
        ),
    )

    launcher.start(background=True)
    assert signalled.wait(timeout=1)
    launcher.close()

    assert launcher.state is EnzymeDesignProductLifecycleState.STOPPED
    assert provisioning.calls
    assert len(provisioning.calls) == len(runtime_worker.calls)
    assert retired == ["runtime-owner", "store"]
