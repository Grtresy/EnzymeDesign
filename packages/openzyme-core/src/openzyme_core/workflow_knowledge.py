from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any

from .docs import DocumentRecord
from .docs import DocumentRegistry
from .docs import default_document_registry


_WORKFLOW_REF_PREFIX = "workflow:"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CAPABILITY_PATTERN = re.compile(
    r"^[a-z][a-z0-9._-]*:[a-z0-9][a-z0-9._-]*$"
)
_VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def workflow_manifest_content_sha256(payload: dict[str, Any]) -> str:
    """Hash the complete manifest contract except its declared digest."""

    canonical = dict(payload)
    canonical.pop("content_sha256", None)
    return _canonical_json_sha256(canonical)


def is_workflow_ref(value: str) -> bool:
    return value.startswith(_WORKFLOW_REF_PREFIX)


@dataclass(frozen=True, slots=True)
class KnowledgeReference:
    doc_id: str
    version: str
    content_sha256: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KnowledgeReference":
        reference = cls(
            doc_id=str(payload["doc_id"]),
            version=str(payload["version"]),
            content_sha256=str(payload["content_sha256"]),
        )
        if not _ID_PATTERN.fullmatch(reference.doc_id):
            raise ValueError(f"invalid knowledge doc_id {reference.doc_id!r}")
        if not reference.version or any(
            character.isspace() for character in reference.version
        ):
            raise ValueError(
                f"invalid knowledge version {reference.version!r} for {reference.doc_id!r}"
            )
        _require_digest(reference.content_sha256, label="knowledge content_sha256")
        return reference

    def to_dict(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id,
            "version": self.version,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class WorkflowManifest:
    workflow_id: str
    version: str
    content_sha256: str
    title: str
    summary: str
    capability_requirements: tuple[str, ...]
    tool_requirements: tuple[str, ...]
    knowledge_refs: tuple[KnowledgeReference, ...]
    manifest_path: str

    @property
    def selection_ref(self) -> str:
        return (
            f"{_WORKFLOW_REF_PREFIX}{self.workflow_id}@{self.version}"
            f"#{self.content_sha256}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "content_sha256": self.content_sha256,
            "title": self.title,
            "summary": self.summary,
            "capability_requirements": list(self.capability_requirements),
            "tool_requirements": list(self.tool_requirements),
            "knowledge_refs": [reference.to_dict() for reference in self.knowledge_refs],
            "manifest_path": self.manifest_path,
            "selection_ref": self.selection_ref,
        }


@dataclass(frozen=True, slots=True)
class WorkflowKnowledgePack:
    manifest: WorkflowManifest
    documents: tuple[DocumentRecord, ...]

    def render_prompt_document(self) -> str:
        manifest = self.manifest
        lines = [
            "# Explicitly selected workflow knowledge pack",
            "",
            f"workflow_id: {manifest.workflow_id}",
            f"version: {manifest.version}",
            f"content_sha256: {manifest.content_sha256}",
            (
                "manifest_owner: WorkflowRegistry selection owner; this exact "
                "manifest is already resolved and loaded"
            ),
            (
                f"manifest_path: {manifest.manifest_path} (WorkflowRegistry "
                "provenance only; not a docs.read path)"
            ),
            (
                "knowledge_owner: DocumentRegistry; docs.read accepts only the "
                "knowledge_refs below by doc_id or registered knowledge path"
            ),
            "capability_requirements: "
            + (", ".join(manifest.capability_requirements) or "none"),
            "tool_requirements: " + (", ".join(manifest.tool_requirements) or "none"),
            "knowledge_refs:",
        ]
        for reference in manifest.knowledge_refs:
            lines.append(
                f"- {reference.doc_id}@{reference.version}#{reference.content_sha256}"
            )
        for document in self.documents:
            lines.extend(
                (
                    "",
                    f"## Knowledge document: {document.doc_id}",
                    f"version: {document.version}",
                    f"content_sha256: {document.content_sha256}",
                    "",
                    document.content,
                )
            )
        return "\n".join(lines)


@dataclass(slots=True)
class WorkflowRegistry:
    manifests: dict[tuple[str, str], WorkflowManifest]
    document_registry: DocumentRegistry

    @classmethod
    def from_directory(
        cls,
        root: Path,
        *,
        document_registry: DocumentRegistry,
        base_path: str = "docs/v3/workflow-packs",
    ) -> "WorkflowRegistry":
        manifests: dict[tuple[str, str], WorkflowManifest] = {}
        for path in sorted(root.rglob("*.workflow.json")):
            raw_payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw_payload, dict):
                raise ValueError(f"workflow manifest {path} must be a JSON object")
            payload = dict(raw_payload)
            allowed_fields = {
                "workflow_id",
                "version",
                "content_sha256",
                "title",
                "summary",
                "capability_requirements",
                "tool_requirements",
                "knowledge_refs",
            }
            unknown_fields = sorted(set(payload) - allowed_fields)
            if unknown_fields:
                raise ValueError(
                    f"workflow manifest {path} has unknown fields: "
                    f"{', '.join(unknown_fields)}"
                )
            declared_digest = str(payload.get("content_sha256") or "")
            _require_digest(declared_digest, label="workflow content_sha256")
            actual_digest = workflow_manifest_content_sha256(payload)
            if not hmac.compare_digest(declared_digest, actual_digest):
                raise ValueError(
                    f"workflow manifest digest drift for {path}: "
                    f"expected {declared_digest!r}, computed {actual_digest!r}"
                )
            workflow_id = str(payload["workflow_id"])
            version = str(payload["version"])
            if not _ID_PATTERN.fullmatch(workflow_id):
                raise ValueError(f"invalid workflow_id {workflow_id!r} in {path}")
            if not _VERSION_PATTERN.fullmatch(version):
                raise ValueError(f"invalid workflow version {version!r} in {path}")
            capability_requirements = tuple(
                str(item) for item in payload.get("capability_requirements", ())
            )
            tool_requirements = tuple(
                str(item) for item in payload.get("tool_requirements", ())
            )
            if len(capability_requirements) != len(set(capability_requirements)):
                raise ValueError(
                    f"workflow manifest {workflow_id!r} has duplicate capability requirements"
                )
            if len(tool_requirements) != len(set(tool_requirements)):
                raise ValueError(
                    f"workflow manifest {workflow_id!r} has duplicate tool requirements"
                )
            if any(not requirement for requirement in capability_requirements):
                raise ValueError(
                    f"workflow manifest {workflow_id!r} has an empty capability requirement"
                )
            if any(
                not _CAPABILITY_PATTERN.fullmatch(requirement)
                for requirement in capability_requirements
            ):
                raise ValueError(
                    f"workflow manifest {workflow_id!r} has an invalid capability requirement"
                )
            if any(
                not _ID_PATTERN.fullmatch(requirement)
                for requirement in tool_requirements
            ):
                raise ValueError(
                    f"workflow manifest {workflow_id!r} has an invalid tool requirement"
                )
            knowledge_refs = tuple(
                KnowledgeReference.from_dict(dict(item))
                for item in payload.get("knowledge_refs", ())
            )
            doc_ids = tuple(reference.doc_id for reference in knowledge_refs)
            if len(doc_ids) != len(set(doc_ids)):
                raise ValueError(
                    f"workflow manifest {workflow_id!r} has duplicate knowledge refs"
                )
            manifest = WorkflowManifest(
                workflow_id=workflow_id,
                version=version,
                content_sha256=declared_digest,
                title=str(payload.get("title") or payload["workflow_id"]),
                summary=str(payload.get("summary") or ""),
                capability_requirements=capability_requirements,
                tool_requirements=tool_requirements,
                knowledge_refs=knowledge_refs,
                manifest_path=(
                    f"{base_path.rstrip('/')}/{path.relative_to(root).as_posix()}"
                ),
            )
            if not manifest.workflow_id or not manifest.version:
                raise ValueError(f"workflow manifest {path} requires id and version")
            if not manifest.knowledge_refs:
                raise ValueError(
                    f"workflow manifest {manifest.selection_ref!r} requires knowledge_refs"
                )
            key = (manifest.workflow_id, manifest.version)
            if key in manifests:
                raise ValueError(
                    f"duplicate workflow manifest {manifest.selection_ref!r}"
                )
            manifests[key] = manifest
        if not manifests:
            raise ValueError(f"workflow registry {base_path!r} is empty")
        return cls(manifests=manifests, document_registry=document_registry)

    def list_manifests(self) -> tuple[WorkflowManifest, ...]:
        return tuple(
            self.manifests[key]
            for key in sorted(self.manifests, key=lambda item: (item[0], item[1]))
        )

    def resolve(self, selection_ref: str) -> WorkflowKnowledgePack:
        workflow_id, version, expected_digest = _parse_workflow_ref(selection_ref)
        manifest = self.manifests.get((workflow_id, version))
        if manifest is None:
            raise ValueError(f"workflow {selection_ref!r} is not registered")
        if not hmac.compare_digest(manifest.content_sha256, expected_digest):
            raise ValueError(
                f"workflow {workflow_id!r} manifest digest drift: "
                f"expected {expected_digest!r}, found {manifest.content_sha256!r}"
            )
        documents = tuple(
            self.document_registry.read(
                reference.doc_id,
                version=reference.version,
                content_sha256=reference.content_sha256,
            )
            for reference in manifest.knowledge_refs
        )
        return WorkflowKnowledgePack(manifest=manifest, documents=documents)


