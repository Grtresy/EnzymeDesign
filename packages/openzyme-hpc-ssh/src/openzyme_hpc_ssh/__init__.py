"""SSH/SFTP/rsync Workspace Runtime Adapter for the HPC Plugin."""

from .workspace import *  # noqa: F403
from .workspace import __all__ as _workspace_exports

COMPONENT_ID = "openzyme.hpc.ssh"
COMPONENT_KIND = "adapter"
MIGRATION_STATE = "target_implemented_not_cutover"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_workspace_exports,
]
