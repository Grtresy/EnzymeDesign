from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Literal


_CONTAINER_ABSENCE_HOLD_SECONDS = 0.1
_CONTAINER_RETIREMENT_RETRY_SECONDS = 0.1
_CONTAINER_RUN_ID_LABEL = "io.openzyme.run_id"
_CONTAINER_ROOT_DIGEST_LABEL = "io.openzyme.sandbox_root_digest"
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")


@dataclass(frozen=True, slots=True)
class PodmanContainerLease:
    """Bind and retire one exact Podman container before reading its mounts."""

    podman_binary: str
    container_name: str
    cidfile_path: Path
    run_id: str
    sandbox_root_digest: str

    @classmethod
    def create(
        cls,
        *,
        podman_binary: str,
        workspace_root: Path,
        sandbox_root: Path,
        run_id: str,
    ) -> PodmanContainerLease:
        if _SAFE_RUN_ID.fullmatch(run_id) is None:
            raise ValueError("podman run_id is not safe for a container lease")
        resolved_workspace_root = workspace_root.resolve()
        workspace_stat = resolved_workspace_root.lstat()
        if (
            not stat.S_ISDIR(workspace_stat.st_mode)
            or resolved_workspace_root.is_symlink()
        ):
            raise RuntimeError("podman workspace root must be a real directory")
        resolved_sandbox_root = sandbox_root.resolve()
        if (
            resolved_sandbox_root == resolved_workspace_root
            or resolved_workspace_root not in resolved_sandbox_root.parents
        ):
            raise RuntimeError("podman sandbox root is outside its workspace root")

        lease_dir = resolved_workspace_root / ".podman-leases"
        lease_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        lease_stat = lease_dir.lstat()
        if not stat.S_ISDIR(lease_stat.st_mode) or lease_dir.is_symlink():
            raise RuntimeError("podman lease root must be a real directory")
        lease_dir.chmod(0o700)
        cidfile_path = lease_dir / f"{run_id}.cid"
        try:
            cidfile_path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("podman cidfile target already exists")

        root_digest = "sha256:" + hashlib.sha256(
            str(resolved_sandbox_root).encode("utf-8")
        ).hexdigest()
        return cls(
            podman_binary=podman_binary,
            container_name=f"openzyme-{run_id}",
            cidfile_path=cidfile_path,
            run_id=run_id,
            sandbox_root_digest=root_digest,
        )

    def require_absent_before_run(self) -> None:
        try:
            completed = subprocess.run(
                [
                    self.podman_binary,
                    "container",
                    "exists",
                    self.container_name,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise RuntimeError(
                "podman could not inspect the container lease name"
            ) from exc
        if completed.returncode == 1:
            return
        if completed.returncode == 0:
            raise RuntimeError("podman container lease name already exists")
        raise RuntimeError("podman could not prove the container lease name is absent")

    def run_options(self) -> list[str]:
        return [
            "--name",
            self.container_name,
            "--cidfile",
            str(self.cidfile_path),
            "--label",
            f"{_CONTAINER_RUN_ID_LABEL}={self.run_id}",
            "--label",
            f"{_CONTAINER_ROOT_DIGEST_LABEL}={self.sandbox_root_digest}",
        ]

    def retire(self) -> None:
        """Fail-stop until Podman proves the exact container is absent.

        Lifecycle commands intentionally have no timeout. Returning after a
        bounded CLI timeout while conmon/container still owns rw mounts would
        let callers race a live writer. Process-isolated supervision is needed
        before this fail-stop can itself become bounded.
        """

        while True:
            cid_state, container_id = self._bound_cid()
            if cid_state == "invalid":
                time.sleep(_CONTAINER_RETIREMENT_RETRY_SECONDS)
                continue
            if cid_state == "absent":
                if self._container_exists(self.container_name) is not False:
                    time.sleep(_CONTAINER_RETIREMENT_RETRY_SECONDS)
                    continue
                time.sleep(_CONTAINER_ABSENCE_HOLD_SECONDS)
                repeated_state, _ = self._bound_cid()
                if (
                    repeated_state == "absent"
                    and self._container_exists(self.container_name) is False
                ):
                    return
                continue

            if container_id is None:
                raise AssertionError("valid cid state lacks a container id")
            cid_exists = self._container_exists(container_id)
            name_exists = self._container_exists(self.container_name)
            if cid_exists is False and name_exists is False:
                time.sleep(_CONTAINER_ABSENCE_HOLD_SECONDS)
                repeated_state, repeated_cid = self._bound_cid()
                if (
                    repeated_state == "valid"
                    and repeated_cid == container_id
                    and self._container_exists(container_id) is False
                    and self._container_exists(self.container_name) is False
                ):
                    if self._remove_retired_cidfile():
                        return
                    time.sleep(_CONTAINER_RETIREMENT_RETRY_SECONDS)
                continue
            if cid_exists is not True:
                time.sleep(_CONTAINER_RETIREMENT_RETRY_SECONDS)
                continue

            identity = self._inspect_identity(container_id)
            if identity is None:
                time.sleep(_CONTAINER_RETIREMENT_RETRY_SECONDS)
                continue
            inspected_id, run_id, root_digest = identity
            if (
                inspected_id != container_id
                or run_id != self.run_id
                or root_digest != self.sandbox_root_digest
            ):
                # Identity ambiguity authorizes neither killing another
                # container nor observing the potentially mutable mounts.
                time.sleep(_CONTAINER_RETIREMENT_RETRY_SECONDS)
                continue

            self._run_retirement_command(
                [self.podman_binary, "kill", container_id]
            )
            self._run_retirement_command(
                [self.podman_binary, "wait", container_id]
            )
            self._run_retirement_command(
                [
                    self.podman_binary,
                    "rm",
                    "--force",
                    "--time",
                    "0",
                    "--ignore",
                    container_id,
                ]
            )

    def _container_exists(self, reference: str) -> bool | None:
        completed = self._run_retirement_command(
            [
                self.podman_binary,
                "container",
                "exists",
                reference,
            ]
        )
        if completed is None:
            return None
        if completed.returncode == 0:
            return True
        if completed.returncode == 1:
            return False
        return None

    @staticmethod
    def _run_retirement_command(
        command: list[str],
    ) -> subprocess.CompletedProcess[bytes] | None:
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=False,
            )
        except Exception:
            return None

    def _bound_cid(
        self,
    ) -> tuple[Literal["absent", "invalid", "valid"], str | None]:
        try:
            path_stat = self.cidfile_path.lstat()
        except FileNotFoundError:
            return "absent", None
        except Exception:
            return "invalid", None
        try:
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or self.cidfile_path.is_symlink()
                or path_stat.st_nlink != 1
            ):
                return "invalid", None
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.cidfile_path, flags)
            try:
                before = os.fstat(descriptor)
                payload = os.read(descriptor, 129)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_nlink != 1
                or after.st_nlink != 1
                or len(payload) > 128
            ):
                return "invalid", None
            container_id = payload.decode("ascii", errors="ignore").strip()
            if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
                return "invalid", None
        except Exception:
            return "invalid", None
        return "valid", container_id

    def _inspect_identity(
        self,
        container_id: str,
    ) -> tuple[str, str, str] | None:
        try:
            completed = self._run_retirement_command(
                [
                    self.podman_binary,
                    "container",
                    "inspect",
                    "--format",
                    (
                        "{{.Id}} "
                        f'{{{{index .Config.Labels "{_CONTAINER_RUN_ID_LABEL}"}}}} '
                        f'{{{{index .Config.Labels "{_CONTAINER_ROOT_DIGEST_LABEL}"}}}}'
                    ),
                    container_id,
                ]
            )
            if completed is None or completed.returncode != 0:
                return None
            parts = completed.stdout.strip().split()
            if len(parts) != 3:
                return None
            decoded = tuple(part.decode("ascii") for part in parts)
        except Exception:
            return None
        if re.fullmatch(r"[0-9a-f]{64}", decoded[0]) is None:
            return None
        return decoded[0], decoded[1], decoded[2]

    def _remove_retired_cidfile(self) -> bool:
        try:
            target_stat = self.cidfile_path.lstat()
        except FileNotFoundError:
            return True
        except Exception:
            return False
        try:
            if (
                not stat.S_ISREG(target_stat.st_mode)
                or self.cidfile_path.is_symlink()
                or target_stat.st_nlink != 1
            ):
                return False
            self.cidfile_path.unlink()
        except Exception:
            return False
        return True


__all__ = ["PodmanContainerLease"]
