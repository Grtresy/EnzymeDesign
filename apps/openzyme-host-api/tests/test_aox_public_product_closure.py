from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from openzyme_core import canonical_digest
from openzyme_pipeline import aox_reference
from openzyme_host_api.aox_cutover_tool_policy import AOX_REPORT_TASK_ID
from openzyme_host_api.aox_cutover_tool_policy import AOX_RESEARCH_TASK_ID
from openzyme_host_api.aox_public_product_closure import (
    AoxPublicProductClosureError,
)
from openzyme_host_api.aox_public_product_closure import (
    validate_aox_public_product_closure,
)


def _content_digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


def _task(
    task_id: str,
    role: str,
    kind: str,
    *,
    status: str = "completed",
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "role": role,
        "kind": kind,
        "status": status,
        "assigned_ref": f"agent:{role}",
        "lane_id": f"lane:{role}",
        "finish_ref": f"finish:{role}",
        "finish_payload_digest": "sha256:" + role[0] * 64,
        "finished_by": f"agent:{role}",
        "evidence_refs": [],
    }


def _workspace_tasks(tasks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "items": [
            {
                "task": {
                    key: task[key]
                    for key in ("task_id", "kind", "status", "assigned_ref", "lane_id")
                }
            }
            for task in tasks
        ]
    }


def _events() -> list[dict[str, object]]:
    return [
        {
            "event_id": "event:1",
            "cursor": 1,
            "session_id": "session:aox",
            "event_type": "task.finished",
            "actor_ref": "agent:reporter",
            "command_id": "command:1",
            "payload": {"task_id": AOX_REPORT_TASK_ID},
        }
    ]


def _event_receipts(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "event_id": item["event_id"],
            "cursor": item["cursor"],
            "event_type": item["event_type"],
            "actor_ref": item["actor_ref"],
            "command_id": item["command_id"],
            "payload_digest": canonical_digest(item["payload"]),
        }
        for item in events
    ]


def test_positive_closure_requires_exact_tasks_source_report_and_final_answer() -> None:
    execution_task_id = "task:aox-execution"
    tasks = [
        _task(AOX_RESEARCH_TASK_ID, "researcher", "research"),
        _task(execution_task_id, "executor", "execution"),
        _task(AOX_REPORT_TASK_ID, "reporter", "reporting"),
    ]
    report_states = [
        {
            "report_id": "report:aox",
            "task_id": AOX_REPORT_TASK_ID,
            "status": "ready",
            "artifact_id": None,
        }
    ]
    draft_states = [
        {
            "draft_id": "draft:aox",
            "task_id": AOX_REPORT_TASK_ID,
            "owner_agent_id": "agent:reporter",
            "status": "published",
            "content_ref": "document:report",
            "published_report_id": "report:aox",
        }
    ]
    final_content = "AOX report published with PubMed evidence."
    conversation = [
        {
            "message_id": "message:user",
            "role": "user",
            "sender": "user:local-dev",
            "recipient": "agent:master",
            "content_digest": _content_digest("run AOX"),
        },
        {
            "message_id": "message:final",
            "role": "assistant",
            "sender": "agent:master",
            "recipient": "user:local-dev",
            "content_digest": _content_digest(final_content),
        },
    ]
    events = _events()
    payload = {
        "schema_id": "aox_public_product_closure@1",
        "session_id": "session:aox",
        "attempt_id": "attempt:positive",
        "attempt_kind": "positive",
        "tasks": tasks,
        "report_states": report_states,
        "draft_states": draft_states,
        "conversation_receipts": conversation,
        "final_answer": {
            "message_id": "message:final",
            "sender": "agent:master",
            "recipient": "user:local-dev",
            "content": final_content,
            "content_digest": _content_digest(final_content),
        },
        "durable_event_receipts": _event_receipts(events),
        "latest_event_cursor": 1,
        "source_linked_report": {
            "ready": True,
            "blocker_codes": [],
            "report_id": "report:aox",
            "draft_id": "draft:aox",
            "content_ref": "document:report",
            "primary_artifact_id": "artifact:pubmed",
            "primary_artifact_digest": "sha256:" + "a" * 64,
            "source_ref_ids": ["source:pmid"],
        },
        "fault_negative_state_closure": None,
    }
    closure = {**payload, "closure_digest": canonical_digest(payload)}
    workspace = {
        "task_board": _workspace_tasks(tasks),
        "reports": report_states,
        "report_drafts": [
            {
                key: value
                for key, value in draft_states[0].items()
                if key != "content_ref"
            }
        ],
        "conversation": [
            {
                **{
                    key: item[key]
                    for key in ("message_id", "role", "sender", "recipient")
                },
                "content": "run AOX" if item["role"] == "user" else final_content,
            }
            for item in conversation
        ],
    }

    validate_aox_public_product_closure(
        closure,
        session_id="session:aox",
        attempt_id="attempt:positive",
        attempt_kind="positive",
        execution_task_id=execution_task_id,
        workspace=workspace,
        events=events,
    )

    extra_task = deepcopy(workspace)
    extra_task["task_board"]["items"].append(
        {"task": {"task_id": "task:extra", "status": "completed"}}
    )
    with pytest.raises(AoxPublicProductClosureError) as error:
        validate_aox_public_product_closure(
            closure,
            session_id="session:aox",
            attempt_id="attempt:positive",
            attempt_kind="positive",
            execution_task_id=execution_task_id,
            workspace=extra_task,
            events=events,
        )
    assert error.value.error_code == "aox_public_task_snapshot_mismatch"


