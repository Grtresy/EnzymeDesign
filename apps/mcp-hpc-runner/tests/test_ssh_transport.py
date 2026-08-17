from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import socket
import stat
import tempfile
from typing import Iterator

import pytest

from mcp_hpc_runner.config import ClusterConfig
from mcp_hpc_runner.config import ExecutionConfig
from mcp_hpc_runner.config import RunnerConfig
from mcp_hpc_runner.config import SshTransportMode
from mcp_hpc_runner.config import SshTransportPolicy
from mcp_hpc_runner.config import load_config
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.transport import SshChannelLimitError
from mcp_hpc_runner.transport import SshCommandCompiler
from mcp_hpc_runner.transport import SshControlRoot
from mcp_hpc_runner.transport import SshTransportIdentity
from mcp_hpc_runner.transport import SshTransportError
from mcp_hpc_runner.transport import SshTransportManager
from mcp_hpc_runner.transport import SshTransportOwnershipError


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.stages: list[str | None] = []

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:
        del check, timeout
        self.commands.append(list(args))
        self.stages.append(stage)
        return CommandResult(
            args=list(args),
            returncode=0,
            stdout="",
            stderr="",
            stage=stage,
        )


class HealthFailOnceRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_health = False

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:
        result = super().run(args, check=check, timeout=timeout, stage=stage)
        if stage == "transport_health" and self.fail_next_health:
            self.fail_next_health = False
            return replace(result, returncode=255, stderr="private ssh failure")
        return result


class ExitFailOnceRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_exit = False

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:
        result = super().run(args, check=check, timeout=timeout, stage=stage)
        if stage in {"transport_retire", "transport_shutdown"} and self.fail_next_exit:
            self.fail_next_exit = False
            return replace(result, returncode=255, stderr="private exit ambiguity")
        return result


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@contextmanager
def _short_private_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="ozt-", dir="/tmp") as raw:
        yield Path(raw) / "c"


def _config(
    root: Path,
    *,
    policy: SshTransportPolicy | None = None,
    cluster: ClusterConfig | None = None,
    deployment_id: str = "test-runner",
) -> RunnerConfig:
    return RunnerConfig(
        cluster=cluster
        or ClusterConfig(ssh_host="hpc-login", ssh_user="alice"),
        execution=ExecutionConfig(),
        ssh_transport=policy
        or SshTransportPolicy(
            mode=SshTransportMode.CONTROLMASTER_V1,
            channel_acquire_timeout_seconds=0.1,
        ),
        deployment_id=deployment_id,
        transport_control_root=str(root),
    )


def test_transport_policy_defaults_are_bounded_and_disabled() -> None:
    policy = SshTransportPolicy()

    assert policy.mode is SshTransportMode.DISABLED
    assert policy.control_persist_seconds == 300
    assert policy.max_channels_per_target == 4
    assert policy.connect_attempts == 1
    assert policy.pre_effect_recovery_attempts == 1
    assert policy.policy_digest.startswith("sha256:")

    with pytest.raises(ValueError, match="pre_effect_recovery_attempts"):
        replace(policy, pre_effect_recovery_attempts=2)
    with pytest.raises(ValueError, match="max_channels_per_target"):
        replace(policy, max_channels_per_target=0)
    with pytest.raises(ValueError):
        replace(policy, mode="interactive_shell")  # type: ignore[arg-type]


