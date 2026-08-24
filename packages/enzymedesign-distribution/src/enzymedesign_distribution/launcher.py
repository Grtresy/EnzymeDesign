"""Executable EnzymeDesign Host and durable-worker launcher.

Deployment configuration remains an explicit composition-root concern.  The CLI
therefore requires an exact ``module:factory`` locator whose zero-argument factory
returns this launcher; it never guesses a database, project, provider, or security
policy from ambient state.
"""

from __future__ import annotations

import argparse
from builtins import ExceptionGroup
import importlib
import json
import sys
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from pathlib import Path
from threading import Event
from threading import RLock
from threading import Thread
from types import MappingProxyType
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_host_api import HostSecurityPolicy
from openzyme_store_sqlite import SQLiteControlStore

from .application_runtime import EnzymeDesignApplicationRuntime
from .application_runtime import build_enzymedesign_v2_host_app


ENZYMEDESIGN_LAUNCHER_SCHEMA_VERSION = "enzymedesign_launcher@1"


class EnzymeDesignProductLifecycleState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EnzymeDesignProductWorkerBounds:
    poll_interval_seconds: float = 0.25
    maximum_sessions_per_tick: int = 64
    maximum_provisioning_per_session: int = 1
    maximum_runtime_commands_per_session: int = 1
    shutdown_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.poll_interval_seconds, int | float)
            or isinstance(self.poll_interval_seconds, bool)
            or not 0.01 <= float(self.poll_interval_seconds) <= 60
        ):
            raise ValueError("worker poll interval must be within [0.01, 60]")
        for field_name, maximum in (
            ("maximum_sessions_per_tick", 1_024),
            ("maximum_provisioning_per_session", 64),
            ("maximum_runtime_commands_per_session", 64),
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= maximum
            ):
                raise ValueError(f"{field_name} exceeds its closed bound")
        if (
            not isinstance(self.shutdown_timeout_seconds, int | float)
            or isinstance(self.shutdown_timeout_seconds, bool)
            or not 0.1 <= float(self.shutdown_timeout_seconds) <= 300
        ):
            raise ValueError("worker shutdown timeout must be within [0.1, 300]")


@dataclass(frozen=True, slots=True)
class EnzymeDesignProductWorkerTick:
    session_ids: tuple[str, ...]
    provisioning_receipt_count: int
    runtime_receipt_count: int


@dataclass(frozen=True, slots=True)
class EnzymeDesignLauncherPreflightReceipt:
    """Read-only proof for one exact file-backed EnzymeDesign application."""

    database_path: str
    store_provider_id: str
    store_provider_contract_digest: str
    store_identity_digest: str
    active_epoch_id: str
    active_release_digest: str
    activation_digest: str
    extension_bundle_digest: str
    declared_tool_catalog_digest: str
    adapter_runtime_digest: str
    runtime_proof_digest: str
    workflow_registry_snapshot_digest: str
    role_policy_digest: str
    workspace_adapter_binding_digest: str
    file_backed: bool
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        database_path = Path(self.database_path)
        if (
            self.file_backed is not True
            or not database_path.is_absolute()
            or not self.database_path
            or database_path.resolve(strict=False) != database_path
        ):
            raise ValueError("launcher preflight requires a file-backed database")
        if (
            self.store_provider_id != SQLiteControlStore.provider_id
            or self.store_provider_contract_digest
            != SQLiteControlStore.provider_contract_digest
        ):
            raise ValueError("launcher preflight store identity is not official")
        for field_name in ("store_provider_id", "active_epoch_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "store_provider_contract_digest",
            "store_identity_digest",
            "active_release_digest",
            "activation_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "adapter_runtime_digest",
            "runtime_proof_digest",
            "workflow_registry_snapshot_digest",
            "role_policy_digest",
            "workspace_adapter_binding_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.fallback_performed is not False:
            raise ValueError("launcher preflight cannot report fallback")

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_payload(), "receipt_digest": self.receipt_digest}

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(self._digest_payload())

    def _digest_payload(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_launcher_preflight@1",
            "database_path": self.database_path,
            "store_provider_id": self.store_provider_id,
            "store_provider_contract_digest": self.store_provider_contract_digest,
            "store_identity_digest": self.store_identity_digest,
            "active_epoch_id": self.active_epoch_id,
            "active_release_digest": self.active_release_digest,
            "activation_digest": self.activation_digest,
            "extension_bundle_digest": self.extension_bundle_digest,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "adapter_runtime_digest": self.adapter_runtime_digest,
            "runtime_proof_digest": self.runtime_proof_digest,
            "workflow_registry_snapshot_digest": (
                self.workflow_registry_snapshot_digest
            ),
            "role_policy_digest": self.role_policy_digest,
            "workspace_adapter_binding_digest": self.workspace_adapter_binding_digest,
            "file_backed": self.file_backed,
            "fallback_performed": self.fallback_performed,
        }


