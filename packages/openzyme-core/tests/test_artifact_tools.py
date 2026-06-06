from __future__ import annotations

import json
from pathlib import Path

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


def _dispatch(context: SessionRuntimeContext, arguments: dict[str, object], tool_name: str = "artifact.get") -> dict[str, object]:
    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_artifact",
            tool_name=tool_name,
            arguments=arguments,
        ),
    )
    assert result.ok is True
    return json.loads(result.content)


def _dispatch_result(context: SessionRuntimeContext, arguments: dict[str, object], tool_name: str) -> tuple[object, dict[str, object]]:
    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id=f"call_{tool_name}",
            tool_name=tool_name,
            arguments=arguments,
        ),
    )
    return result, json.loads(result.content)


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


def _save_file_artifact(
    repositories: CoreRepositories,
    *,
    path: Path,
    artifact_id: str,
    relative_path: str,
    kind: ArtifactKind = ArtifactKind.RESULT,
    metadata: dict[str, object] | None = None,
) -> None:
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id="sess_artifacts",
            task_id="task_research",
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=kind,
            storage_uri=str(path),
            relative_path=relative_path,
            title=relative_path,
            description=None,
            metadata=metadata or {},
            created_at="2026-04-20T12:03:00+00:00",
        )
    )


def test_artifact_catalog_tools_do_not_return_storage_uri(tmp_path: Path) -> None:
    repositories, context = _build_context()
    fasta = tmp_path / "protein.fasta"
    fasta.write_text(">seq\nMSEQUENCE\n", encoding="utf-8")
    _save_file_artifact(
        repositories,
        path=fasta,
        artifact_id="art_fasta",
        relative_path="inputs/protein.fasta",
        kind=ArtifactKind.SEQUENCE,
        metadata={"format": "fasta", "source_storage_uri": "/tmp/private/source.fasta"},
    )

    listed = _dispatch(context, {}, tool_name="artifact.list")
    fetched = _dispatch(context, {"artifact_id": "art_fasta"})

    assert "storage_uri" not in json.dumps(listed)
    assert "source_storage_uri" not in json.dumps(listed)
    assert "storage_uri" not in json.dumps(fetched)
    assert "source_storage_uri" not in json.dumps(fetched)


def test_artifact_list_paginates_and_filters_by_kind(tmp_path: Path) -> None:
    repositories, context = _build_context()
    for index in range(3):
        path = tmp_path / f"result_{index}.json"
        path.write_text("{}", encoding="utf-8")
        _save_file_artifact(
            repositories,
            path=path,
            artifact_id=f"art_result_{index}",
            relative_path=f"results/{index}.json",
            kind=ArtifactKind.RESULT,
            metadata={"format": "json"},
        )
    log_path = tmp_path / "run.log"
    log_path.write_text("ok", encoding="utf-8")
    _save_file_artifact(
        repositories,
        path=log_path,
        artifact_id="art_log",
        relative_path="logs/run.log",
        kind=ArtifactKind.LOG,
        metadata={"format": "log"},
    )

    first = _dispatch(
        context,
        {"kind": "result", "offset": 0, "limit": 2},
        tool_name="artifact.list",
    )
    second = _dispatch(
        context,
        {"kind": "result", "offset": first["next_offset"], "limit": 2},
        tool_name="artifact.list",
    )

    assert first["total_count"] == 3
    assert first["offset"] == 0
    assert first["limit"] == 2
    assert first["next_offset"] == 2
    assert [item["kind"] for item in first["artifacts"]] == ["result", "result"]
    assert second["next_offset"] is None
    assert [item["artifact_id"] for item in second["artifacts"]] == ["art_result_2"]