def test_load_config_resolves_transport_and_digest_authority(tmp_path: Path) -> None:
    config_path = tmp_path / "runner.toml"
    config_path.write_text(
        "\n".join(
            [
                "[runner]",
                'deployment_id = "host-a"',
                'transport_control_root = "private-control"',
                "[cluster]",
                'ssh_host = "HPC.EXAMPLE"',
                'ssh_user = "alice"',
                'credential_policy_id = "cred-a"',
                'host_key_policy_id = "known-hosts-a"',
                "[execution]",
                "[ssh_transport]",
                'mode = "controlmaster_v1"',
                "control_persist_seconds = 120",
                "max_channels_per_target = 2",
                "connect_attempts = 2",
                "pre_effect_recovery_attempts = 1",
                "backoff_initial_seconds = 0.1",
                "backoff_multiplier = 2.0",
                "backoff_max_seconds = 0.5",
                "health_check_interval_seconds = 2.0",
                "health_check_timeout_seconds = 1.0",
                "channel_acquire_timeout_seconds = 3.0",
                "shutdown_timeout_seconds = 4.0",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    changed = replace(
        config,
        ssh_transport=replace(config.ssh_transport, max_channels_per_target=3),
    )

    assert config.cluster.normalized_ssh_target == "alice@hpc.example"
    assert config.control_root == (tmp_path / "private-control").resolve()
    assert config.ssh_transport.mode is SshTransportMode.CONTROLMASTER_V1
    assert config.effective_config_digest.startswith("sha256:")
    assert config.effective_config_digest != changed.effective_config_digest

    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\nunsupported_knob = 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields"):
        load_config(config_path)

    config_path.write_text(
        "\n".join(
            [
                "[runner]",
                'deployment_id = "host-a"',
                "unrecognized_authority = true",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runner contains unsupported fields"):
        load_config(config_path)


def test_controlmaster_compiler_shares_one_control_path_without_stateful_shell(
    tmp_path: Path,
) -> None:
    control_path = tmp_path / "cm.sock"
    policy = SshTransportPolicy(mode=SshTransportMode.CONTROLMASTER_V1)
    compiler = SshCommandCompiler(
        target="alice@hpc-login",
        policy=policy,
        control_path=control_path,
    )

    ssh = compiler.ssh(["bash", "-lc", "cd /tmp && export A=1"])
    scp = compiler.scp_download("mcp_runs/r/out/x", tmp_path / "x", recursive=True)
    rsync_shell = compiler.rsync_remote_shell()
    marker = f"ControlPath={control_path}"

    assert marker in ssh
    assert marker in scp
    assert marker in rsync_shell
    assert compiler.master_start()[:2] == ["ssh", "-MNf"]
    assert "-tt" not in ssh
    assert "ControlMaster=yes" not in ssh
    assert ssh[-1] == "bash -lc 'cd /tmp && export A=1'"


def test_transport_identity_changes_for_every_authority_dimension() -> None:
    with _short_private_root() as root:
        baseline = _config(root)
        baseline_digest = SshTransportIdentity.from_config(baseline).identity_digest
        variants = [
            _config(root, deployment_id="other-runner"),
            _config(
                root,
                cluster=ClusterConfig(
                    ssh_host="other-hpc",
                    ssh_user="alice",
                ),
            ),
            _config(
                root,
                cluster=ClusterConfig(
                    ssh_host="hpc-login",
                    ssh_user="alice",
                    credential_policy_id="credential-b",
                ),
            ),
            _config(
                root,
                cluster=ClusterConfig(
                    ssh_host="hpc-login",
                    ssh_user="alice",
                    host_key_policy_id="known-hosts-b",
                ),
            ),
            _config(
                root,
                policy=replace(
                    baseline.ssh_transport,
                    control_persist_seconds=301,
                ),
            ),
        ]

        assert all(
            SshTransportIdentity.from_config(item).identity_digest != baseline_digest
            for item in variants
        )


def test_control_root_is_private_bounded_and_contains_no_target_metadata() -> None:
    with _short_private_root() as root_path:
        root = SshControlRoot(root_path, deployment_digest="sha256:" + "a" * 64)
        root.prepare()
        control_path = root.control_path("sha256:" + "b" * 64, 1)
        owner = root.record_owner(
            control_path,
            identity_digest="sha256:" + "b" * 64,
            generation=1,
            runner_nonce="nonce-only",
        )

        root_metadata = root_path / "root-owner.json"
        encoded = root_metadata.read_text(encoding="utf-8") + json.dumps(
            owner.to_dict()
        )
        assert stat.S_IMODE(root_path.stat().st_mode) == 0o700
        assert stat.S_IMODE(root_metadata.stat().st_mode) == 0o600
        assert len(str(control_path).encode("utf-8")) <= 100
        assert "hpc-login" not in encoded
        assert "alice" not in encoded
        assert "credential" not in encoded
        assert str(control_path) not in encoded


def test_transport_manager_rejects_an_overlong_control_root_before_creating_it(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / ("long-control-root-" + "x" * 96)

    with pytest.raises(
        ValueError,
        match="shorter runner.transport_control_root",
    ):
        SshTransportManager(
            _config(root_path),
            RecordingRunner(),  # type: ignore[arg-type]
        )

    assert not root_path.exists()


def test_example_control_root_supports_the_maximum_transport_generation() -> None:
    example_path = (
        Path(__file__).parents[1] / "config" / "hpc_runner.example.toml"
    )
    config = load_config(example_path)
    root = SshControlRoot(
        config.control_root,
        deployment_digest="sha256:" + "a" * 64,
    )

    control_path = root.control_path("sha256:" + "b" * 64, 999_999_999)

    assert len(str(control_path).encode("utf-8")) <= 100


def test_control_root_rejects_symlink_and_unsafe_mode(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(SshTransportOwnershipError, match="real directory"):
        SshControlRoot(link, deployment_digest="sha256:" + "a" * 64).prepare()

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    with pytest.raises(SshTransportOwnershipError, match="0700"):
        SshControlRoot(unsafe, deployment_digest="sha256:" + "a" * 64).prepare()


def test_owned_stale_socket_is_removed_but_foreign_socket_is_preserved() -> None:
    with _short_private_root() as root_path:
        root = SshControlRoot(root_path, deployment_digest="sha256:" + "a" * 64)
        root.prepare()
        identity = "sha256:" + "b" * 64
        owned_path = root.control_path(identity, 1)
        owned_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        owned_socket.bind(str(owned_path))
        root.record_owner(
            owned_path,
            identity_digest=identity,
            generation=1,
            runner_nonce="old-runner",
        )
        owned_socket.close()
        root.remove_owned_stale_socket(
            owned_path,
            identity_digest=identity,
            generation=1,
        )
        assert not owned_path.exists()

        foreign_path = root.control_path(identity, 2)
        foreign_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        foreign_socket.bind(str(foreign_path))
        root.record_owner(
            foreign_path,
            identity_digest="sha256:" + "c" * 64,
            generation=2,
            runner_nonce="foreign-runner",
        )
        foreign_socket.close()
        with pytest.raises(SshTransportOwnershipError, match="cannot be proven"):
            root.remove_owned_stale_socket(
                foreign_path,
                identity_digest=identity,
                generation=2,
            )
        assert foreign_path.exists()


def test_manager_reuses_generation_limits_channels_and_retires_owned_master() -> None:
    with _short_private_root() as root:
        runner = RecordingRunner()
        config = _config(
            root,
            policy=SshTransportPolicy(
                mode=SshTransportMode.CONTROLMASTER_V1,
                max_channels_per_target=1,
                channel_acquire_timeout_seconds=0.1,
            ),
        )
        manager = SshTransportManager(
            config,
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-a",
        )

        manager.run_ssh(["pwd"], stage="layout")
        manager.run_ssh(["true"], stage="preflight")
        with manager.channel():
            with pytest.raises(SshChannelLimitError, match="budget"):
                with manager.channel():
                    pass

        assert manager.current_generation == 1
        assert sum("-MNf" in command for command in runner.commands) == 1
        channel_commands = [
            command
            for command in runner.commands
            if command[-1] in {"pwd", "true"}
        ]
        assert len(channel_commands) == 2
        control_options = [
            item
            for command in channel_commands
            for item in command
            if item.startswith("ControlPath=")
        ]
        assert len(set(control_options)) == 1

        report = manager.shutdown()
        assert report["clean"] is True
        assert report["closed_generations"] == [1]
        assert manager.shutdown() == report
        assert any("exit" in command for command in runner.commands)


def test_recovery_generation_advances_beyond_persisted_attempt_generation() -> None:
    with _short_private_root() as root:
        runner = RecordingRunner()
        manager = SshTransportManager(
            _config(root),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-recovery",
        )

        assert manager.ensure_recovery_generation(after_generation=7) == 8
        assert manager.current_generation == 8
        assert manager.ensure_recovery_generation(after_generation=7) == 8
        assert sum("-MNf" in command for command in runner.commands) == 1

        with pytest.raises(ValueError, match="bound"):
            manager.ensure_recovery_generation(after_generation=999_999_999)


def test_fake_controlmaster_soak_reuses_and_rotates_owned_generations() -> None:
    with _short_private_root() as root:
        runner = RecordingRunner()
        manager = SshTransportManager(
            _config(root),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-soak",
        )

        expected_generation = 1
        for iteration in range(256):
            result = manager.run_ssh(
                ["true", f"soak-{iteration}"],
                stage="transport_soak",
            )
            assert result.returncode == 0
            if (iteration + 1) % 32 == 0 and iteration + 1 < 256:
                expected_generation = manager.replace_degraded_generation(
                    expected_generation=expected_generation
                )

        report = manager.shutdown()

        assert expected_generation == 8
        assert manager.current_generation == 0
        assert runner.stages.count("transport_soak") == 256
        assert sum("-MNf" in command for command in runner.commands) == 8
        assert runner.stages.count("transport_retire") == 7
        assert report["clean"] is True
        assert report["closed_generations"] == [8]
        assert list(root.glob("*.owner.json")) == []


def test_manager_replaces_only_the_expected_idle_generation() -> None:
    with _short_private_root() as root:
        runner = RecordingRunner()
        manager = SshTransportManager(
            _config(root),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-a",
        )
        manager.run_ssh(["true"])

        assert manager.replace_degraded_generation(expected_generation=1) == 2
        assert manager.current_generation == 2
        assert sum("-MNf" in command for command in runner.commands) == 2
        assert any("exit" in command for command in runner.commands)
        manager.shutdown()


def test_manager_health_failure_retires_generation_before_replacement() -> None:
    with _short_private_root() as root:
        runner = HealthFailOnceRunner()
        clock = MutableClock()
        manager = SshTransportManager(
            _config(
                root,
                policy=SshTransportPolicy(
                    mode=SshTransportMode.CONTROLMASTER_V1,
                    health_check_interval_seconds=0.1,
                    channel_acquire_timeout_seconds=0.1,
                ),
            ),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-a",
            monotonic=clock,
        )
        manager.run_ssh(["first"])
        clock.value = 1.0
        runner.fail_next_health = True

        manager.run_ssh(["second"])

        assert manager.current_generation == 2
        lifecycle_stages = [
            stage
            for stage in runner.stages
            if stage in {"transport_health", "transport_retire", "transport_connect"}
        ]
        assert lifecycle_stages == [
            "transport_connect",
            "transport_health",
            "transport_health",
            "transport_retire",
            "transport_connect",
            "transport_health",
        ]
        manager.shutdown()


def test_restart_advances_past_owned_stale_generation() -> None:
    with _short_private_root() as root:
        config = _config(root)
        first_runner = RecordingRunner()
        first = SshTransportManager(
            config,
            first_runner,  # type: ignore[arg-type]
            runner_nonce="runner-before-crash",
        )
        first.run_ssh(["true"])
        assert first.current_generation == 1

        replacement_runner = HealthFailOnceRunner()
        replacement_runner.fail_next_health = True
        restarted = SshTransportManager(
            config,
            replacement_runner,  # type: ignore[arg-type]
            runner_nonce="runner-after-crash",
        )
        restarted.run_ssh(["true"])

        assert restarted.current_generation == 2
        restarted.shutdown()


def test_shutdown_is_bounded_and_can_finish_after_active_channel_releases() -> None:
    with _short_private_root() as root:
        runner = RecordingRunner()
        manager = SshTransportManager(
            _config(
                root,
                policy=SshTransportPolicy(
                    mode=SshTransportMode.CONTROLMASTER_V1,
                    channel_acquire_timeout_seconds=0.1,
                    shutdown_timeout_seconds=0.1,
                ),
            ),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-a",
        )
        active = manager.channel()
        active.__enter__()

        incomplete = manager.shutdown()
        assert incomplete["clean"] is False
        assert incomplete["active_channels"] == 1
        assert incomplete["closed_generations"] == []
        with pytest.raises(SshTransportError, match="not accepting"):
            with manager.channel():
                pass

        active.__exit__(None, None, None)
        complete = manager.shutdown()
        assert complete["clean"] is True
        assert complete["active_channels"] == 0
        assert complete["closed_generations"] == [1]


def test_failed_master_exit_preserves_owner_evidence_until_confirmed() -> None:
    with _short_private_root() as root:
        runner = ExitFailOnceRunner()
        manager = SshTransportManager(
            _config(root),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-a",
        )
        manager.run_ssh(["true"])
        owner_paths = list(root.glob("*.owner.json"))
        assert len(owner_paths) == 1
        runner.fail_next_exit = True

        incomplete = manager.shutdown()

        assert incomplete["clean"] is False
        assert incomplete["closed_generations"] == []
        assert incomplete["unclosed_generation_count"] == 1
        assert owner_paths[0].exists()

        complete = manager.shutdown()
        assert complete["clean"] is True
        assert complete["closed_generations"] == [1]
        assert complete["unclosed_generation_count"] == 0
        assert not owner_paths[0].exists()


def test_failed_retire_is_isolated_and_retried_during_shutdown() -> None:
    with _short_private_root() as root:
        runner = ExitFailOnceRunner()
        manager = SshTransportManager(
            _config(root),
            runner,  # type: ignore[arg-type]
            runner_nonce="runner-a",
        )
        manager.run_ssh(["true"])
        runner.fail_next_exit = True

        assert manager.replace_degraded_generation(expected_generation=1) == 2
        assert len(list(root.glob("*.owner.json"))) == 2

        report = manager.shutdown()
        assert report["clean"] is True
        assert report["closed_generations"] == [1, 2]
        assert list(root.glob("*.owner.json")) == []
