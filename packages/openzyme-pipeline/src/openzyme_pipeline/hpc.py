from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import call


@dataclass(frozen=True, slots=True)
class HpcWorkspace:
    hpc_workspace_id: str
    label: str
    normalized_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "hpc_workspace",
            "hpc_workspace_id": self.hpc_workspace_id,
            "label": self.label,
            "normalized_label": self.normalized_label,
        }

    def stage_artifact(self, artifact_id: str, *, workspace_path: str) -> dict[str, Any]:
        return dict(
            call(
                "hpc.stage_artifact",
                {
                    "hpc_workspace": self.to_dict(),
                    "artifact_id": artifact_id,
                    "workspace_path": workspace_path,
                },
            )
        )

    def fetch_outputs(self, run: dict[str, Any] | str) -> dict[str, Any]:
        run_id = run if isinstance(run, str) else str(run.get("run_id") or "")
        return dict(
            call(
                "hpc.fetch_outputs",
                {
                    "hpc_workspace": self.to_dict(),
                    "run_id": run_id,
                },
            )
        )


def workspace(label: str) -> HpcWorkspace:
    payload = dict(call("hpc.workspace", {"label": label}))
    return HpcWorkspace(
        hpc_workspace_id=str(payload["hpc_workspace_id"]),
        label=str(payload["label"]),
        normalized_label=str(payload["normalized_label"]),
    )


__all__ = ["HpcWorkspace", "workspace"]
