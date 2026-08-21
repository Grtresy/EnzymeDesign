from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import sys


SCHEMA = "openzyme_workspace_transfer_helper@1"
TREE_MANIFEST_SCHEMA = "openzyme_workspace_transfer_tree@1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "intent_digest",
        "transfer_ref",
        "transfer_manifest_digest",
        "direction",
        "workspace_path",
        "transfer_path",
        "object_kind",
        "max_bytes",
        "expected_content_digest",
        "expected_size_bytes",
        "revision_identity",
    }
)


class TransferRejected(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TransferRejected(
                "workspace_transfer_request_invalid",
                f"duplicate request key {key!r}",
            )
        result[key] = value
    return result


def _relative_path(value: object, *, field_name: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "\x00" in value
        or "\\" in value
        or any(character in value for character in ("*", "?", "[", "]"))
    ):
        raise TransferRejected(
            "workspace_transfer_path_invalid",
            f"{field_name} must be one exact relative POSIX path",
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise TransferRejected(
            "workspace_transfer_path_escape",
            f"{field_name} escapes its controlled root",
        )
    return path


def _resolve(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        observed = current / part
        if observed.exists() or observed.is_symlink():
            metadata = observed.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise TransferRejected(
                    "workspace_transfer_symlink_forbidden",
                    "transfer paths must not traverse symbolic links",
                )
            if current != root and not stat.S_ISDIR(current.lstat().st_mode):
                raise TransferRejected(
                    "workspace_transfer_path_invalid",
                    "a transfer path parent is not a directory",
                )
        current = observed
    try:
        current.relative_to(root)
    except ValueError as exc:
        raise TransferRejected(
            "workspace_transfer_path_escape",
            "transfer path escaped its controlled root",
        ) from exc
    return current


def _regular_file_digest(path: Path, *, remaining_bytes: int) -> tuple[str, int]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise TransferRejected(
            "workspace_transfer_special_file_forbidden",
            "only regular files and directories may be transferred",
        )
    if metadata.st_nlink != 1:
        raise TransferRejected(
            "workspace_transfer_hardlink_forbidden",
            "hard-linked files are outside the transfer contract",
        )
    if metadata.st_size > remaining_bytes:
        raise TransferRejected(
            "workspace_transfer_size_exceeded",
            "transfer source exceeds its declared byte budget",
        )
    digest = hashlib.sha256()
    observed_size = 0
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(1024 * 1024):
                observed_size += len(chunk)
                if observed_size > remaining_bytes:
                    raise TransferRejected(
                        "workspace_transfer_size_exceeded",
                        "transfer source grew beyond its declared byte budget",
                    )
                digest.update(chunk)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        after.st_ino != metadata.st_ino
        or after.st_dev != metadata.st_dev
        or after.st_size != observed_size
        or after.st_mtime_ns != metadata.st_mtime_ns
        or after.st_nlink != 1
    ):
        raise TransferRejected(
            "workspace_transfer_source_drift",
            "transfer source changed while it was inspected",
        )
    return f"sha256:{digest.hexdigest()}", observed_size


def _inspect(path: Path, *, max_bytes: int) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        raise TransferRejected(
            "workspace_transfer_source_missing",
            "transfer source does not exist",
        )
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise TransferRejected(
            "workspace_transfer_symlink_forbidden",
            "symbolic links are outside the transfer contract",
        )
    if stat.S_ISREG(metadata.st_mode):
        digest, size = _regular_file_digest(path, remaining_bytes=max_bytes)
        return {
            "object_kind": "file",
            "content_digest": digest,
            "size_bytes": size,
            "entry_count": 1,
        }
    if not stat.S_ISDIR(metadata.st_mode):
        raise TransferRejected(
            "workspace_transfer_special_file_forbidden",
            "only regular files and directories may be transferred",
        )

    entries: list[dict[str, object]] = []
    total_size = 0
    for current_root, directory_names, file_names in os.walk(
        path,
        topdown=True,
        followlinks=False,
    ):
        directory_names.sort()
        file_names.sort()
        current = Path(current_root)
        for name in directory_names:
            child = current / name
            child_metadata = child.lstat()
            if stat.S_ISLNK(child_metadata.st_mode):
                raise TransferRejected(
                    "workspace_transfer_symlink_forbidden",
                    "directory trees must not contain symbolic links",
                )
            if not stat.S_ISDIR(child_metadata.st_mode):
                raise TransferRejected(
                    "workspace_transfer_special_file_forbidden",
                    "directory trees contain an unsupported entry",
                )
            entries.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "kind": "directory",
                }
            )
        for name in file_names:
            child = current / name
            relative = child.relative_to(path).as_posix()
            digest, size = _regular_file_digest(
                child,
                remaining_bytes=max_bytes - total_size,
            )
            total_size += size
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size_bytes": size,
                    "content_digest": digest,
                }
            )
        if len(entries) > 100_000:
            raise TransferRejected(
                "workspace_transfer_entry_limit_exceeded",
                "directory transfer exceeds the entry-count limit",
            )
    entries.sort(key=lambda item: (str(item["path"]), str(item["kind"])))
    manifest = {
        "schema_version": TREE_MANIFEST_SCHEMA,
        "entries": entries,
    }
    return {
        "object_kind": "directory",
        "content_digest": _sha256(_json_bytes(manifest)),
        "size_bytes": total_size,
        "entry_count": len(entries),
    }


