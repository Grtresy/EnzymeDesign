"""Closed Compute/HPC runner wire contracts and revision-bound execution DTOs."""

from .workspace_job_wire import *  # noqa: F403
from .workspace_job_wire import __all__ as _workspace_job_wire_exports
from .workloads import *  # noqa: F403
from .workloads import __all__ as _workload_exports

COMPONENT_ID = "openzyme.execution.contracts"
COMPONENT_KIND = "capability_contracts"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_workspace_job_wire_exports,
    *_workload_exports,
]