def _parse_workflow_ref(selection_ref: str) -> tuple[str, str, str]:
    if not is_workflow_ref(selection_ref):
        raise ValueError(
            "workflow reference must use "
            f"{_WORKFLOW_REF_PREFIX}<id>@<version>#sha256:<digest>"
        )
    value = selection_ref.removeprefix(_WORKFLOW_REF_PREFIX)
    identity, digest_separator, content_sha256 = value.rpartition("#")
    workflow_id, version_separator, version = identity.rpartition("@")
    if (
        not digest_separator
        or not version_separator
        or not workflow_id
        or not version
        or not _ID_PATTERN.fullmatch(workflow_id)
        or not _VERSION_PATTERN.fullmatch(version)
    ):
        raise ValueError(
            "workflow reference must use "
            f"{_WORKFLOW_REF_PREFIX}<id>@<version>#sha256:<digest>"
        )
    _require_digest(content_sha256, label="workflow reference digest")
    return workflow_id, version, content_sha256


def _require_digest(value: str, *, label: str) -> None:
    if not _DIGEST_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must use sha256:<64 lowercase hex characters>")


def validate_workflow_requirements(
    pack: WorkflowKnowledgePack,
    *,
    available_tools: set[str],
    available_capabilities: set[str],
) -> None:
    missing_tools = sorted(
        set(pack.manifest.tool_requirements) - available_tools
    )
    missing_capabilities = sorted(
        set(pack.manifest.capability_requirements) - available_capabilities
    )
    if missing_tools or missing_capabilities:
        raise ValueError(
            "workflow requirements unavailable for "
            f"{pack.manifest.selection_ref!r}: "
            f"missing_tools={missing_tools!r}, "
            f"missing_capabilities={missing_capabilities!r}"
        )


def default_workflow_registry() -> WorkflowRegistry:
    root = Path(__file__).resolve().parents[4] / "docs" / "v3" / "workflow-packs"
    return WorkflowRegistry.from_directory(
        root,
        document_registry=default_document_registry(),
    )


__all__ = [
    "KnowledgeReference",
    "WorkflowKnowledgePack",
    "WorkflowManifest",
    "WorkflowRegistry",
    "default_workflow_registry",
    "is_workflow_ref",
    "validate_workflow_requirements",
    "workflow_manifest_content_sha256",
]
