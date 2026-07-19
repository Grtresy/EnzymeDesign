from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import tempfile
from typing import Any
from uuid import uuid4

from openzyme_domain import ArtifactKind
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SessionArtifactRecord
from openzyme_domain.control_plane import utc_now_iso

from .artifact_projection import project_artifact_for_agent
from .artifact_projection import sanitize_private_artifact_fields
from .tooling import ToolInvocation
from .tooling import ToolRegistryProtocol
from .tooling import ToolResult

WORKSPACE_ROOT = PurePosixPath("/workspace")
WORKSPACE_INPUT = PurePosixPath("/workspace/input")
WORKSPACE_OUTPUT = PurePosixPath("/workspace/output")
WORKSPACE_SRC = PurePosixPath("/workspace/src")
WORKSPACE_DIRECTORIES = ("src", "input", "work", "output", "logs", "manifest")
FASTA_ZERO_RECORDS_VALIDATION_PROFILE = "fasta_zero_records@1"
_EMPTY_RESULT_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_DERIVATION_CONTRACT_PATTERN = re.compile(
    r"^[a-z][a-z0-9_.-]*@[1-9][0-9]*$"
)


class ArtifactBoundaryError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.hint = hint
        self.details = {} if details is None else dict(details)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class FileDigest:
    content_digest: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class TreeManifest:
    tree_digest: str
    files: tuple[dict[str, Any], ...]
    total_bytes: int


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    materialization_id: str
    artifact_id: str
    artifact_digest: str
    path: str
    mode: str
    reused: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "materialization_id": self.materialization_id,
            "artifact_id": self.artifact_id,
            "artifact_digest": self.artifact_digest,
            "path": self.path,
            "mode": self.mode,
            "reused": self.reused,
        }


@dataclass(frozen=True, slots=True)
class RegisterResult:
    artifact: SessionArtifactRecord
    content_digest: str | None
    tree_digest: str | None
    validation: dict[str, Any]
    reused: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact": project_artifact_for_agent(self.artifact),
            "content_digest": self.content_digest,
            "tree_digest": self.tree_digest,
            "validation": self.validation,
            "reused": self.reused,
        }


