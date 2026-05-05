from __future__ import annotations

import json

from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRecord
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_artifact_tools
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus


def _build_context() -> tuple[CoreRepositories, SessionRuntimeContext]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session(
        session_id="sess_artifacts",
        project_id="proj_001",
        title="Artifact reads",
        objective="Read a large dossier",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-20T12:00:00+00:00",
        updated_at="2026-04-20T12:00:00+00:00",
    )
    task = Task(
        task_id="task_research",
        session_id=session.session_id,
        subject="Research",
        description="Collect evidence",
        status=TaskStatus.COMPLETED,
        priority=TaskPriority.HIGH,
        kind="research",
        assigned_ref="agent:researcher",
        created_at="2026-04-20T12:00:01+00:00",
        updated_at="2026-04-20T12:00:02+00:00",
    )
    repositories.sessions.save(session)
    repositories.tasks.save(task)
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_large",
            session_id=session.session_id,
            task_id=task.task_id,
            lane_id=None,
            engine_name="deep_research",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref="eng_in_large",
            output_ref="eng_out_large",
            approval_id=None,
            idempotency_key="task_research:deep_research:test",
            started_at="2026-04-20T12:01:00+00:00",
            finished_at="2026-04-20T12:02:00+00:00",
        )
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="eng_in_large",
            session_id=session.session_id,
            invocation_id="inv_large",
            document_kind="deep_research_input",
            payload={"brief": "collect evidence"},
            created_at="2026-04-20T12:01:00+00:00",
            updated_at="2026-04-20T12:01:00+00:00",
        )
    )
    evidence_items = [
        {
            "summary": f"Evidence item {index}",
            "query": "enzyme thermostability",
            "confidence_label": "high",
            "sources": [{"title": f"Paper {index}", "locator": f"https://example.org/{index}", "kind": "paper"}],
        }
        for index in range(60)
    ]
    source_refs = [
        {"title": f"Paper {index}", "locator": f"https://example.org/{index}", "kind": "paper"}
        for index in range(60)
    ]
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="eng_out_large",
            session_id=session.session_id,
            invocation_id="inv_large",
            document_kind="deep_research_dossier",
            payload={
                "status": "completed",
                "completion_reason": "research_completed",
                "research_brief": "collect evidence",
                "summary": "Large dossier summary",
                "evidence_items": evidence_items,
                "source_refs": source_refs,
                "unresolved_gaps": ["Need validation"],
                "artifacts": [],
                "raw_notes": [],
                "recent_turns": [],
                "large_lookup": {f"key_{index:03d}": {"value": "x" * 500} for index in range(60)},
                "clarification_question": None,
            },
            created_at="2026-04-20T12:02:00+00:00",
            updated_at="2026-04-20T12:02:00+00:00",
        )
    )
    repositories.research_summaries.save(
        ResearchSummary(
            summary_id="inv_large:summary",
            session_id=session.session_id,
            task_id=task.task_id,
            lane_id=None,
            invocation_id="inv_large",
            status=ResearchSummaryStatus.COMPLETED,
            completion_reason="research_completed",
            research_brief="collect evidence",
            summary="Large dossier summary",
            clarification_question=None,
            created_at="2026-04-20T12:02:00+00:00",
            updated_at="2026-04-20T12:02:00+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="inv_large:dossier",
            session_id=session.session_id,
            task_id=task.task_id,
            lane_id=None,
            invocation_id="inv_large",
            run_id=None,
            kind=ArtifactKind.RESEARCH_DOSSIER,
            storage_uri="engine-document://eng_out_large",
            relative_path="deep-research/inv_large/dossier.json",
            title="Deep research dossier",
            description="Normalized dossier",
            metadata={"output_ref": "eng_out_large", "evidence_count": 60, "source_ref_count": 60, "gap_count": 1},
            created_at="2026-04-20T12:02:01+00:00",
        )
    )
    registry = ToolRegistry()
    register_artifact_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    return repositories, context


def _dispatch(context: SessionRuntimeContext, arguments: dict[str, object]) -> dict[str, object]:
    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_artifact",
            tool_name="artifact.get",
            arguments=arguments,
        ),
    )
    assert result.ok is True
    return json.loads(result.content)


def test_artifact_get_summarizes_large_research_dossier_by_default() -> None:
    _repositories, context = _build_context()

    payload = _dispatch(context, {"artifact_id": "inv_large:dossier"})

    assert payload["artifact"]["kind"] == "research_dossier"
    assert payload["output_document"]["document_id"] == "eng_out_large"
    assert payload["canonical_summary"]["summary"] == "Large dossier summary"
    assert payload["counts"]["evidence_items"] == 60
    assert "evidence_items" not in payload["output_payload"]
    omitted_paths = {item["path"] for item in payload["omitted_fields"]}
    assert "output_payload.evidence_items" in omitted_paths
    assert "output_payload.source_refs" in omitted_paths


def test_artifact_get_pages_large_research_dossier_fields_and_clamps_limit() -> None:
    _repositories, context = _build_context()

    first_page = _dispatch(
        context,
        {
            "artifact_id": "inv_large:dossier",
            "path": "output_payload.evidence_items",
            "limit": 30,
        },
    )
    clamped_page = _dispatch(
        context,
        {
            "artifact_id": "inv_large:dossier",
            "path": "output_payload.source_refs",
            "limit": 100,
        },
    )

    assert len(first_page["items"]) == 30
    assert first_page["next_offset"] == 30
    assert len(clamped_page["items"]) == 50
    assert clamped_page["limit"] == 50


def test_artifact_get_pages_large_dict_keys_for_path_discovery() -> None:
    _repositories, context = _build_context()

    page = _dispatch(
        context,
        {
            "artifact_id": "inv_large:dossier",
            "path": "output_payload.large_lookup",
            "limit": 3,
        },
    )

    assert page["type"] == "dict"
    assert page["item_count"] > 3
    assert len(page["keys"]) == 3
    assert page["keys"][0]["path"].startswith("output_payload.large_lookup.")
    assert page["next_offset"] == 3


def test_artifact_get_reports_missing_path_with_top_level_options() -> None:
    _repositories, context = _build_context()
    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_artifact",
            tool_name="artifact.get",
            arguments={"artifact_id": "inv_large:dossier", "path": "output_payload.missing"},
        ),
    )

    payload = json.loads(result.content)
    assert result.ok is False
    assert "does not exist" in payload["error"]
    assert "output_payload" in payload["available_top_level_paths"]
