"""File-native Reporting Plugin target surfaces and compatibility contracts."""

from .application import *  # noqa: F403
from .application import __all__ as _application_exports
from .contracts import *  # noqa: F403
from .contracts import __all__ as _contract_exports
from .lifecycle import *  # noqa: F403
from .lifecycle import __all__ as _lifecycle_exports
from .legacy_repositories import *  # noqa: F403
from .legacy_repositories import __all__ as _legacy_repository_exports
from .manifest_locator import REPORTING_COMPONENT_MANIFEST_DIGEST
from .manifest_locator import locate_component_manifest
from .publication import *  # noqa: F403
from .publication import __all__ as _publication_exports
from .projection import *  # noqa: F403
from .projection import __all__ as _projection_exports
from .refs import *  # noqa: F403
from .refs import __all__ as _ref_exports
from .runtime_contributions import *  # noqa: F403
from .runtime_contributions import __all__ as _runtime_exports
from .transaction import *  # noqa: F403
from .transaction import __all__ as _transaction_exports

COMPONENT_ID = "openzyme.reporting"
COMPONENT_KIND = "plugin"
MIGRATION_STATE = "target_implemented_host_mount_pending"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "REPORTING_COMPONENT_MANIFEST_DIGEST",
    "locate_component_manifest",
    *_application_exports,
    *_contract_exports,
    *_lifecycle_exports,
    *_legacy_repository_exports,
    *_publication_exports,
    *_projection_exports,
    *_ref_exports,
    *_runtime_exports,
    *_transaction_exports,
]
