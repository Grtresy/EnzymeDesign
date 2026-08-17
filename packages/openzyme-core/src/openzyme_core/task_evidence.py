from __future__ import annotations

from typing import Any


TASK_FINISH_EVIDENCE_REF_FORMAT = "TaskEvidenceRef@1 object"
TASK_FINISH_EVIDENCE_REF_KINDS = (
    "revision_path",
    "report",
    "controlled_operation_result",
    "scientific_deliverable",
    "scientific_closure",
)


def task_finish_evidence_ref_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "kind",
            "project_id",
            "session_id",
            "task_id",
            "owner_id",
            "owner_digest",
            "revision_path_ref",
            "report_ref",
            "controlled_operation_result_ref",
            "scientific_deliverable_ref",
            "scientific_closure_ref",
        ],
        "properties": {
            "schema_version": {"const": "task_evidence_ref@1"},
            "kind": {"enum": list(TASK_FINISH_EVIDENCE_REF_KINDS)},
            "project_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "task_id": {"type": "string", "minLength": 1},
            "owner_id": {"type": "string", "minLength": 1},
            "owner_digest": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "revision_path_ref": {"type": ["object", "null"]},
            "report_ref": {"type": ["object", "null"]},
            "controlled_operation_result_ref": {
                "type": ["object", "null"]
            },
            "scientific_deliverable_ref": {"type": ["object", "null"]},
            "scientific_closure_ref": {"type": ["object", "null"]},
        },
        "allOf": [
            {
                "if": {"properties": {"kind": {"const": "revision_path"}}},
                "then": {
                    "properties": {
                        "revision_path_ref": {"type": "object"},
                        "report_ref": {"type": "null"},
                        "controlled_operation_result_ref": {"type": "null"},
                        "scientific_deliverable_ref": {"type": "null"},
                        "scientific_closure_ref": {"type": "null"},
                    }
                },
            },
            {
                "if": {"properties": {"kind": {"const": "report"}}},
                "then": {
                    "properties": {
                        "revision_path_ref": {"type": "null"},
                        "report_ref": {"type": "object"},
                        "controlled_operation_result_ref": {"type": "null"},
                        "scientific_deliverable_ref": {"type": "null"},
                        "scientific_closure_ref": {"type": "null"},
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "kind": {"const": "controlled_operation_result"}
                    }
                },
                "then": {
                    "properties": {
                        "revision_path_ref": {"type": "null"},
                        "report_ref": {"type": "null"},
                        "controlled_operation_result_ref": {"type": "object"},
                        "scientific_deliverable_ref": {"type": "null"},
                        "scientific_closure_ref": {"type": "null"},
                    }
                },
            },
            {
                "if": {
                    "properties": {"kind": {"const": "scientific_deliverable"}}
                },
                "then": {
                    "properties": {
                        "revision_path_ref": {"type": "null"},
                        "report_ref": {"type": "null"},
                        "controlled_operation_result_ref": {"type": "null"},
                        "scientific_deliverable_ref": {"type": "object"},
                        "scientific_closure_ref": {"type": "null"},
                    }
                },
            },
            {
                "if": {"properties": {"kind": {"const": "scientific_closure"}}},
                "then": {
                    "properties": {
                        "revision_path_ref": {"type": "null"},
                        "report_ref": {"type": "null"},
                        "controlled_operation_result_ref": {"type": "null"},
                        "scientific_deliverable_ref": {"type": "null"},
                        "scientific_closure_ref": {"type": "object"},
                    }
                },
            },
        ],
        "description": (
            "Closed TaskEvidenceRef@1 union. Legacy strings and aliases, "
            "mutable paths, branches, private refs, URLs, Host/HPC paths, and "
            "free-form digests are invalid."
        ),
    }


def task_finish_evidence_refs_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": 64,
        "items": task_finish_evidence_ref_schema(),
    }


def task_finish_evidence_contract_details() -> dict[str, Any]:
    return {
        "expected_format": TASK_FINISH_EVIDENCE_REF_FORMAT,
        "schema_version": "task_evidence_ref@1",
        "supported_kinds": list(TASK_FINISH_EVIDENCE_REF_KINDS),
        "scientific_deliverable_kind_installed": True,
        "scientific_closure_kind_installed": True,
        "legacy_string_refs_allowed": False,
    }


__all__ = [
    "TASK_FINISH_EVIDENCE_REF_FORMAT",
    "TASK_FINISH_EVIDENCE_REF_KINDS",
    "task_finish_evidence_contract_details",
    "task_finish_evidence_ref_schema",
    "task_finish_evidence_refs_schema",
]
