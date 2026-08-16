from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import stat
import threading
import time
from typing import Callable
from typing import Any
from typing import Iterator
from typing import Protocol

from .config import RunnerConfig
from .config import SshTransportMode
from .config import SshTransportPolicy


SSH_TRANSPORT_IDENTITY_SCHEMA_VERSION = "ssh_transport_identity@1"
SSH_CONTROL_ROOT_SCHEMA_VERSION = "ssh_control_root@1"
SSH_CONTROL_SOCKET_OWNER_SCHEMA_VERSION = "ssh_control_socket_owner@1"
SSH_TRANSPORT_MANAGER_SCHEMA_VERSION = "ssh_transport_manager@1"
_CONTROL_PATH_MAX_BYTES = 100
_BASE_SSH_OPTIONS = (
    "BatchMode=yes",
    "ConnectTimeout=15",
    "ServerAliveInterval=30",
    "ServerAliveCountMax=2",
)


class SshTransportError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


class SshTransportOwnershipError(SshTransportError):
    pass


class SshChannelLimitError(SshTransportError):
    pass


class TransportCommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
        input_text: str | None = None,
    ) -> Any: ...


def _digest_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True, slots=True)
class SshTransportIdentity:
    deployment_id: str
    effective_config_digest: str
    normalized_target: str
    credential_policy_id: str
    host_key_policy_id: str
    policy_digest: str
    identity_digest: str

    @classmethod
    def from_config(cls, config: RunnerConfig) -> "SshTransportIdentity":
        payload = {
            "schema_version": SSH_TRANSPORT_IDENTITY_SCHEMA_VERSION,
            "deployment_id": config.deployment_id,
            "effective_config_digest": config.effective_config_digest,
            "normalized_target": config.cluster.normalized_ssh_target,
            "credential_policy_id": config.cluster.credential_policy_id,
            "host_key_policy_id": config.cluster.host_key_policy_id,
            "policy_digest": config.ssh_transport.policy_digest,
        }
        return cls(
            deployment_id=config.deployment_id,
            effective_config_digest=config.effective_config_digest,
            normalized_target=config.cluster.normalized_ssh_target,
            credential_policy_id=config.cluster.credential_policy_id,
            host_key_policy_id=config.cluster.host_key_policy_id,
            policy_digest=config.ssh_transport.policy_digest,
            identity_digest=_digest_json(payload),
        )

    def to_private_dict(self) -> dict[str, str]:
        return {
            "schema_version": SSH_TRANSPORT_IDENTITY_SCHEMA_VERSION,
            "deployment_id": self.deployment_id,
            "effective_config_digest": self.effective_config_digest,
            "normalized_target": self.normalized_target,
            "credential_policy_id": self.credential_policy_id,
            "host_key_policy_id": self.host_key_policy_id,
            "policy_digest": self.policy_digest,
            "identity_digest": self.identity_digest,
        }

    def to_safe_ref(self) -> dict[str, str]:
        return {
            "schema_version": SSH_TRANSPORT_IDENTITY_SCHEMA_VERSION,
            "identity_digest": self.identity_digest,
            "policy_digest": self.policy_digest,
        }


