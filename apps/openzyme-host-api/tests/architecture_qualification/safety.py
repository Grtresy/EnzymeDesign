from __future__ import annotations

import ast
import asyncio
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import socket
import subprocess
from types import TracebackType
from typing import Any
from unittest.mock import patch
import webbrowser

from .external_ports import ControlledPortOutcome
from .external_ports import EffectAcceptance
from .external_ports import ExternalEffectLedger


_ORIGINAL_POPEN = subprocess.Popen
_CREDENTIAL_NAME = re.compile(
    r"(?:^|_)(?:API_?KEY|ACCESS_?KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|COOKIE)(?:$|_)",
    re.IGNORECASE,
)
_CREDENTIAL_EXACT = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "OPENAI_API_KEY",
        "SSH_AUTH_SOCK",
        "TAVILY_API_KEY",
    }
)
_FORBIDDEN_SCENARIO_NAMES = frozenset(
    {
        "CoreRepositories",
        "SQLiteRepositoryProvider",
        "build_local_eval_foundation",
        "v3_legacy_repositories_for_tests",
    }
)
_FORBIDDEN_SCENARIO_MODULES = frozenset(
    {
        "openzyme_host_api.foundation",
        "openzyme_core.repositories",
        "sqlite3",
    }
)


class QualificationSafetyViolation(RuntimeError):
    code = "architecture_qualification_external_effect_forbidden"


class QualificationSourcePolicyError(ValueError):
    code = "architecture_qualification_source_policy_invalid"


def is_credential_name(name: str) -> bool:
    return name.upper() in _CREDENTIAL_EXACT or _CREDENTIAL_NAME.search(name) is not None


def scrubbed_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    return {
        key: value
        for key, value in environment.items()
        if not is_credential_name(key)
    }


def _declared_port_modes(registry: Mapping[str, object]) -> dict[str, str]:
    raw_ports = registry.get("external_ports")
    if not isinstance(raw_ports, list):
        raise QualificationSafetyViolation("registry external_ports are unavailable")
    ports: dict[str, str] = {}
    for raw_port in raw_ports:
        if not isinstance(raw_port, dict):
            raise QualificationSafetyViolation("registry external port is not an object")
        port_id = raw_port.get("port_id")
        mode = raw_port.get("qualification_mode")
        if not isinstance(port_id, str) or not isinstance(mode, str):
            raise QualificationSafetyViolation("registry external port identity is invalid")
        ports[port_id] = mode
    return ports


@dataclass(frozen=True, slots=True)
class BlockedInvocation:
    boundary: str
    operation: str


