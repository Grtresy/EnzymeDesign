"""Effect guard for explicitly non-live diagnostic pytest processes."""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
from types import TracebackType
from typing import Any, Callable

import pytest

DIAGNOSTIC_GUARD_ENV = "OPENZYME_TEST_GATE_DIAGNOSTIC"


class DiagnosticEffectError(RuntimeError):
    """Raised when diagnostic collection or execution attempts an external effect."""


def _is_loopback_address(address: object) -> bool:
    if isinstance(address, str):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class DiagnosticEffectGuard:
    """Deny remote sockets and collection-time child processes."""

    def __init__(self, *, block_subprocesses: bool) -> None:
        self.block_subprocesses = block_subprocesses
        self._restored = False
        self._subprocesses_restored = not block_subprocesses
        self._original_socket_connect = socket.socket.connect
        self._original_socket_connect_ex = socket.socket.connect_ex
        self._original_create_connection = socket.create_connection
        self._original_popen = subprocess.Popen
        self._original_os_system = os.system
        self._original_os_popen = os.popen
        self._original_spawn: dict[str, Callable[..., Any]] = {}

    def install(self) -> None:
        original_connect = self._original_socket_connect
        original_connect_ex = self._original_socket_connect_ex
        original_create_connection = self._original_create_connection

        def guarded_connect(
            sock: socket.socket,
            address: object,
        ) -> None:
            if sock.family != socket.AF_UNIX and not _is_loopback_address(address):
                raise DiagnosticEffectError(
                    f"diagnostic effect guard blocked remote socket connect: {address!r}"
                )
            original_connect(sock, address)

        def guarded_connect_ex(
            sock: socket.socket,
            address: object,
        ) -> int:
            if sock.family != socket.AF_UNIX and not _is_loopback_address(address):
                raise DiagnosticEffectError(
                    "diagnostic effect guard blocked remote socket connect_ex: "
                    f"{address!r}"
                )
            return original_connect_ex(sock, address)

        def guarded_create_connection(
            address: tuple[str, int],
            timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
            source_address: tuple[str, int] | None = None,
            *,
            all_errors: bool = False,
        ) -> socket.socket:
            if not _is_loopback_address(address):
                raise DiagnosticEffectError(
                    "diagnostic effect guard blocked remote create_connection: "
                    f"{address!r}"
                )
            return original_create_connection(
                address,
                timeout,
                source_address,
                all_errors=all_errors,
            )

        socket.socket.connect = guarded_connect
        socket.socket.connect_ex = guarded_connect_ex
        socket.create_connection = guarded_create_connection
        if self.block_subprocesses:
            self._install_subprocess_guard()

    def _install_subprocess_guard(self) -> None:
        def blocked(*args: object, **kwargs: object) -> Any:
            del args, kwargs
            raise DiagnosticEffectError(
                "diagnostic effect guard blocked a child process during collection"
            )

        subprocess.Popen = blocked
        os.system = blocked
        os.popen = blocked
        for name in (
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
        ):
            candidate = getattr(os, name, None)
            if candidate is not None:
                self._original_spawn[name] = candidate
                setattr(os, name, blocked)

    def restore_subprocesses(self) -> None:
        if self._subprocesses_restored:
            return
        subprocess.Popen = self._original_popen
        os.system = self._original_os_system
        os.popen = self._original_os_popen
        for name, implementation in self._original_spawn.items():
            setattr(os, name, implementation)
        self._subprocesses_restored = True

    def restore(self) -> None:
        if self._restored:
            return
        self.restore_subprocesses()
        socket.socket.connect = self._original_socket_connect
        socket.socket.connect_ex = self._original_socket_connect_ex
        socket.create_connection = self._original_create_connection
        self._restored = True

    def __enter__(self) -> DiagnosticEffectGuard:
        self.install()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.restore()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        del session
        self.restore_subprocesses()

    def pytest_sessionfinish(
        self,
        session: pytest.Session,
        exitstatus: int | pytest.ExitCode,
    ) -> None:
        del session, exitstatus
        self.restore()

    def pytest_unconfigure(self, config: pytest.Config) -> None:
        del config
        self.restore()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("openzyme-test-gate")
    group.addoption(
        "--test-gate-diagnostic-guard",
        action="store_true",
        help="deny remote sockets and collection-time child processes",
    )


def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("--test-gate-diagnostic-guard"):
        return
    if os.environ.get(DIAGNOSTIC_GUARD_ENV) != "1":
        raise pytest.UsageError(
            f"{DIAGNOSTIC_GUARD_ENV}=1 is required for the diagnostic effect guard"
        )
    guard = DiagnosticEffectGuard(block_subprocesses=bool(config.option.collectonly))
    guard.install()
    config.pluginmanager.register(guard, "openzyme-test-gate-diagnostic-effect-guard")