@dataclass(frozen=True, slots=True)
class _VerifiedSQLiteStoreIdentity:
    database_path: Path
    file_backed: bool
    identity_digest: str


class EnzymeDesignLauncherError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        require_identifier(code, field_name="code")
        self.code = code
        self.component = "enzymedesign.distribution"
        self.effect_certainty = "no_effect"
        self.mutation_applied = False
        self.fallback_performed = False
        seed = canonical_sha256_digest(
            {"component": self.component, "code": code, "message": message}
        ).removeprefix("sha256:")[:24]
        self.diagnostic_id = f"diagnostic-enzymedesign-{seed}"
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "enzymedesign_launcher_error@1",
            "code": self.code,
            "message": str(self),
            "component": self.component,
            "effect_certainty": self.effect_certainty,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "diagnostic_id": self.diagnostic_id,
        }


@dataclass(frozen=True, slots=True)
class EnzymeDesignLauncherConfig:
    database_path: Path
    factory_locator: str
    expected_factory_id: str
    expected_factory_digest: str
    component_configuration: Mapping[str, object]
    worker_bounds: EnzymeDesignProductWorkerBounds
    host: str
    port: int

    def __post_init__(self) -> None:
        path = self.database_path.resolve(strict=False)
        if not self.database_path.is_absolute() or str(path) == ":memory:":
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_database_path_invalid",
                "EnzymeDesign launcher database_path must be an absolute file path",
            )
        if not path.parent.is_dir():
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_database_parent_missing",
                "EnzymeDesign launcher database parent directory does not exist",
            )
        object.__setattr__(self, "database_path", path)
        _split_factory_locator(self.factory_locator)
        require_identifier(self.expected_factory_id, field_name="expected_factory_id")
        require_digest(
            self.expected_factory_digest,
            field_name="expected_factory_digest",
        )
        configuration = dict(self.component_configuration)
        if any(
            not isinstance(key, str) or not key or key != key.strip()
            for key in configuration
        ):
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_component_configuration_invalid",
                "Component configuration keys must be non-empty exact strings",
            )
        object.__setattr__(
            self,
            "component_configuration",
            MappingProxyType(configuration),
        )
        if not self.host or self.host != self.host.strip():
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_host_invalid",
                "EnzymeDesign launcher server host is invalid",
            )
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65_535
        ):
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_port_invalid",
                "EnzymeDesign launcher server port must be within [1, 65535]",
            )


