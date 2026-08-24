from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient
import pytest

from openzyme_contracts import canonical_sha256_digest
from openzyme_standard.launcher import STANDARD_LAUNCHER_SCHEMA_VERSION
from openzyme_standard.launcher import StandardProductLauncherConfig
from openzyme_standard.launcher import StandardProductLauncherError
from openzyme_standard.launcher import load_standard_product_launcher_config
from openzyme_standard.launcher import main
from openzyme_standard.launcher import serve_standard_product
from openzyme_standard.lifecycle import StandardProductLifecycle
from openzyme_standard.lifecycle import StandardProductLifecycleError
from openzyme_standard.lifecycle import StandardProductLifecycleState
from openzyme_standard.lifecycle import StandardProductWorkerBounds


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _config_payload(database_path: Path) -> dict[str, object]:
    return {
        "schema_version": STANDARD_LAUNCHER_SCHEMA_VERSION,
        "database_path": str(database_path),
        "component_factory": {
            "locator": "deployment.standard:create_factory",
            "factory_id": "deployment.standard.factory",
            "factory_digest": _digest("deployment-standard-factory"),
            "configuration": {
                "project_config_path": "/configuration/projects.json"
            },
        },
        "worker_bounds": {
            "poll_interval_seconds": 0.5,
            "maximum_sessions_per_tick": 8,
            "maximum_provisioning_per_session": 1,
            "maximum_runtime_commands_per_session": 2,
            "shutdown_timeout_seconds": 3,
        },
        "server": {"host": "127.0.0.1", "port": 8765},
    }


def test_launcher_config_is_closed_absolute_and_has_no_ambient_defaults(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "standard.sqlite3"
    config_path = tmp_path / "standard-launcher.json"
    payload = _config_payload(database_path)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_standard_product_launcher_config(config_path)

    assert config.database_path == database_path
    assert config.factory_locator == "deployment.standard:create_factory"
    assert config.worker_bounds.maximum_runtime_commands_per_session == 2
    assert dict(config.component_configuration) == {
        "project_config_path": "/configuration/projects.json"
    }

    payload["implicit_provider_fallback"] = True
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StandardProductLauncherError) as unknown:
        load_standard_product_launcher_config(config_path)
    assert unknown.value.code == "standard_launcher_config_keys_invalid"

    with pytest.raises(StandardProductLauncherError) as relative:
        load_standard_product_launcher_config(Path("standard-launcher.json"))
    assert relative.value.code == "standard_launcher_config_path_invalid"

    with pytest.raises(StandardProductLauncherError) as missing:
        load_standard_product_launcher_config(tmp_path / "missing.json")
    assert missing.value.code == "standard_launcher_config_unreadable"


def test_console_reports_a_safe_structured_preflight_error(
    tmp_path: Path,
    capsys,
) -> None:  # noqa: ANN001
    with pytest.raises(SystemExit) as caught:
        main(["--config", str(tmp_path / "missing.json"), "preflight"])

    assert caught.value.code == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"]["code"] == "standard_launcher_config_unreadable"
    assert payload["error"]["component"] == "openzyme.standard"
    assert payload["error"]["mutation_applied"] is False
    assert payload["error"]["fallback_performed"] is False


@dataclass(slots=True)
class _Worker:
    calls: list[tuple[str, int]] = field(default_factory=list)

    def tick(self, *, session_id: str, maximum: int) -> tuple[object, ...]:
        self.calls.append((session_id, maximum))
        return (object(),)


@dataclass(slots=True)
class _FailingWorker:
    error: BaseException

    def tick(self, *, session_id: str, maximum: int) -> tuple[object, ...]:
        del session_id, maximum
        raise self.error


@dataclass(slots=True)
class _StoreWriter:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True, slots=True)
class _SessionRecords:
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


