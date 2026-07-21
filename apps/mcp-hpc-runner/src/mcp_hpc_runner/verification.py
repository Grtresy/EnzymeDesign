from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from typing import Any

from .recovery import classify_pre_effect_failure
from .recovery import PreEffectFailureClass
from .transport import SshTransportManager


CANONICAL_TREE_MANIFEST_SCHEMA_VERSION = "canonical_tree_manifest@1"
AUTHORIZED_INPUT_SCHEMA_VERSION = "authorized_runner_input@1"
REMOTE_VERIFICATION_RECEIPT_SCHEMA_VERSION = "remote_input_verification@1"
_REMOTE_MARKER = "OPENZYME_REMOTE_VERIFY_V1:"
_MAX_TREE_ENTRIES = 100_000
_MAX_RELATIVE_PATH_BYTES = 2_048
_MAX_RECEIPT_BYTES = 4_096
_CHUNK_SIZE = 1024 * 1024
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class InputKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"


class RemoteVerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISSING = "missing"
    KIND_MISMATCH = "kind_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    UNSAFE_TREE = "unsafe_tree"
    METADATA_BOUND_EXCEEDED = "metadata_bound_exceeded"
    TRANSPORT_ERROR = "transport_error"
    INVALID_RECEIPT = "invalid_receipt"


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _validate_relative_path(relative: PurePosixPath) -> str:
    value = relative.as_posix()
    if (
        not value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.parts)
        or len(value.encode("utf-8")) > _MAX_RELATIVE_PATH_BYTES
    ):
        raise ValueError("canonical tree entry path is outside the metadata bound")
    return value


@dataclass(frozen=True, slots=True)
class CanonicalTreeManifest:
    entries: tuple[dict[str, object], ...]
    total_file_bytes: int
    manifest_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": CANONICAL_TREE_MANIFEST_SCHEMA_VERSION,
            "entry_count": len(self.entries),
            "total_file_bytes": self.total_file_bytes,
            "entries": [dict(entry) for entry in self.entries],
            "manifest_digest": self.manifest_digest,
        }


def build_canonical_tree_manifest(root: Path) -> CanonicalTreeManifest:
    root = Path(root)
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("canonical tree root must be a real directory")
    entries: list[dict[str, object]] = []
    total_file_bytes = 0
    for child in sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()):
        child_metadata = child.lstat()
        relative = _validate_relative_path(
            PurePosixPath(child.relative_to(root).as_posix())
        )
        if stat.S_ISLNK(child_metadata.st_mode):
            raise ValueError("canonical tree must not contain symbolic links")
        if stat.S_ISDIR(child_metadata.st_mode):
            entry: dict[str, object] = {"path": relative, "kind": "directory"}
        elif stat.S_ISREG(child_metadata.st_mode):
            total_file_bytes += child_metadata.st_size
            entry = {
                "path": relative,
                "kind": "file",
                "size": child_metadata.st_size,
                "content_digest": _file_digest(child),
            }
        else:
            raise ValueError("canonical tree contains an unsupported entry type")
        entries.append(entry)
        if len(entries) > _MAX_TREE_ENTRIES:
            raise ValueError("canonical tree exceeds the entry metadata bound")
    material = {
        "schema_version": CANONICAL_TREE_MANIFEST_SCHEMA_VERSION,
        "entry_count": len(entries),
        "total_file_bytes": total_file_bytes,
        "entries": entries,
    }
    return CanonicalTreeManifest(
        entries=tuple(entries),
        total_file_bytes=total_file_bytes,
        manifest_digest=canonical_digest(material),
    )


