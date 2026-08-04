from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from typing import Any

from openzyme_core import CoreRepositories
from openzyme_core import build_conversation_projection
from openzyme_core import canonical_digest
from openzyme_pipeline import aox_reference

from .aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from .aox_cutover_tool_policy import evaluate_aox_source_linked_report
from .aox_final_deliverable_validation import S15_AOX_HMM_FIXED_DELIVERABLES


PUBLIC_PRODUCT_CLOSURE_SCHEMA_ID = "aox_public_product_closure@1"
FAULT_NEGATIVE_STATE_CLOSURE_SCHEMA_ID = "aox_fault_negative_state_closure@1"
FAULT_INJECTION_RECEIPT_DOCUMENT_KIND = "aox_fault_injection_receipt"
_TERMINAL_TASK_STATUSES = {"completed", "failed", "blocked", "cancelled"}
_FAULT_TERMINAL_TASK_STATUSES = {"failed", "blocked", "cancelled"}
_PREFAULT_PATHS = {
    "aox_hmm/AOX_ref21.fasta",
    "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
}


class AoxPublicProductClosureError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _fail(error_code: str, message: str) -> None:
    raise AoxPublicProductClosureError(error_code, message)


def _sha256(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _task_receipts(
    repositories: CoreRepositories,
    *,
    session_id: str,
    execution_task_id: str,
) -> list[dict[str, Any]]:
    tasks = repositories.tasks.list_by_session(session_id)
    by_kind = {
        kind: [task for task in tasks if task.kind == kind]
        for kind in ("research", "execution", "reporting")
    }
    if (
        len(tasks) != 3
        or any(len(values) != 1 for values in by_kind.values())
        or by_kind["execution"][0].task_id != execution_task_id
    ):
        _fail(
            "aox_exact_task_set_invalid",
            "AOX closure requires exactly its research, execution, and reporting tasks",
        )
    expected = (
        (by_kind["research"][0].task_id, "research", "researcher"),
        (execution_task_id, "execution", "executor"),
        (by_kind["reporting"][0].task_id, "reporting", "reporter"),
    )
    agents = repositories.agents.list_by_session(session_id)
    agents_by_ref = {
        ref: agent
        for agent in agents
        for ref in (agent.agent_id, agent.member_id)
        if ref
    }
    finishes: dict[str, list[Any]] = {task_id: [] for task_id, _, _ in expected}
    for document in repositories.engine_documents.list_by_session(session_id):
        if document.document_kind != "task_finish":
            continue
        task_id = str(document.payload.get("task_id") or "")
        if task_id in finishes:
            finishes[task_id].append(document)
    by_id = {task.task_id: task for task in tasks}
    receipts: list[dict[str, Any]] = []
    assigned_refs: set[str] = set()
    for task_id, kind, role in expected:
        task = by_id[task_id]
        finish_records = finishes[task_id]
        assigned_ref = str(task.assigned_ref or "")
        agent = agents_by_ref.get(assigned_ref)
        if not all(
            (
                task.kind == kind,
                task.status.value in _TERMINAL_TASK_STATUSES,
                bool(assigned_ref),
                assigned_ref not in assigned_refs,
                agent is not None,
                agent is not None and agent.role == role,
                agent is not None and agent.task_id == task_id,
                agent is not None and agent.lane_id == task.lane_id,
                len(finish_records) == 1,
            )
        ):
            _fail(
                "aox_exact_task_closure_invalid",
                "AOX task identity, owner, role, or finish cardinality is invalid",
            )
        assigned_refs.add(assigned_ref)
        finish = finish_records[0]
        finish_payload = dict(finish.payload)
        evidence_refs = finish_payload.get("evidence_refs")
        if not all(
            (
                finish_payload.get("task_id") == task_id,
                finish_payload.get("status") == task.status.value,
                finish_payload.get("finished_by") == assigned_ref,
                isinstance(evidence_refs, list),
                isinstance(evidence_refs, list)
                and all(isinstance(item, str) and item for item in evidence_refs),
            )
        ):
            _fail(
                "aox_task_finish_owner_invalid",
                "AOX task finish must be exact and authored by its assigned agent",
            )
        receipts.append(
            {
                "task_id": task_id,
                "role": role,
                "kind": kind,
                "status": task.status.value,
                "assigned_ref": assigned_ref,
                "lane_id": task.lane_id,
                "finish_ref": finish.document_id,
                "finish_payload_digest": canonical_digest(finish_payload),
                "finished_by": finish_payload["finished_by"],
                "evidence_refs": list(evidence_refs),
            }
        )
    return receipts


def _report_states(
    repositories: CoreRepositories, session_id: str
) -> list[dict[str, Any]]:
    return [
        {
            "report_id": report.report_id,
            "task_id": report.task_id,
            "status": report.status.value,
            "artifact_id": report.artifact_id,
        }
        for report in repositories.reports.list_by_session(session_id)
    ]


def _draft_states(
    repositories: CoreRepositories, session_id: str
) -> list[dict[str, Any]]:
    return [
        {
            "draft_id": draft.draft_id,
            "task_id": draft.task_id,
            "owner_agent_id": draft.owner_agent_id,
            "status": draft.status.value,
            "content_ref": draft.content_ref,
            "published_report_id": draft.published_report_id,
        }
        for draft in repositories.report_drafts.list_by_session(session_id)
    ]


def _conversation_receipts(
    repositories: CoreRepositories, session_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    entries = build_conversation_projection(repositories, session_id)
    receipts = [
        {
            "message_id": entry.message_id,
            "role": entry.role,
            "sender": entry.sender,
            "recipient": entry.recipient,
            "content_digest": _sha256(entry.content),
        }
        for entry in entries
    ]
    final = next(
        (entry for entry in reversed(entries) if entry.role == "assistant"),
        None,
    )
    if final is None:
        return receipts, None
    return receipts, {
        "message_id": final.message_id,
        "sender": final.sender,
        "recipient": final.recipient,
        "content": final.content,
        "content_digest": _sha256(final.content),
    }


def _event_receipts(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": item.get("event_id"),
            "cursor": item.get("cursor"),
            "event_type": item.get("event_type"),
            "actor_ref": item.get("actor_ref"),
            "command_id": item.get("command_id"),
            "payload_digest": canonical_digest(dict(item.get("payload") or {})),
        }
        for item in events
    ]


def _fault_negative_state_closure(
    repositories: CoreRepositories,
    *,
    session_id: str,
    attempt_id: str,
    execution_task_id: str,
    task_receipts: list[dict[str, Any]],
    report_states: list[dict[str, Any]],
    draft_states: list[dict[str, Any]],
    conversation_receipts: list[dict[str, Any]],
    final_answer: dict[str, Any] | None,
    durable_event_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    receipts = [
        dict(document.payload)
        for document in repositories.engine_documents.list_by_session(session_id)
        if document.document_kind == FAULT_INJECTION_RECEIPT_DOCUMENT_KIND
        and document.payload.get("attempt_id") == attempt_id
    ]
    if len(receipts) != 1:
        _fail(
            "aox_fault_injection_receipt_cardinality_invalid",
            "fault closure requires exactly one persisted exact byte-flip receipt",
        )
    injection = receipts[0]
    target_artifact_id = str(injection.get("target_artifact_id") or "")
    consumers = [
        operation
        for operation in repositories.controlled_operations.list_by_session(session_id)
        if target_artifact_id in operation.input_artifact_ids
    ]
    consumer_states = [
        {
            "operation_id": operation.operation_id,
            "task_id": operation.task_id,
            "sdk_module": operation.sdk_module,
            "function_name": operation.function_name,
            "selected_backend": operation.selected_backend,
            "status": operation.status.value,
            "failure_code": operation.error_code,
            "operation_identity_digest": operation.operation_digest,
        }
        for operation in consumers
    ]
    if not (
        len(consumers) == 1
        and consumers[0].task_id == execution_task_id
        and consumers[0].sdk_module == "bio_tools"
        and consumers[0].function_name == "mafft"
        and consumers[0].status.value in {"failed", "recovery_failed"}
        and consumers[0].error_code == "artifact_blob_digest_mismatch"
    ):
        _fail(
            "aox_fault_consumer_closure_invalid",
            "fault closure requires one terminal failed MAFFT consumer and no alternate",
        )
    artifacts = repositories.artifacts.list_by_session(session_id)
    fixed_paths = {
        str(
            dict(artifact.metadata or {}).get("catalog_relative_path")
            or artifact.relative_path
        )
        for artifact in artifacts
        if str(
            dict(artifact.metadata or {}).get("catalog_relative_path")
            or artifact.relative_path
        )
        in S15_AOX_HMM_FIXED_DELIVERABLES
    }
    post_fault_paths = sorted(fixed_paths - _PREFAULT_PATHS)
    execution = next(
        item for item in task_receipts if item["task_id"] == execution_task_id
    )
    reporter = next(item for item in task_receipts if item["role"] == "reporter")
    if not all(
        (
            execution["status"] in _FAULT_TERMINAL_TASK_STATUSES,
            reporter["status"] != "completed",
            not any(item["status"] in {"ready", "published"} for item in report_states),
            not any(
                item["status"] in {"ready", "published"} or item["published_report_id"]
                for item in draft_states
            ),
            not post_fault_paths,
            not set(S15_AOX_HMM_FIXED_DELIVERABLES).issubset(fixed_paths),
        )
    ):
        _fail(
            "aox_fault_negative_state_invalid",
            "fault closure contains a positive task, report, or downstream deliverable state",
        )
    success_claims = [
        item["message_id"]
        for item in conversation_receipts
        if item["role"] == "assistant"
        and final_answer is not None
        and item["message_id"] == final_answer["message_id"]
        and any(
            marker in final_answer["content"]
            for marker in ("decision=GO", "cutover_eligible=true")
        )
    ]
    if success_claims:
        _fail(
            "aox_fault_success_claim_invalid",
            "fault closure contains a positive public success claim",
        )
    if final_answer is None or not all(
        marker in final_answer["content"]
        for marker in ("artifact_blob_digest_mismatch", "failed")
    ):
        _fail(
            "aox_fault_final_answer_invalid",
            "fault final answer must expose the exact typed failure and failed status",
        )
    payload = {
        "schema_id": FAULT_NEGATIVE_STATE_CLOSURE_SCHEMA_ID,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "target_artifact_id": target_artifact_id,
        "injection_receipt": injection,
        "terminal_failure_operation_id": consumers[0].operation_id,
        "task_receipts": task_receipts,
        "report_states": report_states,
        "draft_states": draft_states,
        "conversation_receipts": conversation_receipts,
        "durable_event_receipts": durable_event_receipts,
        "consumer_states": consumer_states,
        "successful_alternate_consumer_ids": [],
        "observed_prefault_deliverable_paths": sorted(fixed_paths & _PREFAULT_PATHS),
        "post_fault_final_deliverable_paths": post_fault_paths,
        "complete_final_deliverable_set_present": False,
        "success_claim_message_ids": [],
        "final_assistant_failure_message_id": final_answer["message_id"],
        "final_assistant_failure_code": "artifact_blob_digest_mismatch",
        "final_assistant_failure_status": "failed",
    }
    return {**payload, "closure_digest": canonical_digest(payload)}


def build_aox_public_product_closure(
    repositories: CoreRepositories,
    *,
    session_id: str,
    attempt_id: str,
    attempt_kind: str,
    execution_task_id: str,
    events: Sequence[Mapping[str, Any]],
    latest_event_cursor: int,
) -> dict[str, Any]:
    task_receipts = _task_receipts(
        repositories,
        session_id=session_id,
        execution_task_id=execution_task_id,
    )
    report_states = _report_states(repositories, session_id)
    draft_states = _draft_states(repositories, session_id)
    conversation_receipts, final_answer = _conversation_receipts(
        repositories, session_id
    )
    event_receipts = _event_receipts(events)
    cursors = [item["cursor"] for item in event_receipts]
    if not all(
        (
            bool(event_receipts),
            all(type(cursor) is int and cursor > 0 for cursor in cursors),
            cursors == sorted(set(cursors)),
            cursors[-1] == latest_event_cursor,
        )
    ):
        _fail(
            "aox_public_event_closure_invalid",
            "public closure requires the complete ordered durable event stream",
        )
    source_linked_report: dict[str, Any] | None = None
    fault_closure: dict[str, Any] | None = None
    if attempt_kind == "positive":
        if not all(item["status"] == "completed" for item in task_receipts):
            _fail(
                "aox_positive_task_closure_invalid",
                "positive AOX closure requires all three tasks completed",
            )
        research = next(item for item in task_receipts if item["role"] == "researcher")
        reporter = next(item for item in task_receipts if item["role"] == "reporter")
        evaluated = evaluate_aox_source_linked_report(
            repositories,
            session_id=session_id,
            research_task_id=str(research["task_id"]),
            report_task_id=str(reporter["task_id"]),
            reporter_evidence_refs=tuple(reporter["evidence_refs"]),
        )
        source_linked_report = {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in evaluated.items()
        }
        if source_linked_report.get("ready") is not True or final_answer is None:
            _fail(
                "aox_positive_product_closure_invalid",
                "positive AOX closure lacks its source-linked report or final answer",
            )
    elif attempt_kind == "fault":
        fault_closure = _fault_negative_state_closure(
            repositories,
            session_id=session_id,
            attempt_id=attempt_id,
            execution_task_id=execution_task_id,
            task_receipts=task_receipts,
            report_states=report_states,
            draft_states=draft_states,
            conversation_receipts=conversation_receipts,
            final_answer=final_answer,
            durable_event_receipts=event_receipts,
        )
    else:
        _fail("aox_attempt_kind_invalid", "AOX attempt kind is unsupported")
    payload = {
        "schema_id": PUBLIC_PRODUCT_CLOSURE_SCHEMA_ID,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "attempt_kind": attempt_kind,
        "tasks": task_receipts,
        "report_states": report_states,
        "draft_states": draft_states,
        "conversation_receipts": conversation_receipts,
        "final_answer": final_answer,
        "durable_event_receipts": event_receipts,
        "latest_event_cursor": latest_event_cursor,
        "source_linked_report": source_linked_report,
        "fault_negative_state_closure": fault_closure,
    }
    return {**payload, "closure_digest": canonical_digest(payload)}


def validate_aox_public_product_closure(
    closure: Mapping[str, Any],
    *,
    session_id: str,
    attempt_id: str,
    attempt_kind: str,
    execution_task_id: str,
    workspace: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> None:
    value = dict(closure)
    payload = {key: item for key, item in value.items() if key != "closure_digest"}
    fields = {
        "schema_id",
        "session_id",
        "attempt_id",
        "attempt_kind",
        "tasks",
        "report_states",
        "draft_states",
        "conversation_receipts",
        "final_answer",
        "durable_event_receipts",
        "latest_event_cursor",
        "source_linked_report",
        "fault_negative_state_closure",
        "closure_digest",
    }
    if not all(
        (
            set(value) == fields,
            value.get("schema_id") == PUBLIC_PRODUCT_CLOSURE_SCHEMA_ID,
            value.get("session_id") == session_id,
            value.get("attempt_id") == attempt_id,
            value.get("attempt_kind") == attempt_kind,
            value.get("closure_digest") == canonical_digest(payload),
        )
    ):
        _fail(
            "aox_public_product_closure_invalid",
            "public product closure schema, identity, or digest is invalid",
        )
    tasks = value.get("tasks")
    if not (
        isinstance(tasks, list)
        and len(tasks) == 3
        and [item.get("kind") for item in tasks if isinstance(item, dict)]
        == ["research", "execution", "reporting"]
        and [item.get("role") for item in tasks if isinstance(item, dict)]
        == ["researcher", "executor", "reporter"]
        and tasks[1].get("task_id") == execution_task_id
        and len({item.get("task_id") for item in tasks}) == 3
        and len({item.get("assigned_ref") for item in tasks}) == 3
    ):
        _fail(
            "aox_exact_task_closure_invalid",
            "public product closure does not contain exact unique three-task identities",
        )
    expected_task_ids = [str(item["task_id"]) for item in tasks]
    report_task_id = expected_task_ids[2]
    workspace_tasks = {
        str(task.get("task_id")): task
        for item in dict(workspace.get("task_board") or {}).get("items") or []
        if isinstance(item, dict) and isinstance((task := item.get("task")), dict)
    }
    if set(workspace_tasks) != set(expected_task_ids) or any(
        workspace_tasks[str(item["task_id"])].get("status") != item.get("status")
        or workspace_tasks[str(item["task_id"])].get("kind") != item.get("kind")
        or workspace_tasks[str(item["task_id"])].get("assigned_ref")
        != item.get("assigned_ref")
        or workspace_tasks[str(item["task_id"])].get("lane_id") != item.get("lane_id")
        for item in tasks
    ):
        _fail(
            "aox_public_task_snapshot_mismatch",
            "public workspace task projection differs from the Host closure",
        )
    public_reports = [
        {
            key: item.get(key)
            for key in ("report_id", "task_id", "status", "artifact_id")
        }
        for item in workspace.get("reports") or []
        if isinstance(item, dict)
    ]
    public_drafts = [
        {
            key: item.get(key)
            for key in (
                "draft_id",
                "task_id",
                "owner_agent_id",
                "status",
                "published_report_id",
            )
        }
        for item in workspace.get("report_drafts") or []
        if isinstance(item, dict)
    ]
    closure_drafts = [
        {
            key: item.get(key)
            for key in (
                "draft_id",
                "task_id",
                "owner_agent_id",
                "status",
                "published_report_id",
            )
        }
        for item in value.get("draft_states") or []
        if isinstance(item, dict)
    ]
    if public_reports != value.get("report_states") or public_drafts != closure_drafts:
        _fail(
            "aox_public_report_snapshot_mismatch",
            "public workspace report projection differs from the Host closure",
        )
    public_conversation = [
        {
            "message_id": item.get("message_id"),
            "role": item.get("role"),
            "sender": item.get("sender"),
            "recipient": item.get("recipient"),
            "content_digest": _sha256(str(item.get("content") or "")),
        }
        for item in workspace.get("conversation") or []
        if isinstance(item, dict)
    ]
    if public_conversation != value.get("conversation_receipts"):
        _fail(
            "aox_public_conversation_snapshot_mismatch",
            "public conversation projection differs from the Host closure",
        )
    event_receipts = _event_receipts(events)
    if event_receipts != value.get("durable_event_receipts") or value.get(
        "latest_event_cursor"
    ) != (event_receipts[-1]["cursor"] if event_receipts else 0):
        _fail(
            "aox_public_event_snapshot_mismatch",
            "public event replay differs from the Host closure",
        )
    final_answer = value.get("final_answer")
    if final_answer is not None and (
        not isinstance(final_answer, dict)
        or final_answer.get("content_digest")
        != _sha256(str(final_answer.get("content") or ""))
        or not public_conversation
        or public_conversation[-1].get("message_id") != final_answer.get("message_id")
    ):
        _fail(
            "aox_final_answer_invalid",
            "public final answer does not reproduce the final assistant message",
        )
    if attempt_kind == "positive":
        report = value.get("source_linked_report")
        if not all(
            (
                isinstance(report, dict),
                isinstance(report, dict) and report.get("ready") is True,
                all(item.get("status") == "completed" for item in tasks),
                isinstance(final_answer, dict),
                value.get("fault_negative_state_closure") is None,
                isinstance(report, dict) and report.get("blocker_codes") == [],
                isinstance(report, dict)
                and any(
                    item.get("report_id") == report.get("report_id")
                    and item.get("task_id") == report_task_id
                    and item.get("status") in {"ready", "published"}
                    for item in value.get("report_states") or []
                ),
                isinstance(report, dict)
                and any(
                    item.get("draft_id") == report.get("draft_id")
                    and item.get("task_id") == report_task_id
                    and item.get("status") == "published"
                    for item in value.get("draft_states") or []
                ),
            )
        ):
            _fail(
                "aox_positive_product_closure_invalid",
                "positive closure is missing exact task/report/final-answer facts",
            )
    else:
        negative = value.get("fault_negative_state_closure")
        negative_payload = (
            {}
            if not isinstance(negative, dict)
            else {
                key: item for key, item in negative.items() if key != "closure_digest"
            }
        )
        injection = (
            dict(negative.get("injection_receipt") or {})
            if isinstance(negative, dict)
            else {}
        )
        consumers = (
            negative.get("consumer_states") if isinstance(negative, dict) else None
        )
        injection_payload = {
            key: item for key, item in injection.items() if key != "receipt_digest"
        }
        target_artifact_id = str(injection.get("target_artifact_id") or "")
        public_consumers = [
            {
                "operation_id": item.get("operation_id"),
                "task_id": item.get("task_id"),
                "sdk_module": item.get("sdk_module"),
                "function_name": item.get("function_name"),
                "selected_backend": item.get("selected_backend"),
                "status": item.get("status"),
                "failure_code": item.get("error_code"),
                "operation_identity_digest": item.get("operation_digest"),
            }
            for item in dict(workspace.get("scientific_evidence") or {}).get(
                "operations"
            )
            or []
            if isinstance(item, dict)
            and target_artifact_id in set(item.get("input_artifact_ids") or [])
        ]
        consumer = (
            dict(consumers[0])
            if isinstance(consumers, list)
            and len(consumers) == 1
            and isinstance(consumers[0], dict)
            else {}
        )
        execution_task = next(
            item for item in tasks if item.get("task_id") == execution_task_id
        )
        reporter_task = next(item for item in tasks if item.get("role") == "reporter")
        if not all(
            (
                isinstance(negative, dict),
                isinstance(negative, dict)
                and negative.get("schema_id") == FAULT_NEGATIVE_STATE_CLOSURE_SCHEMA_ID,
                isinstance(negative, dict)
                and negative.get("closure_digest")
                == canonical_digest(negative_payload),
                negative.get("session_id") == session_id,
                negative.get("attempt_id") == attempt_id,
                negative.get("task_receipts") == tasks,
                negative.get("report_states") == value.get("report_states"),
                negative.get("draft_states") == value.get("draft_states"),
                negative.get("conversation_receipts")
                == value.get("conversation_receipts"),
                negative.get("durable_event_receipts")
                == value.get("durable_event_receipts"),
                injection.get("schema_id") == "aox_fault_injection_receipt@1",
                injection.get("injection_id") == FAULT_ARTIFACT_BYTE_FLIP_ID,
                injection.get("session_id") == session_id,
                injection.get("attempt_id") == attempt_id,
                injection.get("task_id") == execution_task_id,
                injection.get("target_relative_path") == "aox_hmm/AOX_ref21.fasta",
                injection.get("expected_consumer_tool_id") == "bio_tools.mafft",
                injection.get("byte_offset") == 0,
                type(injection.get("size_bytes")) is int,
                injection.get("size_bytes", 0) > 0,
                injection.get("observed_before_digest")
                == injection.get("expected_content_digest"),
                injection.get("observed_after_digest")
                != injection.get("observed_before_digest"),
                injection.get("source_contract_id")
                == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
                injection.get("source_contract_digest")
                == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST,
                injection.get("source_implementation_digest")
                == aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST,
                injection.get("source_storage_model") == "sealed_blob",
                injection.get("source_storage_path_contract")
                == "artifact_blob_root/sealed/files/{content_digest_hex}",
                isinstance(injection.get("authority_envelope_id"), str),
                bool(injection.get("authority_envelope_id")),
                injection.get("receipt_digest") == canonical_digest(injection_payload),
                isinstance(consumers, list) and len(consumers) == 1,
                isinstance(consumers, list) and consumers == public_consumers,
                consumer.get("failure_code") == "artifact_blob_digest_mismatch",
                consumer.get("status") in {"failed", "recovery_failed"},
                negative.get("successful_alternate_consumer_ids") == [],
                negative.get("terminal_failure_operation_id")
                == consumer.get("operation_id"),
                negative.get("post_fault_final_deliverable_paths") == [],
                negative.get("complete_final_deliverable_set_present") is False,
                negative.get("success_claim_message_ids") == [],
                isinstance(final_answer, dict),
                isinstance(final_answer, dict)
                and negative.get("final_assistant_failure_message_id")
                == final_answer.get("message_id"),
                negative.get("final_assistant_failure_code")
                == "artifact_blob_digest_mismatch",
                negative.get("final_assistant_failure_status") == "failed",
                execution_task.get("status") in _FAULT_TERMINAL_TASK_STATUSES,
                reporter_task.get("status") != "completed",
                not any(
                    item.get("status") in {"ready", "published"}
                    for item in value.get("report_states") or []
                ),
                not any(
                    item.get("status") in {"ready", "published"}
                    or item.get("published_report_id")
                    for item in value.get("draft_states") or []
                ),
                value.get("source_linked_report") is None,
            )
        ):
            _fail(
                "aox_fault_negative_state_closure_invalid",
                "fault closure does not prove the exact byte flip and complete non-success state",
            )
