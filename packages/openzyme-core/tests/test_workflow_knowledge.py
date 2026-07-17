from __future__ import annotations

import hashlib
import json

import pytest

from openzyme_core.docs import DocumentRecord
from openzyme_core.docs import DocumentRegistry
from openzyme_core.workflow_knowledge import WorkflowRegistry
from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_core.workflow_knowledge import validate_workflow_requirements
from openzyme_core.workflow_knowledge import workflow_manifest_content_sha256


def _digest(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _document_registry(
    content: str = "# Controlled workflow\n\nUse real evidence.",
) -> DocumentRegistry:
    record = DocumentRecord(
        doc_id="controlled-workflow",
        title="Controlled workflow",
        summary="Use real evidence.",
        tags=("workflow",),
        version="v3",
        content_sha256=_digest(content),
        path="docs/v3/execution-pipeline-docs/controlled-workflow.md",
        content=content,
    )
    return DocumentRegistry(
        documents={record.doc_id: record},
        paths={record.path: record.doc_id},
    )


def _manifest_payload(document_registry: DocumentRegistry) -> dict[str, object]:
    document = document_registry.read("controlled-workflow")
    payload: dict[str, object] = {
        "workflow_id": "controlled-workflow",
        "version": "1.0.0",
        "title": "Controlled workflow",
        "summary": "A versioned workflow binding.",
        "capability_requirements": ["role:executor", "engine:execution"],
        "tool_requirements": ["docs.read", "sandbox.exec"],
        "knowledge_refs": [
            {
                "doc_id": document.doc_id,
                "version": document.version,
                "content_sha256": document.content_sha256,
            }
        ],
    }
    payload["content_sha256"] = workflow_manifest_content_sha256(payload)
    return payload


def _registry(tmp_path, payload: dict[str, object]) -> WorkflowRegistry:
    manifest_path = tmp_path / "controlled.workflow.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return WorkflowRegistry.from_directory(
        tmp_path,
        document_registry=_document_registry(),
    )


def test_default_workflow_registry_resolves_pinned_relative_manifests() -> None:
    registry = default_workflow_registry()

    manifests = registry.list_manifests()

    assert {manifest.workflow_id for manifest in manifests} == {
        "aox-hmm-live",
        "generic-sandbox-execution",
    }
    for manifest in manifests:
        assert not manifest.manifest_path.startswith("/")
        assert registry.resolve(manifest.selection_ref).manifest == manifest


def test_aox_workflow_v2_pins_scientific_acceptance_without_strategy_graph() -> None:
    registry = default_workflow_registry()
    manifest = next(
        item for item in registry.list_manifests() if item.workflow_id == "aox-hmm-live"
    )

    assert manifest.selection_ref == (
        "workflow:aox-hmm-live@2.0.0#"
        "sha256:88a98c4a9fcc81c85414a66a88bc1c316c00f5ac7ce95414d5c6e2cf0fb1dbad"
    )
    pack = registry.resolve(manifest.selection_ref)
    documents = {document.doc_id: document for document in pack.documents}
    assert {
        doc_id: document.content_sha256 for doc_id, document in documents.items()
    } == {
        "aox-hmm-live": (
            "sha256:735da4c5980e5eebc4fcee16555d2f4e623d84c10d69f906d4adf9c9b838d74e"
        ),
        "aox-motif-rule-score-v1": (
            "sha256:48518a90ae2f6b3f0604118b643d595bacda0799a8ee510a6c679c93946783cf"
        ),
        "aox-sequence-similarity-v1": (
            "sha256:99147d4332068ae75ea1dd424887c90b6a56ba8ebc7b52ac04bf38f64ac22eb5"
        ),
    }

    sop = documents["aox-hmm-live"].content
    expected_accessions = (
        "AAC72747.1",
        "KDQ24956.1",
        "9AVH_A",
        "XP_014653549.1",
        "KIS68002.1",
        "XP_003660923.1",
        "AMW87253.1",
        "AFP17823.1",
        "WP_190019735.1",
        "WP_138089821.1",
        "WP_176407597.1",
        "CAQ19343.1",
        "CAQ19344.1",
    )
    accession_block = sop.split("```text\n", maxsplit=1)[1].split("\n```", maxsplit=1)[
        0
    ]
    assert tuple(accession_block.splitlines()) == expected_accessions
    for required_identity in (
        "PubMed supplies the required literature evidence",
        "NCBI supplies one exact 14-record protein FASTA aggregate",
        "EBI HMMER REST supplies the real `refprot` search receipt",
        "UniProt supplies candidate identity",
        "Semantic Scholar and Tavily are enrichment only",
        "`aox_hmm_reference_set_selection@1`",
        "`aox_reference_selection@1`",
        "`aox_scoring_input_assembly@1`",
        "`hmmer_score_filtered_accessions@1`",
        "`aox_sequence_length_join@1`",
        "`aox_known_positive_probe@2`",
        "`aox_motif_rule_score@1`",
        "`cdhit_cluster_membership@1`",
        "`aox_candidate_graph_nodes@1`",
        "`aox_candidate_graph_edges@1`",
        "`aox_candidate_similarity_graph_manifest@1`",
        '`scientific_outcome.status="empty"`',
        "Scientific fail-closed matrix",
        "workflow graph",
        "execution order",
    ):
        assert required_identity in sop