def test_artifact_get_summarizes_tool_result_full_artifact_by_default() -> None:
    repositories, context = _build_context()
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="eng_tool_result",
            session_id=context.snapshot.session.session_id,
            invocation_id=None,
            document_kind="tool_result_full",
            payload={
                "status": "persisted",
                "reason": "next_prompt_over_budget",
                "token_estimate": 12000,
                "tool_name": "huge.tool",
                "call_id": "call_huge",
                "original_tool_ok": True,
                "original_status": "ok",
                "tool_result": {
                    "ok": True,
                    "status": "ok",
                    "summary": "large result",
                    "content": "x" * 5000,
                },
            },
            created_at="2026-04-20T12:04:00+00:00",
            updated_at="2026-04-20T12:04:00+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_tool_result",
            session_id=context.snapshot.session.session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri="engine-document://eng_tool_result",
            relative_path="tool_results/call_huge.json",
            title="Full tool result",
            description=None,
            metadata={"output_ref": "eng_tool_result", "document_kind": "tool_result_full"},
            created_at="2026-04-20T12:04:01+00:00",
        )
    )

    default_payload = _dispatch(context, {"artifact_id": "art_tool_result"})
    full_page = _dispatch(
        context,
        {
            "artifact_id": "art_tool_result",
            "path": "output_payload.tool_result",
            "offset": 0,
            "limit": 30,
        },
    )

    assert default_payload["output_payload"]["original_tool_ok"] is True
    assert default_payload["output_payload"]["tool_result_summary"] == "large result"
    assert "tool_result" not in default_payload["output_payload"]
    assert {
        item["path"] for item in default_payload["omitted_fields"]
    } == {"output_payload.tool_result"}
    assert full_page["value"]["content"] == "x" * 5000


def test_artifact_tools_reject_cross_session_artifact(tmp_path: Path) -> None:
    repositories, context = _build_context()
    other_path = tmp_path / "other.md"
    other_path.write_text("# other\n", encoding="utf-8")
    repositories.sessions.save(
        Session(
            session_id="sess_other",
            project_id="proj_001",
            title="Other",
            objective="Other session",
            status=SessionStatus.ACTIVE,
            created_at="2026-04-20T12:00:00+00:00",
            updated_at="2026-04-20T12:00:00+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_other",
            session_id="sess_other",
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.REPORT,
            storage_uri=str(other_path),
            relative_path="other.md",
            title="other.md",
            description=None,
            metadata={"format": "markdown"},
            created_at="2026-04-20T12:04:00+00:00",
        )
    )

    for tool_name, arguments in (
        ("artifact.get", {"artifact_id": "art_other"}),
        ("artifact.preview", {"artifact_id": "art_other"}),
        ("artifact.read_text", {"artifact_id": "art_other"}),
        ("artifact.range", {"artifact_id": "art_other", "start_line": 1}),
    ):
        result = context.tool_registry.dispatch(
            context,
            ToolInvocation(call_id=f"call_{tool_name}", tool_name=tool_name, arguments=arguments),
        )
        assert result.ok is False
        assert result.error_code == "artifact_not_found"
        assert "current session" in result.content


def test_artifact_text_preview_read_and_range_for_common_formats(tmp_path: Path) -> None:
    repositories, context = _build_context()
    samples = {
        "art_fasta": ("protein.fasta", ">seq\nMSEQ\n", ArtifactKind.SEQUENCE, {"format": "fasta"}),
        "art_pdb": ("protein.pdb", "ATOM      1  CA  ALA A   1       0.0 0.0 0.0\nEND\n", ArtifactKind.STRUCTURE, {"format": "pdb"}),
        "art_log": ("run.log", "line 1\nline 2\nline 3\n", ArtifactKind.LOG, {"format": "log"}),
        "art_json": ("result.json", "{\"ok\": true}\n", ArtifactKind.RESULT, {"format": "json"}),
        "art_md": ("report.md", "# Report\nBody\n", ArtifactKind.REPORT, {"format": "markdown"}),
    }
    for artifact_id, (filename, content, kind, metadata) in samples.items():
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        _save_file_artifact(
            repositories,
            path=path,
            artifact_id=artifact_id,
            relative_path=filename,
            kind=kind,
            metadata=metadata,
        )

    preview = _dispatch(context, {"artifact_id": "art_fasta", "lines": 1}, tool_name="artifact.preview")
    read_text = _dispatch(context, {"artifact_id": "art_json", "offset": 0, "limit": 20}, tool_name="artifact.read_text")
    line_range = _dispatch(context, {"artifact_id": "art_log", "start_line": 2, "end_line": 3}, tool_name="artifact.range")
    pdb_range = _dispatch(context, {"artifact_id": "art_pdb", "start_line": 1, "end_line": 1}, tool_name="artifact.range")
    md_preview = _dispatch(context, {"artifact_id": "art_md"}, tool_name="artifact.preview")

    assert preview["preview"] == ">seq"
    assert read_text["content"] == "{\"ok\": true}\n"
    assert line_range["lines"] == ["line 2", "line 3"]
    assert pdb_range["lines"][0].startswith("ATOM")
    assert md_preview["preview"].startswith("# Report")
    assert "storage_uri" not in json.dumps([preview, read_text, line_range, pdb_range, md_preview])


