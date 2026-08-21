from __future__ import annotations

import os
import socket
from typing import Any

import pytest


_LIVE_ENV_PREFIXES = (
    "ANTHROPIC_",
    "AWS_",
    "OPENAI_",
    "TAVILY_",
)
_LIVE_ENV_NAMES = frozenset(
    {
        "OPENZYME_AOX_LIVE_ENABLED",
        "OPENZYME_LIVE_E2E_ENABLED",
        "OPENZYME_LIVE_HPC_ENABLED",
    }
)
_FORBIDDEN_OUTCOMES: list[str] = []


def _reject_network(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise RuntimeError(
        "architecture qualification forbids undeclared IP network effects"
    )


@pytest.fixture(autouse=True)
def _no_ip_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", _reject_network)
    monkeypatch.setattr(socket.socket, "connect", _reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _reject_network)


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    _FORBIDDEN_OUTCOMES.clear()
    leaked = sorted(
        name
        for name, value in os.environ.items()
        if value
        and (
            name in _LIVE_ENV_NAMES
            or any(name.startswith(prefix) for prefix in _LIVE_ENV_PREFIXES)
        )
    )
    if leaked:
        raise pytest.UsageError(
            "architecture qualification child received live credentials or opt-ins: "
            + ", ".join(leaked)
        )


def pytest_runtest_logreport(report: Any) -> None:
    if report.skipped or getattr(report, "wasxfail", False):
        _FORBIDDEN_OUTCOMES.append(f"{report.nodeid}:{report.when}")


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int,
) -> None:
    del exitstatus
    if _FORBIDDEN_OUTCOMES:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                "architecture qualification rejected skip/xfail outcomes: "
                + ", ".join(sorted(set(_FORBIDDEN_OUTCOMES)))
            )


__all__: tuple[str, ...] = ()
