from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Literal

from .models import FailureSignature


StagingFailurePhase = Literal[
    "remote_layout",
    "input_parent",
    "input_transfer",
    "runner_control_transfer",
]

_STAGING_FAILURE_PHASES = frozenset(
    {
        "remote_layout",
        "input_parent",
        "input_transfer",
        "runner_control_transfer",
    }
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class HpcStagingFailure(RuntimeError):
    """Sanitized, runner-owned failure for pre-execution HPC staging.

    The exception text and :meth:`to_safe_diagnostic` projection intentionally
    contain no command, SSH target, local/remote path, stderr, or credential.
    The runner persists the same closed projection as ``runner_failure@1``.
    """

    schema_id = "runner_failure@1"

    def __init__(
        self,
        *,
        phase: StagingFailurePhase,
        run_id: str,
        input_ordinal: int | None,
        content_digest: str | None,
        returncode: int,
        timed_out: bool,
        elapsed_seconds: float,
    ) -> None:
        normalized_phase = str(phase)
        normalized_run_id = str(run_id)
        if isinstance(elapsed_seconds, bool) or not isinstance(
            elapsed_seconds, (int, float)
        ):
            raise ValueError("HPC staging failure elapsed_seconds must be numeric")
        normalized_elapsed = round(float(elapsed_seconds), 6)
        if normalized_phase not in _STAGING_FAILURE_PHASES:
            raise ValueError("unsupported HPC staging failure phase")
        if _SAFE_RUN_ID.fullmatch(normalized_run_id) is None:
            raise ValueError("HPC staging failure run_id is not a safe opaque id")
        if input_ordinal is not None and (
            isinstance(input_ordinal, bool)
            or not isinstance(input_ordinal, int)
            or input_ordinal < 1
        ):
            raise ValueError("HPC staging failure input_ordinal must be positive")
        if content_digest is not None and (
            not isinstance(content_digest, str)
            or _SHA256_DIGEST.fullmatch(content_digest) is None
        ):
            raise ValueError("HPC staging failure content_digest must be sha256")
        if isinstance(returncode, bool) or not isinstance(returncode, int):
            raise ValueError("HPC staging failure returncode must be an integer")
        if not isinstance(timed_out, bool):
            raise ValueError("HPC staging failure timed_out must be boolean")
        if not math.isfinite(normalized_elapsed) or normalized_elapsed < 0:
            raise ValueError("HPC staging failure elapsed_seconds must be finite")
        if normalized_phase == "remote_layout":
            if input_ordinal is not None or content_digest is not None:
                raise ValueError("remote_layout failure must not identify an input")
        elif normalized_phase == "runner_control_transfer":
            if input_ordinal is not None or content_digest is None:
                raise ValueError(
                    "runner control transfer requires a digest and no input ordinal"
                )
        elif input_ordinal is None or content_digest is None:
            raise ValueError("input staging failure requires ordinal and digest")

        self.phase = normalized_phase
        self.run_id = normalized_run_id
        self.input_ordinal = input_ordinal
        self.content_digest = content_digest
        self.returncode = int(returncode)
        self.timed_out = bool(timed_out)
        self.elapsed_seconds = normalized_elapsed
        super().__init__(
            "HPC pre-execution staging failed "
            f"(phase={self.phase}, run_id={self.run_id}, "
            f"input_ordinal={self.input_ordinal}, "
            f"content_digest={self.content_digest}, "
            f"returncode={self.returncode}, timed_out={self.timed_out}, "
            f"elapsed_seconds={self.elapsed_seconds})"
        )

    def to_safe_diagnostic(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "phase": self.phase,
            "run_id": self.run_id,
            "input_ordinal": self.input_ordinal,
            "content_digest": self.content_digest,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True, slots=True)
class MappedError:
    code: str
    signature: str


class FailureMapper:
    def __init__(self) -> None:
        self._default_signatures: list[FailureSignature] = [
            FailureSignature(pattern=r"CUDA out of memory", error_code="CUDA_OOM"),
            FailureSignature(
                pattern=r"(No such file or directory|FileNotFoundError)",
                error_code="MISSING_FILE",
            ),
            FailureSignature(
                pattern=r"permission denied", error_code="PERMISSION_DENIED"
            ),
            FailureSignature(pattern=r"sbatch: error", error_code="SBATCH_ERROR"),
            FailureSignature(
                pattern=(
                    r"(ssh: connect to host .*: Connection timed out|"
                    r"Connection to .* port [0-9]+ timed out)"
                ),
                error_code="SSH_CONNECTION_TIMEOUT",
            ),
            FailureSignature(
                pattern=(
                    r"(ssh: connect to host|Could not resolve hostname|"
                    r"No route to host|Connection refused)"
                ),
                error_code="SSH_CONNECTION_FAILED",
            ),
        ]

    def map_error(
        self, stderr: str, custom_signatures: list[FailureSignature] | None = None
    ) -> MappedError | None:
        signatures = list(custom_signatures or []) + self._default_signatures
        for signature in signatures:
            if re.search(signature.pattern, stderr, flags=re.IGNORECASE):
                return MappedError(
                    code=signature.error_code, signature=signature.pattern
                )
        return None