def test_artifact_read_text_truncates_large_file(tmp_path: Path) -> None:
    repositories, context = _build_context()
    large = tmp_path / "large.log"
    large.write_text("0123456789" * 200, encoding="utf-8")
    _save_file_artifact(
        repositories,
        path=large,
        artifact_id="art_large_log",
        relative_path="large.log",
        kind=ArtifactKind.LOG,
        metadata={"format": "log"},
    )

    payload = _dispatch(
        context,
        {"artifact_id": "art_large_log", "offset": 0, "limit": 25},
        tool_name="artifact.read_text",
    )

    assert payload["returned_chars"] == 25
    assert payload["next_offset"] == 25
    assert payload["truncated"] is True


def test_binary_artifact_returns_readable_error(tmp_path: Path) -> None:
    repositories, context = _build_context()
    binary = tmp_path / "array.npy"
    binary.write_bytes(b"\x93NUMPY\x00\x01binary")
    _save_file_artifact(
        repositories,
        path=binary,
        artifact_id="art_binary",
        relative_path="array.npy",
        kind=ArtifactKind.RESULT,
        metadata={"format": "npy"},
    )

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_binary",
            tool_name="artifact.preview",
            arguments={"artifact_id": "art_binary"},
        ),
    )
    payload = json.loads(result.content)

    assert result.ok is False
    assert result.error_code == "artifact_not_text"
    assert payload["error_code"] == "artifact_not_text"
    assert "storage_uri" not in json.dumps(payload)


def test_artifact_create_text_creates_versioned_pipeline_source() -> None:
    repositories, context = _build_context()

    payload = _dispatch(
        context,
        {
            "filename": "aox_hmm_pipeline.py",
            "content": "def main():\n    return 1\n",
            "title": "AOX/HMM pipeline",
        },
        tool_name="artifact.create_text",
    )

    artifact_id = str(payload["artifact"]["artifact_id"])
    artifact = repositories.artifacts.get(artifact_id)
    assert artifact is not None
    assert artifact.kind is ArtifactKind.CODE
    assert artifact.title == "AOX/HMM pipeline"
    assert f"/v1/{artifact_id}/aox_hmm_pipeline.py" in artifact.relative_path
    assert artifact.metadata is not None
    assert artifact.metadata["format"] == "python"
    assert artifact.metadata["semantic_type"] == "pipeline_source"
    assert artifact.metadata["version"] == 1
    assert artifact.metadata["lineage_root_artifact_id"] == artifact_id
    assert str(artifact.metadata["content_digest"]).startswith("sha256:")
    assert "storage_uri" not in json.dumps(payload)

    read_back = _dispatch(context, {"artifact_id": artifact_id}, tool_name="artifact.read_text")
    assert read_back["content"] == "def main():\n    return 1\n"
    assert any(event.event_type == "artifact.recorded" for event in context.event_sink.events)


def test_artifact_patch_text_creates_new_version_and_preserves_base() -> None:
    repositories, context = _build_context()
    created = _dispatch(
        context,
        {"filename": "pipeline.py", "content": "def main():\n    return 1\n"},
        tool_name="artifact.create_text",
    )
    base_id = str(created["artifact"]["artifact_id"])
    base_digest = str(created["content_digest"])

    patched = _dispatch(
        context,
        {
            "base_artifact_id": base_id,
            "base_content_digest": base_digest,
            "content": "def main():\n    return 2\n",
        },
        tool_name="artifact.patch_text",
    )

    new_id = str(patched["artifact"]["artifact_id"])
    assert new_id != base_id
    new_artifact = repositories.artifacts.get(new_id)
    assert new_artifact is not None
    assert new_artifact.metadata is not None
    assert new_artifact.metadata["version"] == 2
    assert new_artifact.metadata["parent_artifact_id"] == base_id
    assert new_artifact.metadata["lineage_root_artifact_id"] == base_id
    assert new_artifact.metadata["content_digest"] != base_digest

    base_read = _dispatch(context, {"artifact_id": base_id}, tool_name="artifact.read_text")
    new_read = _dispatch(context, {"artifact_id": new_id}, tool_name="artifact.read_text")
    assert base_read["content"] == "def main():\n    return 1\n"
    assert new_read["content"] == "def main():\n    return 2\n"

    diff = _dispatch(
        context,
        {"base_artifact_id": base_id, "target_artifact_id": new_id},
        tool_name="artifact.diff_text",
    )
    assert "-    return 1" in diff["diff"]
    assert "+    return 2" in diff["diff"]
    assert "storage_uri" not in json.dumps([patched, diff])


