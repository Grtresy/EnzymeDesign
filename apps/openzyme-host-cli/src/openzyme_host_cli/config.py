from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_HOST_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class HostCliConfig:
    base_url: str = DEFAULT_HOST_BASE_URL
    project_id: str | None = None
    episode_id: str | None = None
    output_format: str = "text"

    @classmethod
    def from_env(cls) -> "HostCliConfig":
        return cls(
            base_url=os.getenv("OPENZYME_HOST_BASE_URL", DEFAULT_HOST_BASE_URL),
            project_id=os.getenv("OPENZYME_PROJECT_ID") or None,
            episode_id=os.getenv("OPENZYME_EPISODE_ID") or None,
            output_format=os.getenv("OPENZYME_OUTPUT_FORMAT", "text"),
        )
