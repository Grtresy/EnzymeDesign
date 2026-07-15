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


def _document_registry(content: str = "# Controlled workflow\n\nUse real evidence.") -> DocumentRegistry:
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