@dataclass(slots=True)
class EnzymeDesignHostLauncher:
    """Own one exact application graph, HTTP surface and bounded workers."""

    runtime: EnzymeDesignApplicationRuntime
    security_policy: HostSecurityPolicy
    close_callback: Callable[[], None] | None = None
    retirement_hooks: tuple[Callable[[], None], ...] = ()
    worker_bounds: EnzymeDesignProductWorkerBounds = EnzymeDesignProductWorkerBounds()
    database_path: Path | None = None
    state: EnzymeDesignProductLifecycleState = EnzymeDesignProductLifecycleState.CREATED
    _closed: bool = False
    _app: Any = field(default=None, init=False, repr=False)
    _accepting: bool = field(default=False, init=False, repr=False)
    _stop_event: Event = field(default_factory=Event, init=False, repr=False)
    _thread: Thread | None = field(default=None, init=False, repr=False)
    _failure: BaseException | None = field(default=None, init=False, repr=False)
    _state_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _tick_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _session_cursor: str | None = field(default=None, init=False, repr=False)
    _admission_gate_installed: bool = field(default=False, init=False, repr=False)
    _preflight_receipt: EnzymeDesignLauncherPreflightReceipt | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.runtime.startup.gate.active_epoch is None:
            raise ValueError("launcher requires one active EnzymeDesign deployment")
        if any(not callable(hook) for hook in self.retirement_hooks):
            raise TypeError("EnzymeDesign retirement hooks must be callable")
        self.retirement_hooks = tuple(self.retirement_hooks)
        if self.database_path is not None:
            resolved = self.database_path.resolve(strict=False)
            if not self.database_path.is_absolute() or str(resolved) == ":memory:":
                raise ValueError("launcher database_path must be an absolute file path")
            self.database_path = resolved

    @property
    def app(self) -> Any:
        self._require_open()
        existing = self._app
        if existing is None:
            existing = build_enzymedesign_v2_host_app(
                runtime=self.runtime,
                security_policy=self.security_policy,
            )
            self._app = existing
        self._install_admission_gate()
        return existing

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    @property
    def preflight_receipt(self) -> EnzymeDesignLauncherPreflightReceipt:
        self._require_open()
        receipt = self._preflight_receipt
        if receipt is None:
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_preflight_unbound",
                "Launcher has not passed exact file-backed preflight",
            )
        return receipt

    def start(self, *, background: bool = True) -> None:
        """Open HTTP admission and optionally start the bounded worker thread."""

        with self._state_lock:
            if self.state is not EnzymeDesignProductLifecycleState.CREATED:
                raise RuntimeError("EnzymeDesign lifecycle may start exactly once")
            # Build and gate the complete Host before opening admission.  A
            # composition failure therefore leaves the lifecycle non-accepting.
            _ = self.app
            self._stop_event = Event()
            self._accepting = True
            self.state = EnzymeDesignProductLifecycleState.RUNNING
            if background:
                self._thread = Thread(
                    target=self._worker_loop,
                    name="enzymedesign-bounded-workers",
                    daemon=False,
                )
                self._thread.start()

    def tick_once(self) -> EnzymeDesignProductWorkerTick:
        """Advance bounded provisioning/reconciliation and runtime commands."""

        with self._state_lock:
            if self.state is not EnzymeDesignProductLifecycleState.RUNNING:
                raise RuntimeError(
                    "EnzymeDesign bounded workers require a running lifecycle"
                )
        with self._tick_lock:
            with self._state_lock:
                if self.state is not EnzymeDesignProductLifecycleState.RUNNING:
                    raise RuntimeError(
                        "EnzymeDesign lifecycle stopped before worker tick"
                    )
            try:
                session_ids = self._discover_session_ids()
                provisioning = 0
                runtime = 0
                for session_id in session_ids:
                    provisioning += len(
                        self.runtime.workspace_provisioning_lifecycle_worker.tick(
                            session_id=session_id,
                            maximum=(
                                self.worker_bounds.maximum_provisioning_per_session
                            ),
                        )
                    )
                    runtime += len(
                        self.runtime.runtime_worker.tick(
                            session_id=session_id,
                            maximum=(
                                self.worker_bounds.maximum_runtime_commands_per_session
                            ),
                        )
                    )
                return EnzymeDesignProductWorkerTick(
                    session_ids=session_ids,
                    provisioning_receipt_count=provisioning,
                    runtime_receipt_count=runtime,
                )
            except BaseException as exc:
                with self._state_lock:
                    self._failure = exc
                    self._accepting = False
                    self.state = EnzymeDesignProductLifecycleState.FAILED
                self._stop_event.set()
                raise

    def tick_workspace_provisioning(
        self,
        *,
        session_id: str,
        maximum: int = 1,
    ) -> tuple[KernelMutationReceipt, ...]:
        self._require_open()
        return self.runtime.workspace_provisioning_lifecycle_worker.tick(
            session_id=session_id,
            maximum=maximum,
        )

    def provision_workspace(
        self,
        *,
        intent_id: str,
        expected_intent_version: int,
        claim_seconds: int,
    ) -> KernelMutationReceipt:
        self._require_open()
        return self.runtime.workspace_provisioning_runner.run(
            intent_id=intent_id,
            expected_intent_version=expected_intent_version,
            claim_seconds=claim_seconds,
        )

    def run_runtime_command(
        self,
        *,
        runtime_command_id: str,
    ) -> KernelMutationReceipt:
        self._require_open()
        return self.runtime.runtime_worker.run(runtime_command_id)

    def tick_runtime_commands(
        self,
        *,
        session_id: str,
        maximum: int = 1,
    ) -> tuple[KernelMutationReceipt, ...]:
        self._require_open()
        return self.runtime.runtime_worker.tick(
            session_id=session_id,
            maximum=maximum,
        )

    def close(self) -> None:
        if self._closed:
            return
        self.stop()

    def stop(self) -> None:
        with self._state_lock:
            if self.state is EnzymeDesignProductLifecycleState.STOPPED:
                self._closed = True
                return
            if self.state not in {
                EnzymeDesignProductLifecycleState.CREATED,
                EnzymeDesignProductLifecycleState.RUNNING,
                EnzymeDesignProductLifecycleState.FAILED,
            }:
                raise RuntimeError("EnzymeDesign lifecycle is already stopping")
            self._accepting = False
            self.state = EnzymeDesignProductLifecycleState.STOPPING
            self._stop_event.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=self.worker_bounds.shutdown_timeout_seconds)
            if thread.is_alive():
                raise RuntimeError(
                    "EnzymeDesign bounded workers did not retire before the deadline"
                )
        errors: list[BaseException] = []
        with self._tick_lock:
            for hook in self.retirement_hooks:
                try:
                    hook()
                except BaseException as exc:
                    errors.append(exc)
            try:
                if self.close_callback is not None:
                    self.close_callback()
                else:
                    self.runtime.store.connection.close()
            except BaseException as exc:
                errors.append(exc)
        with self._state_lock:
            self._closed = True
            self.state = EnzymeDesignProductLifecycleState.STOPPED
        if errors:
            raise ExceptionGroup("EnzymeDesign product retirement failures", errors)

    def __enter__(self) -> EnzymeDesignHostLauncher:
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("EnzymeDesign launcher is closed")

    def _discover_session_ids(self) -> tuple[str, ...]:
        session_ids = self.runtime.store.list_session_ids(
            after_session_id=self._session_cursor,
            max_items=self.worker_bounds.maximum_sessions_per_tick,
        )
        if session_ids:
            self._session_cursor = session_ids[-1]
        elif self._session_cursor is not None:
            self._session_cursor = None
        return session_ids

    def _worker_loop(self) -> None:
        try:
            while not self._stop_event.wait(self.worker_bounds.poll_interval_seconds):
                self.tick_once()
        except BaseException as exc:
            with self._state_lock:
                self._failure = exc
                self._accepting = False
                self.state = EnzymeDesignProductLifecycleState.FAILED
            self._stop_event.set()

    def _install_admission_gate(self) -> None:
        if self._admission_gate_installed:
            return
        self._admission_gate_installed = True
        from starlette.responses import JSONResponse

        @self._app.middleware("http")
        async def lifecycle_admission(request, call_next):  # noqa: ANN001, ANN202
            if not self._accepting:
                return JSONResponse(
                    status_code=503,
                    content={
                        "schema_version": "openzyme_host_error@2",
                        "error": {
                            "code": "enzymedesign_lifecycle_not_accepting",
                            "message": (
                                "EnzymeDesign product lifecycle is not accepting "
                                "HTTP admission"
                            ),
                            "mutation_applied": False,
                            "effect_certainty": "no_effect",
                            "fallback_performed": False,
                            "details": {"lifecycle_state": self.state.value},
                        },
                    },
                )
            return await call_next(request)