@dataclass(frozen=True, slots=True)
class AuthorizedInput:
    kind: InputKind
    content_digest: str
    byte_count: int
    tree_manifest: CanonicalTreeManifest | None = None

    @classmethod
    def from_path(cls, path: Path) -> AuthorizedInput:
        path = Path(path)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("authorized input must not be a symbolic link")
        if stat.S_ISREG(metadata.st_mode):
            return cls(
                kind=InputKind.FILE,
                content_digest=_file_digest(path),
                byte_count=metadata.st_size,
            )
        if stat.S_ISDIR(metadata.st_mode):
            manifest = build_canonical_tree_manifest(path)
            return cls(
                kind=InputKind.DIRECTORY,
                content_digest=manifest.manifest_digest,
                byte_count=manifest.total_file_bytes,
                tree_manifest=manifest,
            )
        raise ValueError("authorized input must be a regular file or directory")

    @property
    def contract_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": AUTHORIZED_INPUT_SCHEMA_VERSION,
                "kind": self.kind.value,
                "content_digest": self.content_digest,
                "byte_count": self.byte_count,
                "tree_manifest_digest": (
                    None
                    if self.tree_manifest is None
                    else self.tree_manifest.manifest_digest
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class RemoteVerification:
    status: RemoteVerificationStatus
    expected_content_digest: str
    observed_content_digest: str | None
    entry_count: int | None
    receipt_digest: str
    returncode: int
    timed_out: bool
    process_started: bool
    elapsed_seconds: float

    @property
    def verified(self) -> bool:
        return self.status is RemoteVerificationStatus.VERIFIED

    def to_private_manifest(self) -> dict[str, object]:
        return {
            "schema_version": REMOTE_VERIFICATION_RECEIPT_SCHEMA_VERSION,
            "status": self.status.value,
            "expected_content_digest": self.expected_content_digest,
            "observed_content_digest": self.observed_content_digest,
            "entry_count": self.entry_count,
            "receipt_digest": self.receipt_digest,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "process_started": self.process_started,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
        }


@dataclass(frozen=True, slots=True)
class RemoteContentObservation:
    status: RemoteVerificationStatus
    kind: InputKind
    content_digest: str | None
    entry_count: int | None
    receipt_digest: str
    returncode: int
    timed_out: bool
    process_started: bool
    elapsed_seconds: float

    @property
    def observed(self) -> bool:
        return (
            self.status is RemoteVerificationStatus.VERIFIED
            and self.content_digest is not None
        )

    def to_private_manifest(self) -> dict[str, object]:
        return {
            "schema_version": "remote_content_observation@1",
            "status": self.status.value,
            "kind": self.kind.value,
            "content_digest": self.content_digest,
            "entry_count": self.entry_count,
            "receipt_digest": self.receipt_digest,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "process_started": self.process_started,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
        }


_REMOTE_VERIFIER = r'''
import hashlib
import json
import os
import stat
import sys

SCHEMA = "canonical_tree_manifest@1"
MARKER = "OPENZYME_REMOTE_VERIFY_V1:"
path = sys.argv[1]
expected_kind = sys.argv[2]
max_entries = int(sys.argv[3])
max_path_bytes = int(sys.argv[4])

def digest_json(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()

def file_digest(value):
    digest = hashlib.sha256()
    with open(value, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()

receipt = {"schema_version": "remote_input_verification@1", "status": "verified", "kind": expected_kind, "content_digest": None, "entry_count": None}
try:
    metadata = os.lstat(path)
except FileNotFoundError:
    receipt["status"] = "missing"
else:
    if stat.S_ISLNK(metadata.st_mode):
        receipt["status"] = "unsafe_tree"
    elif expected_kind == "file":
        if not stat.S_ISREG(metadata.st_mode):
            receipt["status"] = "kind_mismatch"
        else:
            receipt["content_digest"] = file_digest(path)
            receipt["entry_count"] = 1
    elif expected_kind == "directory":
        if not stat.S_ISDIR(metadata.st_mode):
            receipt["status"] = "kind_mismatch"
        else:
            entries = []
            total_file_bytes = 0
            unsafe = False
            bounded = True
            for current, directories, files in os.walk(path, topdown=True, followlinks=False):
                directories.sort()
                files.sort()
                for name in [*directories, *files]:
                    child = os.path.join(current, name)
                    relative = os.path.relpath(child, path).replace(os.sep, "/")
                    if len(relative.encode("utf-8")) > max_path_bytes:
                        bounded = False
                        break
                    child_metadata = os.lstat(child)
                    if stat.S_ISLNK(child_metadata.st_mode):
                        unsafe = True
                        break
                    if stat.S_ISDIR(child_metadata.st_mode):
                        entry = {"path": relative, "kind": "directory"}
                    elif stat.S_ISREG(child_metadata.st_mode):
                        total_file_bytes += child_metadata.st_size
                        entry = {"path": relative, "kind": "file", "size": child_metadata.st_size, "content_digest": file_digest(child)}
                    else:
                        unsafe = True
                        break
                    entries.append(entry)
                    if len(entries) > max_entries:
                        bounded = False
                        break
                if unsafe or not bounded:
                    break
            if unsafe:
                receipt["status"] = "unsafe_tree"
            elif not bounded:
                receipt["status"] = "metadata_bound_exceeded"
            else:
                entries.sort(key=lambda item: item["path"])
                material = {"schema_version": SCHEMA, "entry_count": len(entries), "total_file_bytes": total_file_bytes, "entries": entries}
                receipt["content_digest"] = digest_json(material)
                receipt["entry_count"] = len(entries)
    else:
        receipt["status"] = "kind_mismatch"
print(MARKER + json.dumps(receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
'''.strip()


class RemoteInputVerifier:
    def __init__(self, transport_manager: SshTransportManager) -> None:
        self.transport_manager = transport_manager

    def verify(
        self,
        remote_path: str,
        authorized: AuthorizedInput,
        *,
        timeout: float,
    ) -> RemoteVerification:
        observation = self.observe(
            remote_path,
            authorized.kind,
            timeout=timeout,
        )
        status = observation.status
        if (
            status is RemoteVerificationStatus.VERIFIED
            and observation.content_digest != authorized.content_digest
        ):
            status = RemoteVerificationStatus.DIGEST_MISMATCH
        receipt = {
            "schema_version": REMOTE_VERIFICATION_RECEIPT_SCHEMA_VERSION,
            "status": status.value,
            "expected_content_digest": authorized.content_digest,
            "observed_content_digest": observation.content_digest,
            "entry_count": observation.entry_count,
            "returncode": observation.returncode,
            "timed_out": observation.timed_out,
            "process_started": observation.process_started,
            "elapsed_seconds": round(observation.elapsed_seconds, 6),
            "observation_receipt_digest": observation.receipt_digest,
        }
        return RemoteVerification(
            status=status,
            expected_content_digest=authorized.content_digest,
            observed_content_digest=observation.content_digest,
            entry_count=observation.entry_count,
            receipt_digest=canonical_digest(receipt),
            returncode=observation.returncode,
            timed_out=observation.timed_out,
            process_started=observation.process_started,
            elapsed_seconds=observation.elapsed_seconds,
        )

    def observe(
        self,
        remote_path: str,
        kind: InputKind,
        *,
        timeout: float,
        stage: str = "input_verification",
    ) -> RemoteContentObservation:
        result = self.transport_manager.run_ssh(
            [
                "python3",
                "-c",
                _REMOTE_VERIFIER,
                str(PurePosixPath(remote_path)),
                kind.value,
                str(_MAX_TREE_ENTRIES),
                str(_MAX_RELATIVE_PATH_BYTES),
            ],
            check=False,
            timeout=timeout,
            stage=stage,
        )
        base = {
            "schema_version": "remote_content_observation@1",
            "kind": kind.value,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "process_started": result.process_started,
            "elapsed_seconds": round(result.elapsed_seconds, 6),
        }
        if result.returncode != 0:
            return self._observation(
                base,
                kind=kind,
                status=(
                    RemoteVerificationStatus.TRANSPORT_ERROR
                    if classify_pre_effect_failure(result)
                    is PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                    else RemoteVerificationStatus.INVALID_RECEIPT
                ),
                content_digest=None,
                entry_count=None,
            )
        encoded = result.stdout.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_RECEIPT_BYTES:
            return self._observation(
                base,
                kind=kind,
                status=RemoteVerificationStatus.INVALID_RECEIPT,
                content_digest=None,
                entry_count=None,
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith(_REMOTE_MARKER)]
        if len(lines) != 1:
            return self._observation(
                base,
                kind=kind,
                status=RemoteVerificationStatus.INVALID_RECEIPT,
                content_digest=None,
                entry_count=None,
            )
        try:
            payload = json.loads(lines[0].removeprefix(_REMOTE_MARKER))
            if (
                not isinstance(payload, dict)
                or set(payload)
                != {
                    "schema_version",
                    "status",
                    "kind",
                    "content_digest",
                    "entry_count",
                }
                or payload.get("schema_version")
                != REMOTE_VERIFICATION_RECEIPT_SCHEMA_VERSION
                or payload.get("kind") != kind.value
            ):
                raise ValueError("invalid schema")
            remote_status = RemoteVerificationStatus(str(payload["status"]))
            observed = payload.get("content_digest")
            if observed is not None:
                observed = str(observed)
                if _SHA256.fullmatch(observed) is None:
                    raise ValueError("invalid digest")
            entry_count = payload.get("entry_count")
            if entry_count is not None:
                entry_count = int(entry_count)
                if entry_count < 0 or entry_count > _MAX_TREE_ENTRIES:
                    raise ValueError("invalid entry count")
            if remote_status is RemoteVerificationStatus.VERIFIED and (
                observed is None or entry_count is None
            ):
                raise ValueError("verified receipt is incomplete")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._observation(
                base,
                kind=kind,
                status=RemoteVerificationStatus.INVALID_RECEIPT,
                content_digest=None,
                entry_count=None,
            )
        return self._observation(
            base,
            kind=kind,
            status=remote_status,
            content_digest=observed,
            entry_count=entry_count,
        )

    @staticmethod
    def _observation(
        base: dict[str, object],
        *,
        kind: InputKind,
        status: RemoteVerificationStatus,
        content_digest: str | None,
        entry_count: int | None,
    ) -> RemoteContentObservation:
        receipt = {
            **base,
            "status": status.value,
            "content_digest": content_digest,
            "entry_count": entry_count,
        }
        return RemoteContentObservation(
            status=status,
            kind=kind,
            content_digest=content_digest,
            entry_count=entry_count,
            receipt_digest=canonical_digest(receipt),
            returncode=int(base["returncode"]),
            timed_out=bool(base["timed_out"]),
            process_started=bool(base["process_started"]),
            elapsed_seconds=float(base["elapsed_seconds"]),
        )


def remote_verification_stdout(
    authorized: AuthorizedInput,
    *,
    status: RemoteVerificationStatus = RemoteVerificationStatus.VERIFIED,
    observed_content_digest: str | None = None,
) -> str:
    """Build the closed remote receipt used by deterministic runner tests."""

    observed = (
        authorized.content_digest
        if observed_content_digest is None
        and status is RemoteVerificationStatus.VERIFIED
        else observed_content_digest
    )
    payload: dict[str, Any] = {
        "schema_version": REMOTE_VERIFICATION_RECEIPT_SCHEMA_VERSION,
        "status": status.value,
        "kind": authorized.kind.value,
        "content_digest": observed,
        "entry_count": (
            1
            if authorized.kind is InputKind.FILE
            else len(authorized.tree_manifest.entries if authorized.tree_manifest else ())
        ),
    }
    return _REMOTE_MARKER + json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
