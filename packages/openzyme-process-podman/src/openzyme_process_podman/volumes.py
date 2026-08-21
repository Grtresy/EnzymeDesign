from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol

from openzyme_contracts import AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION
from openzyme_contracts import AgentWorkspaceVolumeBackendPort
from openzyme_contracts import AgentWorkspaceVolumeError
from openzyme_contracts import AgentWorkspaceVolumeFact
from openzyme_contracts import AgentWorkspaceVolumeIdentityError


_SAFE_VOLUME_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")
_OWNER_LABELS = (
    "io.openzyme.workspace_id",
    "io.openzyme.session_id",
    "io.openzyme.agent_member_id",
    "io.openzyme.workspace_generation",
    "io.openzyme.volume_schema",
)


AgentWorkspaceVolumeBackend = AgentWorkspaceVolumeBackendPort


class PodmanVolumeCommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class PodmanVolumeCommandExecutor(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str] | None = None,
    ) -> PodmanVolumeCommandResult: ...


@dataclass(slots=True)
class PodmanAgentWorkspaceVolumeBackend:
    """Podman named-volume mechanism; it owns no Session or workspace truth."""

    executor: PodmanVolumeCommandExecutor
    podman_binary: str = "podman"

    def inspect(self, volume_id: str) -> AgentWorkspaceVolumeFact | None:
        _require_safe_volume_id(volume_id)
        result = self.executor.run(
            (
                self.podman_binary,
                "volume",
                "inspect",
                "--format=json",
                volume_id,
            )
        )
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if "no such volume" in stderr or "not found" in stderr:
                return None
            raise AgentWorkspaceVolumeError(
                f"Podman volume inspection failed: {result.stderr.strip()}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AgentWorkspaceVolumeError(
                "Podman volume inspection did not return JSON"
            ) from exc
        if isinstance(payload, list):
            if len(payload) != 1 or not isinstance(payload[0], dict):
                raise AgentWorkspaceVolumeError(
                    "Podman volume inspection returned an ambiguous identity"
                )
            payload = payload[0]
        if not isinstance(payload, dict) or payload.get("Name") != volume_id:
            raise AgentWorkspaceVolumeError(
                "Podman volume inspection returned another volume identity"
            )
        raw_labels = payload.get("Labels") or {}
        if not isinstance(raw_labels, dict):
            raise AgentWorkspaceVolumeError("Podman volume labels are invalid")
        return AgentWorkspaceVolumeFact(
            volume_id=volume_id,
            labels=tuple(
                sorted((str(key), str(value)) for key, value in raw_labels.items())
            ),
        )

    def create(
        self,
        volume_id: str,
        *,
        labels: tuple[tuple[str, str], ...],
    ) -> AgentWorkspaceVolumeFact:
        _require_safe_volume_id(volume_id)
        argv: list[str] = [self.podman_binary, "volume", "create"]
        for key, value in labels:
            argv.extend(("--label", f"{key}={value}"))
        argv.append(volume_id)
        result = self.executor.run(tuple(argv))
        if result.returncode != 0:
            raise AgentWorkspaceVolumeError(
                f"Podman volume creation failed: {result.stderr.strip()}"
            )
        observed = self.inspect(volume_id)
        if observed is None:
            raise AgentWorkspaceVolumeError(
                "Podman did not persist the created volume identity"
            )
        return observed


@dataclass(slots=True)
class AgentWorkspaceVolumeAllocator:
    backend: AgentWorkspaceVolumeBackend

    def allocate(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
    ) -> AgentWorkspaceVolumeFact:
        if workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        for value, field_name in (
            (workspace_id, "workspace_id"),
            (session_id, "session_id"),
            (agent_member_id, "agent_member_id"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        volume_id = derive_agent_workspace_volume_id(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        expected_labels = tuple(
            sorted(
                {
                    "io.openzyme.workspace_id": workspace_id,
                    "io.openzyme.session_id": session_id,
                    "io.openzyme.agent_member_id": agent_member_id,
                    "io.openzyme.workspace_generation": str(workspace_generation),
                    "io.openzyme.volume_schema": (
                        AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION
                    ),
                }.items()
            )
        )
        existing = self.backend.inspect(volume_id)
        if existing is None:
            existing = self.backend.create(volume_id, labels=expected_labels)
        self.require_exact_owner(existing, expected_labels=expected_labels)
        return existing

    @staticmethod
    def require_exact_owner(
        fact: AgentWorkspaceVolumeFact,
        *,
        expected_labels: tuple[tuple[str, str], ...],
    ) -> None:
        actual = dict(fact.labels)
        expected = dict(expected_labels)
        mismatched = tuple(
            key for key in _OWNER_LABELS if actual.get(key) != expected.get(key)
        )
        if mismatched:
            raise AgentWorkspaceVolumeIdentityError(
                "workspace volume owner labels do not match: "
                + ", ".join(mismatched)
            )


def derive_agent_workspace_volume_id(
    *,
    session_id: str,
    agent_member_id: str,
    workspace_generation: int,
) -> str:
    if workspace_generation <= 0:
        raise ValueError("workspace_generation must be positive")
    identity = json.dumps(
        {
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "workspace_generation": workspace_generation,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    suffix = hashlib.sha256(identity).hexdigest()[:32]
    return f"openzyme-agent-{suffix}-g{workspace_generation}"


def _require_safe_volume_id(volume_id: str) -> None:
    if _SAFE_VOLUME_NAME.fullmatch(volume_id) is None:
        raise ValueError("volume_id is not a safe native volume name")


__all__ = [
    "AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION",
    "AgentWorkspaceVolumeAllocator",
    "AgentWorkspaceVolumeBackend",
    "AgentWorkspaceVolumeError",
    "AgentWorkspaceVolumeFact",
    "AgentWorkspaceVolumeIdentityError",
    "PodmanAgentWorkspaceVolumeBackend",
    "PodmanVolumeCommandExecutor",
    "PodmanVolumeCommandResult",
    "derive_agent_workspace_volume_id",
]