def load_enzymedesign_launcher_config(
    config_path: Path,
) -> EnzymeDesignLauncherConfig:
    """Load one closed JSON document without cwd/env/default discovery."""

    if not config_path.is_absolute():
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_path_invalid",
            "EnzymeDesign launcher --config must be an absolute file path",
        )
    try:
        path = config_path.resolve(strict=True)
    except OSError as exc:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_unreadable",
            "EnzymeDesign launcher configuration path does not resolve to a file",
        ) from exc
    if not path.is_file():
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_not_file",
            "EnzymeDesign launcher configuration path is not a regular file",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_unreadable",
            "EnzymeDesign launcher configuration is not readable canonical JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_invalid",
            "EnzymeDesign launcher configuration must be one JSON object",
        )
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "database_path",
            "component_factory",
            "worker_bounds",
            "server",
        },
        label="launcher configuration",
    )
    if payload["schema_version"] != ENZYMEDESIGN_LAUNCHER_SCHEMA_VERSION:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_schema_version_unsupported",
            "EnzymeDesign launcher schema_version is not supported",
        )
    factory = _require_mapping(payload["component_factory"], "component_factory")
    _require_exact_keys(
        factory,
        {"locator", "factory_id", "factory_digest", "configuration"},
        label="component_factory",
    )
    configuration = _require_mapping(
        factory["configuration"],
        "component_factory.configuration",
    )
    workers = _require_mapping(payload["worker_bounds"], "worker_bounds")
    _require_exact_keys(
        workers,
        {
            "poll_interval_seconds",
            "maximum_sessions_per_tick",
            "maximum_provisioning_per_session",
            "maximum_runtime_commands_per_session",
            "shutdown_timeout_seconds",
        },
        label="worker_bounds",
    )
    server = _require_mapping(payload["server"], "server")
    _require_exact_keys(server, {"host", "port"}, label="server")
    for label, value in (
        ("database_path", payload["database_path"]),
        ("component_factory.locator", factory["locator"]),
        ("component_factory.factory_id", factory["factory_id"]),
        ("component_factory.factory_digest", factory["factory_digest"]),
        ("server.host", server["host"]),
    ):
        if not isinstance(value, str):
            raise EnzymeDesignLauncherError(
                "enzymedesign_launcher_config_type_invalid",
                f"EnzymeDesign launcher {label} must be a string",
            )
    try:
        worker_bounds = EnzymeDesignProductWorkerBounds(
            poll_interval_seconds=workers["poll_interval_seconds"],
            maximum_sessions_per_tick=workers["maximum_sessions_per_tick"],
            maximum_provisioning_per_session=(
                workers["maximum_provisioning_per_session"]
            ),
            maximum_runtime_commands_per_session=(
                workers["maximum_runtime_commands_per_session"]
            ),
            shutdown_timeout_seconds=workers["shutdown_timeout_seconds"],
        )
    except (TypeError, ValueError) as exc:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_worker_bounds_invalid",
            "EnzymeDesign launcher worker bounds are invalid",
        ) from exc
    return EnzymeDesignLauncherConfig(
        database_path=Path(payload["database_path"]),
        factory_locator=factory["locator"],
        expected_factory_id=factory["factory_id"],
        expected_factory_digest=factory["factory_digest"],
        component_configuration=configuration,
        worker_bounds=worker_bounds,
        host=server["host"],
        port=server["port"],
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="enzymedesign-host",
        description="Run one explicitly configured EnzymeDesign Host or worker",
    )
    parser.add_argument("--config", required=True, help="Absolute closed JSON config")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("preflight", help="Verify and report exact composition")
    subparsers.add_parser("serve", help="Serve the configured ASGI Host")

    provision = subparsers.add_parser(
        "provision",
        help="Run one exact durable workspace provisioning intent",
    )
    provision.add_argument("--intent-id", required=True)
    provision.add_argument("--expected-intent-version", required=True, type=int)
    provision.add_argument("--claim-seconds", type=int, default=300)

    drain = subparsers.add_parser(
        "drain",
        help="Claim and run one exact admitted durable runtime command",
    )
    drain.add_argument("--runtime-command-id", required=True)

    tick = subparsers.add_parser(
        "drain-tick",
        help="Run a bounded scan of accepted or expired runtime commands",
    )
    tick.add_argument("--session-id", required=True)
    tick.add_argument("--maximum", type=int, default=1)

    provision_tick = subparsers.add_parser(
        "provision-tick",
        help="Run a bounded scan of provisioning and reconciliation work",
    )
    provision_tick.add_argument("--session-id", required=True)
    provision_tick.add_argument("--maximum", type=int, default=1)

    args = parser.parse_args(argv)
    try:
        config = load_enzymedesign_launcher_config(Path(args.config))
        launcher = _load_launcher(config)
    except EnzymeDesignLauncherError as exc:
        print(
            json.dumps({"error": exc.to_dict()}, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    try:
        if args.mode == "preflight":
            print(
                json.dumps(
                    launcher.preflight_receipt.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return
        if args.mode == "serve":
            launcher.start(background=True)
            _serve(launcher, host=config.host, port=config.port)
            return
        launcher.start(background=False)
        if args.mode == "provision":
            _print_receipt(
                launcher.provision_workspace(
                    intent_id=args.intent_id,
                    expected_intent_version=args.expected_intent_version,
                    claim_seconds=args.claim_seconds,
                )
            )
        elif args.mode == "provision-tick":
            for receipt in launcher.tick_workspace_provisioning(
                session_id=args.session_id,
                maximum=args.maximum,
            ):
                _print_receipt(receipt)
        elif args.mode == "drain":
            _print_receipt(
                launcher.run_runtime_command(
                    runtime_command_id=args.runtime_command_id,
                )
            )
        else:
            for receipt in launcher.tick_runtime_commands(
                session_id=args.session_id,
                maximum=args.maximum,
            ):
                _print_receipt(receipt)
    finally:
        launcher.close()


def _load_launcher(config: EnzymeDesignLauncherConfig) -> EnzymeDesignHostLauncher:
    module_name, attribute_name = _split_factory_locator(config.factory_locator)
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ValueError) as exc:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_import_failed",
            "Configured EnzymeDesign launcher factory module could not be imported",
        ) from exc
    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_missing",
            "Configured EnzymeDesign launcher factory is not callable",
        )
    if (
        getattr(factory, "factory_id", None) != config.expected_factory_id
        or getattr(factory, "factory_digest", None) != config.expected_factory_digest
    ):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_identity_drift",
            "Configured EnzymeDesign launcher factory identity drifted",
        )
    try:
        launcher = factory(config)
    except EnzymeDesignLauncherError:
        raise
    except Exception as exc:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_failed",
            "Configured EnzymeDesign launcher factory failed closed",
        ) from exc
    if not isinstance(launcher, EnzymeDesignHostLauncher):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_result_invalid",
            "Configured factory returned another object type",
        )
    if (
        launcher.database_path != config.database_path
        or launcher.worker_bounds != config.worker_bounds
    ):
        launcher.close()
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_configuration_drift",
            "Constructed launcher differs from exact database or worker bounds",
        )
    try:
        store_identity = _verify_launcher_store_identity(
            launcher=launcher,
            config=config,
        )
        launcher.runtime.validate_identity()
        launcher._preflight_receipt = EnzymeDesignLauncherPreflightReceipt(
            database_path=str(store_identity.database_path),
            store_provider_id=launcher.runtime.store.provider_id,
            store_provider_contract_digest=(
                launcher.runtime.store.provider_contract_digest
            ),
            store_identity_digest=store_identity.identity_digest,
            active_epoch_id=launcher.runtime.active_epoch_id,
            active_release_digest=launcher.runtime.active_release_digest,
            activation_digest=launcher.runtime.activation_digest,
            extension_bundle_digest=launcher.runtime.extension_bundle_digest,
            declared_tool_catalog_digest=(
                launcher.runtime.declared_tool_catalog_digest
            ),
            adapter_runtime_digest=launcher.runtime.adapter_runtime_digest,
            runtime_proof_digest=launcher.runtime.proof_digest,
            workflow_registry_snapshot_digest=(
                launcher.runtime.workflow_registry_snapshot_digest
            ),
            role_policy_digest=launcher.runtime.role_policy_digest,
            workspace_adapter_binding_digest=(
                launcher.runtime.workspace_adapter_binding_digest
            ),
            file_backed=store_identity.file_backed,
        )
    except EnzymeDesignLauncherError as exc:
        close_error = _close_loaded_launcher(launcher, exc)
        if close_error is not None:
            raise exc from close_error
        raise
    except Exception as exc:
        error = EnzymeDesignLauncherError(
            "enzymedesign_launcher_runtime_identity_drift",
            "Constructed launcher runtime identity proof drifted",
        )
        close_error = _close_loaded_launcher(launcher, error)
        raise error from (close_error or exc)
    return launcher