def test_fault_closure_requires_exact_receipt_consumer_and_full_negative_state() -> (
    None
):
    execution_task_id = "task:aox-execution"
    tasks = [
        _task(AOX_RESEARCH_TASK_ID, "researcher", "research"),
        _task(execution_task_id, "executor", "execution", status="failed"),
        _task(AOX_REPORT_TASK_ID, "reporter", "reporting", status="blocked"),
    ]
    failure_content = "status=failed failure_code=artifact_blob_digest_mismatch"
    conversation = [
        {
            "message_id": "message:fault",
            "role": "assistant",
            "sender": "agent:master",
            "recipient": "user:local-dev",
            "content_digest": _content_digest(failure_content),
        }
    ]
    events = _events()
    injection_payload = {
        "schema_id": "aox_fault_injection_receipt@1",
        "injection_id": "derived_required_artifact_blob_byte_flip@2",
        "session_id": "session:aox",
        "attempt_id": "attempt:fault",
        "campaign_id": "campaign:aox",
        "task_id": execution_task_id,
        "lane_id": "lane:executor",
        "authority_envelope_id": "authority:fault",
        "target_artifact_id": "artifact:ref21",
        "target_relative_path": "aox_hmm/AOX_ref21.fasta",
        "byte_offset": 0,
        "expected_consumer_tool_id": "bio_tools.mafft",
        "expected_content_digest": "sha256:" + "1" * 64,
        "observed_before_digest": "sha256:" + "1" * 64,
        "observed_after_digest": "sha256:" + "2" * 64,
        "size_bytes": 100,
        "source_contract_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        "source_contract_digest": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        "source_implementation_digest": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        "source_storage_model": "sealed_blob",
        "source_storage_path_contract": (
            "artifact_blob_root/sealed/files/{content_digest_hex}"
        ),
        "actor_ref": "user:local-dev",
        "idempotency_key": "fault-once",
        "request_digest": "sha256:" + "5" * 64,
        "claim_digest": "sha256:" + "6" * 64,
        "injected_at": "2026-08-01T00:00:00+00:00",
    }
    injection = {
        **injection_payload,
        "receipt_digest": canonical_digest(injection_payload),
    }
    consumer = {
        "operation_id": "operation:mafft",
        "task_id": execution_task_id,
        "sdk_module": "bio_tools",
        "function_name": "mafft",
        "selected_backend": "hpc",
        "status": "failed",
        "failure_code": "artifact_blob_digest_mismatch",
        "operation_identity_digest": "sha256:" + "7" * 64,
    }
    negative_payload = {
        "schema_id": "aox_fault_negative_state_closure@1",
        "session_id": "session:aox",
        "attempt_id": "attempt:fault",
        "target_artifact_id": "artifact:ref21",
        "injection_receipt": injection,
        "terminal_failure_operation_id": "operation:mafft",
        "task_receipts": tasks,
        "report_states": [],
        "draft_states": [],
        "conversation_receipts": conversation,
        "durable_event_receipts": _event_receipts(events),
        "consumer_states": [consumer],
        "successful_alternate_consumer_ids": [],
        "observed_prefault_deliverable_paths": ["aox_hmm/AOX_ref21.fasta"],
        "post_fault_final_deliverable_paths": [],
        "complete_final_deliverable_set_present": False,
        "success_claim_message_ids": [],
        "final_assistant_failure_message_id": "message:fault",
        "final_assistant_failure_code": "artifact_blob_digest_mismatch",
        "final_assistant_failure_status": "failed",
    }
    negative = {
        **negative_payload,
        "closure_digest": canonical_digest(negative_payload),
    }
    payload = {
        "schema_id": "aox_public_product_closure@1",
        "session_id": "session:aox",
        "attempt_id": "attempt:fault",
        "attempt_kind": "fault",
        "tasks": tasks,
        "report_states": [],
        "draft_states": [],
        "conversation_receipts": conversation,
        "final_answer": {
            "message_id": "message:fault",
            "sender": "agent:master",
            "recipient": "user:local-dev",
            "content": failure_content,
            "content_digest": _content_digest(failure_content),
        },
        "durable_event_receipts": _event_receipts(events),
        "latest_event_cursor": 1,
        "source_linked_report": None,
        "fault_negative_state_closure": negative,
    }
    closure = {**payload, "closure_digest": canonical_digest(payload)}
    workspace = {
        "task_board": _workspace_tasks(tasks),
        "reports": [],
        "report_drafts": [],
        "conversation": [
            {
                "message_id": "message:fault",
                "role": "assistant",
                "sender": "agent:master",
                "recipient": "user:local-dev",
                "content": failure_content,
            }
        ],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": "operation:mafft",
                    "task_id": execution_task_id,
                    "sdk_module": "bio_tools",
                    "function_name": "mafft",
                    "selected_backend": "hpc",
                    "status": "failed",
                    "error_code": "artifact_blob_digest_mismatch",
                    "operation_digest": "sha256:" + "7" * 64,
                    "input_artifact_ids": ["artifact:ref21"],
                }
            ]
        },
    }

    validate_aox_public_product_closure(
        closure,
        session_id="session:aox",
        attempt_id="attempt:fault",
        attempt_kind="fault",
        execution_task_id=execution_task_id,
        workspace=workspace,
        events=events,
    )

    tampered = deepcopy(closure)
    tampered_negative = tampered["fault_negative_state_closure"]
    tampered_negative["successful_alternate_consumer_ids"] = ["operation:other"]
    tampered_negative["closure_digest"] = canonical_digest(
        {
            key: value
            for key, value in tampered_negative.items()
            if key != "closure_digest"
        }
    )
    tampered["closure_digest"] = canonical_digest(
        {key: value for key, value in tampered.items() if key != "closure_digest"}
    )
    with pytest.raises(AoxPublicProductClosureError) as error:
        validate_aox_public_product_closure(
            tampered,
            session_id="session:aox",
            attempt_id="attempt:fault",
            attempt_kind="fault",
            execution_task_id=execution_task_id,
            workspace=workspace,
            events=events,
        )
    assert error.value.error_code == "aox_fault_negative_state_closure_invalid"

    missing_final = deepcopy(closure)
    missing_final["final_answer"] = None
    missing_final["closure_digest"] = canonical_digest(
        {
            key: value
            for key, value in missing_final.items()
            if key != "closure_digest"
        }
    )
    with pytest.raises(AoxPublicProductClosureError) as error:
        validate_aox_public_product_closure(
            missing_final,
            session_id="session:aox",
            attempt_id="attempt:fault",
            attempt_kind="fault",
            execution_task_id=execution_task_id,
            workspace=workspace,
            events=events,
        )
    assert error.value.error_code == "aox_fault_negative_state_closure_invalid"
