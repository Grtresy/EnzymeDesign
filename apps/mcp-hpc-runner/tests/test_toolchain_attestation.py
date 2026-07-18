from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from mcp_hpc_runner.config import (
    ClusterConfig,
    ExecutionConfig,
    LoggingConfig,
    RunnerConfig,
    SlurmConfig,
)
from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.models import ExpectedOutput, RunSpec
from mcp_hpc_runner.preflight import PreflightChecker, PreflightResult
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.ssh_runner import (
    SSHRunner,
    _TOOLCHAIN_IDENTITY_MARKER,
    _command_with_toolchain_attestation,
)
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore


def _config(tmp_path: Path) -> RunnerConfig:
    return RunnerConfig(
        cluster=ClusterConfig(ssh_host="hpc-login", ssh_user="alice"),
        slurm=SlurmConfig(),
        execution=ExecutionConfig(artifact_root=str(tmp_path / "artifacts")),
        logging=LoggingConfig(),
    )


def _runtime_request() -> dict[str, object]:
    return {
        "schema_id": "mcp_hpc_toolchain_runtime_request@1",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "entrypoint_kind": "sif",
        "sif_locator": "~/containers/mafft_7.525.sif",
        "runner_contract_digest": "sha256:" + "b" * 64,
    }


def _spec(*, run_id: str = "attested-run") -> RunSpec:
    return RunSpec(
        name="attested-mafft",
        stage="execution",
        command=[
            "bash",
            "-lc",
            (
                'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/mafft"; '
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
                '"$HOME/containers/mafft_7.525.sif" mafft --auto /work/input.fasta '
                '> "$MCP_OUTDIR/bio_tools/mafft/alignment.fasta"'
            ),
        ],
        execution_mode="ssh",
        metadata={
            "tool_contract": {
                "adapter_id": "bio_tools.mafft",
                "preflight_hints": {
                    "entrypoint": {
                        "kind": "sif",
                        "path": "~/containers/mafft_7.525.sif",
                    }
                },
            },
            "toolchain_runtime_request": _runtime_request(),
        },
        run_id=run_id,
    )


class FakeCommandRunner:
    def __init__(
        self,
        remote_stdout: str,
        *,
        remote_returncode: int = 0,
        remote_stderr: str = "",
    ) -> None:
        self.remote_stdout = remote_stdout
        self.remote_returncode = remote_returncode
        self.remote_stderr = remote_stderr
        self.commands: list[tuple[str | None, list[str]]] = []

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:  # noqa: ARG002
        self.commands.append((stage, args))
        stdout = self.remote_stdout if stage == "remote_execution" else ""
        returncode = self.remote_returncode if stage == "remote_execution" else 0
        stderr = self.remote_stderr if stage == "remote_execution" else ""
        return CommandResult(
            args=args,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            stage=stage,
        )


def _runner(
    tmp_path: Path,
    command_runner: FakeCommandRunner,
) -> SSHRunner:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    staging = StagingManager(config, store, command_runner)  # type: ignore[arg-type]
    return SSHRunner(
        config,
        store,
        staging,
        command_runner,  # type: ignore[arg-type]
        FailureMapper(),
    )


def _clean_subprocess_environment(**overrides: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("APPTAINER_", "SINGULARITY_"))
    }
    environment.update(overrides)
    return environment


def test_attestation_and_payload_share_one_canonical_login_shell() -> None:
    spec = _spec()

    command = _command_with_toolchain_attestation(
        spec,
        _runtime_request(),
    )

    assert command[:2] == ["bash", "-lc"]
    script = command[2]
    assert script.index("_oz_digest_before") < script.index("command /usr/bin/apptainer exec")
    assert script.index("command /usr/bin/apptainer exec") < script.index("_oz_digest_after")
    assert script.index("_oz_digest_after") < script.index(_TOOLCHAIN_IDENTITY_MARKER)
    assert 'readonly _oz_sif="$HOME/containers/mafft_7.525.sif"' in script
    assert '"$_oz_sif" mafft --auto /work/input.fasta' in script
    assert '"$HOME/containers/mafft_7.525.sif" mafft' not in script
    assert script.count("/usr/bin/sha256sum") == 2
    assert script.count("bash -lc") == 0