def _verify_launcher_store_identity(
    *,
    launcher: EnzymeDesignHostLauncher,
    config: EnzymeDesignLauncherConfig,
) -> _VerifiedSQLiteStoreIdentity:
    runtime = launcher.runtime
    if not isinstance(runtime, EnzymeDesignApplicationRuntime) or not isinstance(
        getattr(runtime, "store", None),
        SQLiteControlStore,
    ):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher must own the official EnzymeDesign runtime and SQLite store",
        )
    store = runtime.store
    if (
        store.provider_id != SQLiteControlStore.provider_id
        or store.provider_contract_digest != SQLiteControlStore.provider_contract_digest
    ):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher SQLite store provider identity drifted",
        )
    try:
        rows = tuple(store.connection.execute("PRAGMA database_list").fetchall())
    except Exception as exc:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher SQLite database identity could not be observed",
        ) from exc
    if len(rows) != 1 or len(rows[0]) < 3:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher SQLite connection contains an unexpected attached database",
        )
    sequence, database_name, observed_path_value = rows[0][:3]
    if (
        sequence != 0
        or database_name != "main"
        or not isinstance(observed_path_value, str)
        or not observed_path_value
    ):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher SQLite main database is not one file-backed identity",
        )
    observed_path = Path(observed_path_value)
    file_backed = observed_path.is_absolute()
    if not file_backed:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher SQLite main database path is not absolute",
        )
    observed_path = observed_path.resolve(strict=False)
    if observed_path != config.database_path:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_store_identity_drift",
            "Launcher SQLite main database differs from the exact configured path",
        )
    return _VerifiedSQLiteStoreIdentity(
        database_path=observed_path,
        file_backed=file_backed,
        identity_digest=canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_launcher_store_identity@1",
                "provider_id": store.provider_id,
                "provider_contract_digest": store.provider_contract_digest,
                "database_list": [
                    {
                        "sequence": sequence,
                        "database_name": database_name,
                        "database_path": str(observed_path),
                    }
                ],
                "file_backed": file_backed,
            }
        ),
    )