@dataclass(frozen=True, slots=True)
class SourceSnapshotResult:
    artifact: SessionArtifactRecord
    source_tree_digest: str
    file_digests: dict[str, str]
    reused: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact": project_artifact_for_agent(self.artifact),
            "source_snapshot_artifact_id": self.artifact.artifact_id,
            "source_tree_digest": self.source_tree_digest,
            "file_digests": self.file_digests,
            "reused": self.reused,
        }


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _artifact_kind(value: str | ArtifactKind) -> ArtifactKind:
    if isinstance(value, ArtifactKind):
        return value
    try:
        return ArtifactKind(str(value))
    except ValueError as exc:
        allowed_values = [item.value for item in ArtifactKind]
        raise ArtifactBoundaryError(
            "artifact_kind_invalid",
            f"artifact kind {value!r} is invalid",
            hint=f"Use exactly one of: {', '.join(allowed_values)}.",
            details={"allowed_values": allowed_values},
        ) from exc


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _safe_ref(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    safe = safe.strip("._-")
    return safe[:120] or "artifact"


def _public_path(value: str | None, *, default: PurePosixPath) -> PurePosixPath:
    if value in {None, ""}:
        return default
    text = str(value)
    if text.startswith("/openzyme/"):
        text = "/workspace/" + text.removeprefix("/openzyme/")
    candidate = PurePosixPath(text)
    if candidate.is_absolute():
        return candidate
    if default in {WORKSPACE_INPUT, WORKSPACE_OUTPUT, WORKSPACE_SRC}:
        return default / candidate
    return default.parent / candidate


def _ensure_relative_safe(relative: PurePosixPath, *, error_code: str) -> None:
    if relative.is_absolute() or not relative.parts:
        raise ArtifactBoundaryError(error_code, "path must be relative inside the workspace")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ArtifactBoundaryError(error_code, "path must not contain empty, '.', or '..' segments")


def _workspace_relative(
    path: PurePosixPath,
    root: PurePosixPath,
    *,
    error_code: str,
    allow_root: bool = False,
) -> PurePosixPath:
    if not path.is_absolute():
        raise ArtifactBoundaryError(error_code, "workspace path must be absolute")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ArtifactBoundaryError(error_code, f"path must be under {root}") from exc
    if allow_root and relative == PurePosixPath("."):
        return relative
    _ensure_relative_safe(relative, error_code=error_code)
    return relative


def _resolve_workspace_host_path(
    workspace_path: Path,
    public_path: PurePosixPath,
    *,
    allowed_root: PurePosixPath,
    error_code: str,
    allow_root: bool = False,
) -> Path:
    relative = _workspace_relative(
        public_path,
        allowed_root,
        error_code=error_code,
        allow_root=allow_root,
    )
    target = (workspace_path / allowed_root.relative_to(WORKSPACE_ROOT) / relative).resolve()
    allowed_host_root = (workspace_path / allowed_root.relative_to(WORKSPACE_ROOT)).resolve()
    if target != allowed_host_root and allowed_host_root not in target.parents:
        raise ArtifactBoundaryError(error_code, "path escapes the allowed sandbox workspace root")
    for parent in (target, *target.parents):
        if parent == workspace_path.resolve().parent:
            break
        if parent.is_symlink():
            raise ArtifactBoundaryError(error_code, "path traverses a symlink")
    return target


def _file_digest(path: Path) -> FileDigest:
    stat = path.stat()
    return FileDigest(
        content_digest=_sha256_bytes(path.read_bytes()),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _tree_manifest(path: Path) -> TreeManifest:
    if path.is_symlink():
        raise ArtifactBoundaryError("artifact_register_invalid_path", "directory artifact source cannot be a symlink")
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        if child.is_dir():
            continue
        if child.is_symlink():
            raise ArtifactBoundaryError("artifact_register_invalid_path", "directory artifact cannot contain symlinks")
        digest = _file_digest(child)
        relative_path = child.relative_to(path).as_posix()
        files.append(
            {
                "relative_path": relative_path,
                "content_digest": digest.content_digest,
                "size_bytes": digest.size_bytes,
            }
        )
        total_bytes += digest.size_bytes
    if not files:
        raise ArtifactBoundaryError("artifact_validation_failed", "directory artifact must contain at least one file")
    return TreeManifest(
        tree_digest=_json_digest(files),
        files=tuple(files),
        total_bytes=total_bytes,
    )


def _digest_path(path: Path) -> tuple[str, dict[str, Any]]:
    if path.is_symlink():
        raise ArtifactBoundaryError("artifact_register_invalid_path", "artifact source cannot be a symlink")
    if path.is_file():
        digest = _file_digest(path)
        return digest.content_digest, {
            "type": "file",
            "content_digest": digest.content_digest,
            "size_bytes": digest.size_bytes,
            "mtime_ns": digest.mtime_ns,
        }
    if path.is_dir():
        manifest = _tree_manifest(path)
        return manifest.tree_digest, {
            "type": "directory",
            "tree_digest": manifest.tree_digest,
            "file_manifest": list(manifest.files),
            "total_bytes": manifest.total_bytes,
        }
    raise ArtifactBoundaryError("artifact_register_invalid_path", "artifact source must be a file or directory")


def _copy_path(source: Path, target: Path) -> None:
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copyfile(source, target)


def _chmod_readonly(path: Path) -> None:
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_dir():
                child.chmod(0o555)
            else:
                child.chmod(0o444)
        path.chmod(0o555)
    else:
        path.chmod(0o444)


def _summary_digest(entries: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "relative_path": item["relative_path"],
            "kind": item["kind"],
            "size": item["size"],
            "content_digest": item["content_digest"],
        }
        for item in sorted(entries, key=lambda value: value["relative_path"])
    ]
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def summarize_workspace_directory(workspace_path: Path) -> dict[str, Any]:
    root = workspace_path.resolve()
    entries: list[dict[str, Any]] = []
    directory_summaries: dict[str, dict[str, Any]] = {}
    for directory_name in WORKSPACE_DIRECTORIES:
        directory = root / directory_name
        files = []
        total_bytes = 0
        latest_mtime = 0.0
        if directory.exists():
            for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
                if path.is_dir():
                    continue
                relative_path = path.relative_to(root).as_posix()
                stat = path.lstat()
                latest_mtime = max(latest_mtime, stat.st_mtime)
                if path.is_symlink():
                    size = 0
                    content_digest = "sha256:symlink"
                    kind = "symlink"
                else:
                    content = path.read_bytes()
                    size = len(content)
                    content_digest = "sha256:" + hashlib.sha256(content).hexdigest()
                    kind = "file"
                total_bytes += size
                files.append(
                    {
                        "relative_path": relative_path,
                        "kind": kind,
                        "size": size,
                        "content_digest": content_digest,
                    }
                )
        directory_digest = _summary_digest(files)
        directory_summaries[directory_name] = {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "latest_mtime": latest_mtime,
            "content_digest": directory_digest,
            "truncated": False,
        }
        entries.extend(files)
    return {
        "directories": directory_summaries,
        "file_count": sum(item["file_count"] for item in directory_summaries.values()),
        "total_bytes": sum(item["total_bytes"] for item in directory_summaries.values()),
        "volume_digest": _summary_digest(entries),
        "truncated": False,
    }


def _artifact_digest(artifact: SessionArtifactRecord) -> str:
    metadata = dict(artifact.metadata or {})
    for key in ("sealed_digest", "content_digest", "tree_digest", "source_tree_digest"):
        value = metadata.get(key)
        if value:
            return str(value)
    storage_path = _storage_path(artifact)
    if storage_path is None:
        raise ArtifactBoundaryError(
            "artifact_blob_store_unavailable",
            "artifact content is not available as sealed Host storage",
        )
    digest, _summary = _digest_path(storage_path)
    return digest


def _storage_path(artifact: SessionArtifactRecord) -> Path | None:
    uri = str(artifact.storage_uri or "")
    if not uri or "://" in uri:
        return None
    return Path(uri)


def _validate_nonempty(path: Path) -> None:
    if path.is_file():
        if path.stat().st_size <= 0:
            raise ArtifactBoundaryError("artifact_validation_failed", "artifact file is empty")
        return
    manifest = _tree_manifest(path)
    if manifest.total_bytes <= 0:
        raise ArtifactBoundaryError("artifact_validation_failed", "artifact directory content is empty")


def _validate_fasta(path: Path) -> None:
    _validate_nonempty(path)
    if not path.is_file():
        raise ArtifactBoundaryError("artifact_validation_failed", "FASTA artifact must be a file")
    text = path.read_text(encoding="utf-8")
    records = [line for line in text.splitlines() if line.startswith(">")]
    sequence_lines = [line for line in text.splitlines() if line and not line.startswith(">")]
    if not records or not sequence_lines:
        raise ArtifactBoundaryError("artifact_validation_failed", "FASTA artifact is missing records or sequences")


def _validate_zero_record_fasta(
    path: Path,
    *,
    kind: ArtifactKind,
    format_value: str | None,
    metadata: dict[str, Any],
) -> dict[str, str]:
    normalized_format = None if format_value in {None, ""} else str(format_value).lower()
    reason = metadata.get("empty_result_reason")
    derivation_contract_id = metadata.get("derivation_contract_id")
    if kind is not ArtifactKind.SEQUENCE or normalized_format not in {
        "fa",
        "faa",
        "fasta",
    }:
        raise ArtifactBoundaryError(
            "artifact_validation_failed",
            "fasta_zero_records@1 requires kind=sequence and format=fasta",
        )
    if not isinstance(reason, str) or _EMPTY_RESULT_REASON_PATTERN.fullmatch(
        reason
    ) is None:
        raise ArtifactBoundaryError(
            "artifact_validation_failed",
            "fasta_zero_records@1 requires one stable empty-result reason",
        )
    if not isinstance(
        derivation_contract_id, str
    ) or _DERIVATION_CONTRACT_PATTERN.fullmatch(derivation_contract_id) is None:
        raise ArtifactBoundaryError(
            "artifact_validation_failed",
            "fasta_zero_records@1 requires one versioned derivation contract",
        )
    if not path.is_file() or path.read_bytes() != b"":
        raise ArtifactBoundaryError(
            "artifact_validation_failed",
            "fasta_zero_records@1 requires an exact zero-byte regular file",
        )
    return {
        "empty_result_reason": reason,
        "derivation_contract_id": derivation_contract_id,
    }


def _validate_hmm(path: Path) -> None:
    _validate_nonempty(path)
    if not path.is_file():
        raise ArtifactBoundaryError("artifact_validation_failed", "HMM artifact must be a file")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "HMMER" not in text or "//" not in text:
        raise ArtifactBoundaryError("artifact_validation_failed", "HMM artifact is missing HMMER markers")


def _validate_csv(path: Path, *, required_columns: tuple[str, ...]) -> None:
    _validate_nonempty(path)
    if not path.is_file():
        raise ArtifactBoundaryError("artifact_validation_failed", "CSV artifact must be a file")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
    if not columns:
        raise ArtifactBoundaryError("artifact_validation_failed", "CSV artifact is missing a header row")
    missing = [column for column in required_columns if column not in columns]
    if missing:
        raise ArtifactBoundaryError(
            "artifact_validation_failed",
            "CSV artifact is missing required columns",
            details={"missing_columns": missing, "columns": list(columns)},
        )


def _validate_json(path: Path) -> None:
    _validate_nonempty(path)
    if not path.is_file():
        raise ArtifactBoundaryError("artifact_validation_failed", "JSON artifact must be a file")
    json.loads(path.read_text(encoding="utf-8"))


def _run_validator(
    path: Path,
    *,
    kind: ArtifactKind,
    format_value: str | None,
    validation_profile: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    normalized_format = None if format_value in {None, ""} else str(format_value).lower()
    required_columns_raw = metadata.get("required_columns") or ()
    required_columns = tuple(str(item) for item in required_columns_raw)
    profile_details: dict[str, str] = {}
    try:
        if validation_profile is not None:
            if validation_profile != FASTA_ZERO_RECORDS_VALIDATION_PROFILE:
                raise ArtifactBoundaryError(
                    "artifact_validator_missing",
                    f"no artifact validation profile is registered for {validation_profile!r}",
                )
            profile_details = _validate_zero_record_fasta(
                path,
                kind=kind,
                format_value=format_value,
                metadata=metadata,
            )
        elif normalized_format in {None, "txt", "text", "log", "md", "markdown", "pdb", "pdbqt", "py", "python", "fpocket"}:
            _validate_nonempty(path)
        elif normalized_format in {"fa", "faa", "fasta"}:
            _validate_fasta(path)
        elif normalized_format == "hmm":
            _validate_hmm(path)
        elif normalized_format == "csv":
            _validate_csv(path, required_columns=required_columns)
        elif normalized_format == "json":
            _validate_json(path)
        else:
            raise ArtifactBoundaryError(
                "artifact_validator_missing",
                f"no artifact validator is registered for format {normalized_format!r}",
            )
    except UnicodeError as exc:
        raise ArtifactBoundaryError("artifact_validation_failed", "artifact is not valid UTF-8 text") from exc
    result: dict[str, Any] = {
        "status": "passed",
        "format": normalized_format,
        "required_columns": list(required_columns),
    }
    if validation_profile is not None:
        result.update(
            {
                "validation_profile": validation_profile,
                **profile_details,
            }
        )
    return result


def _blob_store_root(blob_store_root: Path | None) -> Path:
    root = blob_store_root or Path(tempfile.gettempdir()) / "openzyme-artifact-blobs"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _workspace_root(workspace_root: Path | None) -> Path:
    root = workspace_root or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


@dataclass(slots=True)
class ArtifactBoundaryService:
    repositories: Any
    workspace_root: Path | None = None
    blob_store_root: Path | None = None

    def materialize(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        artifact_id: str,
        target: str | None = None,
        mode: str = "copy",
    ) -> MaterializationResult:
        if mode not in {"copy", "readonly"}:
            raise ArtifactBoundaryError("artifact_materialization_conflict", "mode must be 'copy' or 'readonly'")
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None or artifact.session_id != session_id:
            raise ArtifactBoundaryError("artifact_scope_forbidden", "artifact is not available in this session")
        source, artifact_digest, source_summary = self._verify_artifact_blob(artifact)
        public_target = self._materialize_target(artifact, target)
        workspace_path = self._workspace_path(sandbox_workspace_id)
        target_path = _resolve_workspace_host_path(
            workspace_path,
            public_target,
            allowed_root=WORKSPACE_INPUT,
            error_code="artifact_materialize_target_forbidden",
        )
        if target_path.exists():
            existing_digest, existing_summary = _digest_path(target_path)
            if existing_summary["type"] != source_summary["type"]:
                raise ArtifactBoundaryError(
                    "artifact_materialize_type_conflict",
                    "materialization target already exists with a different artifact type",
                )
            if existing_digest != artifact_digest:
                raise ArtifactBoundaryError(
                    "artifact_materialization_conflict",
                    "materialization target already exists with different content",
                )
            if mode == "readonly":
                _chmod_readonly(target_path)
            reused = True
        else:
            _copy_path(source, target_path)
            copied_digest, copied_summary = _digest_path(target_path)
            source_digest_after, source_summary_after = _digest_path(source)
            if (
                copied_digest != artifact_digest
                or copied_summary["type"] != source_summary["type"]
                or source_digest_after != artifact_digest
                or source_summary_after["type"] != source_summary["type"]
            ):
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink(missing_ok=True)
                raise ArtifactBoundaryError(
                    "artifact_blob_digest_mismatch",
                    "artifact content changed while it was being materialized",
                    details={"artifact_id": artifact.artifact_id},
                )
            if mode == "readonly":
                _chmod_readonly(target_path)
            reused = False
        materialization_id = _json_digest(
            {
                "sandbox_workspace_id": sandbox_workspace_id,
                "artifact_id": artifact_id,
                "artifact_digest": artifact_digest,
                "target_path": public_target.as_posix(),
                "mode": mode,
            }
        )
        self.repositories.artifact_materializations.save(
            materialization_id=materialization_id,
            sandbox_workspace_id=sandbox_workspace_id,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            target_path=public_target.as_posix(),
            mode=mode,
            sandbox_path=public_target.as_posix(),
            created_at=utc_now_iso(),
        )
        self._update_workspace(
            workspace,
            materialized_input_artifact_ids=self._append_id(
                workspace.materialized_input_artifact_ids, artifact_id
            ),
        )
        return MaterializationResult(
            materialization_id=materialization_id,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            path=public_target.as_posix(),
            mode=mode,
            reused=reused,
        )

    def register(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        path: str,
        kind: str | ArtifactKind = ArtifactKind.RESULT,
        format: str | None = None,
        validation_profile: str | None = None,
        metadata: dict[str, Any] | None = None,
        invocation_id: str | None = None,
        run_id: str | None = None,
        source_snapshot_artifact_id: str | None = None,
    ) -> RegisterResult:
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        kind_value = _artifact_kind(kind)
        explicit_source_snapshot = source_snapshot_artifact_id is not None
        if source_snapshot_artifact_id is None:
            source_snapshot_id = self._latest_source_snapshot_id(workspace)
        else:
            source_snapshot_id = str(source_snapshot_artifact_id).strip()
        if source_snapshot_id is None:
            raise ArtifactBoundaryError("source_snapshot_required", "artifacts.register requires a source snapshot")
        if not source_snapshot_id:
            raise ArtifactBoundaryError("source_snapshot_required", "artifacts.register requires a source snapshot")
        source_snapshot = self.repositories.artifacts.get(source_snapshot_id)
        if source_snapshot is None or source_snapshot.session_id != session_id:
            raise ArtifactBoundaryError("source_snapshot_unavailable", "source snapshot artifact is unavailable")
        source_snapshot_metadata = dict(source_snapshot.metadata or {})
        if explicit_source_snapshot and (
            source_snapshot.kind is not ArtifactKind.CODE
            or source_snapshot_metadata.get("semantic_type")
            != "pipeline_source_snapshot"
            or source_snapshot_metadata.get("format") != "source_tree"
            or source_snapshot_metadata.get("sandbox_workspace_id")
            != sandbox_workspace_id
            or not source_snapshot_metadata.get("source_tree_digest")
        ):
            raise ArtifactBoundaryError(
                "source_snapshot_unavailable",
                "source snapshot artifact is not bound to this sandbox workspace",
            )
        metadata_payload = dict(metadata or {})
        if format is not None:
            metadata_payload["format"] = str(format)
        metadata_validation_profile = metadata_payload.get("validation_profile")
        if (
            metadata_validation_profile == FASTA_ZERO_RECORDS_VALIDATION_PROFILE
            and validation_profile != FASTA_ZERO_RECORDS_VALIDATION_PROFILE
        ):
            raise ArtifactBoundaryError(
                "artifact_validation_failed",
                "fasta_zero_records@1 must be selected through validation_profile",
            )
        if (
            validation_profile is not None
            and metadata_validation_profile not in {None, "", validation_profile}
        ):
            raise ArtifactBoundaryError(
                "artifact_validation_failed",
                "artifact validation_profile conflicts with metadata",
            )
        if validation_profile is not None:
            metadata_payload["validation_profile"] = str(validation_profile)
        public_path = _public_path(path, default=WORKSPACE_OUTPUT / "artifact")
        workspace_path = self._workspace_path(sandbox_workspace_id)
        source_path = _resolve_workspace_host_path(
            workspace_path,
            public_path,
            allowed_root=WORKSPACE_OUTPUT,
            error_code="artifact_register_invalid_path",
        )
        if not source_path.exists():
            raise ArtifactBoundaryError("artifact_register_invalid_path", "registered artifact source does not exist")
        relative_path = _workspace_relative(
            public_path,
            WORKSPACE_OUTPUT,
            error_code="artifact_register_invalid_path",
        ).as_posix()
        source_digest, source_summary_before = _digest_path(source_path)
        validation = _run_validator(
            source_path,
            kind=kind_value,
            format_value=metadata_payload.get("format"),
            validation_profile=validation_profile,
            metadata=metadata_payload,
        )
        metadata_digest = _json_digest(metadata_payload)
        register_key = _json_digest(
            {
                "sandbox_workspace_id": sandbox_workspace_id,
                "source_path": public_path.as_posix(),
                "source_digest": source_digest,
                "source_snapshot_artifact_id": source_snapshot_id,
                "metadata_digest": metadata_digest,
            }
        )
        existing = self.repositories.artifacts.find_by_metadata(
            session_id=session_id,
            key="s08_register_idempotency_key",
            value=register_key,
        )
        if existing is not None:
            self._verify_artifact_blob(existing)
            self._update_workspace(
                workspace,
                registered_artifact_ids=self._append_id(
                    workspace.registered_artifact_ids,
                    existing.artifact_id,
                ),
            )
            return RegisterResult(
                artifact=existing,
                content_digest=dict(existing.metadata or {}).get("content_digest"),
                tree_digest=dict(existing.metadata or {}).get("tree_digest"),
                validation=dict((existing.metadata or {}).get("validation") or {}),
                reused=True,
            )
        sealed_path, sealed_digest, sealed_summary = self._seal_source(
            source_path=source_path,
            source_digest=source_digest,
            source_summary_before=source_summary_before,
        )
        source_digest_after, source_summary_after = _digest_path(source_path)
        if source_digest_after != source_digest or source_summary_after != source_summary_before:
            self.repositories.artifact_blob_gc.enqueue(
                blob_ref=str(sealed_path),
                reason="artifact_source_unstable",
                created_at=utc_now_iso(),
            )
            raise ArtifactBoundaryError("artifact_source_unstable", "registered artifact source changed while sealing")
        if sealed_digest != source_digest:
            self.repositories.artifact_blob_gc.enqueue(
                blob_ref=str(sealed_path),
                reason="artifact_sealed_digest_mismatch",
                created_at=utc_now_iso(),
            )
            raise ArtifactBoundaryError("artifact_sealed_digest_mismatch", "sealed artifact digest does not match source")
        artifact_metadata = {
            **metadata_payload,
            "source": "sandbox_artifact_boundary",
            "storage_model": "sealed_blob",
            "sandbox_workspace_id": sandbox_workspace_id,
            "source_snapshot_artifact_id": source_snapshot_id,
            "source_tree_digest": source_snapshot_metadata.get("source_tree_digest"),
            "source_workspace_path": public_path.as_posix(),
            "source_digest": source_digest,
            "sealed_digest": sealed_digest,
            "validation": validation,
            "s08_register_idempotency_key": register_key,
            "provenance": {
                "sandbox_workspace_id": sandbox_workspace_id,
                "source_snapshot_artifact_id": source_snapshot_id,
                "source_workspace_path": public_path.as_posix(),
                "source_digest": source_digest,
                "sealed_digest": sealed_digest,
                "input_artifact_ids": list(workspace.materialized_input_artifact_ids),
            },
        }
        if sealed_summary["type"] == "file":
            artifact_metadata["content_digest"] = sealed_digest
        else:
            artifact_metadata["tree_digest"] = sealed_digest
            artifact_metadata["file_manifest"] = sealed_summary.get("file_manifest", [])
        self._require_register_provenance(artifact_metadata)
        artifact = SessionArtifactRecord(
            artifact_id=_new_id("art"),
            session_id=session_id,
            task_id=workspace.focus_task_id,
            lane_id=workspace.focus_lane_id,
            invocation_id=invocation_id,
            run_id=run_id,
            kind=kind_value,
            storage_uri=str(sealed_path),
            relative_path=relative_path,
            title=PurePosixPath(relative_path).name,
            description=None,
            metadata=artifact_metadata,
            created_at=utc_now_iso(),
        )
        try:
            self.repositories.artifacts.commit_immutable(artifact)
        except Exception as exc:
            self.repositories.artifact_blob_gc.enqueue(
                blob_ref=str(sealed_path),
                reason="artifact_commit_failed",
                created_at=utc_now_iso(),
            )
            raise ArtifactBoundaryError("artifact_commit_failed", "artifact row commit failed") from exc
        self._update_workspace(
            workspace,
            registered_artifact_ids=self._append_id(workspace.registered_artifact_ids, artifact.artifact_id),
        )
        return RegisterResult(
            artifact=artifact,
            content_digest=artifact_metadata.get("content_digest"),
            tree_digest=artifact_metadata.get("tree_digest"),
            validation=validation,
            reused=False,
        )

    def seal_external_bytes(
        self,
        *,
        session_id: str,
        content: bytes,
        filename: str,
        kind: str | ArtifactKind = ArtifactKind.RESULT,
        format: str,
        title: str,
        provider: str,
        provenance: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
        invocation_id: str | None = None,
        description: str | None = None,
        license_scope: str = "safe_provider_evidence",
    ) -> RegisterResult:
        """Seal Host-retrieved provider bytes without a sandbox source snapshot.

        This is a narrow ingress seam for licensed/safe external evidence. It
        keeps the same immutable blob and repository boundary as sandbox output
        while recording provider provenance instead of pretending a temporary
        Host file is already sealed.
        """

        kind_value = _artifact_kind(kind)
        if not isinstance(content, bytes) or not content:
            raise ArtifactBoundaryError(
                "artifact_validation_failed",
                "external provider artifact content must be non-empty bytes",
            )
        safe_filename = _safe_ref(PurePosixPath(filename).name)
        if not safe_filename:
            raise ArtifactBoundaryError(
                "artifact_validation_failed",
                "external provider artifact filename is invalid",
            )
        safe_provenance = sanitize_private_artifact_fields(dict(provenance))
        safe_metadata = sanitize_private_artifact_fields(dict(metadata or {}))
        required_provenance = ("request_digest", "retrieved_at")
        missing = [
            key for key in required_provenance if not safe_provenance.get(key)
        ]
        if missing:
            raise ArtifactBoundaryError(
                "artifact_provenance_incomplete",
                "external provider artifact provenance is incomplete",
                details={"missing": missing},
            )
        source_digest = _sha256_bytes(content)
        metadata_payload = {
            **safe_metadata,
            "format": str(format),
            "provider": str(provider),
            "license_scope": str(license_scope),
            "source": "external_provider_artifact_boundary",
            "storage_model": "sealed_blob",
            "content_digest": source_digest,
            "sealed_digest": source_digest,
            "provenance": {
                **safe_provenance,
                "provider": str(provider),
                "content_digest": source_digest,
                "sealed_digest": source_digest,
            },
        }
        idempotency_key = _json_digest(
            {
                "session_id": session_id,
                "invocation_id": invocation_id,
                "filename": safe_filename,
                "content_digest": source_digest,
                "metadata": metadata_payload,
            }
        )
        metadata_payload["external_seal_idempotency_key"] = idempotency_key
        existing = self.repositories.artifacts.find_by_metadata(
            session_id=session_id,
            key="external_seal_idempotency_key",
            value=idempotency_key,
        )
        validation = {
            "status": "passed",
            "format": str(format),
            "boundary": "external_provider",
        }
        if existing is not None:
            self._verify_artifact_blob(existing)
            return RegisterResult(
                artifact=existing,
                content_digest=source_digest,
                tree_digest=None,
                validation=validation,
                reused=True,
            )

        temporary_root = Path(tempfile.mkdtemp(prefix="openzyme-provider-seal-"))
        temporary_source = temporary_root / safe_filename
        try:
            temporary_source.write_bytes(content)
            source_summary = _digest_path(temporary_source)[1]
            sealed_path, sealed_digest, _ = self._seal_source(
                source_path=temporary_source,
                source_digest=source_digest,
                source_summary_before=source_summary,
            )
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        if sealed_digest != source_digest:
            raise ArtifactBoundaryError(
                "artifact_sealed_digest_mismatch",
                "sealed provider artifact digest does not match source",
            )
        artifact = SessionArtifactRecord(
            artifact_id=_new_id("art_provider"),
            session_id=session_id,
            task_id=task_id,
            lane_id=lane_id,
            invocation_id=invocation_id,
            run_id=None,
            kind=kind_value,
            storage_uri=str(sealed_path),
            relative_path=f"provider_evidence/{safe_filename}",
            title=title,
            description=description,
            metadata=metadata_payload,
            created_at=utc_now_iso(),
        )
        try:
            self.repositories.artifacts.commit_immutable(artifact)
        except Exception as exc:
            self.repositories.artifact_blob_gc.enqueue(
                blob_ref=str(sealed_path),
                reason="external_provider_artifact_commit_failed",
                created_at=utc_now_iso(),
            )
            raise ArtifactBoundaryError(
                "artifact_commit_failed",
                "external provider artifact row commit failed",
            ) from exc
        return RegisterResult(
            artifact=artifact,
            content_digest=sealed_digest,
            tree_digest=None,
            validation=validation,
            reused=False,
        )

    def snapshot_code(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        paths: str | list[str] | tuple[str, ...] | None,
        entrypoint: str,
        metadata: dict[str, Any] | None = None,
    ) -> SourceSnapshotResult:
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        workspace_path = self._workspace_path(sandbox_workspace_id)
        source_root = (workspace_path / "src").resolve()
        if not source_root.exists() or not source_root.is_dir():
            raise ArtifactBoundaryError("source_snapshot_empty", "workspace source directory is empty")
        selected_files = self._select_source_files(source_root, paths)
        if not selected_files:
            raise ArtifactBoundaryError("source_snapshot_empty", "source snapshot contains no files")
        file_entries: list[dict[str, Any]] = []
        for source_file in selected_files:
            digest = _file_digest(source_file)
            file_entries.append(
                {
                    "relative_path": source_file.relative_to(source_root).as_posix(),
                    "content_digest": digest.content_digest,
                    "size_bytes": digest.size_bytes,
                }
            )
        file_entries.sort(key=lambda item: item["relative_path"])
        source_tree_digest = _json_digest(file_entries)
        source_snapshot_id = _new_id("art")
        existing = self.repositories.artifacts.find_by_metadata(
            session_id=session_id,
            key="source_tree_digest",
            value=source_tree_digest,
            kind=ArtifactKind.CODE.value,
            metadata_filter={"sandbox_workspace_id": sandbox_workspace_id, "entrypoint": entrypoint},
        )
        if existing is not None:
            self._verify_artifact_blob(existing)
            self._update_workspace(
                workspace,
                source_code_artifact_ids=self._append_id(workspace.source_code_artifact_ids, existing.artifact_id),
            )
            return SourceSnapshotResult(
                artifact=existing,
                source_tree_digest=source_tree_digest,
                file_digests={item["relative_path"]: item["content_digest"] for item in file_entries},
                reused=True,
            )
        blob_root = _blob_store_root(self.blob_store_root)
        sealed_root = blob_root / "sealed" / "source" / source_tree_digest.removeprefix("sha256:")
        temp_root = blob_root / "tmp" / _new_id("source")
        try:
            for item in file_entries:
                source = source_root / str(item["relative_path"])
                target = temp_root / str(item["relative_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            copied_digest, _copied_summary = _digest_path(temp_root)
            if copied_digest != source_tree_digest:
                raise ArtifactBoundaryError(
                    "source_snapshot_changed",
                    "source files changed while the snapshot was being sealed",
                )
            if sealed_root.exists():
                existing_digest, _existing_summary = _digest_path(sealed_root)
                if existing_digest != source_tree_digest:
                    raise ArtifactBoundaryError(
                        "artifact_blob_digest_mismatch",
                        "an existing source snapshot blob does not match its digest",
                    )
            else:
                sealed_root.parent.mkdir(parents=True, exist_ok=True)
                temp_root.replace(sealed_root)
                _chmod_readonly(sealed_root)
            source_entries_after: list[dict[str, Any]] = []
            for item in file_entries:
                source = source_root / str(item["relative_path"])
                digest = _file_digest(source)
                source_entries_after.append(
                    {
                        "relative_path": item["relative_path"],
                        "content_digest": digest.content_digest,
                        "size_bytes": digest.size_bytes,
                    }
                )
            if _json_digest(source_entries_after) != source_tree_digest:
                raise ArtifactBoundaryError(
                    "source_snapshot_changed",
                    "source files changed while the snapshot was being sealed",
                )
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)
        parent_id = None if not workspace.source_code_artifact_ids else workspace.source_code_artifact_ids[-1]
        snapshot_metadata = {
            **dict(metadata or {}),
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "sandbox_workspace_id": sandbox_workspace_id,
            "entrypoint": entrypoint,
            "source_tree_digest": source_tree_digest,
            "file_digests": {item["relative_path"]: item["content_digest"] for item in file_entries},
            "parent_source_code_artifact_id": parent_id,
        }
        artifact = SessionArtifactRecord(
            artifact_id=source_snapshot_id,
            session_id=session_id,
            task_id=workspace.focus_task_id,
            lane_id=workspace.focus_lane_id,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.CODE,
            storage_uri=str(sealed_root),
            relative_path=f"code/{sandbox_workspace_id}/{source_tree_digest.removeprefix('sha256:')}",
            title=PurePosixPath(entrypoint).name or "source snapshot",
            description="Sandbox source tree snapshot",
            metadata=snapshot_metadata,
            created_at=utc_now_iso(),
        )
        try:
            self.repositories.artifacts.commit_immutable(artifact)
        except Exception as exc:
            raise ArtifactBoundaryError("source_snapshot_failed", "source snapshot artifact commit failed") from exc
        self._update_workspace(
            workspace,
            source_code_artifact_ids=self._append_id(workspace.source_code_artifact_ids, artifact.artifact_id),
        )
        return SourceSnapshotResult(
            artifact=artifact,
            source_tree_digest=source_tree_digest,
            file_digests={item["relative_path"]: item["content_digest"] for item in file_entries},
            reused=False,
        )

    def _require_workspace(self, session_id: str, sandbox_workspace_id: str) -> SandboxWorkspaceRecord:
        workspace = self.repositories.sandbox_workspaces.get(sandbox_workspace_id)
        if workspace is None or workspace.session_id != session_id:
            raise ArtifactBoundaryError("artifact_scope_forbidden", "sandbox workspace is not available in this session")
        return workspace

    def _workspace_path(self, sandbox_workspace_id: str) -> Path:
        return _workspace_root(self.workspace_root) / sandbox_workspace_id

    def _verify_artifact_blob(
        self,
        artifact: SessionArtifactRecord,
    ) -> tuple[Path, str, dict[str, Any]]:
        source = _storage_path(artifact)
        if source is None or not source.exists():
            raise ArtifactBoundaryError(
                "artifact_blob_store_unavailable",
                "artifact sealed storage is unavailable",
            )
        expected_digest = _artifact_digest(artifact)
        actual_digest, summary = _digest_path(source)
        if actual_digest != expected_digest:
            try:
                self.repositories.artifact_blob_gc.enqueue(
                    blob_ref=str(source),
                    reason="artifact_blob_digest_mismatch",
                    created_at=utc_now_iso(),
                )
            except Exception:
                # Integrity failure must remain fail-closed even when quarantine
                # bookkeeping is itself unavailable.
                pass
            raise ArtifactBoundaryError(
                "artifact_blob_digest_mismatch",
                "artifact sealed storage does not match its declared digest",
                details={
                    "artifact_id": artifact.artifact_id,
                    "expected_digest": expected_digest,
                    "actual_digest": actual_digest,
                },
            )
        return source, expected_digest, summary

    def _materialize_target(self, artifact: SessionArtifactRecord, target: str | None) -> PurePosixPath:
        if target not in {None, ""}:
            return _public_path(target, default=WORKSPACE_INPUT / artifact.artifact_id)
        relative = PurePosixPath(str(artifact.relative_path or artifact.artifact_id))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            relative = PurePosixPath(PurePosixPath(str(artifact.relative_path)).name or artifact.artifact_id)
        return WORKSPACE_INPUT / artifact.artifact_id / relative

    def _seal_source(
        self,
        *,
        source_path: Path,
        source_digest: str,
        source_summary_before: dict[str, Any],
    ) -> tuple[Path, str, dict[str, Any]]:
        root = _blob_store_root(self.blob_store_root)
        temp_path = root / "tmp" / _new_id("blobtmp")
        try:
            _copy_path(source_path, temp_path)
            sealed_digest, sealed_summary = _digest_path(temp_path)
            if sealed_digest != source_digest:
                raise ArtifactBoundaryError(
                    "artifact_sealed_digest_mismatch",
                    "sealed artifact digest does not match source",
                )
            digest_part = source_digest.removeprefix("sha256:")
            if source_summary_before["type"] == "file":
                sealed_path = root / "sealed" / "files" / digest_part
            else:
                sealed_path = root / "sealed" / "trees" / digest_part
            if sealed_path.exists():
                existing_digest, existing_summary = _digest_path(sealed_path)
                if (
                    existing_digest != source_digest
                    or existing_summary["type"] != source_summary_before["type"]
                ):
                    raise ArtifactBoundaryError(
                        "artifact_blob_digest_mismatch",
                        "an existing sealed artifact blob does not match its digest",
                    )
            else:
                sealed_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.replace(sealed_path)
                _chmod_readonly(sealed_path)
        except OSError as exc:
            raise ArtifactBoundaryError("artifact_seal_failed", "failed to seal artifact blob") from exc
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path) if temp_path.is_dir() else temp_path.unlink(missing_ok=True)
        return sealed_path, sealed_digest, sealed_summary

    def _require_register_provenance(self, metadata: dict[str, Any]) -> None:
        provenance = dict(metadata.get("provenance") or {})
        required = (
            "sandbox_workspace_id",
            "source_snapshot_artifact_id",
            "source_workspace_path",
            "source_digest",
            "sealed_digest",
        )
        missing = [key for key in required if not provenance.get(key)]
        if missing:
            raise ArtifactBoundaryError(
                "artifact_provenance_incomplete",
                "registered artifact provenance is incomplete",
                details={"missing": missing},
            )

    def _select_source_files(self, source_root: Path, paths: str | list[str] | tuple[str, ...] | None) -> tuple[Path, ...]:
        requested = ["/workspace/src"] if paths is None or paths == "" else ([paths] if isinstance(paths, str) else list(paths))
        selected: set[Path] = set()
        for raw in requested:
            public = _public_path(str(raw), default=WORKSPACE_SRC)
            host_path = _resolve_workspace_host_path(
                source_root.parent,
                public,
                allowed_root=WORKSPACE_SRC,
                error_code="source_snapshot_failed",
                allow_root=True,
            )
            if host_path.is_file():
                if not self._is_excluded_source_file(host_path, source_root):
                    selected.add(host_path)
            elif host_path.is_dir():
                for child in host_path.rglob("*"):
                    if child.is_file() and not child.is_symlink() and not self._is_excluded_source_file(child, source_root):
                        selected.add(child)
            else:
                raise ArtifactBoundaryError("source_snapshot_failed", "source snapshot path does not exist")
        return tuple(sorted(selected, key=lambda item: item.relative_to(source_root).as_posix()))

    def _is_excluded_source_file(self, path: Path, source_root: Path) -> bool:
        excluded_parts = {"__pycache__", ".pytest_cache", ".cache", ".git", ".venv", ".openzyme"}
        relative_parts = path.relative_to(source_root).parts
        if any(part in excluded_parts for part in relative_parts):
            return True
        return any(part.endswith((".tmp", ".lock")) for part in relative_parts)

    def _latest_source_snapshot_id(self, workspace: SandboxWorkspaceRecord) -> str | None:
        if workspace.source_code_artifact_ids:
            return workspace.source_code_artifact_ids[-1]
        if workspace.last_command_summary:
            snapshot_id = workspace.last_command_summary.get("source_snapshot_artifact_id")
            if snapshot_id:
                return str(snapshot_id)
        return None

    def _update_workspace(
        self,
        workspace: SandboxWorkspaceRecord,
        *,
        materialized_input_artifact_ids: tuple[str, ...] | None = None,
        registered_artifact_ids: tuple[str, ...] | None = None,
        source_code_artifact_ids: tuple[str, ...] | None = None,
    ) -> None:
        workspace_path = self._workspace_path(workspace.sandbox_workspace_id)
        directory_summary = summarize_workspace_directory(workspace_path)
        updated = replace(
            workspace,
            directory_summary=directory_summary,
            volume_digest=str(directory_summary.get("volume_digest") or ""),
            materialized_input_artifact_ids=materialized_input_artifact_ids
            if materialized_input_artifact_ids is not None
            else workspace.materialized_input_artifact_ids,
            registered_artifact_ids=registered_artifact_ids
            if registered_artifact_ids is not None
            else workspace.registered_artifact_ids,
            source_code_artifact_ids=source_code_artifact_ids
            if source_code_artifact_ids is not None
            else workspace.source_code_artifact_ids,
            last_attached_at=utc_now_iso(),
        )
        self.repositories.sandbox_workspaces.save(updated)

    def _append_id(self, values: tuple[str, ...], value: str) -> tuple[str, ...]:
        if value in values:
            return values
        return (*values, value)


def _tool_error(invocation: ToolInvocation, exc: ArtifactBoundaryError) -> ToolResult:
    payload = {
        "error": str(exc),
        "error_code": exc.error_code,
        "details": exc.details,
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=exc.error_code,
        error_code=exc.error_code,
        hint=exc.hint,
        details=payload,
    )


def register_artifact_boundary_tools(registry: ToolRegistryProtocol) -> None:
    def _service(context: Any) -> ArtifactBoundaryService:
        return ArtifactBoundaryService(
            context.repositories,
            workspace_root=getattr(context, "sandbox_workspace_root", None),
            blob_store_root=getattr(context, "artifact_blob_root", None),
        )

    def materialize_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).materialize(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=str(invocation.arguments["sandbox_workspace_id"]),
                artifact_id=str(invocation.arguments["artifact_id"]),
                target=None
                if invocation.arguments.get("target") is None
                else str(invocation.arguments.get("target")),
                mode=str(invocation.arguments.get("mode") or "copy"),
            )
        except ArtifactBoundaryError as exc:
            return _tool_error(invocation, exc)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(result.to_payload(), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="artifact_materialized",
        )

    def register_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).register(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=str(invocation.arguments["sandbox_workspace_id"]),
                path=str(invocation.arguments["path"]),
                kind=str(invocation.arguments.get("kind") or ArtifactKind.RESULT.value),
                format=None
                if invocation.arguments.get("format") is None
                else str(invocation.arguments.get("format")),
                validation_profile=(
                    None
                    if invocation.arguments.get("validation_profile") is None
                    else str(invocation.arguments.get("validation_profile"))
                ),
                metadata=dict(invocation.arguments.get("metadata") or {}),
            )
        except (ArtifactBoundaryError, ValueError) as exc:
            if isinstance(exc, ArtifactBoundaryError):
                return _tool_error(invocation, exc)
            return _tool_error(
                invocation,
                ArtifactBoundaryError("artifact_validation_failed", str(exc)),
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(result.to_payload(), sort_keys=True),
            task_id=result.artifact.task_id,
            lane_id=result.artifact.lane_id,
            status="artifact_registered",
        )

    def snapshot_code_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).snapshot_code(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=str(invocation.arguments["sandbox_workspace_id"]),
                paths=invocation.arguments.get("paths"),
                entrypoint=str(invocation.arguments["entrypoint"]),
                metadata=dict(invocation.arguments.get("metadata") or {}),
            )
        except ArtifactBoundaryError as exc:
            return _tool_error(invocation, exc)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(result.to_payload(), sort_keys=True),
            task_id=result.artifact.task_id,
            lane_id=result.artifact.lane_id,
            status="source_snapshot_created",
        )

    registry.register("artifacts.materialize", materialize_handler)
    registry.register("artifacts.register", register_handler)
    registry.register("artifacts.snapshot_code", snapshot_code_handler)


__all__ = [
    "ArtifactBoundaryError",
    "ArtifactBoundaryService",
    "FASTA_ZERO_RECORDS_VALIDATION_PROFILE",
    "MaterializationResult",
    "RegisterResult",
    "SourceSnapshotResult",
    "register_artifact_boundary_tools",
]
