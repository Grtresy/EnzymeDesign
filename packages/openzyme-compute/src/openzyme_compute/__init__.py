"""Revision-bound formal Compute Plugin contracts and application lifecycle."""

from .contracts import *  # noqa: F403
from .contracts import __all__ as _contract_exports
from .lifecycle import *  # noqa: F403
from .lifecycle import __all__ as _lifecycle_exports
from .manifest_locator import COMPUTE_COMPONENT_MANIFEST_DIGEST
from .manifest_locator import locate_component_manifest
from .runtime_contributions import *  # noqa: F403
from .runtime_contributions import __all__ as _runtime_exports
from .transaction import *  # noqa: F403
from .transaction import __all__ as _transaction_exports
from .workspace_revision_executions import *  # noqa: F403
from .workspace_revision_executions import __all__ as _execution_contract_exports

COMPONENT_ID = "openzyme.compute"
COMPONENT_KIND = "plugin"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "COMPUTE_COMPONENT_MANIFEST_DIGEST",
    "MIGRATION_STATE",
    "locate_component_manifest",
    *_contract_exports,
    *_lifecycle_exports,
    *_runtime_exports,
    *_transaction_exports,
    *_execution_contract_exports,
]
