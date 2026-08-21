"""HPC workspace contract owner; the Plugin is not activatable yet."""

from .contracts import *  # noqa: F403
from .contracts import __all__ as _contract_exports
from .inventory import *  # noqa: F403
from .inventory import __all__ as _inventory_exports
from .qualification import *  # noqa: F403
from .qualification import __all__ as _qualification_exports
from .projection_worker import *  # noqa: F403
from .projection_worker import __all__ as _projection_worker_exports
from .routes import *  # noqa: F403
from .routes import __all__ as _route_exports
from .runtime_contributions import *  # noqa: F403
from .runtime_contributions import __all__ as _runtime_contribution_exports
from .scheduler import *  # noqa: F403
from .scheduler import __all__ as _scheduler_exports
from .sqlite_inventory import *  # noqa: F403
from .sqlite_inventory import __all__ as _sqlite_inventory_exports
from .sqlite_workspace_repository import *  # noqa: F403
from .sqlite_workspace_repository import __all__ as _sqlite_workspace_repository_exports
from .workspace_lifecycle import *  # noqa: F403
from .workspace_lifecycle import __all__ as _workspace_lifecycle_exports
from .workspace_application_ports import *  # noqa: F403
from .workspace_application_ports import __all__ as _workspace_application_port_exports
from .workspace_application import *  # noqa: F403
from .workspace_application import __all__ as _workspace_application_exports
from .workspace_state_machine import *  # noqa: F403
from .workspace_state_machine import __all__ as _workspace_state_machine_exports
from .workspace_tools import *  # noqa: F403
from .workspace_tools import __all__ as _workspace_tool_exports

COMPONENT_ID = "openzyme.hpc"
COMPONENT_KIND = "plugin"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_contract_exports,
    *_inventory_exports,
    *_qualification_exports,
    *_projection_worker_exports,
    *_route_exports,
    *_runtime_contribution_exports,
    *_scheduler_exports,
    *_sqlite_inventory_exports,
    *_sqlite_workspace_repository_exports,
    *_workspace_lifecycle_exports,
    *_workspace_application_port_exports,
    *_workspace_application_exports,
    *_workspace_state_machine_exports,
    *_workspace_tool_exports,
]
