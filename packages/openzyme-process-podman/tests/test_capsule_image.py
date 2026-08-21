from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_process_podman import AgentCapsuleImageError
from openzyme_process_podman import CapsuleCommandResult
from openzyme_process_podman import build_agent_capsule_image
from openzyme_process_podman import load_agent_capsule_image_manifest
from openzyme_process_podman import PodmanAgentCapsuleProcessRunner
from openzyme_process_podman import qualify_agent_capsule_image


IMAGE_REF = "localhost/openzyme-agent-capsule@sha256:" + "a" * 64


class _Executor:
    def __init__(self, result: CapsuleCommandResult) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def run(self, argv, *, environment=None):
        self.calls.append((argv, environment))
        return self.result


def test_versioned_image_manifest_pins_required_native_toolchain() -> None:
    manifest = load_agent_capsule_image_manifest()
    versions = dict(manifest.package_versions)

    assert manifest.image_version == "1.1.0"
    assert manifest.base_image_requirement == "oci_digest_pinned"
    assert {"git", "git-lfs", "openssh-client", "python3", "rsync", "curl"}.issubset(
        versions
    )
    assert {"git", "git-lfs", "python3", "ssh", "rsync", "scp", "curl"}.issubset(
        manifest.required_binaries
    )
    assert manifest.credential_persistence == "forbidden"


def test_image_qualification_uses_no_host_mount_and_runs_packaged_probe() -> None:
    executor = _Executor(CapsuleCommandResult(0, "qualified", ""))
    qualification = qualify_agent_capsule_image(
        image_ref=IMAGE_REF,
        executor=executor,
        qualified_at="2026-08-16T02:00:00+00:00",
    )
    argv, environment = executor.calls[0]

    assert qualification.image_ref == IMAGE_REF
    assert environment is None
    assert "--rm" in argv
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--volume" not in argv
    assert "/home" not in " ".join(argv)
    assert "/.ssh" not in " ".join(argv)
    assert argv[-1] == "/usr/local/libexec/openzyme-agent-capsule-qualify"


def test_image_builder_rejects_mutable_base_and_output_tags() -> None:
    executor = _Executor(CapsuleCommandResult(0, "", ""))

    with pytest.raises(AgentCapsuleImageError, match="digest-pinned"):
        build_agent_capsule_image(
            base_image_ref="debian:bookworm-slim",
            output_image_ref="localhost/openzyme-agent-capsule:1.0.0",
            executor=executor,
        )
    with pytest.raises(AgentCapsuleImageError, match="versioned"):
        build_agent_capsule_image(
            base_image_ref="debian@sha256:" + "b" * 64,
            output_image_ref="localhost/openzyme-agent-capsule:latest",
            executor=executor,
        )
    assert executor.calls == []


def test_capsule_assets_package_only_domain_neutral_execution_sdk() -> None:
    containerfile = (
        files("openzyme_process_podman.agent_capsule_assets")
        .joinpath("Containerfile")
        .read_text(encoding="utf-8")
    )
    qualification = (
        files("openzyme_process_podman.agent_capsule_assets")
        .joinpath("qualification.sh")
        .read_text(encoding="utf-8")
    )

    assert "openzyme_execution_sdk" in containerfile
    assert "openzyme_execution_contracts" in containerfile
    assert "openzyme_execution_sdk" in qualification
    assert "openzyme_pipeline" not in containerfile + qualification


def test_retired_core_package_is_not_a_second_capsule_asset_authority() -> None:
    repository_root = Path(__file__).resolve().parents[3]

    assert not (repository_root / "packages/openzyme-core/pyproject.toml").exists()
    assert not (
        repository_root
        / "packages/openzyme-core/src/openzyme_core/agent_capsule_assets/manifest.json"
    ).exists()


def test_capsule_runner_uses_exact_volume_and_explicit_network() -> None:
    executor = _Executor(CapsuleCommandResult(7, "", "connection refused"))
    runner = PodmanAgentCapsuleProcessRunner(
        executor=executor,
        deployment_network="openzyme-agent-network",
    )
    workspace = SimpleNamespace(
        volume_id="openzyme-agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-g1",
        clone_logical_root="/workspace/repository",
        image_ref=IMAGE_REF,
    )

    result = runner.run(
        workspace=workspace,
        argv=("git", "status", "--short"),
        credential_environment=(),
        timeout_seconds=120,
    )
    argv, environment = executor.calls[0]

    assert result.returncode == 7
    assert argv[:5] == (
        "/usr/bin/podman",
        "run",
        "--rm",
        "--network",
        "openzyme-agent-network",
    )
    assert (
        "type=volume,src=openzyme-agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-g1,"
        "dst=/workspace,rw"
    ) in argv
    assert environment == {"PATH": "/usr/bin:/bin"}


def test_capsule_runner_rejects_unsafe_network_name_before_dispatch() -> None:
    executor = _Executor(CapsuleCommandResult(0, "", ""))

    with pytest.raises(ValueError, match="safe Podman network"):
        PodmanAgentCapsuleProcessRunner(
            executor=executor,
            deployment_network="network with spaces",
        )

    assert executor.calls == []