def _copy_regular(source: Path, destination: Path) -> None:
    source_metadata = source.lstat()
    if not stat.S_ISREG(source_metadata.st_mode) or source_metadata.st_nlink != 1:
        raise TransferRejected(
            "workspace_transfer_source_drift",
            "source is no longer one regular unlinked file",
        )
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        destination_flags |= os.O_NOFOLLOW
    source_descriptor = os.open(source, source_flags)
    destination_descriptor = os.open(destination, destination_flags, 0o600)
    try:
        with (
            os.fdopen(source_descriptor, "rb", closefd=False) as source_stream,
            os.fdopen(
                destination_descriptor,
                "wb",
                closefd=False,
            ) as destination_stream,
        ):
            shutil.copyfileobj(source_stream, destination_stream, 1024 * 1024)
            destination_stream.flush()
            os.fsync(destination_stream.fileno())
    finally:
        os.close(source_descriptor)
        os.close(destination_descriptor)


def _copy_directory(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for current_root, directory_names, file_names in os.walk(
        source,
        topdown=True,
        followlinks=False,
    ):
        directory_names.sort()
        file_names.sort()
        current = Path(current_root)
        relative_root = current.relative_to(source)
        destination_root = destination / relative_root
        for name in directory_names:
            child = current / name
            if not stat.S_ISDIR(child.lstat().st_mode):
                raise TransferRejected(
                    "workspace_transfer_source_drift",
                    "source directory changed during transfer",
                )
            (destination_root / name).mkdir(mode=0o700)
        for name in file_names:
            _copy_regular(current / name, destination_root / name)


def _copy_atomic(
    source: Path,
    destination: Path,
    *,
    operation_id: str,
    expected: dict[str, object],
) -> bool:
    if destination.exists() or destination.is_symlink():
        observed = _inspect(destination, max_bytes=int(expected["size_bytes"]))
        if observed == expected:
            return True
        raise TransferRejected(
            "workspace_transfer_destination_collision",
            "transfer destination already contains different content",
        )
    parent = destination.parent
    if not parent.exists() or not stat.S_ISDIR(parent.lstat().st_mode):
        raise TransferRejected(
            "workspace_transfer_parent_missing",
            "transfer destination parent must be created explicitly",
        )
    temporary = parent / f".openzyme-transfer-{operation_id}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise TransferRejected(
            "workspace_transfer_temporary_collision",
            "transfer temporary identity is already occupied",
        )
    renamed = False
    try:
        if expected["object_kind"] == "file":
            _copy_regular(source, temporary)
        else:
            _copy_directory(source, temporary)
        copied = _inspect(temporary, max_bytes=int(expected["size_bytes"]))
        if copied != expected:
            raise TransferRejected(
                "workspace_transfer_copy_mismatch",
                "copied transfer bytes do not match the verified source",
            )
        os.replace(temporary, destination)
        renamed = True
        return False
    finally:
        if not renamed and (temporary.exists() or temporary.is_symlink()):
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary)
            else:
                temporary.unlink()


