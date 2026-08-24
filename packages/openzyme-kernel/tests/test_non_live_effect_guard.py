from __future__ import annotations

import socket
import subprocess
import webbrowser

import pytest

from scripts.test_gate.no_live_effects import ExternalEffectDenyGuard


def test_shared_non_live_guard_blocks_every_declared_effect_entry_point(
    deny_external_effects: ExternalEffectDenyGuard,
) -> None:
    with pytest.raises(AssertionError, match="socket.create_connection"):
        socket.create_connection(("127.0.0.1", 9))

    candidate = object()
    with pytest.raises(AssertionError, match="socket.socket.connect"):
        socket.socket.connect(candidate, ("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="socket.socket.connect_ex"):
        socket.socket.connect_ex(candidate, ("127.0.0.1", 9))

    with pytest.raises(AssertionError, match="subprocess.Popen"):
        subprocess.Popen(("forbidden-non-live-process",))  # noqa: S603
    with pytest.raises(AssertionError, match="subprocess.run"):
        subprocess.run(("forbidden-non-live-process",), check=False)  # noqa: S603
    with pytest.raises(AssertionError, match="webbrowser.open"):
        webbrowser.open("https://forbidden.invalid")

    assert deny_external_effects.attempts == [
        "socket.create_connection",
        "socket.socket.connect",
        "socket.socket.connect_ex",
        "subprocess.Popen",
        "subprocess.run",
        "webbrowser.open",
    ]
