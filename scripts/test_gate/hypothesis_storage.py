"""Process-local, checkout-external storage for Hypothesis pytest state."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


_OWNER_ENV = "OPENZYME_HYPOTHESIS_STORAGE_PID"
_STORAGE_ENV = "HYPOTHESIS_STORAGE_DIRECTORY"


def configure_hypothesis_storage(
    *,
    repo_root: Path,
    storage_path: Path | None = None,
) -> Path:
    """Bind Hypothesis storage before collection without sharing mutable state."""

    process_id = str(os.getpid())
    configured = os.environ.get(_STORAGE_ENV)
    if (
        storage_path is None
        and configured is not None
        and os.environ.get(_OWNER_ENV) == process_id
    ):
        candidate = Path(configured)
    elif storage_path is not None:
        candidate = storage_path
    else:
        cache_root = os.environ.get("XDG_CACHE_HOME")
        base = Path(cache_root) if cache_root else Path(tempfile.gettempdir())
        candidate = base / (
            f"openzyme-hypothesis-{process_id}-{time.monotonic_ns()}"
        )
    if not candidate.is_absolute():
        raise RuntimeError("Hypothesis storage must be absolute")
    resolved = candidate.resolve(strict=False)
    checkout = repo_root.resolve(strict=True)
    try:
        resolved.relative_to(checkout)
    except ValueError:
        pass
    else:
        raise RuntimeError("Hypothesis storage must remain outside the checkout")
    os.environ[_STORAGE_ENV] = str(resolved)
    os.environ[_OWNER_ENV] = process_id

    configuration = sys.modules.get("hypothesis.configuration")
    if configuration is not None:
        configuration.set_hypothesis_home_dir(resolved)
    return resolved
