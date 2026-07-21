from __future__ import annotations

import json

import pytest

from mcp_hpc_runner import cli
from mcp_hpc_runner.remote import CommandResult


class _FakeTransportManager:
    enabled = True

    def __init__(self) -> None:
        self.current_generation = 1
        self.commands: list[list[str]] = []

    def run_ssh(self, remote_argv: list[str], **_: object) -> CommandResult:
        self.commands.append(list(remote_argv))
        return CommandResult(
            args=list(remote_argv),
            returncode=0,
            stdout="",
            stderr="",
        )

    def replace_degraded_generation(self, *, expected_generation: int) -> int:
        assert expected_generation == self.current_generation
        self.current_generation += 1
        return self.current_generation


class _FakeServer:
    instances: list[_FakeServer] = []

    def __init__(self, _config: object) -> None:
        self.transport_manager = _FakeTransportManager()
        self.config = type(
            "Config",
            (),
            {
                "execution": type(
                    "Execution",
                    (),
                    {"preflight_timeout_seconds": 1.0},
                )()
            },
        )()
        self.instances.append(self)

    def close(self) -> dict[str, object]:
        return {
            "clean": True,
            "ambiguous_direct_run_count": 0,
        }


def test_transport_soak_requires_double_opt_in_before_server_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN", raising=False)
    monkeypatch.setattr(cli, "MCPHpcServer", _FakeServer)
    _FakeServer.instances.clear()

    with pytest.raises(ValueError, match="requires --confirm-real-ssh"):
        cli.main(["transport-soak", "--confirm-real-ssh"])

    assert _FakeServer.instances == []


def test_transport_soak_runs_only_bounded_true_channels_and_redacts_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN", "true")
    monkeypatch.setattr(cli, "MCPHpcServer", _FakeServer)
    _FakeServer.instances.clear()

    assert (
        cli.main(
            [
                "transport-soak",
                "--confirm-real-ssh",
                "--iterations",
                "5",
                "--replace-every",
                "2",
            ]
        )
        == 0
    )

    server = _FakeServer.instances[0]
    assert server.transport_manager.commands == [["true"]] * 5
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "ambiguous_direct_run_count": 0,
        "clean_shutdown": True,
        "generation_count": 3,
        "iterations": 5,
        "kind": "non_scientific_real_ssh",
        "schema_version": "ssh_transport_soak_report@1",
    }
