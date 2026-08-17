from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
from typing import Any

from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    doc_id: str
    title: str
    summary: str
    tags: tuple[str, ...]
    version: str
    content_sha256: str
    path: str
    content: str

    def metadata(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "summary": self.summary,
            "tags": list(self.tags),
            "version": self.version,
            "content_sha256": self.content_sha256,
            "path": self.path,
        }

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        payload = self.metadata()
        if include_content:
            payload["content"] = self.content
        return payload


@dataclass(slots=True)
class DocumentRegistry:
    documents: dict[str, DocumentRecord]
    paths: dict[str, str]

    @classmethod
    def from_directory(
        cls,
        root: Path,
        *,
        base_path: str = "docs/v3/execution-pipeline-docs",
        version: str = "v3",
    ) -> "DocumentRegistry":
        documents: dict[str, DocumentRecord] = {}
        paths: dict[str, str] = {}
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(root).as_posix()
            repo_path = f"{base_path}/{relative}"
            doc_id = relative.removesuffix(".md").replace("/", ".")
            content = path.read_text(encoding="utf-8")
            title = _extract_title(content) or path.stem.replace("-", " ").title()
            tags = _infer_tags(relative, content)
            record = DocumentRecord(
                doc_id=doc_id,
                title=title,
                summary=_extract_summary(content),
                tags=tags,
                version=version,
                content_sha256=_content_sha256(content),
                path=repo_path,
                content=content,
            )
            documents[doc_id] = record
            paths[repo_path] = doc_id
        return cls(documents=documents, paths=paths)

    def search(self, query: str, *, tags: tuple[str, ...] = (), limit: int = 5) -> list[DocumentRecord]:
        normalized_query = query.casefold().strip()
        normalized_tags = {tag.casefold() for tag in tags}
        scored: list[tuple[int, DocumentRecord]] = []
        for record in self.documents.values():
            haystack = " ".join((record.doc_id, record.title, record.summary, " ".join(record.tags), record.content)).casefold()
            if normalized_tags and not normalized_tags.issubset({tag.casefold() for tag in record.tags}):
                continue
            score = 0
            if normalized_query:
                for term in normalized_query.split():
                    if term in record.doc_id.casefold():
                        score += 5
                    if term in record.title.casefold():
                        score += 4
                    if term in record.summary.casefold() or term in " ".join(record.tags).casefold():
                        score += 3
                    if term in haystack:
                        score += 1
            else:
                score = 1
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].doc_id))
        return [record for _, record in scored[: max(1, min(limit, 20))]]

    def read(
        self,
        ref: str,
        *,
        version: str | None = None,
        content_sha256: str | None = None,
    ) -> DocumentRecord:
        doc_id = self.paths.get(ref, ref)
        record = self.documents.get(doc_id)
        if record is None:
            if _looks_like_workflow_manifest_ref(ref):
                raise ValueError(
                    f"workflow manifest {ref!r} is owned by WorkflowRegistry; "
                    "selected manifests are already loaded by the workflow-selection "
                    "owner, while docs.read reads only DocumentRegistry knowledge "
                    "refs by doc_id or registered knowledge path"
                )
            raise ValueError(f"document {ref!r} is not registered")
        if version is not None and record.version != version:
            raise ValueError(
                f"document {ref!r} version drift: expected {version!r}, "
                f"found {record.version!r}"
            )
        if content_sha256 is not None and not hmac.compare_digest(
            record.content_sha256, content_sha256
        ):
            raise ValueError(
                f"document {ref!r} digest drift: expected {content_sha256!r}, "
                f"found {record.content_sha256!r}"
            )
        return record


def default_document_registry() -> DocumentRegistry:
    root = Path(__file__).resolve().parents[4] / "docs" / "v3" / "execution-pipeline-docs"
    return DocumentRegistry.from_directory(root)


def register_docs_tools(registry: ToolRegistry, document_registry: DocumentRegistry | None = None) -> None:
    docs = document_registry or default_document_registry()

    def search_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        tags = tuple(str(tag) for tag in invocation.arguments.get("tags", []) or [])
        results = docs.search(
            str(invocation.arguments["query"]),
            tags=tags,
            limit=int(invocation.arguments.get("limit") or 5),
        )
        import json

        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps({"documents": [record.to_dict() for record in results]}, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def read_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        import json

        ref = invocation.arguments.get("doc_id") or invocation.arguments.get("path")
        if not ref:
            raise ValueError("docs.read requires doc_id or path")
        record = docs.read(
            str(ref),
            version=(
                None
                if invocation.arguments.get("version") is None
                else str(invocation.arguments["version"])
            ),
            content_sha256=(
                None
                if invocation.arguments.get("content_sha256") is None
                else str(invocation.arguments["content_sha256"])
            ),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(record.to_dict(include_content=True), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    registry.register("docs.search", search_handler)
    registry.register("docs.read", read_handler)


def _extract_title(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    return None


def _looks_like_workflow_manifest_ref(ref: str) -> bool:
    normalized = ref.strip()
    return normalized.startswith("workflow:") or normalized.endswith(
        ".workflow.json"
    )


def _content_sha256(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _extract_summary(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("-"):
            return stripped[:240]
    return ""


def _infer_tags(relative_path: str, content: str) -> tuple[str, ...]:
    lowered = f"{relative_path}\n{content}".casefold()
    candidates = (
        "pipeline",
        "sandbox",
        "preprocess",
        "hpc",
        "fpocket",
        "vina",
        "batch",
        "dry-run",
    )
    return tuple(tag for tag in candidates if tag in lowered)


__all__ = ["DocumentRecord", "DocumentRegistry", "default_document_registry", "register_docs_tools"]
