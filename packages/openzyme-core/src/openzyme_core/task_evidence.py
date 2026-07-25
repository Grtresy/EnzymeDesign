from __future__ import annotations

from typing import Any

TASK_FINISH_EVIDENCE_REF_FORMAT = "<kind>:<id>"
TASK_FINISH_EVIDENCE_REF_KINDS = (
    "artifact",
    "document",
    "invocation",
    "message",
    "protocol",
    "report",
    "run",
    "sandbox_run",
    "scientific_closure",
)
TASK_FINISH_EVIDENCE_REF_PATTERN = (
    "^(" + "|".join(TASK_FINISH_EVIDENCE_REF_KINDS) + r"):.+$"
)


def task_finish_evidence_ref_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": TASK_FINISH_EVIDENCE_REF_PATTERN,
        "description": (
            "Use '<kind>:<id>'; kinds are exactly the pattern alternatives. "
            "Examples: 'artifact:<id>', 'report:<id>', "
            "'scientific_closure:<id>'. Bare ids are invalid."
        ),
    }


def task_finish_evidence_refs_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": task_finish_evidence_ref_schema(),
    }


def task_finish_evidence_contract_details() -> dict[str, Any]:
    return {
        "expected_format": TASK_FINISH_EVIDENCE_REF_FORMAT,
        "supported_kinds": list(TASK_FINISH_EVIDENCE_REF_KINDS),
        "examples": [
            "artifact:<artifact_id>",
            "report:<report_id>",
            "scientific_closure:<closure_id>",
        ],
    }


__all__ = [
    "TASK_FINISH_EVIDENCE_REF_FORMAT",
    "TASK_FINISH_EVIDENCE_REF_KINDS",
    "TASK_FINISH_EVIDENCE_REF_PATTERN",
    "task_finish_evidence_contract_details",
    "task_finish_evidence_ref_schema",
    "task_finish_evidence_refs_schema",
]