def test_lifecycle_gates_http_ticks_each_durable_worker_and_retires_file_store(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "lifecycle.sqlite3"
    writer = _StoreWriter()
    records = _SessionRecords(("session-b", "session-a"))
    provisioning = _Worker()
    runtime = _Worker()
    retired: list[str] = []
    app = FastAPI()

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    lifecycle = StandardProductLifecycle(
        database_path=database_path,
        store_writer=writer,
        records=records,
        composition=SimpleNamespace(
            retirement_hooks=(lambda: retired.append("retired"),)
        ),
        runtime=SimpleNamespace(
            provisioning_worker=provisioning,
            runtime_worker=runtime,
        ),
        app=app,
        preflight=SimpleNamespace(receipt_digest=_digest("preflight")),
        worker_bounds=StandardProductWorkerBounds(
            poll_interval_seconds=60,
            maximum_sessions_per_tick=1,
            maximum_provisioning_per_session=1,
            maximum_runtime_commands_per_session=2,
            shutdown_timeout_seconds=2,
        ),
    )
    lifecycle._install_admission_gate()

    async def request() -> tuple[int, dict[str, object]]:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/healthz")
            return response.status_code, response.json()

    assert asyncio.run(request())[0] == 503
    lifecycle.start()
    assert asyncio.run(request()) == (200, {"ok": True})

    first_tick = lifecycle.tick_once()
    second_tick = lifecycle.tick_once()
    end_tick = lifecycle.tick_once()
    wrapped_tick = lifecycle.tick_once()

    assert first_tick.session_ids == ("session-a",)
    assert second_tick.session_ids == ("session-b",)
    assert end_tick.session_ids == ()
    assert wrapped_tick.session_ids == ("session-a",)
    assert first_tick.provisioning_receipt_count == 1
    assert second_tick.provisioning_receipt_count == 1
    assert first_tick.runtime_receipt_count == 1
    assert second_tick.runtime_receipt_count == 1
    assert provisioning.calls == [
        ("session-a", 1),
        ("session-b", 1),
        ("session-a", 1),
    ]
    assert runtime.calls == [
        ("session-a", 2),
        ("session-b", 2),
        ("session-a", 2),
    ]
    lifecycle.stop()
    assert lifecycle.state is StandardProductLifecycleState.STOPPED
    assert retired == ["retired"]
    assert asyncio.run(request())[0] == 503
    assert writer.closed is True


def test_lifecycle_worker_failure_closes_http_admission_and_store(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "lifecycle-worker-failure.sqlite3"
    writer = _StoreWriter()
    app = FastAPI()

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    failure = RuntimeError("bounded worker failed")
    lifecycle = StandardProductLifecycle(
        database_path=database_path,
        store_writer=writer,
        records=_SessionRecords(("session-1",)),
        composition=SimpleNamespace(retirement_hooks=()),
        runtime=SimpleNamespace(
            provisioning_worker=_FailingWorker(failure),
            runtime_worker=_Worker(),
        ),
        app=app,
        preflight=SimpleNamespace(receipt_digest=_digest("preflight")),
        worker_bounds=StandardProductWorkerBounds(poll_interval_seconds=60),
    )
    lifecycle._install_admission_gate()
    lifecycle.start()

    with pytest.raises(RuntimeError, match="bounded worker failed"):
        lifecycle.tick_once()

    assert lifecycle.state is StandardProductLifecycleState.FAILED
    assert lifecycle.failure is failure

    async def request() -> int:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return (await client.get("/healthz")).status_code

    assert asyncio.run(request()) == 503
    lifecycle.stop()
    assert writer.closed is True


def test_factory_identity_drift_fails_before_opening_or_building_database(
    tmp_path: Path,
) -> None:
    class _WrongFactory:
        factory_id = "deployment.wrong.factory"
        factory_digest = _digest("wrong-factory")

        def build(self, **_: object) -> object:
            raise AssertionError("identity drift must fail before factory build")

    with pytest.raises(StandardProductLifecycleError) as caught:
        StandardProductLifecycle.compose_file_backed(
            database_path=tmp_path / "not-created.sqlite3",
            factory=_WrongFactory(),  # type: ignore[arg-type]
            component_configuration={},
            expected_factory_id="deployment.expected.factory",
            expected_factory_digest=_digest("expected-factory"),
        )

    assert caught.value.code == "standard_component_factory_identity_drift"
    assert not (tmp_path / "not-created.sqlite3").exists()


def test_lifecycle_never_implicitly_creates_a_missing_store(
    tmp_path: Path,
) -> None:
    class _Factory:
        factory_id = "deployment.expected.factory"
        factory_digest = _digest("expected-factory")

        def build(self, **_: object) -> object:
            raise AssertionError("missing Store must fail before factory verification")

    database_path = tmp_path / "missing.sqlite3"
    with pytest.raises(StandardProductLifecycleError) as caught:
        StandardProductLifecycle.compose_file_backed(
            database_path=database_path,
            factory=_Factory(),  # type: ignore[arg-type]
            component_configuration={},
            expected_factory_id=_Factory.factory_id,
            expected_factory_digest=_Factory.factory_digest,
        )

    assert caught.value.code == "standard_file_store_preflight_failed"
    assert not database_path.exists()


def test_serve_starts_after_composition_and_always_stops(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    calls: list[str] = []

    @dataclass(slots=True)
    class _Lifecycle:
        app: object = field(default_factory=object)
        failure: BaseException | None = None

        def start(self) -> None:
            calls.append("start")

        def stop(self) -> None:
            calls.append("stop")

    lifecycle = _Lifecycle()
    monkeypatch.setattr(
        "openzyme_standard.launcher.compose_standard_product_from_config",
        lambda *_args, **_kwargs: lifecycle,
    )
    config = StandardProductLauncherConfig(
        database_path=tmp_path / "serve.sqlite3",
        factory_locator="deployment.standard:create_factory",
        expected_factory_id="deployment.standard.factory",
        expected_factory_digest=_digest("deployment-standard-factory"),
        component_configuration={},
        worker_bounds=StandardProductWorkerBounds(),
        host="127.0.0.1",
        port=8765,
    )

    def run_server(app: object, *, host: str, port: int) -> None:
        assert app is lifecycle.app
        assert (host, port) == ("127.0.0.1", 8765)
        assert calls == ["start"]
        calls.append("serve")

    serve_standard_product(config, server_runner=run_server)

    assert calls == ["start", "serve", "stop"]
