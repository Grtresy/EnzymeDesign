from __future__ import annotations

from types import SimpleNamespace

import pytest

from openzyme_core import AgentCapsuleImageError
from openzyme_core import AgentWorkspaceVolumeAllocator
from openzyme_core import AgentWorkspaceVolumeFact
from openzyme_core import AgentWorkspaceVolumeIdentityError
from openzyme_core import CapsuleCommandResult
from openzyme_core import PodmanAgentWorkspaceCloneRunner
from openzyme_core import build_agent_capsule_image
from openzyme_core import load_agent_capsule_image_manifest
from openzyme_core import qualify_agent_capsule_image
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import GitObjectFormat


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

    assert manifest.image_version == "1.0.0"
    assert manifest.base_image_requirement == "oci_digest_pinned"
    assert {"git", "git-lfs", "openssh-client", "rsync", "curl"}.issubset(
        versions
    )
    assert {"git", "git-lfs", "ssh", "rsync", "scp", "curl"}.issubset(
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


class _VolumeBackend:
    def __init__(self, existing: AgentWorkspaceVolumeFact | None = None) -> None:
        self.existing = existing

    def inspect(self, volume_id: str):
        del volume_id
        return self.existing

    def create(self, volume_id: str, *, labels):
        self.existing = AgentWorkspaceVolumeFact(volume_id, labels)
        return self.existing


def test_volume_allocator_rejects_cross_agent_relabelling() -> None:
    existing = AgentWorkspaceVolumeFact(
        volume_id="openzyme-agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-g1",
        labels=tuple(
            sorted(
                {
                    "io.openzyme.workspace_id": "workspace_other",
                    "io.openzyme.session_id": "session_1",
                    "io.openzyme.agent_member_id": "member_other",
                    "io.openzyme.workspace_generation": "1",
                    "io.openzyme.volume_schema": "agent_workspace_volume@1",
                }.items()
            )
        ),
    )
    backend = _VolumeBackend(existing)
    allocator = AgentWorkspaceVolumeAllocator(backend)

    with pytest.raises(AgentWorkspaceVolumeIdentityError, match="owner labels"):
        allocator.require_exact_owner(
            existing,
            expected_labels=tuple(
                sorted(
                    {
                        "io.openzyme.workspace_id": "workspace_1",
                        "io.openzyme.session_id": "session_1",
                        "io.openzyme.agent_member_id": "member_1",
                        "io.openzyme.workspace_generation": "1",
                        "io.openzyme.volume_schema": "agent_workspace_volume@1",
                    }.items()
                )
            ),
        )


def test_clone_runner_uses_one_owned_volume_and_never_places_secret_in_argv() -> None:
    output = "\n".join(
        (
            "OPENZYME_REMOTE=https://git.internal/repository.git",
            "OPENZYME_OBJECT_FORMAT=sha1",
            "OPENZYME_HEAD=" + "1" * 40,
            "OPENZYME_TREE=" + "2" * 40,
            "OPENZYME_GIT_DIRECTORY=independent",
        )
    )
    executor = _Executor(CapsuleCommandResult(0, output, ""))
    runner = PodmanAgentWorkspaceCloneRunner(
        executor=executor,
        deployment_network="openzyme-agent-network",
    )
    workspace = SimpleNamespace(
        status=AgentGitWorkspaceStatus.PROVISIONING,
        volume_id="openzyme-agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-g1",
        image_ref=IMAGE_REF,
        internal_git_endpoint="https://git.internal/repository.git",
        base_commit="1" * 40,
        object_format=GitObjectFormat.SHA1,
        clone_logical_root="/workspace/repository",
    )
    token = "ozprovision1.secret.payload"
    result = runner.clone_exact_base(
        workspace=workspace,
        credential_token=token,
    )
    argv, environment = executor.calls[0]
    joined = " ".join(argv)

    assert result.head_commit == "1" * 40
    assert result.head_tree == "2" * 40
    assert "--rm" in argv
    assert "--network" in argv
    assert "openzyme-agent-network" in argv
    assert "--network=none" not in argv
    assert (
        "openzyme-agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-g1:/workspace:rw,U"
        in argv
    )
    assert token not in joined
    assert environment is not None
    assert environment["GIT_CONFIG_VALUE_0"] == f"Authorization: Bearer {token}"
    assert "--reference" not in joined
    assert "worktree" not in joined
    assert "/home/" not in joined
    assert "/.ssh" not in joined
