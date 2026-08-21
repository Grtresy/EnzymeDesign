from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

from openzyme_process_podman import AgentWorkspaceVolumeAllocator
from openzyme_process_podman import AgentWorkspaceVolumeError
from openzyme_process_podman import AgentWorkspaceVolumeFact
from openzyme_process_podman import AgentWorkspaceVolumeIdentityError
from openzyme_process_podman import PodmanAgentWorkspaceVolumeBackend
from openzyme_process_podman import derive_agent_workspace_volume_id


@dataclass(frozen=True, slots=True)
class _Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class _Executor:
    def __init__(self, results: list[_Result]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, *, environment=None):  # type: ignore[no-untyped-def]
        assert environment is None
        self.calls.append(tuple(argv))
        return self.results.pop(0)


def test_podman_volume_inspection_returns_exact_sorted_owner_fact() -> None:
    executor = _Executor(
        [
            _Result(
                0,
                json.dumps(
                    {
                        "Name": "openzyme-agent-test-g1",
                        "Labels": {"z": "last", "a": "first"},
                    }
                ),
            )
        ]
    )

    observed = PodmanAgentWorkspaceVolumeBackend(executor).inspect(
        "openzyme-agent-test-g1"
    )

    assert observed == AgentWorkspaceVolumeFact(
        volume_id="openzyme-agent-test-g1",
        labels=(("a", "first"), ("z", "last")),
    )
    assert executor.calls == [
        (
            "podman",
            "volume",
            "inspect",
            "--format=json",
            "openzyme-agent-test-g1",
        )
    ]


def test_podman_volume_absence_is_observed_without_creation() -> None:
    executor = _Executor([_Result(125, stderr="no such volume")])

    assert (
        PodmanAgentWorkspaceVolumeBackend(executor).inspect(
            "openzyme-agent-test-g1"
        )
        is None
    )


def test_podman_volume_create_reobserves_exact_native_identity() -> None:
    labels = (("io.openzyme.session_id", "sess_1"),)
    executor = _Executor(
        [
            _Result(0, stdout="openzyme-agent-test-g1\n"),
            _Result(
                0,
                stdout=json.dumps(
                    {
                        "Name": "openzyme-agent-test-g1",
                        "Labels": dict(labels),
                    }
                ),
            ),
        ]
    )

    observed = PodmanAgentWorkspaceVolumeBackend(executor).create(
        "openzyme-agent-test-g1",
        labels=labels,
    )

    assert observed.labels == labels
    assert executor.calls[0] == (
        "podman",
        "volume",
        "create",
        "--label",
        "io.openzyme.session_id=sess_1",
        "openzyme-agent-test-g1",
    )


def test_podman_volume_rejects_ambiguous_native_observation() -> None:
    executor = _Executor([_Result(0, stdout="[]")])

    with pytest.raises(AgentWorkspaceVolumeError, match="ambiguous identity"):
        PodmanAgentWorkspaceVolumeBackend(executor).inspect(
            "openzyme-agent-test-g1"
        )


def test_allocator_reuses_only_exact_owner_generation() -> None:
    volume_id = derive_agent_workspace_volume_id(
        session_id="sess_1",
        agent_member_id="member_1",
        workspace_generation=2,
    )
    conflicting = AgentWorkspaceVolumeFact(
        volume_id=volume_id,
        labels=tuple(
            sorted(
                {
                    "io.openzyme.workspace_id": "workspace_other",
                    "io.openzyme.session_id": "sess_1",
                    "io.openzyme.agent_member_id": "member_1",
                    "io.openzyme.workspace_generation": "2",
                    "io.openzyme.volume_schema": "agent_workspace_volume@1",
                }.items()
            )
        ),
    )

    class _Backend:
        def inspect(self, candidate: str) -> AgentWorkspaceVolumeFact | None:
            assert candidate == volume_id
            return conflicting

        def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("conflicting volume must not be replaced")

    with pytest.raises(AgentWorkspaceVolumeIdentityError, match="owner labels"):
        AgentWorkspaceVolumeAllocator(_Backend()).allocate(
            workspace_id="workspace_1",
            session_id="sess_1",
            agent_member_id="member_1",
            workspace_generation=2,
        )