@dataclass(frozen=True, slots=True)
class SshCommandCompiler:
    target: str
    policy: SshTransportPolicy
    control_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.target or any(char.isspace() for char in self.target):
            raise ValueError("SSH target must be a non-empty bounded argv token")
        if self.target.startswith("-") or any(
            char in self.target for char in ("/", "\\", "\x00")
        ):
            raise ValueError("SSH target contains forbidden characters")
        if self.policy.mode is SshTransportMode.CONTROLMASTER_V1:
            if self.control_path is None:
                raise ValueError("ControlMaster mode requires an exact control path")
            _validate_control_path_length(self.control_path)
        elif self.control_path is not None:
            raise ValueError("disabled transport must not receive a control path")

    @classmethod
    def legacy(cls, target: str) -> "SshCommandCompiler":
        return cls(target=target, policy=SshTransportPolicy())

    def option_argv(self) -> list[str]:
        options = list(_BASE_SSH_OPTIONS)
        if self.policy.mode is SshTransportMode.CONTROLMASTER_V1:
            assert self.control_path is not None
            options.extend(
                (
                    "ControlMaster=auto",
                    f"ControlPersist={self.policy.control_persist_seconds}",
                    f"ControlPath={self.control_path}",
                )
            )
        result: list[str] = []
        for option in options:
            result.extend(("-o", option))
        return result

    def ssh(self, remote_argv: list[str]) -> list[str]:
        if not remote_argv:
            raise ValueError("remote argv must not be empty")
        return [
            "ssh",
            *self.option_argv(),
            self.target,
            "--",
            shlex.join(remote_argv),
        ]

    def scp_upload(
        self,
        local_path: Path,
        remote_path: str,
        *,
        recursive: bool,
    ) -> list[str]:
        command = ["scp", *self.option_argv()]
        if recursive:
            command.append("-r")
        command.extend((str(local_path), f"{self.target}:{remote_path}"))
        return command

    def scp_download(
        self,
        remote_path: str,
        local_path: Path,
        *,
        recursive: bool,
    ) -> list[str]:
        command = ["scp", *self.option_argv()]
        if recursive:
            command.append("-r")
        command.extend((f"{self.target}:{remote_path}", str(local_path)))
        return command

    def rsync_remote_shell(self) -> str:
        return shlex.join(["ssh", *self.option_argv()])

    def rsync_upload(self, local_path: Path, remote_path: str) -> list[str]:
        source = str(local_path)
        destination = remote_path
        exact_tree_options: list[str] = []
        if local_path.is_dir():
            source = source.rstrip("/") + "/"
            destination = destination.rstrip("/") + "/"
            exact_tree_options.append("--delete")
        return [
            "rsync",
            "-az",
            "--partial",
            *exact_tree_options,
            "-e",
            self.rsync_remote_shell(),
            source,
            f"{self.target}:{destination}",
        ]

    def rsync_download(self, remote_path: str, local_path: Path) -> list[str]:
        return [
            "rsync",
            "-az",
            "--partial",
            "-e",
            self.rsync_remote_shell(),
            f"{self.target}:{remote_path}",
            str(local_path),
        ]

    def master_start(self) -> list[str]:
        if self.policy.mode is not SshTransportMode.CONTROLMASTER_V1:
            raise ValueError("master lifecycle is unavailable while transport is disabled")
        assert self.control_path is not None
        return [
            "ssh",
            "-MNf",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=2",
            "-o",
            "ControlMaster=yes",
            "-o",
            f"ControlPersist={self.policy.control_persist_seconds}",
            "-o",
            f"ControlPath={self.control_path}",
            self.target,
        ]

    def master_check(self) -> list[str]:
        return self._master_control("check")

    def master_exit(self) -> list[str]:
        return self._master_control("exit")

    def _master_control(self, operation: str) -> list[str]:
        if self.policy.mode is not SshTransportMode.CONTROLMASTER_V1:
            raise ValueError("master lifecycle is unavailable while transport is disabled")
        assert self.control_path is not None
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ControlPath={self.control_path}",
            "-O",
            operation,
            self.target,
        ]


def _validate_control_path_length(path: Path) -> None:
    if len(os.fsencode(path)) > _CONTROL_PATH_MAX_BYTES:
        raise ValueError(
            "runner control path exceeds the bounded Unix socket path length; "
            "configure a shorter runner.transport_control_root"
        )


@dataclass(frozen=True, slots=True)
class SshControlSocketOwner:
    deployment_digest: str
    identity_digest: str
    generation: int
    runner_nonce: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SSH_CONTROL_SOCKET_OWNER_SCHEMA_VERSION,
            "deployment_digest": self.deployment_digest,
            "identity_digest": self.identity_digest,
            "generation": self.generation,
            "runner_nonce": self.runner_nonce,
            "created_at": self.created_at,
        }


