from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import os
from pathlib import Path


DEFAULT_HOST_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class HostCliConfig:
    base_url: str = DEFAULT_HOST_BASE_URL
    project_id: str | None = None
    output_format: str = "text"
    auth_token: str | None = field(default=None, repr=False)
    release_identity_path: Path | None = None

    @classmethod
    def from_env(cls) -> "HostCliConfig":
        return cls(
            base_url=os.environ.get("OPENZYME_HOST_BASE_URL", DEFAULT_HOST_BASE_URL),
            project_id=os.environ.get("OPENZYME_PROJECT_ID") or None,
            output_format=os.environ.get("OPENZYME_OUTPUT_FORMAT", "text"),
            auth_token=os.environ.get("OPENZYME_HOST_AUTH_TOKEN") or None,
            release_identity_path=(
                Path(value).expanduser()
                if (value := os.environ.get("OPENZYME_RELEASE_IDENTITY_FILE"))
                else None
            ),
        )
