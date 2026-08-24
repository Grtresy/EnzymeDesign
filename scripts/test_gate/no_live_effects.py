"""Shared fail-fast external-effect guard for non-live product tests."""

from __future__ import annotations

import socket
import subprocess
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

import pytest


@dataclass(slots=True)
class ExternalEffectDenyGuard:
    attempts: list[str] = field(default_factory=list)

    def rejector(self, effect: str) -> Callable[..., None]:
        def reject(*args: object, **kwargs: object) -> None:
            del args, kwargs
            self.attempts.append(effect)
            raise AssertionError(
                f"non-live product verification attempted forbidden {effect}"
            )

        return reject


@pytest.fixture
def deny_external_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> ExternalEffectDenyGuard:
    """Deny the network, process and browser seams used by external adapters."""

    guard = ExternalEffectDenyGuard()
    monkeypatch.setattr(
        socket,
        "create_connection",
        guard.rejector("socket.create_connection"),
    )
    monkeypatch.setattr(
        socket.socket,
        "connect",
        guard.rejector("socket.socket.connect"),
    )
    monkeypatch.setattr(
        socket.socket,
        "connect_ex",
        guard.rejector("socket.socket.connect_ex"),
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        guard.rejector("subprocess.Popen"),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        guard.rejector("subprocess.run"),
    )
    monkeypatch.setattr(
        webbrowser,
        "open",
        guard.rejector("webbrowser.open"),
    )
    return guard


__all__ = ["ExternalEffectDenyGuard", "deny_external_effects"]
