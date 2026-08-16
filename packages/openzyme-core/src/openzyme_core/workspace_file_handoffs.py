from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import require_repository_path

from .harness import SessionRuntimeContext


# Each chunk is transported as one bounded base64 argv into the capsule. Larger
# content uses multiple native capsule turns and becomes visible only after the
# final whole-file digest check and atomic rename.
WORKSPACE_FILE_WRITE_MAX_BYTES = 16 * 1024 * 1024
_WORKSPACE_FILE_WRITE_CHUNK_BYTES = 80 * 1024
_WORKSPACE_FILE_WRITE_CHUNKS_PER_PROCESS = 8
_SAFE_FILE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class WorkspaceFileHandoffError(RuntimeError):
    error_code = "workspace_file_handoff_failed"


@dataclass(frozen=True, slots=True)
class WorkspaceFileWriteResult:
    workspace_id: str
    workspace_generation: int
    repository_path: str
    size_bytes: int
    content_digest: str
    publication_required: bool = True
    commit_performed: bool = False
    publication_performed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "workspace_file_write_result@1",
            "workspace_id": self.workspace_id,
            "workspace_generation": self.workspace_generation,
            "repository_path": self.repository_path,
            "size_bytes": self.size_bytes,
            "content_digest": self.content_digest,
            "publication_required": self.publication_required,
            "commit_performed": self.commit_performed,
            "publication_performed": self.publication_performed,
        }


def write_json_to_current_agent_workspace(
    context: SessionRuntimeContext,
    *,
    repository_path: str,
    payload: dict[str, Any],
) -> WorkspaceFileWriteResult:
    content = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return write_bytes_to_current_agent_workspace(
        context,
        repository_path=repository_path,
        content=content,
    )


