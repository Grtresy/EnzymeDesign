from __future__ import annotations

from dataclasses import dataclass

from openzyme_domain import CORE_ENTITY_NAMES
from openzyme_graph import FIXED_PHASES
from openzyme_graph import GRAPH_THREAD_KEY
from openzyme_storage import HOST_UI_DEPENDENCY_EXPECTATIONS
from openzyme_storage import RELATIONAL_RECORDS


QUERY_RESOURCES: tuple[str, ...] = (
    "projects",
    "episodes",
    "runs",
    "artifacts",
    "reports",
    "pending_actions",
)

COMMAND_SURFACE: tuple[str, ...] = (
    "create_episode",
    "resume_episode",
    "resolve_approval",
)

STREAM_EVENT_TYPES: tuple[str, ...] = (
    "workflow.phase_changed",
    "workflow.progress_updated",
    "workflow.interrupt_pending",
    "workflow.approval_pending",
    "workflow.run_status_changed",
    "workflow.artifact_available",
    "workflow.report_available",
)

HOST_UI_CLOSED_LOOP_FIELDS: tuple[str, ...] = (
    "episode_id",
    "current_phase",
    "progress",
    "pending_interrupt",
    "pending_approval",
    "runs",
    "artifacts",
    "report",
)


@dataclass(frozen=True, slots=True)
class QueryResourceContract:
    resource_name: str
    canonical_source: str
    primary_id_field: str


@dataclass(frozen=True, slots=True)
class CommandContract:
    command_name: str
    required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkflowStreamEventContract:
    event_type: str
    required_fields: tuple[str, ...]
    source_stream_mode: str
    notes: str


@dataclass(frozen=True, slots=True)
class WorkflowProjection:
    required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunProjection:
    required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactProjection:
    required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportProjection:
    required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HostApiContract:
    query_resources: tuple[QueryResourceContract, ...]
    commands: tuple[CommandContract, ...]
    stream_events: tuple[WorkflowStreamEventContract, ...]
    workflow_projection: WorkflowProjection
    run_projection: RunProjection
    artifact_projection: ArtifactProjection
    report_projection: ReportProjection


def build_host_api_contract() -> HostApiContract:
    query_resources = (
        QueryResourceContract("projects", "projects", "project_id"),
        QueryResourceContract("episodes", "episodes", "episode_id"),
        QueryResourceContract("runs", "runs", "run_id"),
        QueryResourceContract("artifacts", "artifact_records", "artifact_id"),
        QueryResourceContract("reports", "reports", "report_id"),
        QueryResourceContract("pending_actions", "approvals", "approval_id"),
    )
    commands = (
        CommandContract("create_episode", ("project_id", "objective")),
        CommandContract("resume_episode", ("episode_id", "resume_payload")),
        CommandContract("resolve_approval", ("episode_id", "approval_id", "decision")),
    )
    stream_events = (
        WorkflowStreamEventContract(
            "workflow.phase_changed",
            ("episode_id", "phase", "updated_at"),
            "updates",
            "Projected from LangGraph state updates into a Host workflow event.",
        ),
        WorkflowStreamEventContract(
            "workflow.progress_updated",
            ("episode_id", "progress", "updated_at"),
            "updates",
            "Projected from structured graph progress state.",
        ),
        WorkflowStreamEventContract(
            "workflow.interrupt_pending",
            ("episode_id", "interrupt", "updated_at"),
            "updates",
            "Projected from LangGraph interrupt payloads surfaced by the runtime.",
        ),
        WorkflowStreamEventContract(
            "workflow.approval_pending",
            ("episode_id", "approval", "updated_at"),
            "updates",
            "Projected from interrupt payloads representing approval waits.",
        ),
        WorkflowStreamEventContract(
            "workflow.run_status_changed",
            ("episode_id", "run", "updated_at"),
            "updates",
            "Projected from run record and execution progress changes.",
        ),
        WorkflowStreamEventContract(
            "workflow.artifact_available",
            ("episode_id", "artifact", "updated_at"),
            "updates",
            "Projected when canonical artifact metadata becomes queryable.",
        ),
        WorkflowStreamEventContract(
            "workflow.report_available",
            ("episode_id", "report", "updated_at"),
            "updates",
            "Projected when a report record or report artifact becomes available.",
        ),
    )
    return HostApiContract(
        query_resources=query_resources,
        commands=commands,
        stream_events=stream_events,
        workflow_projection=WorkflowProjection(
            required_fields=("episode_id", "current_phase", "progress", "pending_interrupt", "pending_approval"),
        ),
        run_projection=RunProjection(
            required_fields=("run_id", "episode_id", "status", "execution_mode", "approval_id"),
        ),
        artifact_projection=ArtifactProjection(
            required_fields=("artifact_id", "episode_id", "run_id", "kind", "storage_uri"),
        ),
        report_projection=ReportProjection(
            required_fields=("report_id", "episode_id", "status", "artifact_id"),
        ),
    )


def validate_contract_alignment() -> None:
    assert "Episode" in CORE_ENTITY_NAMES
    assert GRAPH_THREAD_KEY == "episode_id"
    assert "episodes" in RELATIONAL_RECORDS
    assert "reports" in RELATIONAL_RECORDS
    assert "execution" in FIXED_PHASES
    assert any("frontend read models" in item for item in HOST_UI_DEPENDENCY_EXPECTATIONS)
