from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import stat
import traceback
from typing import Iterator
from typing import Protocol

from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import canonical_sha256_digest


_BOUND = 32_768


def _bounded(value: str | None) -> str | None:
    if value is None:
        return None
    encoded = value.encode("utf-8", errors="replace")
    return encoded[-_BOUND:].decode("utf-8", errors="replace")


@dataclass(slots=True)
class ProtectedQualificationDiagnosticWriter:
    root: Path = field(repr=False)
    _sequence: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        root = self.root.absolute()
        if root.exists() or root.is_symlink():
            metadata = root.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ValueError("qualification diagnostic root is unsafe")
        else:
            root.mkdir(mode=0o700, parents=False)
        self.root = root

    def record(
        self,
        *,
        diagnostic_id: str,
        component: str,
        phase: str,
        kind: str,
        error_code: str | None,
        return_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        exception: BaseException | None = None,
        private_context: dict[str, object] | None = None,
    ) -> str:
        sequence = self._sequence.get(diagnostic_id, 0) + 1
        self._sequence[diagnostic_id] = sequence
        payload: dict[str, object] = {
            "schema_version": "enzymedesign_qualification_private_diagnostic@2",
            "diagnostic_id": diagnostic_id,
            "sequence": sequence,
            "component": component,
            "phase": phase,
            "kind": kind,
            "error_code": error_code,
            "return_code": return_code,
            "bounded_stdout": _bounded(stdout),
            "bounded_stderr": _bounded(stderr),
            "exception_type": None if exception is None else type(exception).__name__,
            "exception_message": None if exception is None else _bounded(str(exception)),
            "bounded_traceback": (
                None
                if exception is None
                else _bounded("".join(traceback.format_exception(exception)))
            ),
            "private_context": private_context or {},
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "fallback_performed": False,
            "retry_performed": False,
        }
        record_digest = canonical_sha256_digest(payload)
        payload["record_digest"] = record_digest
        diagnostic_suffix = canonical_sha256_digest(
            {"diagnostic_id": diagnostic_id}
        ).removeprefix("sha256:")[:20]
        record_suffix = record_digest.removeprefix("sha256:")[:20]
        path = self.root / (
            f"qualification-diagnostic-{diagnostic_suffix}-{sequence:03d}-{record_suffix}.json"
        )
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return record_digest


@dataclass(slots=True)
class QualificationDiagnosticContext:
    writer: ProtectedQualificationDiagnosticWriter
    diagnostic_id: str | None = None
    component: str | None = None

    @contextmanager
    def bind(self, *, diagnostic_id: str, component: str) -> Iterator[None]:
        previous = (self.diagnostic_id, self.component)
        self.diagnostic_id = diagnostic_id
        self.component = component
        try:
            yield
        finally:
            self.diagnostic_id, self.component = previous

    def record_command(
        self,
        *,
        phase: str,
        return_code: int,
        stdout: str,
        stderr: str,
        command_digest: str,
    ) -> None:
        if self.diagnostic_id is None or self.component is None:
            return
        self.writer.record(
            diagnostic_id=self.diagnostic_id,
            component=self.component,
            phase=phase,
            kind="external-command",
            error_code="qualification_external_command_failed",
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            private_context={"command_digest": command_digest},
        )


class QualificationBridge(Protocol):
    binding: ExternalQualificationBridgeBinding

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome: ...

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome: ...

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None: ...


@dataclass(slots=True)
class DiagnosticQualificationBridge:
    delegate: QualificationBridge
    context: QualificationDiagnosticContext
    component_id: str

    @property
    def binding(self) -> ExternalQualificationBridgeBinding:
        return self.delegate.binding

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._invoke("dispatch", request)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._invoke("reconcile", request)

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None:
        diagnostic_id = f"diagnostic.{request.attempt_id}"
        with self.context.bind(
            diagnostic_id=diagnostic_id,
            component=self.component_id,
        ):
            try:
                self.delegate.restore_dispatched_attempt(request)
            except Exception as exc:
                self.context.writer.record(
                    diagnostic_id=diagnostic_id,
                    component=self.component_id,
                    phase="restore_dispatched_attempt",
                    kind="bridge-exception",
                    error_code=getattr(
                        exc,
                        "error_code",
                        "qualification_bridge_restore_failed",
                    ),
                    exception=exc,
                )
                raise

    def _invoke(
        self,
        method: str,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationProbeOutcome:
        diagnostic_id = f"diagnostic.{request.attempt_id}"
        with self.context.bind(
            diagnostic_id=diagnostic_id,
            component=self.component_id,
        ):
            try:
                outcome = getattr(self.delegate, method)(request)
            except Exception as exc:
                self.context.writer.record(
                    diagnostic_id=diagnostic_id,
                    component=self.component_id,
                    phase=method,
                    kind="bridge-exception",
                    error_code=getattr(exc, "error_code", "qualification_bridge_failed"),
                    exception=exc,
                )
                raise
            if outcome.disposition is not ExternalQualificationProbeDisposition.SUCCEEDED:
                self.context.writer.record(
                    diagnostic_id=diagnostic_id,
                    component=self.component_id,
                    phase=method,
                    kind="terminal-outcome",
                    error_code=outcome.error_code,
                    private_context={
                        "disposition": outcome.disposition.value,
                        "effect_certainty": outcome.effect_certainty.value,
                        "request_digest": request.request_digest,
                    },
                )
            return outcome


@dataclass(frozen=True, slots=True)
class RecordingPodmanCommandPort:
    delegate: object
    context: QualificationDiagnosticContext

    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        result = self.delegate.run(argv)  # type: ignore[attr-defined]
        if result[0] != 0:
            self.context.record_command(
                phase="podman-command",
                return_code=result[0],
                stdout=result[1],
                stderr=result[2],
                command_digest=canonical_sha256_digest({"argv": list(argv)}),
            )
        return result


@dataclass(frozen=True, slots=True)
class RecordingSshCommandPort:
    delegate: object
    context: QualificationDiagnosticContext

    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        result = self.delegate.run(argv)  # type: ignore[attr-defined]
        if result[0] != 0:
            self.context.record_command(
                phase="ssh-command",
                return_code=result[0],
                stdout=result[1],
                stderr=result[2],
                command_digest=canonical_sha256_digest({"argv": list(argv)}),
            )
        return result


@dataclass(frozen=True, slots=True)
class RecordingGitCommandPort:
    delegate: object
    context: QualificationDiagnosticContext

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> tuple[int, str, str]:
        result = self.delegate.run(argv, cwd=cwd)  # type: ignore[attr-defined]
        if result[0] != 0:
            self.context.record_command(
                phase="git-lfs-command",
                return_code=result[0],
                stdout=result[1],
                stderr=result[2],
                command_digest=canonical_sha256_digest(
                    {"argv": list(argv), "cwd": None if cwd is None else str(cwd)}
                ),
            )
        return result


__all__ = [
    "DiagnosticQualificationBridge",
    "ProtectedQualificationDiagnosticWriter",
    "QualificationDiagnosticContext",
    "RecordingGitCommandPort",
    "RecordingPodmanCommandPort",
    "RecordingSshCommandPort",
]
