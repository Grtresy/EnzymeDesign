"""AOX Product Plugin contracts and exact manifest locator."""

from .architecture_qualification import *  # noqa: F403
from .architecture_qualification import __all__ as _qualification_exports
from .calculation_contracts import *  # noqa: F403
from .calculation_contracts import __all__ as _calculation_contract_exports
from .file_bundle_contract import *  # noqa: F403
from .file_bundle_contract import __all__ as _file_bundle_exports
from .file_bundle_finalizer import *  # noqa: F403
from .file_bundle_finalizer import __all__ as _file_bundle_finalizer_exports
from .finalization_handler import *  # noqa: F403
from .finalization_handler import __all__ as _finalization_handler_exports
from .manifest_locator import AOX_COMPONENT_MANIFEST_DIGEST
from .manifest_locator import locate_component_manifest
from .workflow_contracts import *  # noqa: F403
from .workflow_contracts import __all__ as _workflow_contract_exports

COMPONENT_ID = "enzymedesign.aox"
COMPONENT_KIND = "product_plugin"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

__all__ = [
    "AOX_COMPONENT_MANIFEST_DIGEST",
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "locate_component_manifest",
    *_qualification_exports,
    *_calculation_contract_exports,
    *_file_bundle_exports,
    *_file_bundle_finalizer_exports,
    *_finalization_handler_exports,
    *_workflow_contract_exports,
]
