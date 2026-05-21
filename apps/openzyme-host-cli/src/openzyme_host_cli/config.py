from __future__ import annotations

from dataclasses import dataclass
from openzyme_runtime import DEFAULT_HOST_BASE_URL
from openzyme_runtime import get_settings


@dataclass(frozen=True, slots=True)
class HostCliConfig:
    base_url: str = DEFAULT_HOST_BASE_URL
    project_id: str | None = None
    output_format: str = "text"

    @classmethod
    def from_env(cls) -> "HostCliConfig":
        settings = get_settings()
        return cls(
            base_url=settings.host_cli.base_url,
            project_id=settings.host_cli.project_id,
            output_format=settings.host_cli.output_format,
        )