def test_document_registry_exact_read_rejects_version_and_digest_drift() -> None:
    registry = _document_registry()
    document = registry.read("controlled-workflow")

    with pytest.raises(ValueError, match="version drift"):
        registry.read(document.doc_id, version="v2")
    with pytest.raises(ValueError, match="digest drift"):
        registry.read(document.doc_id, content_sha256="sha256:" + "0" * 64)


def test_workflow_registry_rejects_manifest_digest_drift(tmp_path) -> None:
    documents = _document_registry()
    payload = _manifest_payload(documents)
    payload["summary"] = "Mutated after signing."

    with pytest.raises(ValueError, match="manifest digest drift"):
        _registry(tmp_path, payload)


def test_workflow_registry_rejects_unknown_manifest_fields(tmp_path) -> None:
    payload = _manifest_payload(_document_registry())
    payload["unexpected"] = True
    payload["content_sha256"] = workflow_manifest_content_sha256(payload)

    with pytest.raises(ValueError, match="unknown fields"):
        _registry(tmp_path, payload)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        (
            "capability_requirements",
            ["role:executor", "role:executor"],
            "duplicate capability requirements",
        ),
        (
            "capability_requirements",
            ["executor"],
            "invalid capability requirement",
        ),
        (
            "tool_requirements",
            ["docs.read", "docs.read"],
            "duplicate tool requirements",
        ),
        ("tool_requirements", ["docs/read"], "invalid tool requirement"),
    ),
)
def test_workflow_registry_rejects_invalid_requirements(
    tmp_path,
    field_name: str,
    value: list[str],
    message: str,
) -> None:
    payload = _manifest_payload(_document_registry())
    payload[field_name] = value
    payload["content_sha256"] = workflow_manifest_content_sha256(payload)

    with pytest.raises(ValueError, match=message):
        _registry(tmp_path, payload)


def test_workflow_resolution_rejects_knowledge_digest_drift(tmp_path) -> None:
    payload = _manifest_payload(_document_registry())
    knowledge_ref = dict(payload["knowledge_refs"][0])  # type: ignore[index]
    knowledge_ref["content_sha256"] = "sha256:" + "0" * 64
    payload["knowledge_refs"] = [knowledge_ref]
    payload["content_sha256"] = workflow_manifest_content_sha256(payload)
    registry = _registry(tmp_path, payload)
    manifest = registry.list_manifests()[0]

    with pytest.raises(ValueError, match="digest drift"):
        registry.resolve(manifest.selection_ref)


def test_workflow_requirement_validation_is_fail_closed(tmp_path) -> None:
    payload = _manifest_payload(_document_registry())
    registry = _registry(tmp_path, payload)
    pack = registry.resolve(registry.list_manifests()[0].selection_ref)

    with pytest.raises(ValueError, match="missing_tools=.*sandbox.exec"):
        validate_workflow_requirements(
            pack,
            available_tools={"docs.read"},
            available_capabilities={"role:executor", "engine:execution"},
        )
    with pytest.raises(ValueError, match="missing_capabilities=.*engine:execution"):
        validate_workflow_requirements(
            pack,
            available_tools={"docs.read", "sandbox.exec"},
            available_capabilities={"role:executor"},
        )
