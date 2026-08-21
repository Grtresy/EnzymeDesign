"""Provider-neutral local workspace volume facts and backend Port."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION = "agent_workspace_volume@1"
_SAFE_VOLUME_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")


class AgentWorkspaceVolumeError(RuntimeError):
    error_code = "agent_workspace_volume_error"


class AgentWorkspaceVolumeIdentityError(AgentWorkspaceVolumeError):
    error_code = "agent_workspace_volume_identity_mismatch"


@dataclass(frozen=True, slots=True)
class AgentWorkspaceVolumeFact:
    volume_id: str
    labels: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if _SAFE_VOLUME_NAME.fullmatch(self.volume_id) is None:
            raise ValueError("volume_id is not a safe native volume name")
        keys = tuple(key for key, _ in self.labels)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("volume labels must be unique and sorted")

    def label(self, key: str) -> str | None:
        return dict(self.labels).get(key)


class AgentWorkspaceVolumeBackendPort(Protocol):
    def inspect(self, volume_id: str) -> AgentWorkspaceVolumeFact | None: ...

    def create(
        self,
        volume_id: str,
        *,
        labels: tuple[tuple[str, str], ...],
    ) -> AgentWorkspaceVolumeFact: ...


__all__ = [
    "AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION",
    "AgentWorkspaceVolumeBackendPort",
    "AgentWorkspaceVolumeError",
    "AgentWorkspaceVolumeFact",
    "AgentWorkspaceVolumeIdentityError",
]
