#!/usr/bin/env python3
"""Generate final C2 acceptance from one explicit canonical evidence bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from typing import cast

import verify_agent_capability_lease as verifier


def _fixed_documents() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    verifier.verify_all(require_acceptance=False, verify_sources=False)
    names = ("prerequisites", "authority_matrix", "policy", "scope_boundary")
    documents = {
        name: cast(dict[str, Any], verifier.load_document(name)) for name in names
    }
    digests = {
        name: verifier.verify_document(name, document)
        for name, document in documents.items()
    }
    return documents, digests


def build_acceptance_receipt(evidence: dict[str, Any]) -> dict[str, Any]:
    documents, document_digests = _fixed_documents()
    verifier.verify_tasks()
    evidence_digest = verifier.verify_final_evidence(
        evidence,
        verify_sources=True,
    )
    prerequisites = documents["prerequisites"]
    acceptance = {
        "schema_id": "agent_capability_lease_acceptance@1",
        "change_id": verifier.CHANGE_ID,
        "source_revision": evidence["source_revision"],
        "c0_acceptance_receipt_digest": prerequisites["c0"]["receipt_digest"],
        "c1_acceptance_receipt_digest": prerequisites["c1"]["receipt_digest"],
        "prerequisite_bindings_digest": document_digests["prerequisites"],
        "authority_matrix_digest": document_digests["authority_matrix"],
        "capability_policy_document_digest": document_digests["policy"],
        "capability_policy_digest": documents["policy"]["lease_policy_digest"],
        "scope_boundary_digest": document_digests["scope_boundary"],
        "final_evidence_digest": evidence_digest,
        "implementation_snapshot": evidence["implementation_snapshot"],
        "schema": evidence["schema"],
        "focused_validation": evidence["focused_validation"],
        "documentation": evidence["documentation"],
        "openspec_validation": evidence["openspec_validation"],
        "mainline_validation": evidence["mainline_validation"],
        "scope_audit": evidence["scope_audit"],
        "deferred_false_claims": verifier.DEFERRED_FALSE_CLAIMS,
        "test_readiness_is_production_proof": False,
        "eligible_successor": {
            "short_name": "C3",
            "change_id": "provision-independent-agent-git-workspaces",
            "eligible_now": True,
        },
        "status": "passed",
        "issued_at": evidence["issued_at"],
    }
    acceptance["receipt_digest"] = verifier.digest_value(acceptance)
    verifier.verify_document("acceptance", acceptance)
    verifier.verify_acceptance(
        acceptance,
        documents,
        document_digests,
        verify_sources=True,
    )
    return acceptance


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    output = arguments.output.resolve()
    expected_output = (
        verifier.OPERATOR_DIR / verifier.DOCUMENTS["acceptance"][0]
    ).resolve()
    if output != expected_output:
        raise ValueError(f"C2 acceptance output must be {expected_output}")
    if output.exists():
        raise ValueError("final C2 acceptance receipt already exists")
    evidence = verifier.load_json_object(arguments.evidence)
    acceptance = build_acceptance_receipt(evidence)
    output.write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(acceptance["receipt_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