def write_bytes_to_current_agent_workspace(
    context: SessionRuntimeContext,
    *,
    repository_path: str,
    content: bytes,
) -> WorkspaceFileWriteResult:
    require_repository_path(repository_path)
    if context.agent_id is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result requires a canonical current agent"
        )
    if context.agent_capsule_process_runner is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result requires the native agent capsule writer"
        )
    agent = context.repositories.agents.get(
        context.snapshot.session.session_id,
        context.agent_id,
    )
    if agent is None or agent.member_id is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result agent has no canonical member identity"
        )
    workspace = context.repositories.agent_git_workspaces.get_current(
        session_id=context.snapshot.session.session_id,
        agent_member_id=agent.member_id,
    )
    if workspace is None or workspace.status is not AgentGitWorkspaceStatus.READY:
        raise WorkspaceFileHandoffError(
            "persistent tool result requires the exact ready agent Git workspace"
        )
    if len(content) > WORKSPACE_FILE_WRITE_MAX_BYTES:
        raise WorkspaceFileHandoffError(
            "persistent tool result exceeds the bounded native workspace writer limit"
        )
    digest = hashlib.sha256(content).hexdigest()
    filename = repository_path.rsplit("/", 1)[-1]
    if _SAFE_FILE_COMPONENT.fullmatch(filename) is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result filename is not a safe repository component"
        )
    parent_prefix = (
        repository_path.rsplit("/", 1)[0] + "/"
        if "/" in repository_path
        else ""
    )
    temporary_path = f"{parent_prefix}.openzyme-write-{uuid4().hex}"
    initialize_script = r"""
set -euo pipefail
repository_path="$1"
temporary_path="$2"
case "${repository_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
parent="$(dirname -- "${repository_path}")"
mkdir -p -- "${parent}"
umask 077
( set -o noclobber; : >"${temporary_path}" )
""".strip()
    append_script = r"""
set -euo pipefail
temporary_path="$1"
shift
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
for encoded_chunk in "$@"; do
  printf '%s' "${encoded_chunk}" | base64 -d >>"${temporary_path}"
done
""".strip()
    finalize_script = r"""
set -euo pipefail
repository_path="$1"
temporary_path="$2"
expected_digest="$3"
case "${repository_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
observed_digest="$(sha256sum "${temporary_path}" | cut -d' ' -f1)"
test "${observed_digest}" = "${expected_digest}"
chmod 0600 "${temporary_path}"
mv -- "${temporary_path}" "${repository_path}"
printf 'OPENZYME_PATH=%s\n' "${repository_path}"
printf 'OPENZYME_SHA256=%s\n' "${observed_digest}"
""".strip()
    cleanup_script = r"""
set -euo pipefail
temporary_path="$1"
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
rm -f -- "${temporary_path}"
""".strip()

    def cleanup_temporary() -> None:
        try:
            context.agent_capsule_process_runner.run(
                workspace=workspace,
                argv=(
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    cleanup_script,
                    "openzyme-workspace-file-writer",
                    temporary_path,
                ),
                credential_environment=(),
                timeout_seconds=60,
            )
        except Exception:
            return

    try:
        initialize_result = context.agent_capsule_process_runner.run(
            workspace=workspace,
            argv=(
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                initialize_script,
                "openzyme-workspace-file-writer",
                repository_path,
                temporary_path,
            ),
            credential_environment=(),
            timeout_seconds=60,
        )
    except Exception as exc:
        cleanup_temporary()
        raise WorkspaceFileHandoffError(
            "native capsule failed while initializing the workspace file"
        ) from exc
    if initialize_result.returncode != 0:
        cleanup_temporary()
        raise WorkspaceFileHandoffError(
            "native capsule could not initialize the workspace file write"
        )
    encoded_chunks = tuple(
        base64.b64encode(
            content[offset : offset + _WORKSPACE_FILE_WRITE_CHUNK_BYTES]
        ).decode("ascii")
        for offset in range(0, len(content), _WORKSPACE_FILE_WRITE_CHUNK_BYTES)
    )
    for batch_offset in range(
        0,
        len(encoded_chunks),
        _WORKSPACE_FILE_WRITE_CHUNKS_PER_PROCESS,
    ):
        batch = encoded_chunks[
            batch_offset : batch_offset + _WORKSPACE_FILE_WRITE_CHUNKS_PER_PROCESS
        ]
        try:
            append_result = context.agent_capsule_process_runner.run(
                workspace=workspace,
                argv=(
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    append_script,
                    "openzyme-workspace-file-writer",
                    temporary_path,
                    *batch,
                ),
                credential_environment=(),
                timeout_seconds=60,
            )
        except Exception as exc:
            cleanup_temporary()
            raise WorkspaceFileHandoffError(
                "native capsule failed while appending a workspace file chunk"
            ) from exc
        if append_result.returncode != 0:
            cleanup_temporary()
            raise WorkspaceFileHandoffError(
                "native capsule could not append a bounded workspace file chunk"
            )
    try:
        result = context.agent_capsule_process_runner.run(
            workspace=workspace,
            argv=(
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                finalize_script,
                "openzyme-workspace-file-writer",
                repository_path,
                temporary_path,
                digest,
            ),
            credential_environment=(),
            timeout_seconds=60,
        )
    except Exception as exc:
        cleanup_temporary()
        raise WorkspaceFileHandoffError(
            "native capsule failed while finalizing the workspace file"
        ) from exc
    if (
        result.returncode != 0
        or f"OPENZYME_PATH={repository_path}" not in result.stdout.splitlines()
        or f"OPENZYME_SHA256={digest}" not in result.stdout.splitlines()
    ):
        cleanup_temporary()
        raise WorkspaceFileHandoffError(
            "native capsule did not confirm the exact workspace file write"
        )
    return WorkspaceFileWriteResult(
        workspace_id=workspace.workspace_id,
        workspace_generation=workspace.workspace_generation,
        repository_path=repository_path,
        size_bytes=len(content),
        content_digest=f"sha256:{digest}",
    )


__all__ = [
    "WORKSPACE_FILE_WRITE_MAX_BYTES",
    "WorkspaceFileHandoffError",
    "WorkspaceFileWriteResult",
    "write_bytes_to_current_agent_workspace",
    "write_json_to_current_agent_workspace",
]