def test_attestation_rejects_caller_identity_marker_literal() -> None:
    spec = _spec()
    spec.command[2] += f"; printf '{_TOOLCHAIN_IDENTITY_MARKER}{'a' * 64}\\n'; exit 0"

    with pytest.raises(ValueError, match="private identity marker"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_appended_payload_exit() -> None:
    spec = _spec()
    spec.command[2] += "; exit 0"

    with pytest.raises(ValueError, match="complete runner-owned canonical template"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_command_that_does_not_use_runner_owned_image() -> None:
    spec = _spec()
    spec.command[2] = 'printf "payload\\n"'

    with pytest.raises(ValueError, match="runner-owned image exactly once"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_image_reference_outside_apptainer_exec() -> None:
    spec = _spec()
    spec.command[2] = (
        'test -r "$HOME/containers/mafft_7.525.sif"; printf "payload\\n"'
    )

    with pytest.raises(ValueError, match="direct apptainer exec"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_another_sif_image() -> None:
    spec = _spec()
    spec.command[2] = (
        'apptainer exec "$HOME/containers/mafft_7.525.sif" '
        'mafft --version; apptainer exec /tmp/other.sif other-tool'
    )

    with pytest.raises(ValueError, match="another SIF image"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_home_rebinding() -> None:
    spec = _spec()
    spec.command[2] = (
        'HOME=/tmp; apptainer exec "$HOME/containers/mafft_7.525.sif" '
        'mafft --auto input.fasta'
    )

    with pytest.raises(ValueError, match="must not rebind HOME"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_wrong_template_entrypoint() -> None:
    spec = _spec()
    spec.command[2] = spec.command[2].replace(
        "mafft --auto /work/input.fasta",
        "hmmbuild model.hmm alignment.fasta",
    )

    with pytest.raises(ValueError, match="entrypoint does not match"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_sif_token_used_as_bind_value() -> None:
    spec = _spec()
    spec.command[2] = (
        'apptainer exec --bind "$HOME/containers/mafft_7.525.sif" '
        'mafft /tmp/other-rootfs --auto input.fasta'
    )

    with pytest.raises(ValueError, match="options do not match"):
        _command_with_toolchain_attestation(spec, _runtime_request())


def test_attestation_rejects_bind_over_runner_owned_container_paths() -> None:
    spec = _spec()
    spec.command[2] = spec.command[2].replace(
        '"$HOME/containers/mafft_7.525.sif"',
        '--bind "$MCP_WORKDIR/overlay:/opt/openzyme" '
        '"$HOME/containers/mafft_7.525.sif"',
    )

    with pytest.raises(ValueError, match="options do not match"):
        _command_with_toolchain_attestation(spec, _runtime_request())


@pytest.mark.parametrize(
    "suffix",
    [
        '; /tmp/fake-mafft > "$MCP_OUTDIR/bio_tools/mafft/alignment.fasta"',
        ' && /tmp/fake-mafft > "$MCP_OUTDIR/bio_tools/mafft/alignment.fasta"',
        '; printf fake > "$MCP_OUTDIR/bio_tools/mafft/alignment.fasta"',
    ],
)
def test_attestation_rejects_appended_native_or_fake_output_producers(
    suffix: str,
) -> None:
    spec = _spec()
    spec.command[2] += suffix

    with pytest.raises(ValueError, match="complete runner-owned canonical template"):
        _command_with_toolchain_attestation(spec, _runtime_request())


@pytest.mark.parametrize("mutate_during_exec", [False, True])
def test_attested_shell_signs_only_an_unchanged_executed_sif(
    tmp_path: Path,
    mutate_during_exec: bool,
) -> None:
    home = tmp_path / "home"
    sif_path = home / "containers" / "mafft_7.525.sif"
    sif_path.parent.mkdir(parents=True)
    sif_path.write_bytes(b"immutable-mafft-sif\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_apptainer = fake_bin / "apptainer"
    fake_apptainer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"${MUTATE_SIF:-0}\" = 1 ]; then\n"
        "  for argument in \"$@\"; do\n"
        "    case \"$argument\" in *.sif) printf x >> \"$argument\";; esac\n"
        "  done\n"
        "fi\n"
        "printf 'payload\\n'\n",
        encoding="utf-8",
    )
    fake_apptainer.chmod(0o755)
    command = _command_with_toolchain_attestation(
        _spec(),
        _runtime_request(),
        apptainer_executable=str(fake_apptainer),
    )
    environment = _clean_subprocess_environment(
        HOME=str(home),
        PATH=f"{fake_bin}:{os.environ.get('PATH', '')}",
        MUTATE_SIF="1" if mutate_during_exec else "0",
        MCP_WORKDIR=str(tmp_path / "work"),
        MCP_OUTDIR=str(tmp_path / "out"),
        MCP_TMPDIR=str(tmp_path / "tmp"),
    )

    completed = subprocess.run(
        ["bash", "-c", command[2]],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    if mutate_during_exec:
        assert completed.returncode == 86
        assert _TOOLCHAIN_IDENTITY_MARKER not in completed.stdout
    else:
        digest = hashlib.sha256(sif_path.read_bytes()).hexdigest()
        assert completed.returncode == 0
        assert completed.stdout == f"{_TOOLCHAIN_IDENTITY_MARKER}{digest}\n"


def test_preflight_checks_runner_bound_sif_but_does_not_claim_execution_digest(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    command_runner = FakeCommandRunner("")
    checker = PreflightChecker(config, command_runner)  # type: ignore[arg-type]

    descriptors = checker._build_check_descriptors(_spec(), "mcp_runs/run-001")

    assert descriptors[0] == {
        "kind": "binary",
        "path": "/usr/bin/apptainer",
        "severity": "error",
    }
    assert descriptors[1] == {
        "kind": "sif",
        "path": "~/containers/mafft_7.525.sif",
        "severity": "error",
    }
    assert all("content_digest" not in descriptor for descriptor in descriptors)


@pytest.mark.parametrize(
    "executable",
    ["apptainer", "../bin/apptainer", "/usr/bin/apptainer;true", "/usr/bin/tool"],
)
def test_execution_config_rejects_noncanonical_apptainer_executable(
    executable: str,
) -> None:
    with pytest.raises(ValueError, match="absolute path ending in /apptainer"):
        ExecutionConfig(apptainer_executable=executable)


def test_attestation_ignores_path_shims_and_uses_fixed_absolute_executable(
    tmp_path: Path,
) -> None:
    fake_path_shim = tmp_path / "bin" / "apptainer"
    fake_path_shim.parent.mkdir()
    fake_path_shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    command = _command_with_toolchain_attestation(_spec(), _runtime_request())

    assert "command /usr/bin/apptainer exec" in command[2]
    assert f"command {fake_path_shim} exec" not in command[2]


@pytest.mark.parametrize(
    "runtime_environment_name",
    ("APPTAINER_BIND", "SINGULARITY_BINDPATH"),
)
def test_attestation_scrubs_inherited_runtime_control_environment(
    tmp_path: Path,
    runtime_environment_name: str,
) -> None:
    home = tmp_path / "home"
    sif_path = home / "containers" / "mafft_7.525.sif"
    sif_path.parent.mkdir(parents=True)
    sif_path.write_bytes(b"immutable-mafft-sif\n")
    fake_apptainer = tmp_path / "bin" / "apptainer"
    fake_apptainer.parent.mkdir()
    invoked = tmp_path / "invoked"
    fake_apptainer.write_text(
        (
            "#!/bin/sh\n"
            'if [ "${APPTAINER_BIND+x}" = x ] || '
            '[ "${SINGULARITY_BINDPATH+x}" = x ]; then exit 91; fi\n'
            f"printf invoked > {invoked}\n"
        ),
        encoding="utf-8",
    )
    fake_apptainer.chmod(0o755)
    command = _command_with_toolchain_attestation(
        _spec(),
        _runtime_request(),
        apptainer_executable=str(fake_apptainer),
    )

    completed = subprocess.run(
        ["bash", "-c", command[2]],
        check=False,
        capture_output=True,
        text=True,
        env={
            **_clean_subprocess_environment(
                HOME=str(home),
                MCP_WORKDIR=str(tmp_path / "work"),
                MCP_OUTDIR=str(tmp_path / "out"),
                MCP_TMPDIR=str(tmp_path / "tmp"),
            ),
            runtime_environment_name: str(tmp_path / "overlay") + ":/opt/openzyme",
        },
    )

    digest = hashlib.sha256(sif_path.read_bytes()).hexdigest()
    assert completed.returncode == 0
    assert invoked.exists()
    assert completed.stdout == f"{_TOOLCHAIN_IDENTITY_MARKER}{digest}\n"


def test_attestation_fails_closed_when_runtime_control_environment_is_readonly(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    sif_path = home / "containers" / "mafft_7.525.sif"
    sif_path.parent.mkdir(parents=True)
    sif_path.write_bytes(b"immutable-mafft-sif\n")
    fake_apptainer = tmp_path / "bin" / "apptainer"
    fake_apptainer.parent.mkdir()
    invoked = tmp_path / "invoked"
    fake_apptainer.write_text(
        f"#!/bin/sh\nprintf invoked > {invoked}\n",
        encoding="utf-8",
    )
    fake_apptainer.chmod(0o755)
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        "readonly APPTAINER_BIND=/blocked-runtime-control\n",
        encoding="utf-8",
    )
    command = _command_with_toolchain_attestation(
        _spec(),
        _runtime_request(),
        apptainer_executable=str(fake_apptainer),
    )

    completed = subprocess.run(
        ["bash", "-c", command[2]],
        check=False,
        capture_output=True,
        text=True,
        env=_clean_subprocess_environment(
            HOME=str(home),
            MCP_WORKDIR=str(tmp_path / "work"),
            MCP_OUTDIR=str(tmp_path / "out"),
            MCP_TMPDIR=str(tmp_path / "tmp"),
            BASH_ENV=str(bash_env),
        ),
    )

    assert completed.returncode == 87
    assert not invoked.exists()
    assert _TOOLCHAIN_IDENTITY_MARKER not in completed.stdout


def test_ssh_runner_emits_closed_identity_and_removes_private_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest_hex = "a" * 64
    command_runner = FakeCommandRunner(
        f"payload\n{_TOOLCHAIN_IDENTITY_MARKER}{digest_hex}\n"
    )
    monkeypatch.setattr(
        "mcp_hpc_runner.ssh_runner.run_preflight",
        lambda *_args, **_kwargs: PreflightResult(checks=[], passed=True),
    )

    result = _runner(tmp_path, command_runner).exec_run(_spec())

    assert result.status == "completed"
    assert result.stdout == "payload\n"
    assert _TOOLCHAIN_IDENTITY_MARKER not in str(result.logs)
    assert result.metadata["toolchain_runtime_identity"] == {
        "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "runner_contract_digest": "sha256:" + "b" * 64,
        "image_digest": "sha256:" + digest_hex,
    }


@pytest.mark.parametrize(
    "remote_stdout",
    [
        "payload\n",
        f"{_TOOLCHAIN_IDENTITY_MARKER}not-a-digest\npayload\n",
        (
            f"{_TOOLCHAIN_IDENTITY_MARKER}{'a' * 64}\n"
            f"{_TOOLCHAIN_IDENTITY_MARKER}{'b' * 64}\npayload\n"
        ),
    ],
)
def test_ssh_runner_fails_closed_when_attestation_marker_is_not_unique_and_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_stdout: str,
) -> None:
    command_runner = FakeCommandRunner(remote_stdout)
    monkeypatch.setattr(
        "mcp_hpc_runner.ssh_runner.run_preflight",
        lambda *_args, **_kwargs: PreflightResult(checks=[], passed=True),
    )

    result = _runner(tmp_path, command_runner).exec_run(_spec())

    assert result.status == "failed"
    assert result.error_code == "TOOLCHAIN_IDENTITY_MISSING"
    assert result.metadata["toolchain_runtime_identity"] is None
    assert _TOOLCHAIN_IDENTITY_MARKER not in result.stdout


def test_ssh_runner_preserves_transport_timeout_over_missing_success_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_runner = FakeCommandRunner(
        "",
        remote_returncode=255,
        remote_stderr="Connection to 192.0.2.10 port 22222 timed out\n",
    )
    monkeypatch.setattr(
        "mcp_hpc_runner.ssh_runner.run_preflight",
        lambda *_args, **_kwargs: PreflightResult(checks=[], passed=True),
    )

    result = _runner(tmp_path, command_runner).exec_run(_spec())

    assert result.status == "failed"
    assert result.error_code == "SSH_CONNECTION_TIMEOUT"
    assert result.metadata["toolchain_runtime_identity"] is None
    assert result.metadata["status"] == "failed"
    assert result.metadata["exit_code"] == 255
    assert result.metadata["error_code"] == "SSH_CONNECTION_TIMEOUT"


def test_ssh_runner_preserves_unknown_nonzero_over_missing_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_runner = FakeCommandRunner("", remote_returncode=23)
    monkeypatch.setattr(
        "mcp_hpc_runner.ssh_runner.run_preflight",
        lambda *_args, **_kwargs: PreflightResult(checks=[], passed=True),
    )
    spec = _spec(run_id="unknown-nonzero")
    spec.expected_outputs = [
        ExpectedOutput(
            path="bio_tools/mafft/alignment.fasta",
            required=True,
            non_empty=True,
        )
    ]

    result = _runner(tmp_path, command_runner).exec_run(spec)

    assert result.status == "failed"
    assert result.error_code == "RUN_FAILED"
    assert result.artifacts == {}
    assert result.metadata["validation"]["missing_outputs"] == [
        "bio_tools/mafft/alignment.fasta"
    ]
    assert all(stage != "artifact_fetch" for stage, _ in command_runner.commands)
