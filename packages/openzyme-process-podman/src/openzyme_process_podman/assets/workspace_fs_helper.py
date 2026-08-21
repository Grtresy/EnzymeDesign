from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile


SCHEMA_VERSION = "openzyme_workspace_fs_helper@1"
_GLOB_CHARACTERS = ("*", "?", "[", "]")
_HUNK = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?\n?$"
)


class HelperError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HelperError("workspace_helper_duplicate_json_key")
        result[key] = value
    return result


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(encoded)


def _relative(value: object, *, allow_root: bool = False) -> str:
    if (
        not isinstance(value, str)
        or "\x00" in value
        or "\\" in value
        or any(character in value for character in _GLOB_CHARACTERS)
    ):
        raise HelperError("workspace_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise HelperError("workspace_path_escape")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        if allow_root:
            return "."
        raise HelperError("workspace_root_mutation_forbidden")
    return normalized


def _root() -> Path:
    root = Path.cwd()
    if root.is_symlink() or not root.is_dir():
        raise HelperError("workspace_root_invalid")
    return root.resolve(strict=True)


def _resolve(
    root: Path,
    relative: str,
    *,
    allow_missing_leaf: bool = False,
) -> Path:
    if relative == ".":
        return root
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        candidate = current / part
        exists = candidate.exists() or candidate.is_symlink()
        if not exists:
            if allow_missing_leaf and index == len(parts) - 1:
                return candidate
            raise HelperError("workspace_path_missing")
        metadata = os.lstat(candidate)
        if stat.S_ISLNK(metadata.st_mode):
            raise HelperError("workspace_symlink_forbidden")
        if index != len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise HelperError("workspace_parent_not_directory")
        current = candidate
    resolved_parent = current.parent.resolve(strict=True)
    if os.path.commonpath((str(root), str(resolved_parent))) != str(root):
        raise HelperError("workspace_path_escape")
    return current


def _kind(metadata: os.stat_result) -> str:
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    raise HelperError("workspace_special_file_forbidden")


def _reject_hardlink(metadata: os.stat_result) -> None:
    if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
        raise HelperError("workspace_hardlink_forbidden")


def _stable_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _file_bytes(path: Path, *, max_bytes: int | None = None) -> tuple[bytes, bool]:
    metadata = os.lstat(path)
    if _kind(metadata) != "file":
        raise HelperError("workspace_regular_file_required")
    _reject_hardlink(metadata)
    with path.open("rb") as stream:
        if max_bytes is None:
            value = stream.read()
            truncated = False
        else:
            value = stream.read(max_bytes + 1)
            truncated = len(value) > max_bytes
            value = value[:max_bytes]
    if _stable_identity(os.lstat(path)) != _stable_identity(metadata):
        raise HelperError("workspace_file_changed_during_observation")
    return value, truncated


def _file_digest(path: Path) -> str:
    metadata = os.lstat(path)
    if _kind(metadata) != "file":
        raise HelperError("workspace_regular_file_required")
    _reject_hardlink(metadata)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                break
            digest.update(chunk)
    if _stable_identity(os.lstat(path)) != _stable_identity(metadata):
        raise HelperError("workspace_file_changed_during_observation")
    return f"sha256:{digest.hexdigest()}"


def _tree_digest(path: Path) -> str:
    entries: list[dict[str, object]] = []
    for current_root, directory_names, file_names in os.walk(path, followlinks=False):
        directory_names.sort()
        file_names.sort()
        current = Path(current_root)
        for name in directory_names:
            candidate = current / name
            metadata = os.lstat(candidate)
            if _kind(metadata) != "directory":
                raise HelperError("workspace_symlink_forbidden")
            entries.append(
                {
                    "path": candidate.relative_to(path).as_posix(),
                    "kind": "directory",
                }
            )
        for name in file_names:
            candidate = current / name
            metadata = os.lstat(candidate)
            if _kind(metadata) != "file":
                raise HelperError("workspace_special_file_forbidden")
            _reject_hardlink(metadata)
            entries.append(
                {
                    "path": candidate.relative_to(path).as_posix(),
                    "kind": "file",
                    "size": metadata.st_size,
                    "digest": _file_digest(candidate),
                }
            )
    return _canonical_digest(entries)


def _content_digest(path: Path) -> str:
    metadata = os.lstat(path)
    return _file_digest(path) if _kind(metadata) == "file" else _tree_digest(path)


def _require_expected(path: Path, expected: object) -> str:
    if not isinstance(expected, str):
        raise HelperError("workspace_content_precondition_required")
    observed = _content_digest(path)
    if observed != expected:
        raise HelperError("workspace_content_precondition_failed")
    return observed


def _decode_content(value: object) -> bytes:
    if not isinstance(value, str):
        raise HelperError("workspace_content_required")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise HelperError("workspace_content_encoding_invalid") from exc


def _atomic_write(path: Path, value: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".openzyme-write-",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _patch_path(value: str, target: str, prefix: str) -> None:
    candidate = value.strip().split("\t", 1)[0]
    if candidate.startswith(prefix):
        candidate = candidate[len(prefix) :]
    if _relative(candidate) != target:
        raise HelperError("workspace_patch_target_mismatch")


def _apply_unified_patch(current: bytes, patch: bytes, target: str) -> bytes:
    try:
        current_text = current.decode("utf-8")
        patch_text = patch.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HelperError("workspace_patch_utf8_required") from exc
    patch_lines = patch_text.splitlines(keepends=True)
    if len(patch_lines) < 3 or not patch_lines[0].startswith("--- "):
        raise HelperError("workspace_patch_header_invalid")
    if not patch_lines[1].startswith("+++ "):
        raise HelperError("workspace_patch_header_invalid")
    _patch_path(patch_lines[0][4:], target, "a/")
    _patch_path(patch_lines[1][4:], target, "b/")
    original = current_text.splitlines(keepends=True)
    output: list[str] = []
    original_index = 0
    line_index = 2
    while line_index < len(patch_lines):
        match = _HUNK.fullmatch(patch_lines[line_index])
        if match is None:
            raise HelperError("workspace_patch_hunk_invalid")
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_count = int(match.group(4) or "1")
        target_index = old_start - 1
        if target_index < original_index or target_index > len(original):
            raise HelperError("workspace_patch_hunk_out_of_range")
        output.extend(original[original_index:target_index])
        original_index = target_index
        removed_or_context = 0
        added_or_context = 0
        line_index += 1
        while line_index < len(patch_lines) and not patch_lines[line_index].startswith(
            "@@ "
        ):
            line = patch_lines[line_index]
            if line.startswith("\\ No newline at end of file"):
                line_index += 1
                continue
            if not line or line[0] not in {" ", "+", "-"}:
                raise HelperError("workspace_patch_line_invalid")
            marker = line[0]
            content = line[1:]
            if marker in {" ", "-"}:
                if original_index >= len(original) or original[original_index] != content:
                    raise HelperError("workspace_patch_context_mismatch")
                original_index += 1
                removed_or_context += 1
            if marker in {" ", "+"}:
                output.append(content)
                added_or_context += 1
            line_index += 1
        if removed_or_context != old_count or added_or_context != new_count:
            raise HelperError("workspace_patch_count_mismatch")
    output.extend(original[original_index:])
    return "".join(output).encode("utf-8")


def _git_status(root: Path, max_bytes: int) -> dict[str, object]:
    environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}

    def git(*argv: str) -> bytes:
        completed = subprocess.run(
            ("/usr/bin/git", *argv),
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            timeout=20,
        )
        if completed.returncode != 0:
            raise HelperError("workspace_git_observation_failed")
        return completed.stdout

    head = git("rev-parse", "--verify", "HEAD").decode().strip()
    tree = git("rev-parse", "--verify", "HEAD^{tree}").decode().strip()
    status_bytes = git("status", "--porcelain=v1", "-z", "--untracked-files=normal")
    raw_budget = max(1, (max_bytes - 512) * 3 // 4)
    truncated = len(status_bytes) > raw_budget
    status_bytes = status_bytes[:raw_budget]
    return {
        "head_commit": head,
        "head_tree": tree,
        "dirty": bool(status_bytes) or truncated,
        "porcelain_z_base64": base64.b64encode(status_bytes).decode("ascii"),
        "truncated": truncated,
    }


def _observe(root: Path, request: dict[str, object]) -> dict[str, object]:
    operation = request.get("operation")
    relative = _relative(request.get("path"), allow_root=True)
    max_bytes = request.get("max_bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise HelperError("workspace_observation_budget_invalid")
    path = _resolve(root, relative)
    if operation == "status":
        if path != root:
            raise HelperError("workspace_status_requires_root")
        return _git_status(root, max_bytes)
    metadata = os.lstat(path)
    kind = _kind(metadata)
    if operation == "stat":
        return {
            "path": relative,
            "kind": kind,
            "size": metadata.st_size,
            "content_digest": _content_digest(path),
        }
    if operation == "list":
        if kind != "directory":
            raise HelperError("workspace_directory_required")
        entries: list[dict[str, object]] = []
        truncated = False
        for entry in sorted(os.scandir(path), key=lambda item: item.name):
            entry_metadata = entry.stat(follow_symlinks=False)
            entry_kind = _kind(entry_metadata)
            if entry.is_symlink():
                raise HelperError("workspace_symlink_forbidden")
            _reject_hardlink(entry_metadata)
            entries.append(
                {
                    "name": entry.name,
                    "kind": entry_kind,
                    "size": entry_metadata.st_size,
                }
            )
            if len(
                json.dumps(
                    {"path": relative, "entries": entries, "truncated": True},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ) > max(1, max_bytes - 256):
                entries.pop()
                truncated = True
                break
        return {"path": relative, "entries": entries, "truncated": truncated}
    if operation == "read":
        raw_budget = max(1, (max_bytes - 256) * 3 // 4)
        value, truncated = _file_bytes(path, max_bytes=raw_budget)
        return {
            "path": relative,
            "content_base64": base64.b64encode(value).decode("ascii"),
            "returned_content_digest": _sha256(value),
            "content_digest": None if truncated else _sha256(value),
            "truncated": truncated,
        }
    if operation == "hash":
        return {
            "path": relative,
            "kind": kind,
            "content_digest": _content_digest(path),
        }
    raise HelperError("workspace_observation_operation_unknown")


def _mutate(root: Path, request: dict[str, object]) -> dict[str, object]:
    operation = request.get("operation")
    relative = _relative(request.get("path"))
    expected = request.get("expected_content_digest")
    path = _resolve(root, relative, allow_missing_leaf=True)
    exists = path.exists() or path.is_symlink()
    if path.is_symlink():
        raise HelperError("workspace_symlink_forbidden")
    destination_relative = request.get("destination_path")
    destination = None
    if destination_relative is not None:
        destination_text = _relative(destination_relative)
        destination = _resolve(root, destination_text, allow_missing_leaf=True)
        if destination.exists() or destination.is_symlink():
            raise HelperError("workspace_destination_exists")

    if operation == "write":
        content = _decode_content(request.get("content_base64"))
        if exists:
            _require_expected(path, expected)
        elif expected is not None:
            raise HelperError("workspace_content_precondition_failed")
        _atomic_write(path, content)
    elif operation == "mkdir":
        if exists:
            raise HelperError("workspace_destination_exists")
        if expected is not None:
            raise HelperError("workspace_content_precondition_failed")
        path.mkdir()
    elif operation in {"move", "copy"}:
        if not exists or destination is None:
            raise HelperError("workspace_source_or_destination_invalid")
        _require_expected(path, expected)
        if operation == "move":
            os.rename(path, destination)
            path = destination
        else:
            if _kind(os.lstat(path)) != "file":
                raise HelperError("workspace_copy_regular_file_required")
            content, truncated = _file_bytes(path, max_bytes=1_048_576)
            if truncated:
                raise HelperError("workspace_structured_copy_too_large")
            _atomic_write(destination, content)
            path = destination
    elif operation == "remove":
        if not exists:
            raise HelperError("workspace_path_missing")
        _require_expected(path, expected)
        metadata = os.lstat(path)
        if _kind(metadata) == "directory":
            if bool(request.get("recursive")):
                _tree_digest(path)
                shutil.rmtree(path)
            else:
                path.rmdir()
        else:
            _reject_hardlink(metadata)
            path.unlink()
        return {"path": relative, "removed": True}
    elif operation == "apply_patch":
        if not exists:
            raise HelperError("workspace_path_missing")
        _require_expected(path, expected)
        current, truncated = _file_bytes(path, max_bytes=1_048_576)
        if truncated:
            raise HelperError("workspace_structured_patch_too_large")
        patched = _apply_unified_patch(
            current,
            _decode_content(request.get("content_base64")),
            relative,
        )
        _atomic_write(path, patched)
    else:
        raise HelperError("workspace_mutation_operation_unknown")
    return {
        "path": relative,
        "kind": _kind(os.lstat(path)),
        "content_digest": _content_digest(path),
    }


def main() -> int:
    mode: object = None
    try:
        request = json.loads(
            sys.stdin.buffer.read(),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                HelperError("workspace_helper_non_finite_json")
            ),
        )
        if not isinstance(request, dict) or request.get("schema_version") != SCHEMA_VERSION:
            raise HelperError("workspace_helper_request_invalid")
        mode = request.get("mode")
        result = (
            _observe(_root(), request)
            if mode == "observation"
            else _mutate(_root(), request)
            if mode == "mutation"
            else (_ for _ in ()).throw(HelperError("workspace_helper_mode_unknown"))
        )
        response = {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "effect_certainty": (
                "no_effect" if mode == "observation" else "terminal_known"
            ),
            "mutation_applied": False if mode == "observation" else True,
            "result": result,
        }
    except HelperError as exc:
        response = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_code": exc.code,
            "effect_certainty": "no_effect",
            "mutation_applied": False,
        }
    except Exception:
        response = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_code": "workspace_helper_unclassified_failure",
            "effect_certainty": (
                "no_effect" if mode == "observation" else "dispatch_in_doubt"
            ),
            "mutation_applied": False if mode == "observation" else None,
        }
    sys.stdout.write(
        json.dumps(
            response,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
