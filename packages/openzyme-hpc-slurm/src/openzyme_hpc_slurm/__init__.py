"""Slurm scheduler Adapter for the HPC Plugin."""

from .adapter import *  # noqa: F403
from .adapter import __all__ as _adapter_exports
from .qualification import *  # noqa: F403
from .qualification import __all__ as _qualification_exports

COMPONENT_ID = "openzyme.hpc.slurm"
COMPONENT_KIND = "adapter"
MIGRATION_STATE = "target_implemented_not_cutover"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_adapter_exports,
    *_qualification_exports,
]
