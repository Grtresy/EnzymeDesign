from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    approval_id: str | None
    engine_name: str
    runner_run_id: str
    status: RunStatus
    execution_mode: str
    remote_run_dir: str
    created_at: str
    updated_at: str
    finished_at: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


__all__ = ["RunRecord", "RunStatus"]
