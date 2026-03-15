from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
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
class WorkflowBudgetConfig:
    max_decision_rounds: int = 6
    max_auto_actions: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_decision_rounds": self.max_decision_rounds,
            "max_auto_actions": self.max_auto_actions,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> WorkflowBudgetConfig:
        payload = payload or {}
        return cls(
            max_decision_rounds=max(1, int(payload.get("max_decision_rounds") or 6)),
            max_auto_actions=max(1, int(payload.get("max_auto_actions") or 3)),
        )


@dataclass(slots=True)
class TrustPolicyRuleConfig:
    tool: str
    decision: str = "allow"
    risk_level: str = "normal"
    policy_reason: str = ""
    plain_language_reason: str = ""
    trust_decision: str = "auto_allowed"
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "decision": self.decision,
            "risk_level": self.risk_level,
            "policy_reason": self.policy_reason,
            "plain_language_reason": self.plain_language_reason,
            "trust_decision": self.trust_decision,
            "rule_id": self.rule_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> TrustPolicyRuleConfig | None:
        if not isinstance(payload, dict):
            return None
        tool = str(payload.get("tool") or "").strip()
        if not tool:
            return None
        return cls(
            tool=tool,
            decision=str(payload.get("decision") or "allow"),
            risk_level=str(payload.get("risk_level") or "normal"),
            policy_reason=str(payload.get("policy_reason") or ""),
            plain_language_reason=str(payload.get("plain_language_reason") or ""),
            trust_decision=str(payload.get("trust_decision") or "auto_allowed"),
            rule_id=_as_optional_str(payload.get("rule_id")),
        )


@dataclass(slots=True)
class TrustPolicyConfig:
    default_decision: str = "allow"
    default_policy_reason: str = "No trust policy rule requires extra approval for this action."
    default_plain_language_reason: str = "这是低风险动作，当前策略允许系统直接继续。"
    default_trust_decision: str = "auto_allowed"
    rules: list[TrustPolicyRuleConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_decision": self.default_decision,
            "default_policy_reason": self.default_policy_reason,
            "default_plain_language_reason": self.default_plain_language_reason,
            "default_trust_decision": self.default_trust_decision,
            "rules": [item.to_dict() for item in self.rules],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> TrustPolicyConfig:
        payload = payload or {}
        rules = [
            item
            for raw in payload.get("rules") or []
            if (item := TrustPolicyRuleConfig.from_dict(raw)) is not None
        ]
        return cls(
            default_decision=str(payload.get("default_decision") or "allow"),
            default_policy_reason=str(
                payload.get("default_policy_reason")
                or "No trust policy rule requires extra approval for this action."
            ),
            default_plain_language_reason=str(
                payload.get("default_plain_language_reason")
                or "这是低风险动作，当前策略允许系统直接继续。"
            ),
            default_trust_decision=str(payload.get("default_trust_decision") or "auto_allowed"),
            rules=rules,
        )


@dataclass(slots=True)
class HostRuntimeConfig:
    workflow_budget: WorkflowBudgetConfig = field(default_factory=WorkflowBudgetConfig)
    trust_policy: TrustPolicyConfig = field(default_factory=TrustPolicyConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_budget": self.workflow_budget.to_dict(),
            "trust_policy": self.trust_policy.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> HostRuntimeConfig:
        payload = payload or {}
        return cls(
            workflow_budget=WorkflowBudgetConfig.from_dict(payload.get("workflow_budget")),
            trust_policy=TrustPolicyConfig.from_dict(payload.get("trust_policy")),
        )


@dataclass(slots=True)
class ProjectConfig:
    project_id: str
    project_name: str
    created_at: str
    host: HostRuntimeConfig = field(default_factory=HostRuntimeConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": {
                "id": self.project_id,
                "name": self.project_name,
                "created_at": self.created_at,
            },
            "host": self.host.to_dict(),
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
        host=HostRuntimeConfig.from_dict(payload.get("host")),
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
