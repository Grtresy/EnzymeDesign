"""Strict file-backed console launcher for the Standard product graph."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .lifecycle import StandardProductCompositionFactoryPort
from .lifecycle import StandardProductLifecycle
from .lifecycle import StandardProductLifecycleError
from .lifecycle import StandardProductWorkerBounds


STANDARD_LAUNCHER_SCHEMA_VERSION = "openzyme_standard_launcher@1"


class StandardProductLauncherError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        require_identifier(code, field_name="code")
        self.code = code
        self.component = "openzyme.standard"
        self.effect_certainty = "no_effect"
        self.mutation_applied = False
        self.fallback_performed = False
        seed = canonical_sha256_digest(
            {"component": self.component, "code": code, "message": message}
        ).removeprefix("sha256:")[:24]
        self.diagnostic_id = f"diagnostic-standard-{seed}"
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_standard_launcher_error@1",
            "code": self.code,
            "message": str(self),
            "component": self.component,
            "effect_certainty": self.effect_certainty,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "diagnostic_id": self.diagnostic_id,
        }


@dataclass(frozen=True, slots=True)
class StandardProductLauncherConfig:
    database_path: Path
    factory_locator: str
    expected_factory_id: str
    expected_factory_digest: str
    component_configuration: Mapping[str, object]
    worker_bounds: StandardProductWorkerBounds
    host: str
    port: int

    def __post_init__(self) -> None:
        path = self.database_path.resolve(strict=False)
        if not self.database_path.is_absolute() or str(path) == ":memory:":
            raise StandardProductLauncherError(
                "standard_launcher_database_path_invalid",
                "Standard launcher database_path must be an absolute file path",
            )
        if not path.parent.is_dir():
            raise StandardProductLauncherError(
                "standard_launcher_database_parent_missing",
                "Standard launcher database parent directory does not exist",
            )
        object.__setattr__(self, "database_path", path)
        _split_factory_locator(self.factory_locator)
        require_identifier(
            self.expected_factory_id,
            field_name="expected_factory_id",
        )
        require_digest(
            self.expected_factory_digest,
            field_name="expected_factory_digest",
        )
        configuration = dict(self.component_configuration)
        if any(
            not isinstance(key, str) or not key or key != key.strip()
            for key in configuration
        ):
            raise StandardProductLauncherError(
                "standard_launcher_component_configuration_invalid",
                "Component configuration keys must be non-empty exact strings",
            )
        object.__setattr__(
            self,
            "component_configuration",
            MappingProxyType(configuration),
        )
        if not self.host or self.host != self.host.strip():
            raise StandardProductLauncherError(
                "standard_launcher_host_invalid",
                "Standard launcher server host is invalid",
            )
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65_535
        ):
            raise StandardProductLauncherError(
                "standard_launcher_port_invalid",
                "Standard launcher server port must be within [1, 65535]",
            )


def load_standard_product_launcher_config(
    config_path: Path,
) -> StandardProductLauncherConfig:
    """Load one closed JSON configuration without cwd/env/default discovery."""

    if not config_path.is_absolute():
        raise StandardProductLauncherError(
            "standard_launcher_config_path_invalid",
            "Standard launcher --config must be an absolute file path",
        )
    try:
        path = config_path.resolve(strict=True)
    except OSError as exc:
        raise StandardProductLauncherError(
            "standard_launcher_config_unreadable",
            "Standard launcher configuration path does not resolve to a file",
        ) from exc
    if not path.is_file():
        raise StandardProductLauncherError(
            "standard_launcher_config_not_file",
            "Standard launcher configuration path is not a regular file",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StandardProductLauncherError(
            "standard_launcher_config_unreadable",
            "Standard launcher configuration is not readable canonical JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise StandardProductLauncherError(
            "standard_launcher_config_invalid",
            "Standard launcher configuration must be one JSON object",
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
    if payload["schema_version"] != STANDARD_LAUNCHER_SCHEMA_VERSION:
        raise StandardProductLauncherError(
            "standard_launcher_schema_version_unsupported",
            "Standard launcher schema_version is not supported",
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
            raise StandardProductLauncherError(
                "standard_launcher_config_type_invalid",
                f"Standard launcher {label} must be a string",
            )
    try:
        worker_bounds = StandardProductWorkerBounds(
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
        raise StandardProductLauncherError(
            "standard_launcher_worker_bounds_invalid",
            "Standard launcher worker bounds are invalid",
        ) from exc
    return StandardProductLauncherConfig(
        database_path=Path(payload["database_path"]),
        factory_locator=factory["locator"],
        expected_factory_id=factory["factory_id"],
        expected_factory_digest=factory["factory_digest"],
        component_configuration=configuration,
        worker_bounds=worker_bounds,
        host=server["host"],
        port=server["port"],
    )


def load_standard_product_composition_factory(
    locator: str,
) -> StandardProductCompositionFactoryPort:
    module_name, attribute_name = _split_factory_locator(locator)
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ValueError) as exc:
        raise StandardProductLauncherError(
            "standard_launcher_factory_import_failed",
            "Configured Standard component factory module could not be imported",
        ) from exc
    constructor = getattr(module, attribute_name, None)
    if not callable(constructor):
        raise StandardProductLauncherError(
            "standard_launcher_factory_not_callable",
            "Configured Standard component factory attribute is not callable",
        )
    try:
        factory = constructor()
    except Exception as exc:
        raise StandardProductLauncherError(
            "standard_launcher_factory_construction_failed",
            "Configured Standard component factory could not be constructed",
        ) from exc
    if (
        not isinstance(getattr(factory, "factory_id", None), str)
        or not isinstance(getattr(factory, "factory_digest", None), str)
        or not callable(getattr(factory, "build", None))
    ):
        raise StandardProductLauncherError(
            "standard_launcher_factory_contract_invalid",
            "Configured Standard component factory does not implement its Port",
        )
    return factory


def compose_standard_product_from_config(
    config: StandardProductLauncherConfig,
    *,
    factory: StandardProductCompositionFactoryPort | None = None,
) -> StandardProductLifecycle:
    resolved_factory = factory or load_standard_product_composition_factory(
        config.factory_locator
    )
    return StandardProductLifecycle.compose_file_backed(
        database_path=config.database_path,
        factory=resolved_factory,
        component_configuration=config.component_configuration,
        expected_factory_id=config.expected_factory_id,
        expected_factory_digest=config.expected_factory_digest,
        worker_bounds=config.worker_bounds,
    )


def serve_standard_product(
    config: StandardProductLauncherConfig,
    *,
    factory: StandardProductCompositionFactoryPort | None = None,
    server_runner: Callable[..., None] | None = None,
) -> None:
    """Open admission/workers only after exact composition preflight succeeds."""

    lifecycle = compose_standard_product_from_config(config, factory=factory)
    try:
        lifecycle.start()
        runner = server_runner or _load_uvicorn_runner()
        try:
            runner(lifecycle.app, host=config.host, port=config.port)
        except (StandardProductLauncherError, StandardProductLifecycleError):
            raise
        except Exception as exc:
            raise StandardProductLauncherError(
                "standard_server_failed",
                "The configured Standard ASGI server failed",
            ) from exc
        if lifecycle.failure is not None:
            raise StandardProductLauncherError(
                "standard_product_worker_failed",
                "A Standard durable worker failed while the Host was running",
            ) from lifecycle.failure
    finally:
        lifecycle.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="openzyme-standard",
        description="Run one exact file-backed OpenZyme Standard composition",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Absolute path to openzyme_standard_launcher@1 JSON",
    )
    parser.add_argument(
        "mode",
        choices=("preflight", "worker-tick", "serve"),
    )
    args = parser.parse_args(argv)
    try:
        config = load_standard_product_launcher_config(args.config)
        if args.mode == "serve":
            serve_standard_product(config)
            return
        lifecycle = compose_standard_product_from_config(config)
        try:
            if args.mode == "preflight":
                _print_json(lifecycle.preflight.to_dict())
            else:
                lifecycle.start()
                _print_json(lifecycle.tick_once().to_dict())
        finally:
            lifecycle.stop()
    except (StandardProductLauncherError, StandardProductLifecycleError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "openzyme_standard_console_error@1",
                    "error": exc.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None


def _load_uvicorn_runner() -> Callable[..., None]:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on server extra
        raise StandardProductLauncherError(
            "standard_launcher_server_dependency_missing",
            "Standard serve mode requires the server optional dependency",
        ) from exc
    return uvicorn.run


def _split_factory_locator(locator: str) -> tuple[str, str]:
    if not isinstance(locator, str) or locator.count(":") != 1:
        raise StandardProductLauncherError(
            "standard_launcher_factory_locator_invalid",
            "Component factory must be one exact module:attribute locator",
        )
    module_name, attribute_name = locator.split(":", 1)
    if (
        not module_name
        or not attribute_name
        or module_name != module_name.strip()
        or attribute_name != attribute_name.strip()
        or any(not item.isidentifier() for item in module_name.split("."))
        or not attribute_name.isidentifier()
    ):
        raise StandardProductLauncherError(
            "standard_launcher_factory_locator_invalid",
            "Component factory must be one exact module:attribute locator",
        )
    return module_name, attribute_name


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise StandardProductLauncherError(
            "standard_launcher_config_type_invalid",
            f"Standard launcher {label} must be a JSON object",
        )
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    observed = set(value)
    if observed != expected:
        raise StandardProductLauncherError(
            "standard_launcher_config_keys_invalid",
            f"Standard {label} keys differ from its closed schema",
        )


def _print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


__all__ = [
    "STANDARD_LAUNCHER_SCHEMA_VERSION",
    "StandardProductLauncherConfig",
    "StandardProductLauncherError",
    "compose_standard_product_from_config",
    "load_standard_product_composition_factory",
    "load_standard_product_launcher_config",
    "main",
    "serve_standard_product",
]


if __name__ == "__main__":  # pragma: no cover - console entry point owns this
    main()
