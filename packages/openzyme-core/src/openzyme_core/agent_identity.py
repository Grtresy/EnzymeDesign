from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Literal
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain.control_plane import utc_now_iso

from .repositories import CoreRepositories
from .teammate_roster import TEAMMATE_ROLE_NAMES


RESERVED_MASTER_AGENT_ID = "agent:master"

ROLE_NICKNAME_POOLS: dict[str, tuple[str, ...]] = {
    "researcher": ("Ada", "Curie", "Franklin", "Turing"),
    "executor": ("Michael", "Grace", "Linus", "Katherine"),
    "reporter": ("Sagan", "Carson", "McPhee", "Didion"),
}

_HANDLE_SAFE_RE = re.compile(r"[^a-z0-9_-]+")
_TEAMMATE_ROLE_SET = set(TEAMMATE_ROLE_NAMES)


class AgentIdentityError(ValueError):
    """Raised when an agent identity or reference violates V3 identity rules."""


@dataclass(frozen=True, slots=True)
class AgentReferenceResolution:
    agent: AgentMember | None
    resolution: str

    @property
    def agent_id(self) -> str | None:
        return None if self.agent is None else self.agent.agent_id


def is_teammate_role_alias(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in _TEAMMATE_ROLE_SET:
        return True
    if normalized.startswith("agent:"):
        return normalized.removeprefix("agent:") in _TEAMMATE_ROLE_SET
    return False


def require_canonical_agent_id(agent_id: str) -> str:
    normalized = agent_id.strip()
    if not normalized:
        raise AgentIdentityError("agent_id must be non-empty")
    if is_teammate_role_alias(normalized):
        raise AgentIdentityError(
            f"{normalized!r} is a teammate role alias, not a canonical agent_id"
        )
    if not normalized.startswith("agent:"):
        raise AgentIdentityError(
            f"{normalized!r} is not a canonical agent_id; expected an agent:* identity"
        )
    return normalized


def canonical_agent_id_for_new_member(role: str) -> str:
    if role not in _TEAMMATE_ROLE_SET and role != "master":
        raise AgentIdentityError(f"unknown agent role {role!r}")
    if role == "master":
        return RESERVED_MASTER_AGENT_ID
    return f"agent:{role}:{uuid4().hex[:12]}"


def normalize_handle(value: str) -> str:
    handle = value.strip()
    if not handle:
        raise AgentIdentityError("agent handle must be non-empty")
    if not handle.startswith("@"):
        handle = f"@{handle}"
    slug = _slugify(handle[1:])
    if not slug:
        raise AgentIdentityError(f"agent handle {value!r} does not contain a valid slug")
    return f"@{slug}"


def handle_for_nickname(nickname: str) -> str:
    return normalize_handle(nickname)


def display_name_for_agent(agent: AgentMember) -> str:
    return agent.display_name or agent.nickname or agent.name


def handle_for_agent(agent: AgentMember) -> str:
    return agent.handle or handle_for_nickname(display_name_for_agent(agent))


def resolve_agent_reference(
    repositories: CoreRepositories,
    *,
    session_id: str,
    reference: str,
) -> AgentReferenceResolution:
    normalized = reference.strip()
    if not normalized:
        return AgentReferenceResolution(agent=None, resolution="blank")
    if is_teammate_role_alias(normalized):
        return AgentReferenceResolution(agent=None, resolution="role_alias_forbidden")
    direct = repositories.agents.get(session_id, normalized)
    if direct is not None:
        return AgentReferenceResolution(agent=direct, resolution="agent_id")

    agents = repositories.agents.list_by_session(session_id)
    if normalized.startswith("@"):
        wanted = normalize_handle(normalized).lower()
        for agent in agents:
            if handle_for_agent(agent).lower() == wanted:
                return AgentReferenceResolution(agent=agent, resolution="handle")
        return AgentReferenceResolution(agent=None, resolution="handle_not_found")

    wanted_name = normalized.casefold()
    matches = [
        agent
        for agent in agents
        if wanted_name
        in {
            agent.name.casefold(),
            (agent.nickname or "").casefold(),
            (agent.display_name or "").casefold(),
        }
    ]
    if len(matches) == 1:
        return AgentReferenceResolution(agent=matches[0], resolution="name")
    if len(matches) > 1:
        return AgentReferenceResolution(agent=None, resolution="name_ambiguous")
    return AgentReferenceResolution(agent=None, resolution="unresolved")


def create_agent_member(
    repositories: CoreRepositories,
    *,
    session_id: str,
    role: Literal["researcher", "executor", "reporter"],
    lane_id: str | None = None,
    task_id: str | None = None,
    parent_agent_id: str | None = None,
) -> AgentMember:
    """Create one teammate with a canonical identity and project-unique handle."""

    session = repositories.sessions.get(session_id)
    if session is None:
        raise AgentIdentityError(f"session {session_id!r} does not exist")

    connection = repositories.agents.connection
    # This code path is the repository-level uniqueness backstop for generated
    # nicknames/handles. It reserves against all sessions in the same project.
    with connection:
        used_nicknames, used_handles = _used_project_identity_values(
            connection,
            project_id=session.project_id,
        )
        nickname, handle = _next_available_nickname_and_handle(
            role=role,
            used_nicknames=used_nicknames,
            used_handles=used_handles,
        )
        now = utc_now_iso()
        agent = AgentMember(
            agent_id=canonical_agent_id_for_new_member(role),
            session_id=session_id,
            lane_id=lane_id,
            task_id=task_id,
            name=nickname,
            role=role,
            status=AgentMemberStatus.IDLE,
            parent_agent_id=parent_agent_id,
            created_at=now,
            updated_at=now,
            runtime_state="idle",
            current_correlation_id=None,
            wakeup_reason=None,
            last_active_at=None,
            idle_since=now,
            shutdown_requested_at=None,
            member_id=f"member_{uuid4().hex[:12]}",
            nickname=nickname,
            display_name=nickname,
            handle=handle,
        )
        _insert_agent_member(connection, agent)
    return agent


def _next_available_nickname_and_handle(
    *,
    role: str,
    used_nicknames: set[str],
    used_handles: set[str],
) -> tuple[str, str]:
    pool = ROLE_NICKNAME_POOLS.get(role) or (role.title(),)
    suffix = 1
    while True:
        for base in pool:
            nickname = base if suffix == 1 else f"{base}-{suffix}"
            handle = handle_for_nickname(nickname)
            if nickname.casefold() in used_nicknames:
                continue
            if handle.lower() in used_handles:
                continue
            return nickname, handle
        suffix += 1


def _used_project_identity_values(
    connection: sqlite3.Connection,
    *,
    project_id: str,
) -> tuple[set[str], set[str]]:
    rows = connection.execute(
        """
        SELECT agent_members.name, agent_members.nickname, agent_members.display_name, agent_members.handle
        FROM agent_members
        JOIN sessions ON sessions.session_id = agent_members.session_id
        WHERE sessions.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    nicknames: set[str] = set()
    handles: set[str] = set()
    for row in rows:
        for value in (row["nickname"], row["display_name"], row["name"]):
            if value:
                nicknames.add(str(value).casefold())
        handle = row["handle"]
        if handle:
            handles.add(str(handle).lower())
    return nicknames, handles


def _insert_agent_member(connection: sqlite3.Connection, agent: AgentMember) -> None:
    connection.execute(
        """
        INSERT INTO agent_members (
            member_id, agent_id, session_id, lane_id, task_id, name, role, status,
            parent_agent_id, created_at, updated_at, runtime_state,
            current_correlation_id, wakeup_reason, last_active_at, idle_since,
            shutdown_requested_at, nickname, display_name, handle
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent.member_id,
            agent.agent_id,
            agent.session_id,
            agent.lane_id,
            agent.task_id,
            agent.name,
            agent.role,
            agent.status.value,
            agent.parent_agent_id,
            agent.created_at,
            agent.updated_at,
            agent.runtime_state,
            agent.current_correlation_id,
            agent.wakeup_reason,
            agent.last_active_at,
            agent.idle_since,
            agent.shutdown_requested_at,
            agent.nickname,
            agent.display_name,
            agent.handle,
        ),
    )


def _slugify(value: str) -> str:
    slug = value.strip().lower().replace(" ", "-")
    slug = _HANDLE_SAFE_RE.sub("-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-_")


__all__ = [
    "AgentIdentityError",
    "AgentReferenceResolution",
    "RESERVED_MASTER_AGENT_ID",
    "ROLE_NICKNAME_POOLS",
    "canonical_agent_id_for_new_member",
    "create_agent_member",
    "display_name_for_agent",
    "handle_for_agent",
    "handle_for_nickname",
    "is_teammate_role_alias",
    "normalize_handle",
    "require_canonical_agent_id",
    "resolve_agent_reference",
]
