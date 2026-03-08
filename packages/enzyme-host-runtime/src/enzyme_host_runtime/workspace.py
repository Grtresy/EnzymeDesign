from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from mcp_project_memory.models import utc_now_iso

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STATE_PATH = Path(".enzyme/cli_state.json")
_CONFIG_PATH = Path("enzyme.yaml")


class WorkspaceError(RuntimeError):
    pass


@dataclass(slots=True)
class ProjectConfig:
    project_id: str
    project_name: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": {
                "id": self.project_id,
                "name": self.project_name,
                "created_at": self.created_at,
            }
        }


@dataclass(slots=True)
class CliState:
    project_id: str
    project_root: str
    current_episode_id: str | None = None
    last_run_id: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at or utc_now_iso()
        return payload


@dataclass(slots=True)
class ProjectContext:
    root: Path
    config: ProjectConfig
    cli_state: CliState


def init_project(base_dir: Path, name: str) -> ProjectContext:
    project_id = sanitize_project_id(name)
    root = (base_dir / name).resolve()
    if root.exists():
        raise WorkspaceError(f"Project directory already exists: {root}")

    config = ProjectConfig(
        project_id=project_id,
        project_name=name,
        created_at=utc_now_iso(),
    )
    root.mkdir(parents=True, exist_ok=False)
    ensure_workspace_layout(root)
    _write_json(root / _CONFIG_PATH, config.to_dict())
    cli_state = CliState(project_id=project_id, project_root=str(root))
    write_cli_state(root, cli_state)
    return ProjectContext(root=root, config=config, cli_state=cli_state)


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    search_roots = [current]
    search_roots.extend(current.parents)
    for candidate in search_roots:
        if (candidate / _CONFIG_PATH).exists():
            return candidate
    raise WorkspaceError(f"Could not find OpenZyme project root from {start}")


def load_project_context(start: Path) -> ProjectContext:
    root = find_project_root(start)
    config = load_project_config(root)
    cli_state = read_cli_state(root)
    return ProjectContext(root=root, config=config, cli_state=cli_state)


def load_project_config(root: Path) -> ProjectConfig:
    payload = _read_json(root / _CONFIG_PATH)
    project = payload.get("project")
    if not isinstance(project, dict):
        raise WorkspaceError(f"Invalid project config: {root / _CONFIG_PATH}")
    project_id = str(project.get("id") or root.name)
    sanitize_project_id(project_id)
    created_at = str(project.get("created_at") or utc_now_iso())
    return ProjectConfig(
        project_id=project_id,
        project_name=str(project.get("name") or project_id),
        created_at=created_at,
    )


def ensure_workspace_layout(root: Path) -> None:
    (root / "data" / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "data" / "refs").mkdir(parents=True, exist_ok=True)
    (root / "episodes").mkdir(parents=True, exist_ok=True)
    (root / ".enzyme").mkdir(parents=True, exist_ok=True)


def read_cli_state(root: Path) -> CliState:
    state_path = root / _STATE_PATH
    if not state_path.exists():
        cli_state = CliState(project_id=load_project_config(root).project_id, project_root=str(root))
        write_cli_state(root, cli_state)
        return cli_state
    payload = _read_json(state_path)
    return CliState(
        project_id=str(payload.get("project_id") or load_project_config(root).project_id),
        project_root=str(payload.get("project_root") or root),
        current_episode_id=_as_optional_str(payload.get("current_episode_id")),
        last_run_id=_as_optional_str(payload.get("last_run_id")),
        updated_at=_as_optional_str(payload.get("updated_at")),
    )


def write_cli_state(root: Path, state: CliState) -> CliState:
    ensure_workspace_layout(root)
    if state.updated_at is None:
        state.updated_at = utc_now_iso()
    _write_json(root / _STATE_PATH, state.to_dict())
    return state


def allocate_episode_id(root: Path) -> str:
    episodes_dir = root / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    numeric_ids = []
    for child in episodes_dir.iterdir():
        if child.is_dir() and child.name.isdigit():
            numeric_ids.append(int(child.name))
    next_id = 1 if not numeric_ids else max(numeric_ids) + 1
    return f"{next_id:04d}"


def list_episode_ids(root: Path) -> list[str]:
    episodes_dir = root / "episodes"
    if not episodes_dir.exists():
        return []
    episode_ids = [child.name for child in episodes_dir.iterdir() if child.is_dir()]
    return sorted(episode_ids)


def set_current_episode(root: Path, episode_id: str | None) -> CliState:
    cli_state = read_cli_state(root)
    cli_state.current_episode_id = episode_id
    cli_state.updated_at = utc_now_iso()
    return write_cli_state(root, cli_state)


def set_last_run(root: Path, run_id: str | None) -> CliState:
    cli_state = read_cli_state(root)
    cli_state.last_run_id = run_id
    cli_state.updated_at = utc_now_iso()
    return write_cli_state(root, cli_state)


def resolve_episode_id(root: Path, explicit_episode_id: str | None = None) -> str:
    if explicit_episode_id:
        return explicit_episode_id
    cli_state = read_cli_state(root)
    if cli_state.current_episode_id:
        return cli_state.current_episode_id
    raise WorkspaceError("No active episode. Run `enzyme new-episode` first.")


def sanitize_project_id(value: str) -> str:
    candidate = value.strip()
    if not _PROJECT_ID_RE.match(candidate):
        raise WorkspaceError(
            "Project name must use only letters, numbers, dot, underscore, or dash"
        )
    return candidate


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    return rendered or None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Invalid JSON in {path}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