def test_artifact_patch_text_uses_unique_storage_for_sibling_versions() -> None:
    repositories, context = _build_context()
    created = _dispatch(
        context,
        {"filename": "pipeline.py", "content": "def main():\n    return 1\n"},
        tool_name="artifact.create_text",
    )
    base_id = str(created["artifact"]["artifact_id"])
    base_digest = str(created["content_digest"])

    first = _dispatch(
        context,
        {
            "base_artifact_id": base_id,
            "base_content_digest": base_digest,
            "content": "def main():\n    return 2\n",
        },
        tool_name="artifact.patch_text",
    )
    second = _dispatch(
        context,
        {
            "base_artifact_id": base_id,
            "base_content_digest": base_digest,
            "content": "def main():\n    return 3\n",
        },
        tool_name="artifact.patch_text",
    )

    first_artifact = repositories.artifacts.get(str(first["artifact"]["artifact_id"]))
    second_artifact = repositories.artifacts.get(str(second["artifact"]["artifact_id"]))
    assert first_artifact is not None
    assert second_artifact is not None
    assert first_artifact.storage_uri != second_artifact.storage_uri
    assert _dispatch(context, {"artifact_id": first_artifact.artifact_id}, tool_name="artifact.read_text")["content"].endswith("2\n")
    assert _dispatch(context, {"artifact_id": second_artifact.artifact_id}, tool_name="artifact.read_text")["content"].endswith("3\n")


def test_artifact_patch_text_rejects_stale_digest() -> None:
    _repositories, context = _build_context()
    created = _dispatch(
        context,
        {"filename": "pipeline.py", "content": "def main():\n    return 1\n"},
        tool_name="artifact.create_text",
    )

    result, payload = _dispatch_result(
        context,
        {
            "base_artifact_id": str(created["artifact"]["artifact_id"]),
            "base_content_digest": "sha256:stale",
            "content": "def main():\n    return 2\n",
        },
        tool_name="artifact.patch_text",
    )

    assert result.ok is False
    assert result.error_code == "stale_artifact_digest"
    assert payload["error_code"] == "stale_artifact_digest"
    assert payload["expected_content_digest"] == created["content_digest"]


def test_artifact_source_tools_reject_invalid_source_inputs(tmp_path: Path) -> None:
    repositories, context = _build_context()
    bad_filename_result, bad_filename_payload = _dispatch_result(
        context,
        {"filename": "../pipeline.txt", "content": "print('bad')\n"},
        tool_name="artifact.create_text",
    )
    bad_utf8_result, bad_utf8_payload = _dispatch_result(
        context,
        {"filename": "pipeline.py", "content": "\udcff"},
        tool_name="artifact.create_text",
    )
    result_path = tmp_path / "result.txt"
    result_path.write_text("plain text\n", encoding="utf-8")
    _save_file_artifact(
        repositories,
        path=result_path,
        artifact_id="art_result",
        relative_path="result.txt",
        kind=ArtifactKind.RESULT,
        metadata={"format": "text"},
    )
    non_code_result, non_code_payload = _dispatch_result(
        context,
        {
            "base_artifact_id": "art_result",
            "base_content_digest": "sha256:any",
            "content": "print('patch')\n",
        },
        tool_name="artifact.patch_text",
    )
    missing_digest_result, missing_digest_payload = _dispatch_result(
        context,
        {"base_artifact_id": "art_result", "content": "print('patch')\n"},
        tool_name="artifact.patch_text",
    )

    assert bad_filename_result.ok is False
    assert bad_filename_result.error_code == "invalid_pipeline_source_filename"
    assert bad_filename_payload["error_code"] == "invalid_pipeline_source_filename"
    assert bad_utf8_result.ok is False
    assert bad_utf8_result.error_code == "artifact_not_utf8"
    assert bad_utf8_payload["error_code"] == "artifact_not_utf8"
    assert non_code_result.ok is False
    assert non_code_result.error_code == "artifact_not_pipeline_source"
    assert non_code_payload["error_code"] == "artifact_not_pipeline_source"
    assert missing_digest_result.ok is False
    assert missing_digest_result.error_code == "missing_required_argument"
    assert missing_digest_payload["argument"] == "base_content_digest"
