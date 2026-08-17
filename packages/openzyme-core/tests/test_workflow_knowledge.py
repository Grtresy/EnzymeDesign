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
        "tool_requirements": ["docs.read", "workspace.exec"],
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


def test_selected_workflow_pack_exposes_registry_owners_without_reloading_manifest() -> (
    None
):
    registry = default_workflow_registry()
    manifest = next(
        item
        for item in registry.list_manifests()
        if item.workflow_id == "aox-hmm-live"
    )

    rendered = registry.resolve(manifest.selection_ref).render_prompt_document()

    assert (
        "manifest_owner: WorkflowRegistry selection owner; this exact manifest "
        "is already resolved and loaded"
    ) in rendered
    assert (
        f"manifest_path: {manifest.manifest_path} (WorkflowRegistry provenance "
        "only; not a docs.read path)"
    ) in rendered
    assert (
        "knowledge_owner: DocumentRegistry; docs.read accepts only the "
        "knowledge_refs below"
    ) in rendered


def test_aox_workflow_v2_pins_file_first_scientific_acceptance() -> None:
    registry = default_workflow_registry()
    manifest = next(
        item for item in registry.list_manifests() if item.workflow_id == "aox-hmm-live"
    )

    assert manifest.selection_ref == (
        "workflow:aox-hmm-live@2.0.0#"
        "sha256:2a1b2da3761ee01b2a905c8042b400851bb73cd02051b5d886f60e48f231fd7f"
    )
    pack = registry.resolve(manifest.selection_ref)
    documents = {document.doc_id: document for document in pack.documents}
    assert {
        doc_id: document.content_sha256 for doc_id, document in documents.items()
    } == {
        "aox-hmm-live": (
            "sha256:185a0f099c7349988b923c8b0f10e6333af225ce29538bac8d699526ffd96b10"
        ),
        "aox-motif-rule-score-v1": (
            "sha256:2e5c9e08f4750d0cc98c07aba0bc96ef5611ee32812977749d46c65c2ddc4570"
        ),
        "aox-sequence-similarity-v1": (
            "sha256:0efec4c10df2896186928fab621b28382fc0a81f1a371a2226d02a3f21787733"
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
    normalized_sop = " ".join(sop.split())
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
        "`aox_sequence_length_join@2`",
        "`aox_motif_rule_score@1`",
        "`hmmer_afa_alignment_canonicalization@1`",
        "`cdhit_cluster_membership@1`",
        "`aox_candidate_graph_nodes@1`",
        "`aox_candidate_graph_edges@1`",
        "`aox_candidate_similarity_graph_manifest@1`",
        "full post-motif, pre-clustering candidate set",
        "representative-only `aox_hmm/AOX_candidates_cdhit85.fasta`",
        "`candidate_membership_set_mismatch`",
        '`scientific_outcome.status="empty"`',
        "Scientific fail-closed matrix",
        "publication ref, commit, tree, normalized path",
        "Job success alone and local path presence are insufficient",
    ):
        assert " ".join(required_identity.split()) in normalized_sop


def test_document_registry_exact_read_rejects_version_and_digest_drift() -> None:
    registry = _document_registry()
    document = registry.read("controlled-workflow")

    with pytest.raises(ValueError, match="version drift"):
        registry.read(document.doc_id, version="v2")
    with pytest.raises(ValueError, match="digest drift"):
        registry.read(document.doc_id, content_sha256="sha256:" + "0" * 64)


@pytest.mark.parametrize(
    "manifest_ref",
    (
        "workflow:controlled-workflow@1.0.0#sha256:" + "0" * 64,
        "docs/v3/workflow-packs/controlled.workflow.json",
    ),
)
def test_document_registry_reports_workflow_manifest_namespace_misroute(
    manifest_ref: str,
) -> None:
    registry = _document_registry()

    with pytest.raises(ValueError) as error:
        registry.read(manifest_ref)

    message = str(error.value)
    assert "owned by WorkflowRegistry" in message
    assert "already loaded by the workflow-selection owner" in message
    assert "docs.read reads only DocumentRegistry knowledge refs" in message


def test_document_registry_keeps_plain_missing_document_error() -> None:
    with pytest.raises(ValueError, match="document 'missing' is not registered"):
        _document_registry().read("missing")


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

    with pytest.raises(ValueError, match="missing_tools=.*workspace.exec"):
        validate_workflow_requirements(
            pack,
            available_tools={"docs.read"},
            available_capabilities={"role:executor", "engine:execution"},
        )
    with pytest.raises(ValueError, match="missing_capabilities=.*engine:execution"):
        validate_workflow_requirements(
            pack,
            available_tools={"docs.read", "workspace.exec"},
            available_capabilities={"role:executor"},
        )