class QualificationSafetyGuard(AbstractContextManager["QualificationSafetyGuard"]):
    """Deny ambient external effects; explicit controlled ports remain outside it."""

    def __init__(self, *, registry: Mapping[str, object]) -> None:
        self._port_modes = _declared_port_modes(registry)
        self._patches: list[Any] = []
        self._saved_credentials: dict[str, str] = {}
        self._blocked: list[BlockedInvocation] = []
        self._entered = False

    @property
    def blocked_invocations(self) -> tuple[BlockedInvocation, ...]:
        return tuple(self._blocked)

    def require_declared_port(self, port_id: str, *, mode: str) -> None:
        actual = self._port_modes.get(port_id)
        if actual != mode:
            raise QualificationSafetyViolation(
                f"external port {port_id!r} is not declared with mode {mode!r}"
            )

    def launch_local_fault_process(
        self,
        *,
        ledger: ExternalEffectLedger,
        port_id: str,
        argv: tuple[str, ...],
        cwd: Path,
        environment: Mapping[str, str],
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.Popen[bytes]:
        """Launch only the declared, isolated qualification fault process seam."""

        if not self._entered:
            raise QualificationSafetyViolation(
                "local fault process launch requires an entered safety guard"
            )
        self.require_declared_port(port_id, mode="local_fault_process")
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise QualificationSafetyViolation("local fault process argv is invalid")
        if not cwd.resolve(strict=True).is_dir():
            raise QualificationSafetyViolation("local fault process cwd is invalid")
        credential_names = sorted(
            key for key in environment if is_credential_name(key)
        )
        if credential_names:
            raise QualificationSafetyViolation(
                "local fault process environment still contains credentials"
            )
        process = _ORIGINAL_POPEN(
            argv,
            close_fds=True,
            cwd=str(cwd),
            env=dict(environment),
            pass_fds=pass_fds,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        record_local_fault_process_launch(
            registry={
                "external_ports": [
                    {
                        "port_id": declared_port_id,
                        "qualification_mode": mode,
                    }
                    for declared_port_id, mode in sorted(self._port_modes.items())
                ]
            },
            ledger=ledger,
            port_id=port_id,
            argv=argv,
            pid=process.pid,
        )
        return process

    def _deny(self, boundary: str, operation: str) -> None:
        self._blocked.append(BlockedInvocation(boundary, operation))
        raise QualificationSafetyViolation(
            f"qualification denied ambient {boundary} invocation {operation!r}"
        )

    def __enter__(self) -> "QualificationSafetyGuard":
        if self._entered:
            raise RuntimeError("qualification safety guard is not reentrant")
        self._entered = True
        for key in tuple(os.environ):
            if is_credential_name(key):
                self._saved_credentials[key] = os.environ.pop(key)

        owner = self
        original_socket = socket.socket

        class GuardedSocket(original_socket):
            def _deny_network(self, operation: str) -> None:
                if self.family in {socket.AF_INET, socket.AF_INET6}:
                    owner._deny("network", operation)

            def bind(self, address: object) -> None:
                self._deny_network("socket.bind")
                return super().bind(address)  # type: ignore[arg-type]

            def connect(self, address: object) -> None:
                self._deny_network("socket.connect")
                return super().connect(address)  # type: ignore[arg-type]

            def connect_ex(self, address: object) -> int:
                self._deny_network("socket.connect_ex")
                return super().connect_ex(address)  # type: ignore[arg-type]

            def sendto(self, data: bytes, *args: object) -> int:
                self._deny_network("socket.sendto")
                return super().sendto(data, *args)  # type: ignore[arg-type]

        def deny_create_connection(*args: object, **kwargs: object) -> None:
            del args, kwargs
            owner._deny("network", "socket.create_connection")

        def deny_getaddrinfo(*args: object, **kwargs: object) -> None:
            del args, kwargs
            owner._deny("network", "socket.getaddrinfo")

        def deny_process(*args: object, **kwargs: object) -> None:
            del args, kwargs
            owner._deny("process", "subprocess")

        async def deny_async_process(*args: object, **kwargs: object) -> None:
            del args, kwargs
            owner._deny("process", "asyncio.subprocess")

        def deny_browser(*args: object, **kwargs: object) -> None:
            del args, kwargs
            owner._deny("browser", "webbrowser.open")

        def suppress_env_file_loading(*args: object, **kwargs: object) -> None:
            del args, kwargs
            return None

        patch_specs = (
            patch.object(socket, "socket", GuardedSocket),
            patch.object(socket, "create_connection", deny_create_connection),
            patch.object(socket, "getaddrinfo", deny_getaddrinfo),
            patch.object(subprocess, "Popen", deny_process),
            patch.object(subprocess, "run", deny_process),
            patch.object(subprocess, "call", deny_process),
            patch.object(subprocess, "check_call", deny_process),
            patch.object(subprocess, "check_output", deny_process),
            patch.object(os, "system", deny_process),
            patch.object(os, "popen", deny_process),
            patch.object(asyncio, "create_subprocess_exec", deny_async_process),
            patch.object(asyncio, "create_subprocess_shell", deny_async_process),
            patch.object(webbrowser, "open", deny_browser),
            patch.object(webbrowser, "open_new", deny_browser),
            patch.object(webbrowser, "open_new_tab", deny_browser),
            patch(
                "openzyme_runtime.settings.load_env_files",
                suppress_env_file_loading,
            ),
        )
        try:
            for patcher in patch_specs:
                patcher.start()
                self._patches.append(patcher)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        for patcher in reversed(self._patches):
            patcher.stop()
        self._patches.clear()
        os.environ.update(self._saved_credentials)
        self._saved_credentials.clear()
        self._entered = False


def validate_qualification_scenario_sources(
    *,
    repo_root: Path,
    source_files: tuple[str, ...],
) -> None:
    """Keep scenario action code on public/service/worker seams, never fixture truth."""

    violations: list[str] = []
    for relative in sorted(set(source_files)):
        path = repo_root / relative
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise QualificationSourcePolicyError(
                f"qualification scenario source {relative!r} is unreadable"
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_SCENARIO_NAMES:
                violations.append(f"{relative}:{node.lineno}:{node.id}")
            elif isinstance(node, ast.Attribute):
                if node.attr in {
                    "v3_legacy_repositories_for_tests",
                    "v3_repository_scope",
                }:
                    violations.append(f"{relative}:{node.lineno}:{node.attr}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_SCENARIO_MODULES:
                        violations.append(f"{relative}:{node.lineno}:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in _FORBIDDEN_SCENARIO_MODULES:
                    violations.append(f"{relative}:{node.lineno}:{module}")
                for alias in node.names:
                    if alias.name in _FORBIDDEN_SCENARIO_NAMES:
                        violations.append(f"{relative}:{node.lineno}:{alias.name}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"execute", "executemany", "executescript"}:
                    violations.append(f"{relative}:{node.lineno}:{node.func.attr}")
    if violations:
        raise QualificationSourcePolicyError(
            "qualification scenario source violates production-only policy: "
            + ", ".join(sorted(set(violations)))
        )


def record_local_fault_process_launch(
    *,
    registry: Mapping[str, object],
    ledger: ExternalEffectLedger,
    port_id: str,
    argv: tuple[str, ...],
    pid: int,
) -> None:
    modes = _declared_port_modes(registry)
    if modes.get(port_id) != "local_fault_process":
        raise QualificationSafetyViolation(
            f"local fault process port {port_id!r} is not registered"
        )
    ledger.append(
        port_id=port_id,
        operation="spawn",
        request={"argv": list(argv)},
        outcome=ControlledPortOutcome(
            acceptance=EffectAcceptance.ACCEPTED,
            response={"local_pid": pid, "non_cutover": True},
        ),
    )


__all__ = [
    "BlockedInvocation",
    "QualificationSafetyGuard",
    "QualificationSafetyViolation",
    "QualificationSourcePolicyError",
    "is_credential_name",
    "record_local_fault_process_launch",
    "scrubbed_environment",
    "validate_qualification_scenario_sources",
]
