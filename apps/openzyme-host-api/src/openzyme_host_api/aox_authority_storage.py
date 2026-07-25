from __future__ import annotations

import os
from pathlib import Path

from .aox_cutover_evidence import CutoverEvidenceError


def publish_private_canonical_authority(
    path: Path,
    content: bytes,
) -> None:
    parent = path.parent
    if (
        not parent.is_dir()
        or parent.is_symlink()
        or path.exists()
        or path.is_symlink()
    ):
        raise CutoverEvidenceError(
            "attempt_authority_publish_target_invalid",
            "authority target must be absent under an existing real directory",
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        written = 0
        while written < len(content):
            written += os.write(descriptor, content[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o400, follow_symlinks=False)
    parent_descriptor = os.open(
        parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


__all__ = ["publish_private_canonical_authority"]