def execute_request(
    request: dict[str, object],
    *,
    workspace_root: Path,
    transfer_root: Path,
) -> dict[str, object]:
    if frozenset(request) != _FIELDS or request.get("schema_version") != SCHEMA:
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "transfer helper request is not one closed schema",
        )
    operation_id = request["operation_id"]
    transfer_ref = request["transfer_ref"]
    if (
        not isinstance(operation_id, str)
        or _IDENTIFIER.fullmatch(operation_id) is None
        or not isinstance(transfer_ref, str)
        or _IDENTIFIER.fullmatch(transfer_ref) is None
    ):
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "operation and transfer identities must be opaque",
        )
    for field_name in ("intent_digest", "transfer_manifest_digest"):
        value = request[field_name]
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise TransferRejected(
                "workspace_transfer_request_invalid",
                f"{field_name} must be a digest",
            )
    direction = request["direction"]
    object_kind = request["object_kind"]
    if direction not in {"upload", "download", "sync_revision"}:
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "unsupported transfer direction",
        )
    if object_kind not in {"file", "directory", "revision_tree"}:
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "unsupported transfer object kind",
        )
    max_bytes = request["max_bytes"]
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or not 1 <= max_bytes <= 68_719_476_736
    ):
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "transfer byte budget is invalid",
        )
    expected_digest = request["expected_content_digest"]
    expected_size = request["expected_size_bytes"]
    if expected_digest is not None and (
        not isinstance(expected_digest, str)
        or _DIGEST.fullmatch(expected_digest) is None
    ):
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "expected content identity is invalid",
        )
    if expected_size is not None and (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
        or expected_size > max_bytes
    ):
        raise TransferRejected(
            "workspace_transfer_request_invalid",
            "expected transfer size is invalid",
        )
    revision_identity = request["revision_identity"]
    if direction == "sync_revision":
        if object_kind != "revision_tree" or not isinstance(revision_identity, dict):
            raise TransferRejected(
                "workspace_transfer_revision_identity_missing",
                "revision sync requires one exact revision-tree identity",
            )
    elif revision_identity is not None or object_kind == "revision_tree":
        raise TransferRejected(
            "workspace_transfer_revision_identity_unexpected",
            "ordinary upload/download cannot claim revision semantics",
        )

    workspace_path = _relative_path(
        request["workspace_path"],
        field_name="workspace_path",
    )
    transfer_path = _relative_path(
        request["transfer_path"],
        field_name="transfer_path",
    )
    workspace = _resolve(workspace_root, workspace_path)
    transfer = _resolve(transfer_root, transfer_path)
    source, destination = (
        (workspace, transfer) if direction == "upload" else (transfer, workspace)
    )
    observed = _inspect(source, max_bytes=max_bytes)
    observed_kind = observed["object_kind"]
    expected_kind = "directory" if object_kind == "revision_tree" else object_kind
    if observed_kind != expected_kind:
        raise TransferRejected(
            "workspace_transfer_object_kind_mismatch",
            "transfer source kind differs from its reserved contract",
        )
    if expected_digest is not None and observed["content_digest"] != expected_digest:
        raise TransferRejected(
            "workspace_transfer_content_mismatch",
            "transfer source digest differs from its reserved contract",
        )
    if expected_size is not None and observed["size_bytes"] != expected_size:
        raise TransferRejected(
            "workspace_transfer_size_mismatch",
            "transfer source size differs from its reserved contract",
        )
    replayed = _copy_atomic(
        source,
        destination,
        operation_id=operation_id,
        expected=observed,
    )
    return {
        "schema_version": SCHEMA,
        "ok": True,
        "effect_certainty": "terminal_known",
        "mutation_applied": True,
        "result": {
            "transfer_ref": transfer_ref,
            "transfer_manifest_digest": request["transfer_manifest_digest"],
            "direction": direction,
            "workspace_path": workspace_path.as_posix(),
            "object_kind": object_kind,
            "content_digest": observed["content_digest"],
            "size_bytes": observed["size_bytes"],
            "entry_count": observed["entry_count"],
            "revision_identity": revision_identity,
            "replayed": replayed,
            "checkpoint_performed": False,
            "publication_performed": False,
            "workspace_cleanup_performed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        },
    }


def _main() -> int:
    transfer_root = Path(sys.argv[1] if len(sys.argv) == 2 else "/openzyme-transfer")
    try:
        request = json.loads(
            sys.stdin.buffer.read(),
            object_pairs_hook=_closed_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                TransferRejected(
                    "workspace_transfer_request_invalid",
                    f"non-finite request value {value}",
                )
            ),
        )
        if not isinstance(request, dict):
            raise TransferRejected(
                "workspace_transfer_request_invalid",
                "transfer helper request must be an object",
            )
        response = execute_request(
            request,
            workspace_root=Path.cwd(),
            transfer_root=transfer_root,
        )
    except TransferRejected as exc:
        response = {
            "schema_version": SCHEMA,
            "ok": False,
            "error_code": exc.code,
            "effect_certainty": "no_effect",
            "mutation_applied": False,
        }
    except Exception:
        response = {
            "schema_version": SCHEMA,
            "ok": False,
            "error_code": "workspace_transfer_helper_unclassified",
            "effect_certainty": "dispatch_in_doubt",
            "mutation_applied": None,
        }
    sys.stdout.buffer.write(_json_bytes(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
