from __future__ import annotations

from dataclasses import dataclass
import re

from .models import FailureSignature


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
                pattern=r"(ssh: connect to host|Connection timed out)",
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