class SshControlRoot:
    def __init__(self, root: Path, *, deployment_digest: str) -> None:
        self.root = root
        self.deployment_digest = deployment_digest

    def prepare(self) -> None:
        if self.root.exists() or self.root.is_symlink():
            self._validate_directory()
        else:
            self.root.mkdir(parents=True, mode=0o700)
            self.root.chmod(0o700)
            self._validate_directory()
        owner_path = self.root / "root-owner.json"
        if owner_path.exists() or owner_path.is_symlink():
            payload = self._read_safe_json(owner_path)
            if (
                payload.get("schema_version") != SSH_CONTROL_ROOT_SCHEMA_VERSION
                or payload.get("deployment_digest") != self.deployment_digest
                or payload.get("owner_uid") != os.getuid()
            ):
                raise SshTransportOwnershipError(
                    "transport_control_root_owner_mismatch",
                    "runner control root ownership metadata does not match",
                )
            return
        self._write_private_json(
            owner_path,
            {
                "schema_version": SSH_CONTROL_ROOT_SCHEMA_VERSION,
                "deployment_digest": self.deployment_digest,
                "owner_uid": os.getuid(),
            },
        )

    def control_path(self, identity_digest: str, generation: int) -> Path:
        if generation < 1 or generation > 999_999_999:
            raise ValueError("transport generation is outside the bounded range")
        digest_suffix = identity_digest.removeprefix("sha256:")[:20]
        if len(digest_suffix) != 20 or any(
            char not in "0123456789abcdef" for char in digest_suffix
        ):
            raise ValueError("transport identity digest is invalid")
        path = self.root / f"cm-{digest_suffix}-{generation}.sock"
        _validate_control_path_length(path)
        return path

    @staticmethod
    def owner_path(control_path: Path) -> Path:
        return control_path.with_name(control_path.name + ".owner.json")

    def record_owner(
        self,
        control_path: Path,
        *,
        identity_digest: str,
        generation: int,
        runner_nonce: str,
    ) -> SshControlSocketOwner:
        owner = SshControlSocketOwner(
            deployment_digest=self.deployment_digest,
            identity_digest=identity_digest,
            generation=generation,
            runner_nonce=runner_nonce,
            created_at=_now_iso(),
        )
        self._write_private_json(self.owner_path(control_path), owner.to_dict())
        return owner

    def load_owner(self, control_path: Path) -> SshControlSocketOwner | None:
        owner_path = self.owner_path(control_path)
        if not owner_path.exists() and not owner_path.is_symlink():
            return None
        payload = self._read_safe_json(owner_path)
        if payload.get("schema_version") != SSH_CONTROL_SOCKET_OWNER_SCHEMA_VERSION:
            raise SshTransportOwnershipError(
                "transport_socket_owner_invalid",
                "control socket ownership metadata is invalid",
            )
        try:
            return SshControlSocketOwner(
                deployment_digest=str(payload["deployment_digest"]),
                identity_digest=str(payload["identity_digest"]),
                generation=int(payload["generation"]),
                runner_nonce=str(payload["runner_nonce"]),
                created_at=str(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SshTransportOwnershipError(
                "transport_socket_owner_invalid",
                "control socket ownership metadata is incomplete",
            ) from exc

    def assert_owned(
        self,
        control_path: Path,
        *,
        identity_digest: str,
        generation: int,
        runner_nonce: str | None = None,
    ) -> SshControlSocketOwner:
        owner = self.load_owner(control_path)
        if (
            owner is None
            or owner.deployment_digest != self.deployment_digest
            or owner.identity_digest != identity_digest
            or owner.generation != generation
            or (runner_nonce is not None and owner.runner_nonce != runner_nonce)
        ):
            raise SshTransportOwnershipError(
                "transport_socket_owner_mismatch",
                "control socket ownership cannot be proven",
            )
        return owner

    def remove_owned_stale_socket(
        self,
        control_path: Path,
        *,
        identity_digest: str,
        generation: int,
    ) -> None:
        self.assert_owned(
            control_path,
            identity_digest=identity_digest,
            generation=generation,
        )
        if control_path.is_symlink():
            raise SshTransportOwnershipError(
                "transport_socket_symlink_rejected",
                "control socket path is a symlink",
            )
        if control_path.exists():
            socket_mode = control_path.lstat().st_mode
            if not stat.S_ISSOCK(socket_mode):
                raise SshTransportOwnershipError(
                    "transport_socket_type_rejected",
                    "owned control path is not a Unix socket",
                )
            control_path.unlink()
        self.owner_path(control_path).unlink(missing_ok=True)

    def _validate_directory(self) -> None:
        metadata = self.root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SshTransportOwnershipError(
                "transport_control_root_type_rejected",
                "runner control root must be a real directory",
            )
        if metadata.st_uid != os.getuid():
            raise SshTransportOwnershipError(
                "transport_control_root_owner_rejected",
                "runner control root has an unexpected owner",
            )
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise SshTransportOwnershipError(
                "transport_control_root_mode_rejected",
                "runner control root must have mode 0700",
            )

    @staticmethod
    def _read_safe_json(path: Path) -> dict[str, object]:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SshTransportOwnershipError(
                "transport_owner_metadata_type_rejected",
                "transport ownership metadata must be a regular file",
            )
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise SshTransportOwnershipError(
                "transport_owner_metadata_permissions_rejected",
                "transport ownership metadata permissions are unsafe",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SshTransportOwnershipError(
                "transport_owner_metadata_invalid",
                "transport ownership metadata cannot be read",
            ) from exc
        if not isinstance(payload, dict):
            raise SshTransportOwnershipError(
                "transport_owner_metadata_invalid",
                "transport ownership metadata must be an object",
            )
        return payload

    @staticmethod
    def _write_private_json(path: Path, payload: dict[str, object]) -> None:
        if path.exists() or path.is_symlink():
            raise SshTransportOwnershipError(
                "transport_owner_metadata_exists",
                "transport ownership metadata already exists",
            )
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise


@dataclass(frozen=True, slots=True)
class SshTransportChannel:
    identity_digest: str
    generation: int
    compiler: SshCommandCompiler


@dataclass(slots=True)
class _ManagedGeneration:
    generation: int
    control_path: Path
    compiler: SshCommandCompiler
    semaphore: threading.BoundedSemaphore
    active_channels: int = 0
    last_health_check: float = 0.0


class SshTransportManager:
    """Runner-lifespan owner of one isolated ControlMaster generation per identity."""

    def __init__(
        self,
        config: RunnerConfig,
        command_runner: TransportCommandRunner,
        *,
        runner_nonce: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.command_runner = command_runner
        self.identity = SshTransportIdentity.from_config(config)
        self.policy = config.ssh_transport
        self.runner_nonce = runner_nonce or secrets.token_hex(16)
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._generation: _ManagedGeneration | None = None
        self._retired_generations: dict[int, _ManagedGeneration] = {}
        self._accepting_channels = True
        self._shutdown_report: dict[str, object] | None = None
        self._root: SshControlRoot | None = None
        if self.enabled:
            self._root = SshControlRoot(
                config.control_root,
                deployment_digest=_digest_json(
                    {
                        "schema_version": SSH_TRANSPORT_MANAGER_SCHEMA_VERSION,
                        "deployment_id": config.deployment_id,
                    }
                ),
            )
            # Validate the longest supported generation before creating the
            # private root or attempting any SSH connection.  Repository-local
            # paths can exceed OpenSSH's Unix socket limit even when the first
            # generation's filename itself is short.
            self._root.control_path(
                self.identity.identity_digest,
                999_999_999,
            )
            self._root.prepare()

    @property
    def enabled(self) -> bool:
        return self.policy.mode is SshTransportMode.CONTROLMASTER_V1

    @property
    def current_generation(self) -> int:
        with self._lock:
            return 0 if self._generation is None else self._generation.generation

    def ensure_ready(self) -> int:
        if not self.enabled:
            return 0
        with self._lock:
            if not self._accepting_channels:
                raise SshTransportError(
                    "transport_shutting_down",
                    "SSH transport is not accepting new channels",
                )
            return self._ensure_healthy_generation_locked().generation

    def ensure_recovery_generation(self, *, after_generation: int) -> int:
        """Own a fresh generation whose identity is newer than persisted work."""

        if not self.enabled:
            return 0
        if after_generation < 0 or after_generation >= 999_999_999:
            raise ValueError("recovery generation bound is invalid")
        with self._lock:
            if not self._accepting_channels:
                raise SshTransportError(
                    "transport_shutting_down",
                    "SSH transport is not accepting recovery channels",
                )
            current = self._generation
            if current is not None and current.generation > after_generation:
                return current.generation
            if current is not None:
                if current.active_channels:
                    raise SshTransportError(
                        "transport_generation_busy",
                        "SSH transport generation still has active channels",
                    )
                self._retire_generation_locked(current)
            self._generation = self._start_generation_locked(after_generation + 1)
            return self._generation.generation

    def recovery_backoff(self, recovery_index: int) -> None:
        if recovery_index < 0 or recovery_index >= 1:
            raise ValueError("recovery index is outside the bounded policy")
        self._sleep(
            min(
                self.policy.backoff_initial_seconds
                * (self.policy.backoff_multiplier**recovery_index),
                self.policy.backoff_max_seconds,
            )
        )

    def run_ssh(
        self,
        remote_argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        stage: str | None = None,
        input_text: str | None = None,
    ) -> Any:
        with self.channel() as channel:
            kwargs: dict[str, Any] = {
                "check": check,
                "timeout": timeout,
                "stage": stage,
            }
            if input_text is not None:
                kwargs["input_text"] = input_text
            return self.command_runner.run(
                channel.compiler.ssh(remote_argv),
                **kwargs,
            )

    def run_upload(
        self,
        local_path: Path,
        remote_path: str,
        *,
        use_rsync: bool,
        check: bool = False,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> Any:
        with self.channel() as channel:
            command = (
                channel.compiler.rsync_upload(local_path, remote_path)
                if use_rsync
                else channel.compiler.scp_upload(
                    local_path,
                    remote_path,
                    recursive=local_path.is_dir(),
                )
            )
            return self.command_runner.run(
                command,
                check=check,
                timeout=timeout,
                stage=stage,
            )

    def run_download(
        self,
        remote_path: str,
        local_path: Path,
        *,
        use_rsync: bool,
        check: bool = False,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> Any:
        with self.channel() as channel:
            command = (
                channel.compiler.rsync_download(remote_path, local_path)
                if use_rsync
                else channel.compiler.scp_download(
                    remote_path,
                    local_path,
                    recursive=True,
                )
            )
            return self.command_runner.run(
                command,
                check=check,
                timeout=timeout,
                stage=stage,
            )

    @contextmanager
    def channel(self) -> Iterator[SshTransportChannel]:
        if not self.enabled:
            yield SshTransportChannel(
                identity_digest=self.identity.identity_digest,
                generation=0,
                compiler=SshCommandCompiler.legacy(self.config.cluster.ssh_target),
            )
            return
        with self._lock:
            if not self._accepting_channels:
                raise SshTransportError(
                    "transport_shutting_down",
                    "SSH transport is not accepting new channels",
                )
            generation = self._ensure_healthy_generation_locked()
        acquired = generation.semaphore.acquire(
            timeout=self.policy.channel_acquire_timeout_seconds
        )
        if not acquired:
            raise SshChannelLimitError(
                "transport_channel_limit",
                "SSH transport channel budget is exhausted",
            )
        with self._lock:
            if not self._accepting_channels:
                generation.semaphore.release()
                raise SshTransportError(
                    "transport_shutting_down",
                    "SSH transport stopped before channel admission",
                )
            generation.active_channels += 1
        try:
            yield SshTransportChannel(
                identity_digest=self.identity.identity_digest,
                generation=generation.generation,
                compiler=generation.compiler,
            )
        finally:
            with self._lock:
                generation.active_channels -= 1
                generation.semaphore.release()
                self._condition.notify_all()

    def replace_degraded_generation(self, *, expected_generation: int) -> int:
        if not self.enabled:
            return 0
        with self._lock:
            current = self._generation
            if current is None or current.generation != expected_generation:
                raise SshTransportError(
                    "transport_generation_changed",
                    "SSH transport generation changed before recovery",
                )
            if current.active_channels:
                raise SshTransportError(
                    "transport_generation_busy",
                    "SSH transport generation still has active channels",
                )
            self._retire_generation_locked(current)
            self._generation = self._start_generation_locked(
                current.generation + 1
            )
            return self._generation.generation

    def shutdown(self) -> dict[str, object]:
        with self._lock:
            if self._shutdown_report is not None:
                return dict(self._shutdown_report)
        if not self.enabled:
            self._accepting_channels = False
            report = {
                "schema_version": SSH_TRANSPORT_MANAGER_SCHEMA_VERSION,
                "clean": True,
                "active_channels": 0,
                "closed_generations": [],
            }
            self._shutdown_report = report
            return dict(report)
        deadline = self._monotonic() + self.policy.shutdown_timeout_seconds
        with self._condition:
            self._accepting_channels = False
            while (
                self._generation is not None
                and self._generation.active_channels > 0
                and self._monotonic() < deadline
            ):
                self._condition.wait(
                    timeout=max(0.0, deadline - self._monotonic())
                )
            generation = self._generation
            active_channels = 0 if generation is None else generation.active_channels
        with self._lock:
            candidates = dict(self._retired_generations)
            if generation is not None and active_channels == 0:
                candidates[generation.generation] = generation
            closed: list[int] = []
            unclosed: list[int] = []
            if active_channels == 0:
                for candidate in candidates.values():
                    if self._exit_owned_generation_locked(
                        candidate,
                        stage="transport_shutdown",
                    ):
                        closed.append(candidate.generation)
                    else:
                        unclosed.append(candidate.generation)
                self._generation = None
            clean = active_channels == 0 and not unclosed
            report = {
                "schema_version": SSH_TRANSPORT_MANAGER_SCHEMA_VERSION,
                "clean": clean,
                "active_channels": active_channels,
                "closed_generations": sorted(closed),
                "unclosed_generation_count": len(unclosed),
            }
            if clean:
                self._shutdown_report = report
        return dict(report)

    def _ensure_healthy_generation_locked(self) -> _ManagedGeneration:
        if self._generation is None:
            self._generation = self._start_generation_locked(1)
            return self._generation
        elapsed = self._monotonic() - self._generation.last_health_check
        if elapsed < self.policy.health_check_interval_seconds:
            return self._generation
        result = self.command_runner.run(
            self._generation.compiler.master_check(),
            check=False,
            timeout=self.policy.health_check_timeout_seconds,
            stage="transport_health",
        )
        self._generation.last_health_check = self._monotonic()
        if result.returncode == 0:
            return self._generation
        if self._generation.active_channels:
            raise SshTransportError(
                "transport_generation_degraded",
                "SSH transport health failed while channels remain active",
            )
        previous = self._generation
        self._retire_generation_locked(previous)
        self._generation = self._start_generation_locked(
            previous.generation + 1
        )
        return self._generation

    def _start_generation_locked(self, generation: int) -> _ManagedGeneration:
        assert self._root is not None
        control_path = self._root.control_path(
            self.identity.identity_digest,
            generation,
        )
        while (
            control_path.exists()
            or control_path.is_symlink()
            or self._root.owner_path(control_path).exists()
            or self._root.owner_path(control_path).is_symlink()
        ):
            owner = self._root.load_owner(control_path)
            if owner is None:
                raise SshTransportOwnershipError(
                    "transport_socket_owner_missing",
                    "existing control socket has no ownership proof",
                )
            self._root.assert_owned(
                control_path,
                identity_digest=self.identity.identity_digest,
                generation=generation,
            )
            stale_compiler = SshCommandCompiler(
                target=self.config.cluster.ssh_target,
                policy=self.policy,
                control_path=control_path,
            )
            health = self.command_runner.run(
                stale_compiler.master_check(),
                check=False,
                timeout=self.policy.health_check_timeout_seconds,
                stage="transport_health",
            )
            if health.returncode == 0:
                raise SshTransportOwnershipError(
                    "transport_socket_live_owner_conflict",
                    "an existing ControlMaster is still live for this generation",
                )
            if not control_path.exists() and not control_path.is_symlink():
                self._root.remove_owned_stale_socket(
                    control_path,
                    identity_digest=self.identity.identity_digest,
                    generation=generation,
                )
            elif control_path.is_symlink():
                raise SshTransportOwnershipError(
                    "transport_socket_symlink_rejected",
                    "control socket path is a symlink",
                )
            elif not stat.S_ISSOCK(control_path.lstat().st_mode):
                raise SshTransportOwnershipError(
                    "transport_socket_type_rejected",
                    "owned control path is not a Unix socket",
                )
            # A failed health probe does not prove that unlinking a possibly
            # live local master socket is safe. Preserve its ownership evidence
            # and isolate the next connect on a higher generation instead.
            generation += 1
            control_path = self._root.control_path(
                self.identity.identity_digest,
                generation,
            )
        compiler = SshCommandCompiler(
            target=self.config.cluster.ssh_target,
            policy=self.policy,
            control_path=control_path,
        )
        for attempt in range(self.policy.connect_attempts):
            self._root.record_owner(
                control_path,
                identity_digest=self.identity.identity_digest,
                generation=generation,
                runner_nonce=self.runner_nonce,
            )
            self.command_runner.run(
                compiler.master_start(),
                check=False,
                timeout=self.policy.health_check_timeout_seconds,
                stage="transport_connect",
            )
            candidate = _ManagedGeneration(
                generation=generation,
                control_path=control_path,
                compiler=compiler,
                semaphore=threading.BoundedSemaphore(
                    self.policy.max_channels_per_target
                ),
                last_health_check=self._monotonic(),
            )
            health = self.command_runner.run(
                compiler.master_check(),
                check=False,
                timeout=self.policy.health_check_timeout_seconds,
                stage="transport_health",
            )
            candidate.last_health_check = self._monotonic()
            if health.returncode == 0:
                return candidate
            self._retire_generation_locked(candidate)
            if attempt + 1 < self.policy.connect_attempts:
                self._sleep(
                    min(
                        self.policy.backoff_initial_seconds
                        * (self.policy.backoff_multiplier**attempt),
                        self.policy.backoff_max_seconds,
                    )
                )
                generation += 1
                control_path = self._root.control_path(
                    self.identity.identity_digest,
                    generation,
                )
                while (
                    control_path.exists()
                    or control_path.is_symlink()
                    or self._root.owner_path(control_path).exists()
                    or self._root.owner_path(control_path).is_symlink()
                ):
                    generation += 1
                    control_path = self._root.control_path(
                        self.identity.identity_digest,
                        generation,
                    )
                compiler = SshCommandCompiler(
                    target=self.config.cluster.ssh_target,
                    policy=self.policy,
                    control_path=control_path,
                )
        raise SshTransportError(
            "transport_connect_failed",
            "SSH ControlMaster could not be established within the bounded policy",
        )

    def _retire_generation_locked(self, generation: _ManagedGeneration) -> bool:
        return self._exit_owned_generation_locked(
            generation,
            stage="transport_retire",
        )

    def _exit_owned_generation_locked(
        self,
        generation: _ManagedGeneration,
        *,
        stage: str,
    ) -> bool:
        assert self._root is not None
        self._root.assert_owned(
            generation.control_path,
            identity_digest=self.identity.identity_digest,
            generation=generation.generation,
            runner_nonce=self.runner_nonce,
        )
        result = self.command_runner.run(
            generation.compiler.master_exit(),
            check=False,
            timeout=self.policy.health_check_timeout_seconds,
            stage=stage,
        )
        if result.returncode != 0 or result.timed_out:
            self._retired_generations[generation.generation] = generation
            return False
        self._remove_owner_metadata(generation)
        self._retired_generations.pop(generation.generation, None)
        return True

    def _remove_owner_metadata(self, generation: _ManagedGeneration) -> None:
        assert self._root is not None
        owner_path = self._root.owner_path(generation.control_path)
        owner = self._root.assert_owned(
            generation.control_path,
            identity_digest=self.identity.identity_digest,
            generation=generation.generation,
            runner_nonce=self.runner_nonce,
        )
        del owner
        owner_path.unlink(missing_ok=True)
        if generation.control_path.exists() and not generation.control_path.is_symlink():
            if stat.S_ISSOCK(generation.control_path.lstat().st_mode):
                generation.control_path.unlink()


def compile_legacy_ssh(target: str, remote_argv: list[str]) -> list[str]:
    return SshCommandCompiler.legacy(target).ssh(remote_argv)
