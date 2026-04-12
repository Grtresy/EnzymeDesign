from openzyme_graph import FIXED_PHASES
from openzyme_graph import GRAPH_THREAD_KEY
from openzyme_graph import RESUMABLE_STATUSES
from openzyme_graph import CheckpointLineage
from openzyme_graph import GraphPhase
from openzyme_graph import InterruptEnvelope
from openzyme_graph import InterruptType
from openzyme_graph import NodeProgress
from openzyme_graph import ProgressStatus
from openzyme_graph import ResumeAnchor
from openzyme_graph import SupervisorState
from openzyme_graph import SupervisorStatus
from openzyme_graph import build_langgraph_config
from openzyme_graph import build_resume_command_payload
from openzyme_graph import build_subgraph_contracts
from openzyme_graph.state import validate_domain_and_storage_alignment


def test_fixed_phases_are_stable() -> None:
    assert FIXED_PHASES == (
        "intake",
        "research",
        "design",
        "execution",
        "report_review",
    )


def test_supervisor_thread_uses_episode_id() -> None:
    checkpoint = CheckpointLineage(
        thread_id="ep_001",
        checkpoint_ns="supervisor",
        checkpoint_id="chk_001",
    )
    progress = NodeProgress(
        phase=GraphPhase.INTAKE,
        active_node="collect_constraints",
        status=ProgressStatus.RUNNING,
        updated_at="2026-04-11T12:00:00+00:00",
    )
    state = SupervisorState(
        episode_id="ep_001",
        current_phase=GraphPhase.INTAKE,
        status=SupervisorStatus.ACTIVE,
        checkpoint=checkpoint,
        progress=progress,
    )

    assert GRAPH_THREAD_KEY == "episode_id"
    assert state.thread_id == "ep_001"
    assert state.is_resumable is True
    assert SupervisorStatus.ACTIVE in RESUMABLE_STATUSES


def test_interrupt_envelope_is_normalized_for_resume() -> None:
    envelope = InterruptEnvelope(
        type=InterruptType.APPROVAL,
        episode_id="ep_001",
        phase=GraphPhase.EXECUTION,
        resume_anchor=ResumeAnchor(
            episode_id="ep_001",
            checkpoint=CheckpointLineage(
                thread_id="ep_001",
                checkpoint_ns="execution",
                checkpoint_id="chk_002",
            ),
            active_state_version=4,
        ),
        reason="Run submission requires approval",
    )

    payload = envelope.to_dict()
    assert payload["type"] == "approval"
    assert payload["phase"] == "execution"
    assert payload["resume_anchor"]["active_state_version"] == 4

    runtime_payload = envelope.to_runtime_interrupt_payload()
    assert runtime_payload["checkpoint_ns"] == "execution"
    assert runtime_payload["active_state_version"] == 4


def test_subgraph_contracts_cover_all_fixed_phases() -> None:
    contracts = build_subgraph_contracts()

    assert set(contracts.keys()) == set(GraphPhase)
    assert contracts[GraphPhase.INTAKE].required_inputs == (
        "episode_id",
        "user_goal",
        "project_context",
    )
    assert contracts[GraphPhase.INTAKE].completion_outputs == ("intake_handoff",)
    assert contracts[GraphPhase.RESEARCH].completion_outputs == ("research_handoff",)
    assert contracts[GraphPhase.DESIGN].completion_outputs == ("design_handoff",)
    assert contracts[GraphPhase.EXECUTION].completion_outputs == ("execution_handoff",)
    assert InterruptType.APPROVAL in contracts[GraphPhase.EXECUTION].interrupt_types


def test_graph_projection_alignment_is_explicit() -> None:
    progress = NodeProgress(
        phase=GraphPhase.REPORT_REVIEW,
        active_node="generate_report",
        status=ProgressStatus.WAITING,
        updated_at="2026-04-11T12:05:00+00:00",
        message="Waiting for final review",
    )

    assert progress.to_dict()["phase"] == "report_review"
    assert progress.to_dict()["status"] == "waiting"
    assert progress.to_runtime_progress_state()["active_node"] == "generate_report"


def test_graph_contract_reuses_domain_and_storage_boundaries() -> None:
    validate_domain_and_storage_alignment()


def test_langgraph_runtime_helpers_follow_official_thread_and_resume_shape() -> None:
    assert build_langgraph_config("ep_001") == {"configurable": {"thread_id": "ep_001"}}
    assert build_resume_command_payload(True) == {"resume": True}


def test_supervisor_runtime_state_is_projection_friendly() -> None:
    state = SupervisorState(
        episode_id="ep_001",
        current_phase=GraphPhase.EXECUTION,
        status=SupervisorStatus.INTERRUPTED,
        checkpoint=CheckpointLineage(
            thread_id="ep_001",
            checkpoint_ns="execution",
            checkpoint_id="chk_010",
        ),
        progress=NodeProgress(
            phase=GraphPhase.EXECUTION,
            active_node="await_approval",
            status=ProgressStatus.WAITING,
            updated_at="2026-04-11T12:10:00+00:00",
        ),
    )

    runtime_state = state.to_runtime_state()
    assert runtime_state["current_phase"] == "execution"
    assert runtime_state["checkpoint_id"] == "chk_010"
