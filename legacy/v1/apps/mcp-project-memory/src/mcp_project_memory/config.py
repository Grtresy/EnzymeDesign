from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib


@dataclass(slots=True)
class ProjectMemoryConfig:
    projects_root: Path | None = None
    projects: dict[str, Path] = field(default_factory=dict)

    def resolve_project_root(self, project_id: str) -> Path:
        if project_id in self.projects:
            return self.projects[project_id]
        if self.projects_root is None:
            raise KeyError(f"Unknown project_id: {project_id}")
        return self.projects_root / project_id


def load_config(config_path: str | Path | None) -> ProjectMemoryConfig:
    config_file = (
        Path(config_path).expanduser()
        if config_path is not None
        else _default_config_path()
    )
    if config_file is None or not config_file.exists():
        return ProjectMemoryConfig()

    raw = tomllib.loads(config_file.read_text(encoding="utf-8"))
    base_dir = config_file.resolve().parent
    projects_root_raw = raw.get("projects_root")
    projects_root = _resolve_config_path(projects_root_raw, base_dir) if projects_root_raw else None
    projects_raw = raw.get("projects", {})
    projects = {
        project_id: _resolve_config_path(path, base_dir)
        for project_id, path in projects_raw.items()
    }
    return ProjectMemoryConfig(projects_root=projects_root, projects=projects)


def _default_config_path() -> Path | None:
    raw = os.getenv("PROJECT_MEMORY_CONFIG")
    return Path(raw).expanduser() if raw else None


def _resolve_config_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