def _close_loaded_launcher(
    launcher: EnzymeDesignHostLauncher,
    error: EnzymeDesignLauncherError,
) -> BaseException | None:
    try:
        launcher.close()
    except BaseException as close_error:
        error.add_note(
            f"launcher retirement also failed with {type(close_error).__name__}"
        )
        return close_error
    return None


def _split_factory_locator(locator: str) -> tuple[str, str]:
    if locator.count(":") != 1:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_locator_invalid",
            "Launcher factory must be one exact module:attribute locator",
        )
    module_name, attribute_name = locator.split(":", 1)
    if (
        not module_name
        or not attribute_name
        or module_name != module_name.strip()
        or attribute_name != attribute_name.strip()
    ):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_factory_locator_invalid",
            "Launcher factory locator is invalid",
        )
    return module_name, attribute_name


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_type_invalid",
            f"EnzymeDesign launcher {label} must be one JSON object",
        )
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(value) != expected:
        raise EnzymeDesignLauncherError(
            "enzymedesign_launcher_config_keys_invalid",
            f"EnzymeDesign {label} fields differ from the closed contract",
        )


def _serve(launcher: EnzymeDesignHostLauncher, *, host: str, port: int) -> None:
    if not host or host != host.strip() or not 1 <= port <= 65_535:
        raise ValueError("serve host/port is invalid")
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional server extra
        raise RuntimeError(
            "serve mode requires the enzymedesign server optional dependency"
        ) from exc
    uvicorn.run(launcher.app, host=host, port=port)


def _print_receipt(receipt: KernelMutationReceipt) -> None:
    print(json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True))


__all__ = [
    "ENZYMEDESIGN_LAUNCHER_SCHEMA_VERSION",
    "EnzymeDesignHostLauncher",
    "EnzymeDesignLauncherConfig",
    "EnzymeDesignLauncherError",
    "EnzymeDesignLauncherPreflightReceipt",
    "EnzymeDesignProductLifecycleState",
    "EnzymeDesignProductWorkerBounds",
    "EnzymeDesignProductWorkerTick",
    "load_enzymedesign_launcher_config",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    main()
